"""
Lifecycle Management for Purview Write-back Operations.

Defines the lifecycle states and transition rules for AI-generated
Suggested Description write-backs. Provides a Cosmos DB-backed store
for persisting lifecycle and audit records.

Lifecycle states:
    pending   — Suggested Description written to Purview, awaiting review.
    approved  — Human reviewer accepted the suggestion.
    rejected  — Human reviewer rejected the suggestion.

Valid transitions:
    (none)    → pending    (initial write)
    pending   → approved   (human approval)
    pending   → rejected   (human rejection)

Invariants:
    - Only a "pending" entry may be overwritten with a new write.
    - An "approved" or "rejected" entry BLOCKS further writes.
    - Transitions are enforced deterministically.

This module does NOT:
    - Import or invoke the Orchestrator
    - Invoke any LLM or AI service
    - Write to Purview (that is the write-back service's responsibility)
    - Modify validation rules or frozen contracts

Authentication: Cosmos DB access via azure.cosmos ContainerProxy
(caller provides pre-authenticated container proxies).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("enrichment.lifecycle")


# ---------------------------------------------------------------------------
# Lifecycle Status
# ---------------------------------------------------------------------------

class LifecycleStatus(str, Enum):
    """Explicit lifecycle states for Suggested Description write-backs."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Transition Rules
# ---------------------------------------------------------------------------

# Maps current status → set of allowed target statuses.
# None represents the absence of any prior lifecycle record.
VALID_TRANSITIONS: Dict[Optional[LifecycleStatus], set[LifecycleStatus]] = {
    None: {LifecycleStatus.PENDING},
    LifecycleStatus.PENDING: {LifecycleStatus.PENDING, LifecycleStatus.APPROVED, LifecycleStatus.REJECTED},
    LifecycleStatus.APPROVED: set(),   # Terminal — no transitions allowed
    LifecycleStatus.REJECTED: set(),   # Terminal — no transitions allowed
}


class LifecycleTransitionError(Exception):
    """Raised when an invalid lifecycle transition is attempted."""

    def __init__(
        self,
        current_status: Optional[LifecycleStatus],
        target_status: LifecycleStatus,
        asset_id: str,
    ) -> None:
        self.current_status = current_status
        self.target_status = target_status
        self.asset_id = asset_id
        current_label = current_status.value if current_status else "(none)"
        super().__init__(
            f"Invalid lifecycle transition for asset '{asset_id}': "
            f"'{current_label}' → '{target_status.value}'. "
            f"Allowed targets from '{current_label}': "
            f"{sorted(s.value for s in VALID_TRANSITIONS.get(current_status, set()))}."
        )


def validate_transition(
    current_status: Optional[LifecycleStatus],
    target_status: LifecycleStatus,
    asset_id: str,
) -> None:
    """Validate a lifecycle transition. Raises LifecycleTransitionError on failure.

    If a status value is not present in VALID_TRANSITIONS (e.g., a future
    state like 'expired'), this defaults to an empty allowed set, which
    means the transition is BLOCKED. This guarantees that adding new enum
    values without updating VALID_TRANSITIONS fails explicitly rather than
    allowing undefined behavior.
    """
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise LifecycleTransitionError(current_status, target_status, asset_id)


# ---------------------------------------------------------------------------
# Lifecycle Record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LifecycleRecord:
    """Immutable snapshot of a lifecycle record for a single asset."""

    asset_id: str
    entity_type: str
    correlation_id: str
    status: LifecycleStatus
    suggested_description: str
    description_hash: str
    created_at: str
    updated_at: str

    def to_cosmos_item(self) -> Dict[str, Any]:
        """Serialize to a Cosmos DB document."""
        return {
            "id": self.asset_id,
            "entityType": self.entity_type,
            "correlationId": self.correlation_id,
            "lifecycleStatus": self.status.value,
            "suggestedDescription": self.suggested_description,
            "descriptionHash": self.description_hash,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "recordType": "lifecycle",
        }

    @classmethod
    def from_cosmos_item(cls, item: Dict[str, Any]) -> LifecycleRecord:
        """Deserialize from a Cosmos DB document."""
        desc = item.get("suggestedDescription", "")
        return cls(
            asset_id=item["id"],
            entity_type=item["entityType"],
            correlation_id=item["correlationId"],
            status=LifecycleStatus(item["lifecycleStatus"]),
            suggested_description=desc,
            description_hash=item.get(
                "descriptionHash",
                hashlib.sha256(desc.encode("utf-8")).hexdigest(),
            ),
            created_at=item["createdAt"],
            updated_at=item["updatedAt"],
        )


# ---------------------------------------------------------------------------
# Lifecycle Store (Cosmos DB)
# ---------------------------------------------------------------------------

class LifecycleStore:
    """
    Cosmos DB-backed store for lifecycle and audit records.

    Accepts pre-authenticated ContainerProxy objects. Does not manage
    credentials or Cosmos client lifecycle — the caller is responsible.

    Container expectations:
        lifecycle_container: partition key = /entityType
        audit_container:     partition key = /entityType
    """

    def __init__(
        self,
        lifecycle_container: Any,
        audit_container: Any,
    ) -> None:
        self._lifecycle = lifecycle_container
        self._audit = audit_container

    def get_lifecycle_record(
        self,
        asset_id: str,
        entity_type: str,
    ) -> Optional[LifecycleRecord]:
        """
        Read a lifecycle record from Cosmos DB.

        Returns None if no record exists for this asset.
        """
        try:
            item = self._lifecycle.read_item(
                item=asset_id,
                partition_key=entity_type,
            )
            record = LifecycleRecord.from_cosmos_item(item)
            logger.debug(
                "Lifecycle record read",
                extra={
                    "assetId": asset_id,
                    "entityType": entity_type,
                    "lifecycleStatus": record.status.value,
                },
            )
            return record
        except Exception as exc:
            # CosmosResourceNotFoundError or any read failure
            exc_name = type(exc).__name__
            if "NotFound" in exc_name or "ResourceNotFound" in exc_name:
                logger.debug(
                    "No lifecycle record found (expected for new assets)",
                    extra={"assetId": asset_id, "entityType": entity_type},
                )
                return None
            raise

    def upsert_lifecycle_record(self, record: LifecycleRecord) -> Dict[str, Any]:
        """Create or update a lifecycle record in Cosmos DB."""
        item = record.to_cosmos_item()
        result = self._lifecycle.upsert_item(body=item)
        logger.info(
            "Lifecycle record upserted",
            extra={
                "assetId": record.asset_id,
                "entityType": record.entity_type,
                "lifecycleStatus": record.status.value,
                "correlationId": record.correlation_id,
            },
        )
        return result

    def write_audit_record(self, audit: Dict[str, Any]) -> Dict[str, Any]:
        """Write an audit record to the audit container."""
        result = self._audit.upsert_item(body=audit)
        logger.info(
            "Writeback audit record created",
            extra={
                "auditId": audit.get("id"),
                "assetId": audit.get("assetId"),
                "entityType": audit.get("entityType"),
                "operation": audit.get("operation"),
                "correlationId": audit.get("correlationId"),
            },
        )
        return result
