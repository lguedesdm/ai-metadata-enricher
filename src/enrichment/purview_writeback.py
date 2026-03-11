"""
Purview Write-back Service — Controlled, Auditable Suggested Description Writes.

Provides a safe, non-destructive write-back of exactly one AI-generated
Suggested Description to Microsoft Purview, completing the governance loop.

This module:
- Writes ONLY to the AI_Enrichment Business Metadata attribute
- Operates on exactly one asset at a time
- Enforces a lifecycle: pending → approved / rejected
- Prevents overwrite of non-pending or authoritative metadata
- Persists audit and lifecycle state to Cosmos DB
- Provides explicit error handling for auth, permission, not-found, network
- Emits structured logs with assetId, correlationId, lifecycle status, result

Security guarantees:
- NEVER writes to authoritative metadata fields (description)
- NEVER overwrites an existing non-pending Suggested Description
- NEVER processes multiple assets in a single invocation
- All operations are explicitly invoked — nothing runs automatically

This module does NOT:
- Invoke the LLM or any AI service
- Modify validation rules or frozen contracts
- Interact with the Orchestrator (consumer, message_handler)
- Implement approval workflow automation
- Create or modify infrastructure

Usage (explicit invocation only):
    from src.enrichment.purview_client import PurviewClient
    from src.enrichment.lifecycle import LifecycleStore
    from src.enrichment.purview_writeback import PurviewWritebackService

    service = PurviewWritebackService(purview_client, lifecycle_store)
    result = service.write_suggested_description(
        entity_guid="12345-abcde-...",
        entity_type="table",
        suggested_description="AI-generated description.",
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

import requests

from .lifecycle import (
    LifecycleRecord,
    LifecycleStatus,
    LifecycleStore,
    LifecycleTransitionError,
    validate_transition,
)
from .purview_client import PurviewClient

logger = logging.getLogger("enrichment.purview_writeback")


# ---------------------------------------------------------------------------
# Error Classification
# ---------------------------------------------------------------------------

class WritebackErrorCategory(str, Enum):
    """Categorization of write-back failures for structured handling."""

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    ENTITY_NOT_FOUND = "entity_not_found"
    NETWORK = "network"
    LIFECYCLE_VIOLATION = "lifecycle_violation"
    AUTHORITATIVE_METADATA_CONFLICT = "authoritative_metadata_conflict"
    COSMOS_FAILURE = "cosmos_failure"
    PARTIAL_WRITE = "partial_write"
    UNKNOWN = "unknown"


class PurviewWritebackError(Exception):
    """Explicit, classifiable error from a write-back operation."""

    def __init__(
        self,
        message: str,
        category: WritebackErrorCategory,
        asset_id: str,
        correlation_id: str,
        original_error: Optional[Exception] = None,
    ) -> None:
        self.category = category
        self.asset_id = asset_id
        self.correlation_id = correlation_id
        self.original_error = original_error
        super().__init__(message)


# ---------------------------------------------------------------------------
# Write-back Result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WritebackResult:
    """Immutable outcome of a Purview write-back operation.

    Attributes:
        success:            Whether the write-back completed successfully.
        asset_id:           The entity GUID that was targeted.
        correlation_id:     End-to-end traceability identifier.
        lifecycle_status:   The lifecycle status after the operation.
        operation:          The operation performed (write, approve, reject).
        error:              Error message if the operation failed.
        error_category:     Classified error category if failed.
        purview_response:   Raw Purview API response on success.
    """

    success: bool
    asset_id: str
    correlation_id: str
    lifecycle_status: Optional[str] = None
    operation: str = ""
    error: Optional[str] = None
    error_category: Optional[str] = None
    purview_written: bool = False
    description_hash: Optional[str] = None
    purview_response: Optional[Dict[str, Any]] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Purview Write-back Service
# ---------------------------------------------------------------------------

class PurviewWritebackService:
    """
    Controlled write-back of Suggested Descriptions to Microsoft Purview.

    This service enforces the full governance chain:
    1. Lifecycle status check (Cosmos DB)
    2. Entity existence verification (Purview read)
    3. Authoritative metadata protection
    4. Atomic write of AI_Enrichment.suggested_description (Business Metadata POST)
    5. Lifecycle state persistence (Cosmos DB)
    6. Audit record creation (Cosmos DB)

    All operations target exactly ONE asset. No batch processing.
    All operations are explicitly invoked. Nothing runs automatically.

    Lifecycle:
        service = PurviewWritebackService(purview_client, lifecycle_store)
        result = service.write_suggested_description(guid, type, desc, corr_id)
        # Later, after human review:
        result = service.approve(guid, type, corr_id)
        # or
        result = service.reject(guid, type, corr_id)
    """

    def __init__(
        self,
        purview_client: PurviewClient,
        lifecycle_store: LifecycleStore,
    ) -> None:
        self._purview = purview_client
        self._lifecycle_store = lifecycle_store

        logger.info("PurviewWritebackService initialized")

    @staticmethod
    def _compute_description_hash(description: str) -> str:
        """Compute a deterministic SHA-256 hash of a description string.

        Used to bind lifecycle approvals to a specific description version.
        """
        return hashlib.sha256(description.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Primary Write Operation
    # ------------------------------------------------------------------

    def write_suggested_description(
        self,
        entity_guid: str,
        entity_type: str,
        suggested_description: str,
        correlation_id: str,
    ) -> WritebackResult:
        """
        Write a Suggested Description to a single Purview entity.

        This method enforces the full governance chain before writing:
        1. Reads lifecycle state from Cosmos DB
        2. Blocks if existing lifecycle is approved or rejected
        3. Reads the entity from Purview to confirm existence
        4. Writes ONLY to AI_Enrichment.suggested_description (Business Metadata)
        5. Creates a PENDING lifecycle record in Cosmos DB
        6. Creates an audit record in Cosmos DB

        Args:
            entity_guid:           The GUID of the Purview entity.
            entity_type:           The entity type (partition key for Cosmos).
            suggested_description: The AI-generated description to write.
            correlation_id:        End-to-end traceability identifier.

        Returns:
            WritebackResult with success status and audit details.

        Raises:
            PurviewWritebackError: On any classified failure.
        """
        log_extra = {
            "assetId": entity_guid,
            "correlationId": correlation_id,
            "entityType": entity_type,
            "operation": "write_suggested_description",
        }

        logger.info(
            "Starting Purview write-back for single asset",
            extra=log_extra,
        )

        # -- Step 1: Check lifecycle status in Cosmos DB ------------------
        try:
            existing_record = self._lifecycle_store.get_lifecycle_record(
                asset_id=entity_guid,
                entity_type=entity_type,
            )
        except Exception as exc:
            return self._handle_cosmos_failure(
                exc, entity_guid, correlation_id, "lifecycle_read", log_extra
            )

        current_status = existing_record.status if existing_record else None

        # -- Step 2: Validate lifecycle transition → PENDING --------------
        try:
            validate_transition(current_status, LifecycleStatus.PENDING, entity_guid)
        except LifecycleTransitionError as exc:
            logger.warning(
                "Write-back BLOCKED — lifecycle violation: %s",
                exc,
                extra={**log_extra, "currentLifecycleStatus": current_status.value if current_status else None},
            )
            self._write_audit(
                asset_id=entity_guid,
                entity_type=entity_type,
                correlation_id=correlation_id,
                operation="write_suggested_description",
                outcome="BLOCKED",
                reason=str(exc),
                lifecycle_status=current_status.value if current_status else None,
            )
            return WritebackResult(
                success=False,
                asset_id=entity_guid,
                correlation_id=correlation_id,
                lifecycle_status=current_status.value if current_status else None,
                operation="write_suggested_description",
                error=str(exc),
                error_category=WritebackErrorCategory.LIFECYCLE_VIOLATION.value,
            )

        # -- Step 3: Read entity from Purview to verify existence ---------
        try:
            entity = self._purview.get_entity(entity_guid)
        except requests.HTTPError as exc:
            return self._handle_purview_http_error(
                exc, entity_guid, correlation_id, "entity_read", log_extra
            )
        except requests.ConnectionError as exc:
            return self._handle_network_error(
                exc, entity_guid, correlation_id, "entity_read", log_extra
            )
        except Exception as exc:
            return self._handle_unknown_error(
                exc, entity_guid, correlation_id, "entity_read", log_extra
            )

        # -- Step 4: Verify no authoritative metadata conflict ------------
        entity_attrs = entity.get("entity", {}).get("attributes", {})
        authoritative_desc = entity_attrs.get("description", "")
        if authoritative_desc and authoritative_desc.strip():
            logger.info(
                "Authoritative description exists — write-back proceeds to "
                "AI_Enrichment.suggested_description only (authoritative metadata untouched)",
                extra={
                    **log_extra,
                    "authoritativeDescriptionLength": len(authoritative_desc),
                },
            )

        # -- Step 5: Write AI_Enrichment Business Metadata to Purview -----
        try:
            purview_response = self._purview.write_suggested_description(
                entity_guid=entity_guid,
                description=suggested_description,
            )
        except requests.HTTPError as exc:
            return self._handle_purview_http_error(
                exc, entity_guid, correlation_id, "write", log_extra
            )
        except requests.ConnectionError as exc:
            return self._handle_network_error(
                exc, entity_guid, correlation_id, "write", log_extra
            )
        except Exception as exc:
            return self._handle_unknown_error(
                exc, entity_guid, correlation_id, "write", log_extra
            )

        # -- Step 6: Create PENDING lifecycle record in Cosmos DB ---------
        # CRITICAL: Purview has already been written at this point.
        # If Cosmos fails here, we have a PARTIAL WRITE — Purview modified
        # but no lifecycle/audit record. The result must make this explicit.
        now_iso = datetime.now(timezone.utc).isoformat()
        desc_hash = self._compute_description_hash(suggested_description)
        new_record = LifecycleRecord(
            asset_id=entity_guid,
            entity_type=entity_type,
            correlation_id=correlation_id,
            status=LifecycleStatus.PENDING,
            suggested_description=suggested_description,
            description_hash=desc_hash,
            created_at=existing_record.created_at if existing_record else now_iso,
            updated_at=now_iso,
        )

        try:
            self._lifecycle_store.upsert_lifecycle_record(new_record)
        except Exception as exc:
            # PARTIAL WRITE: Purview updated, Cosmos failed.
            error_msg = (
                f"PARTIAL WRITE: Purview AI_Enrichment Business Metadata was written successfully, "
                f"but Cosmos DB lifecycle record failed: {exc}. "
                f"Manual reconciliation required for asset '{entity_guid}'."
            )
            logger.error(
                error_msg,
                extra={
                    **log_extra,
                    "errorCategory": WritebackErrorCategory.PARTIAL_WRITE.value,
                    "phase": "lifecycle_write",
                    "purviewWritten": True,
                },
                exc_info=True,
            )
            try:
                self._write_audit(
                    asset_id=entity_guid,
                    entity_type=entity_type,
                    correlation_id=correlation_id,
                    operation="write_suggested_description",
                    outcome="PARTIAL_WRITE",
                    reason=error_msg,
                    error_category=WritebackErrorCategory.PARTIAL_WRITE.value,
                    lifecycle_status=None,
                )
            except Exception:
                logger.error(
                    "Failed to write audit record after partial write",
                    extra={**log_extra, "phase": "audit_write_after_partial"},
                    exc_info=True,
                )
            return WritebackResult(
                success=False,
                asset_id=entity_guid,
                correlation_id=correlation_id,
                operation="write_suggested_description",
                error=error_msg,
                error_category=WritebackErrorCategory.PARTIAL_WRITE.value,
                purview_written=True,
                description_hash=desc_hash,
                purview_response=purview_response,
            )

        # -- Step 7: Write audit record -----------------------------------
        self._write_audit(
            asset_id=entity_guid,
            entity_type=entity_type,
            correlation_id=correlation_id,
            operation="write_suggested_description",
            outcome="SUCCESS",
            reason="Suggested Description written to Purview",
            lifecycle_status=LifecycleStatus.PENDING.value,
            suggested_description_length=len(suggested_description),
        )

        logger.info(
            "Purview write-back completed successfully",
            extra={
                **log_extra,
                "lifecycleStatus": LifecycleStatus.PENDING.value,
                "purviewResult": "SUCCESS",
                "descriptionLength": len(suggested_description),
            },
        )

        return WritebackResult(
            success=True,
            asset_id=entity_guid,
            correlation_id=correlation_id,
            lifecycle_status=LifecycleStatus.PENDING.value,
            operation="write_suggested_description",
            purview_written=True,
            description_hash=desc_hash,
            purview_response=purview_response,
        )

    # ------------------------------------------------------------------
    # Lifecycle Transitions
    # ------------------------------------------------------------------

    def approve(
        self,
        entity_guid: str,
        entity_type: str,
        correlation_id: str,
    ) -> WritebackResult:
        """
        Approve a pending Suggested Description.

        Transitions lifecycle status from PENDING → APPROVED.
        Does NOT modify any Purview data.

        Args:
            entity_guid:    The GUID of the Purview entity.
            entity_type:    The entity type (partition key for Cosmos).
            correlation_id: End-to-end traceability identifier.

        Returns:
            WritebackResult with the transition outcome.
        """
        return self._transition_lifecycle(
            entity_guid=entity_guid,
            entity_type=entity_type,
            target_status=LifecycleStatus.APPROVED,
            correlation_id=correlation_id,
        )

    def reject(
        self,
        entity_guid: str,
        entity_type: str,
        correlation_id: str,
    ) -> WritebackResult:
        """
        Reject a pending Suggested Description.

        Transitions lifecycle status from PENDING → REJECTED.
        Does NOT modify any Purview data.

        Args:
            entity_guid:    The GUID of the Purview entity.
            entity_type:    The entity type (partition key for Cosmos).
            correlation_id: End-to-end traceability identifier.

        Returns:
            WritebackResult with the transition outcome.
        """
        return self._transition_lifecycle(
            entity_guid=entity_guid,
            entity_type=entity_type,
            target_status=LifecycleStatus.REJECTED,
            correlation_id=correlation_id,
        )

    def _transition_lifecycle(
        self,
        entity_guid: str,
        entity_type: str,
        target_status: LifecycleStatus,
        correlation_id: str,
    ) -> WritebackResult:
        """Internal: execute a lifecycle transition with full audit."""
        operation = f"lifecycle_{target_status.value}"
        log_extra = {
            "assetId": entity_guid,
            "correlationId": correlation_id,
            "entityType": entity_type,
            "operation": operation,
            "targetStatus": target_status.value,
        }

        logger.info(
            "Starting lifecycle transition",
            extra=log_extra,
        )

        # Read current lifecycle
        try:
            existing_record = self._lifecycle_store.get_lifecycle_record(
                asset_id=entity_guid,
                entity_type=entity_type,
            )
        except Exception as exc:
            return self._handle_cosmos_failure(
                exc, entity_guid, correlation_id, "lifecycle_read", log_extra
            )

        if existing_record is None:
            error_msg = (
                f"No lifecycle record found for asset '{entity_guid}'. "
                f"Cannot transition to '{target_status.value}' without a prior write."
            )
            logger.warning(error_msg, extra=log_extra)
            return WritebackResult(
                success=False,
                asset_id=entity_guid,
                correlation_id=correlation_id,
                operation=operation,
                error=error_msg,
                error_category=WritebackErrorCategory.LIFECYCLE_VIOLATION.value,
            )

        current_status = existing_record.status

        # Validate transition
        try:
            validate_transition(current_status, target_status, entity_guid)
        except LifecycleTransitionError as exc:
            logger.warning(
                "Lifecycle transition BLOCKED: %s",
                exc,
                extra={**log_extra, "currentLifecycleStatus": current_status.value},
            )
            self._write_audit(
                asset_id=entity_guid,
                entity_type=entity_type,
                correlation_id=correlation_id,
                operation=operation,
                outcome="BLOCKED",
                reason=str(exc),
                lifecycle_status=current_status.value,
            )
            return WritebackResult(
                success=False,
                asset_id=entity_guid,
                correlation_id=correlation_id,
                lifecycle_status=current_status.value,
                operation=operation,
                error=str(exc),
                error_category=WritebackErrorCategory.LIFECYCLE_VIOLATION.value,
            )

        # Execute transition
        now_iso = datetime.now(timezone.utc).isoformat()
        updated_record = LifecycleRecord(
            asset_id=entity_guid,
            entity_type=entity_type,
            correlation_id=correlation_id,
            status=target_status,
            suggested_description=existing_record.suggested_description,
            description_hash=existing_record.description_hash,
            created_at=existing_record.created_at,
            updated_at=now_iso,
        )

        try:
            self._lifecycle_store.upsert_lifecycle_record(updated_record)
        except Exception as exc:
            return self._handle_cosmos_failure(
                exc, entity_guid, correlation_id, "lifecycle_write", log_extra
            )

        # Write audit
        self._write_audit(
            asset_id=entity_guid,
            entity_type=entity_type,
            correlation_id=correlation_id,
            operation=operation,
            outcome="SUCCESS",
            reason=f"Lifecycle transitioned: {current_status.value} → {target_status.value}",
            lifecycle_status=target_status.value,
        )

        logger.info(
            "Lifecycle transition completed",
            extra={
                **log_extra,
                "previousStatus": current_status.value,
                "newStatus": target_status.value,
            },
        )

        return WritebackResult(
            success=True,
            asset_id=entity_guid,
            correlation_id=correlation_id,
            lifecycle_status=target_status.value,
            operation=operation,
            description_hash=existing_record.description_hash,
        )

    # ------------------------------------------------------------------
    # Error Handlers (private)
    # ------------------------------------------------------------------

    def _handle_purview_http_error(
        self,
        exc: requests.HTTPError,
        asset_id: str,
        correlation_id: str,
        phase: str,
        log_extra: Dict[str, Any],
    ) -> WritebackResult:
        """Classify and handle Purview HTTP errors."""
        status_code = exc.response.status_code if exc.response is not None else 0

        if status_code == 401:
            category = WritebackErrorCategory.AUTHENTICATION
        elif status_code == 403:
            category = WritebackErrorCategory.AUTHORIZATION
        elif status_code == 404:
            category = WritebackErrorCategory.ENTITY_NOT_FOUND
        else:
            category = WritebackErrorCategory.UNKNOWN

        error_msg = (
            f"Purview API error during {phase}: "
            f"HTTP {status_code} — {exc}"
        )

        logger.error(
            error_msg,
            extra={
                **log_extra,
                "errorCategory": category.value,
                "httpStatusCode": status_code,
                "phase": phase,
            },
            exc_info=True,
        )

        self._write_audit(
            asset_id=asset_id,
            entity_type=log_extra.get("entityType", "unknown"),
            correlation_id=correlation_id,
            operation=log_extra.get("operation", "unknown"),
            outcome="ERROR",
            reason=error_msg,
            error_category=category.value,
        )

        return WritebackResult(
            success=False,
            asset_id=asset_id,
            correlation_id=correlation_id,
            operation=log_extra.get("operation", "unknown"),
            error=error_msg,
            error_category=category.value,
        )

    def _handle_network_error(
        self,
        exc: Exception,
        asset_id: str,
        correlation_id: str,
        phase: str,
        log_extra: Dict[str, Any],
    ) -> WritebackResult:
        """Handle network/connection errors."""
        error_msg = f"Network error during {phase}: {exc}"

        logger.error(
            error_msg,
            extra={
                **log_extra,
                "errorCategory": WritebackErrorCategory.NETWORK.value,
                "phase": phase,
            },
            exc_info=True,
        )

        self._write_audit(
            asset_id=asset_id,
            entity_type=log_extra.get("entityType", "unknown"),
            correlation_id=correlation_id,
            operation=log_extra.get("operation", "unknown"),
            outcome="ERROR",
            reason=error_msg,
            error_category=WritebackErrorCategory.NETWORK.value,
        )

        return WritebackResult(
            success=False,
            asset_id=asset_id,
            correlation_id=correlation_id,
            operation=log_extra.get("operation", "unknown"),
            error=error_msg,
            error_category=WritebackErrorCategory.NETWORK.value,
        )

    def _handle_cosmos_failure(
        self,
        exc: Exception,
        asset_id: str,
        correlation_id: str,
        phase: str,
        log_extra: Dict[str, Any],
    ) -> WritebackResult:
        """Handle Cosmos DB failures."""
        error_msg = f"Cosmos DB error during {phase}: {exc}"

        logger.error(
            error_msg,
            extra={
                **log_extra,
                "errorCategory": WritebackErrorCategory.COSMOS_FAILURE.value,
                "phase": phase,
            },
            exc_info=True,
        )

        # Audit write may also fail if Cosmos is down, but attempt it.
        try:
            self._write_audit(
                asset_id=asset_id,
                entity_type=log_extra.get("entityType", "unknown"),
                correlation_id=correlation_id,
                operation=log_extra.get("operation", "unknown"),
                outcome="ERROR",
                reason=error_msg,
                error_category=WritebackErrorCategory.COSMOS_FAILURE.value,
            )
        except Exception:
            logger.error(
                "Failed to write audit record after Cosmos failure",
                extra={**log_extra, "phase": "audit_write_after_cosmos_failure"},
                exc_info=True,
            )

        return WritebackResult(
            success=False,
            asset_id=asset_id,
            correlation_id=correlation_id,
            operation=log_extra.get("operation", "unknown"),
            error=error_msg,
            error_category=WritebackErrorCategory.COSMOS_FAILURE.value,
        )

    def _handle_unknown_error(
        self,
        exc: Exception,
        asset_id: str,
        correlation_id: str,
        phase: str,
        log_extra: Dict[str, Any],
    ) -> WritebackResult:
        """Handle unclassified errors."""
        error_msg = f"Unexpected error during {phase}: {type(exc).__name__}: {exc}"

        logger.error(
            error_msg,
            extra={
                **log_extra,
                "errorCategory": WritebackErrorCategory.UNKNOWN.value,
                "phase": phase,
            },
            exc_info=True,
        )

        self._write_audit(
            asset_id=asset_id,
            entity_type=log_extra.get("entityType", "unknown"),
            correlation_id=correlation_id,
            operation=log_extra.get("operation", "unknown"),
            outcome="ERROR",
            reason=error_msg,
            error_category=WritebackErrorCategory.UNKNOWN.value,
        )

        return WritebackResult(
            success=False,
            asset_id=asset_id,
            correlation_id=correlation_id,
            operation=log_extra.get("operation", "unknown"),
            error=error_msg,
            error_category=WritebackErrorCategory.UNKNOWN.value,
        )

    # ------------------------------------------------------------------
    # Audit Helper
    # ------------------------------------------------------------------

    def _write_audit(
        self,
        asset_id: str,
        entity_type: str,
        correlation_id: str,
        operation: str,
        outcome: str,
        reason: str,
        lifecycle_status: Optional[str] = None,
        error_category: Optional[str] = None,
        suggested_description_length: Optional[int] = None,
    ) -> None:
        """Write an audit record to Cosmos DB. Best-effort — failures logged."""
        now_iso = datetime.now(timezone.utc).isoformat()
        audit_id = f"wb:{asset_id}:{correlation_id}"

        audit_record: Dict[str, Any] = {
            "id": audit_id,
            "entityType": entity_type,
            "assetId": asset_id,
            "correlationId": correlation_id,
            "operation": operation,
            "outcome": outcome,
            "reason": reason,
            "recordType": "writeback_audit",
            "timestamp": now_iso,
        }

        if lifecycle_status is not None:
            audit_record["lifecycleStatus"] = lifecycle_status
        if error_category is not None:
            audit_record["errorCategory"] = error_category
        if suggested_description_length is not None:
            audit_record["suggestedDescriptionLength"] = suggested_description_length

        try:
            self._lifecycle_store.write_audit_record(audit_record)
        except Exception as audit_exc:
            # Audit write failure must not break the primary operation.
            logger.error(
                "Failed to write audit record: %s",
                audit_exc,
                extra={
                    "assetId": asset_id,
                    "correlationId": correlation_id,
                    "operation": operation,
                    "auditWriteError": str(audit_exc),
                },
                exc_info=True,
            )
