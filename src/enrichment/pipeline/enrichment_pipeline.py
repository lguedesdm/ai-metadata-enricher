"""
Enrichment Pipeline — Deterministic single-asset enrichment execution.

This module integrates all enrichment components into one deterministic,
sequential pipeline for a single asset.

Pipeline steps (in order):
  1. RAG retrieval       — AISearchClient hybrid search via RAGQueryPipeline
  2. Prompt construction — build_llm_messages() from frozen prompt contract
  3. LLM invocation      — AzureOpenAIClient.complete() [EXACTLY ONE CALL]
  4. Validation          — validate_llm_output() blocking + advisory rules
  5. Purview writeback   — PurviewWritebackService (only on PASS)
  6. State update        — state_store.upsert_state() (only after writeback)
  7. Audit persistence   — state_store.upsert_audit() (always)

Pipeline behavior requirements enforced:
  - Exactly one LLM invocation per asset (single call site at Step 3)
  - RAG retrieval executes before LLM invocation (Steps 1-2 before Step 3)
  - LLM output must pass validation before writeback (Step 4 gates Step 5)
  - Writeback updates only Suggested Description (enforced by PurviewClient)
  - Official Description is never modified (enforced by PurviewClient)
  - Audit records include correlation_id (every record carries it)
  - State update only after successful writeback (Step 6 after Step 5 success)
  - Failure paths never write to Purview (returns before Step 5 on any failure)

This module does NOT:
  - Modify frozen contracts, prompt templates, or validation rules
  - Implement retries, batching, or performance optimizations
  - Contain domain logic (hashing, normalization, element splitting)
  - Create new Azure services or modify infrastructure definitions
"""

from __future__ import annotations

import logging
import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.orchestrator.cosmos_state_store import CosmosStateStore

logger = logging.getLogger("enrichment.pipeline")


# ---------------------------------------------------------------------------
# Pipeline Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnrichmentPipelineResult:
    """Immutable result of a single enrichment pipeline execution.

    Attributes:
        success:           True if all steps completed (validation PASS +
                           writeback success + state updated).
                           True on validation BLOCK (message is complete,
                           not a transient error).
                           False on any exception or writeback failure
                           (message should be abandoned for retry).
        asset_id:          The asset identifier targeted.
        correlation_id:    End-to-end traceability identifier.
        validation_status: "PASS", "BLOCK", or "ERROR".
        writeback_success: True if Purview writeback completed.
        error:             Error description if success is False.
    """

    success: bool
    asset_id: str
    correlation_id: str
    validation_status: str
    writeback_success: bool
    error: Optional[str] = field(default=None)


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def run_enrichment_pipeline(
    asset: Dict[str, Any],
    asset_id: str,
    entity_type: str,
    source_system: str,
    element_name: str,
    correlation_id: str,
    current_hash: str,
    state_store: Optional["CosmosStateStore"] = None,
    reference_time: Optional[datetime] = None,
) -> EnrichmentPipelineResult:
    """Execute the complete enrichment pipeline for a single asset.

    This is the sole integration point between the Orchestrator and the
    enrichment subsystem.  It is called exactly once per REPROCESS decision,
    for exactly one asset.

    The pipeline is deterministic:
      - Same inputs → same execution path → same Purview write
      - LLM is invoked at exactly one code site (Step 3)
      - No loops, no retries, no conditional second LLM calls
      - reference_time is propagated to RAG so retries use the same
        temporal context and produce the same ranked context chunks

    Args:
        asset:          Full asset metadata dictionary (from Service Bus payload).
        asset_id:       Stable asset identifier (asset["id"]).
        entity_type:    Asset entity type (e.g. "table", "column").
        source_system:  Source system identifier (e.g. "synergy").
        element_name:   Human-readable element name — used as RAG query text.
        correlation_id: Propagated from the orchestrator for end-to-end tracing.
        current_hash:   SHA-256 hash of the current asset metadata, computed
                        upstream by the orchestrator.  Written to state only
                        after successful Purview writeback.
        state_store:    CosmosStateStore instance (Managed Identity).
                        If None, state/audit persistence is skipped (test mode).
        reference_time: Fixed reference time for deterministic RAG freshness
                        scoring.  Generated once by the orchestrator and
                        propagated here so retries use the same temporal
                        context.  Defaults to datetime.now(utc) if not provided.

    Returns:
        EnrichmentPipelineResult describing the pipeline outcome.
    """
    # Establish reference time once — used for RAG freshness and state timestamp.
    # The orchestrator passes this in so all elements in a message share the
    # same temporal context across retries.
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)

    log_extra: Dict[str, Any] = {
        "correlationId": correlation_id,
        "assetId": asset_id,
        "entityType": entity_type,
        "sourceSystem": source_system,
        "elementName": element_name,
    }

    logger.info("Enrichment pipeline starting", extra=log_extra)

    # ------------------------------------------------------------------
    # STEP 1 — RAG Retrieval
    # ------------------------------------------------------------------
    try:
        rag_pipeline = _build_rag_pipeline()
        try:
            context = rag_pipeline.retrieve_context_for_asset(
                asset_id=asset_id,
                entity_type=entity_type,
                source_system=source_system,
                element_name=element_name,
                correlation_id=correlation_id,
                reference_time=reference_time,
            )
        finally:
            rag_pipeline.close()

        logger.info(
            "RAG retrieval complete",
            extra={
                **log_extra,
                "resultsUsed": context.results_used,
                "hasContext": context.has_context,
            },
        )
    except Exception as exc:
        error_msg = f"RAG retrieval failed: {type(exc).__name__}: {exc}"
        logger.error(error_msg, extra=log_extra, exc_info=True)
        _write_pipeline_audit(
            state_store=state_store,
            asset_id=asset_id,
            entity_type=entity_type,
            source_system=source_system,
            correlation_id=correlation_id,
            current_hash=current_hash,
            pipeline_step="rag_retrieval",
            outcome="ERROR",
            validation_status="ERROR",
            writeback_success=False,
            error=error_msg,
        )
        return EnrichmentPipelineResult(
            success=False,
            asset_id=asset_id,
            correlation_id=correlation_id,
            validation_status="ERROR",
            writeback_success=False,
            error=error_msg,
        )

    # ------------------------------------------------------------------
    # STEP 2 — Prompt Construction
    # ------------------------------------------------------------------
    from src.enrichment.llm.prompt_builder import build_llm_messages  # noqa: PLC0415

    messages = build_llm_messages(
        asset=asset,
        entity_type=entity_type,
        formatted_context=context.formatted_context,
    )

    logger.info(
        "Prompt constructed",
        extra={
            **log_extra,
            "messageCount": len(messages),
        },
    )

    # ------------------------------------------------------------------
    # STEP 3 — LLM Invocation [EXACTLY ONE CALL PER ASSET]
    # ------------------------------------------------------------------
    deployment_name = _get_deployment_name()
    execution_duration_ms: int = 0
    _llm_start = datetime.now(timezone.utc)
    try:
        llm_client = _build_llm_client()
        try:
            raw_output: str = llm_client.complete(messages=messages)
        finally:
            llm_client.close()
        execution_duration_ms = int(
            (datetime.now(timezone.utc) - _llm_start).total_seconds() * 1000
        )

        logger.info(
            "LLM invocation complete — one call executed",
            extra={
                **log_extra,
                "deployment": deployment_name,
                "rawOutputLength": len(raw_output),
                "executionDurationMs": execution_duration_ms,
            },
        )
    except Exception as exc:
        execution_duration_ms = int(
            (datetime.now(timezone.utc) - _llm_start).total_seconds() * 1000
        )
        error_msg = f"LLM invocation failed: {type(exc).__name__}: {exc}"
        logger.error(error_msg, extra=log_extra, exc_info=True)
        _write_pipeline_audit(
            state_store=state_store,
            asset_id=asset_id,
            entity_type=entity_type,
            source_system=source_system,
            correlation_id=correlation_id,
            current_hash=current_hash,
            pipeline_step="llm_invocation",
            outcome="ERROR",
            validation_status="ERROR",
            writeback_success=False,
            model=deployment_name,
            error=error_msg,
            execution_duration_ms=execution_duration_ms,
        )
        return EnrichmentPipelineResult(
            success=False,
            asset_id=asset_id,
            correlation_id=correlation_id,
            validation_status="ERROR",
            writeback_success=False,
            error=error_msg,
        )

    # ------------------------------------------------------------------
    # STEP 4 — Validation
    # ------------------------------------------------------------------
    from src.enrichment.output_validator import validate_llm_output  # noqa: PLC0415

    validation_result = validate_llm_output(
        raw_output=raw_output,
        correlation_id=correlation_id,
    )

    if validation_result.status.value == "BLOCK":
        logger.warning(
            "LLM output BLOCKED by validation — Purview not written",
            extra={
                **log_extra,
                "validationStatus": "BLOCK",
                "blockingErrors": validation_result.blocking_errors,
            },
        )
        _write_pipeline_audit(
            state_store=state_store,
            asset_id=asset_id,
            entity_type=entity_type,
            source_system=source_system,
            correlation_id=correlation_id,
            current_hash=current_hash,
            pipeline_step="validation",
            outcome="BLOCKED",
            validation_status="BLOCK",
            writeback_success=False,
            model=deployment_name,
            blocking_errors=validation_result.blocking_errors,
        )
        # Return success=True: validation BLOCK is not a transient error.
        # The message is complete — retrying immediately would produce the same
        # invalid output.  State is NOT updated (no writeback occurred).
        return EnrichmentPipelineResult(
            success=True,
            asset_id=asset_id,
            correlation_id=correlation_id,
            validation_status="BLOCK",
            writeback_success=False,
        )

    logger.info(
        "LLM output passed validation",
        extra={
            **log_extra,
            "validationStatus": "PASS",
            "advisoryFlagCount": len(validation_result.advisory_flags),
        },
    )

    # Extract suggested_description from validated YAML output
    suggested_description = _extract_suggested_description(raw_output)
    if not suggested_description:
        error_msg = (
            "Validation passed but suggested_description could not be "
            "extracted from LLM output."
        )
        logger.error(error_msg, extra=log_extra)
        _write_pipeline_audit(
            state_store=state_store,
            asset_id=asset_id,
            entity_type=entity_type,
            source_system=source_system,
            correlation_id=correlation_id,
            current_hash=current_hash,
            pipeline_step="description_extraction",
            outcome="ERROR",
            validation_status="PASS",
            writeback_success=False,
            model=deployment_name,
            error=error_msg,
        )
        return EnrichmentPipelineResult(
            success=False,
            asset_id=asset_id,
            correlation_id=correlation_id,
            validation_status="PASS",
            writeback_success=False,
            error=error_msg,
        )

    # ------------------------------------------------------------------
    # IDEMPOTENCY CHECK — skip writeback if already enriched at this hash
    # ------------------------------------------------------------------
    # Azure Service Bus uses at-least-once delivery.  If a container crashed
    # after Purview writeback but before the Cosmos state update, the message
    # is redelivered.  Check for an existing state record that confirms the
    # writeback already succeeded for this exact hash to prevent a duplicate
    # Purview write on replay.  Read failures are non-fatal — proceed with
    # writeback rather than silently dropping enrichment.
    if state_store is not None:
        try:
            existing_state = state_store.get_state(
                asset_id=asset_id,
                entity_type=entity_type,
            )
            if (
                existing_state is not None
                and existing_state.get("contentHash") == current_hash
            ):
                logger.info(
                    "Idempotency: asset already enriched at current hash — skipping writeback",
                    extra={
                        **log_extra,
                        "contentHash": current_hash[:16] + "...",
                        "idempotentSkip": True,
                    },
                )
                return EnrichmentPipelineResult(
                    success=True,
                    asset_id=asset_id,
                    correlation_id=correlation_id,
                    validation_status="PASS",
                    writeback_success=True,
                )
        except Exception as idempotency_exc:
            # Non-fatal: if state read fails, proceed with writeback.
            # Better a duplicate write than a silently dropped enrichment.
            logger.warning(
                "Idempotency state read failed — proceeding with writeback: %s",
                idempotency_exc,
                extra={**log_extra},
            )

    # ------------------------------------------------------------------
    # STEP 5 — Purview Writeback  (only reached on validation PASS)
    # ------------------------------------------------------------------
    from src.enrichment.purview_writeback import PurviewWritebackService  # noqa: PLC0415

    try:
        lifecycle_store = _build_lifecycle_store(state_store)
        purview_client = _build_purview_client()
        try:
            writeback_service = PurviewWritebackService(
                purview_client=purview_client,
                lifecycle_store=lifecycle_store,
            )
            writeback_result = writeback_service.write_suggested_description(
                entity_guid=asset_id,
                entity_type=entity_type,
                suggested_description=suggested_description,
                correlation_id=correlation_id,
            )
        finally:
            purview_client.close()
    except Exception as exc:
        error_msg = f"Purview writeback setup failed: {type(exc).__name__}: {exc}"
        logger.error(error_msg, extra=log_extra, exc_info=True)
        _write_pipeline_audit(
            state_store=state_store,
            asset_id=asset_id,
            entity_type=entity_type,
            source_system=source_system,
            correlation_id=correlation_id,
            current_hash=current_hash,
            pipeline_step="writeback_setup",
            outcome="ERROR",
            validation_status="PASS",
            writeback_success=False,
            model=deployment_name,
            error=error_msg,
        )
        return EnrichmentPipelineResult(
            success=False,
            asset_id=asset_id,
            correlation_id=correlation_id,
            validation_status="PASS",
            writeback_success=False,
            error=error_msg,
        )

    if not writeback_result.success:
        error_msg = (
            f"Purview writeback failed: {writeback_result.error} "
            f"(category={writeback_result.error_category})"
        )
        logger.error(error_msg, extra=log_extra)
        _write_pipeline_audit(
            state_store=state_store,
            asset_id=asset_id,
            entity_type=entity_type,
            source_system=source_system,
            correlation_id=correlation_id,
            current_hash=current_hash,
            pipeline_step="writeback",
            outcome="ERROR",
            validation_status="PASS",
            writeback_success=False,
            model=deployment_name,
            error=error_msg,
        )
        return EnrichmentPipelineResult(
            success=False,
            asset_id=asset_id,
            correlation_id=correlation_id,
            validation_status="PASS",
            writeback_success=False,
            error=error_msg,
        )

    logger.info(
        "Purview writeback succeeded — Suggested Description written",
        extra={
            **log_extra,
            "lifecycleStatus": writeback_result.lifecycle_status,
            "purviewWritten": True,
        },
    )

    # ------------------------------------------------------------------
    # STEP 6 — State Update  (only after successful writeback)
    # ------------------------------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()

    if state_store is not None:
        try:
            state_store.upsert_state({
                "id": asset_id,
                "entityType": entity_type,
                "sourceSystem": source_system,
                "contentHash": current_hash,
                "lastProcessed": now_iso,
            })
            logger.info(
                "State updated after successful writeback",
                extra={**log_extra, "authMethod": "ManagedIdentity"},
            )
        except Exception as exc:
            error_msg = f"State update failed after writeback: {type(exc).__name__}: {exc}"
            logger.error(error_msg, extra=log_extra, exc_info=True)
            # State update failure after successful writeback: the writeback
            # succeeded (Purview was written) but we cannot confirm state.
            # Write a best-effort audit record and return failure so the
            # message is abandoned — the next delivery will re-enrich but
            # the writeback will be blocked by the PENDING lifecycle record.
            _write_pipeline_audit(
                state_store=state_store,
                asset_id=asset_id,
                entity_type=entity_type,
                source_system=source_system,
                correlation_id=correlation_id,
                current_hash=current_hash,
                pipeline_step="state_update",
                outcome="ERROR",
                validation_status="PASS",
                writeback_success=True,
                model=deployment_name,
                error=error_msg,
            )
            return EnrichmentPipelineResult(
                success=False,
                asset_id=asset_id,
                correlation_id=correlation_id,
                validation_status="PASS",
                writeback_success=True,
                error=error_msg,
            )

    # ------------------------------------------------------------------
    # STEP 7 — Enrichment Audit Persistence
    # ------------------------------------------------------------------
    _write_pipeline_audit(
        state_store=state_store,
        asset_id=asset_id,
        entity_type=entity_type,
        source_system=source_system,
        correlation_id=correlation_id,
        current_hash=current_hash,
        pipeline_step="complete",
        outcome="SUCCESS",
        validation_status="PASS",
        writeback_success=True,
        model=deployment_name,
        advisory_flag_count=len(validation_result.advisory_flags),
        execution_duration_ms=execution_duration_ms,
    )

    logger.info(
        "Enrichment pipeline completed successfully",
        extra={
            **log_extra,
            "validationStatus": "PASS",
            "writebackSuccess": True,
        },
    )

    return EnrichmentPipelineResult(
        success=True,
        asset_id=asset_id,
        correlation_id=correlation_id,
        validation_status="PASS",
        writeback_success=True,
    )


# ---------------------------------------------------------------------------
# Internal helpers — client construction
# ---------------------------------------------------------------------------


def _build_rag_pipeline():
    """Construct a RAGQueryPipeline from environment configuration."""
    from src.enrichment.rag.pipeline import RAGQueryPipeline  # noqa: PLC0415
    from src.enrichment.rag.config import RAGConfig  # noqa: PLC0415

    config = RAGConfig()
    return RAGQueryPipeline(config)


def _build_llm_client():
    """Construct an AzureOpenAIClient from environment configuration."""
    from src.enrichment.llm_client import AzureOpenAIClient  # noqa: PLC0415
    from src.enrichment.config import EnrichmentConfig  # noqa: PLC0415

    config = EnrichmentConfig()
    return AzureOpenAIClient(config)


def _build_purview_client():
    """Construct a PurviewClient from environment configuration."""
    from src.enrichment.purview_client import PurviewClient  # noqa: PLC0415
    from src.enrichment.config import EnrichmentConfig  # noqa: PLC0415

    config = EnrichmentConfig()
    return PurviewClient(config)


def _get_deployment_name() -> str:
    """Retrieve the configured LLM deployment name (for audit records)."""
    import os  # noqa: PLC0415

    return os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "unknown")


def _build_lifecycle_store(state_store: Optional["CosmosStateStore"]):
    """Build a LifecycleStore from the CosmosStateStore connection.

    Constructs the LifecycleStore directly from infrastructure-layer
    ContainerProxy objects exposed by CosmosStateStore.  This preserves
    the correct dependency direction: enrichment → infrastructure.
    The orchestrator layer does NOT construct enrichment-layer objects.

    If state_store is None (test mode), returns a no-op stub.
    """
    if state_store is not None:
        from src.enrichment.lifecycle import LifecycleStore  # noqa: PLC0415

        return LifecycleStore(
            lifecycle_container=state_store.state_container,
            audit_container=state_store.audit_container,
        )

    return _NoOpLifecycleStore()


class _NoOpLifecycleStore:
    """Minimal LifecycleStore stub for environments without Cosmos DB.

    Used when state_store is None (e.g., isolated unit tests).
    All operations are no-ops; no state is persisted.
    """

    def get_lifecycle_record(self, asset_id: str, entity_type: str):
        return None

    def upsert_lifecycle_record(self, record) -> Dict[str, Any]:
        return {}

    def write_audit_record(self, audit: Dict[str, Any]) -> Dict[str, Any]:
        return {}


# ---------------------------------------------------------------------------
# Internal helpers — YAML extraction
# ---------------------------------------------------------------------------


def _extract_suggested_description(raw_output: str) -> str:
    """Extract the suggested_description field from validated YAML output.

    The output_validator guarantees the output is valid YAML with a
    non-empty suggested_description field before this is called.

    Returns:
        The suggested_description string, or "" on any parse failure.
    """
    try:
        parsed = yaml.safe_load(raw_output)
        if isinstance(parsed, dict):
            value = parsed.get("suggested_description", "")
            return str(value).strip() if value else ""
    except Exception as exc:
        logger.warning("Could not parse YAML to extract description: %s", exc)
    return ""


# ---------------------------------------------------------------------------
# Internal helpers — Audit record writing
# ---------------------------------------------------------------------------


def _write_pipeline_audit(
    state_store: Optional["CosmosStateStore"],
    asset_id: str,
    entity_type: str,
    source_system: str,
    correlation_id: str,
    current_hash: str,
    pipeline_step: str,
    outcome: str,
    validation_status: str,
    writeback_success: bool,
    model: str = "unknown",
    error: Optional[str] = None,
    blocking_errors: Optional[list] = None,
    advisory_flag_count: int = 0,
    execution_duration_ms: int = 0,
) -> None:
    """Write a pipeline audit record to Cosmos DB.

    Audit records always include correlation_id for end-to-end traceability.
    The token_usage field is 0 because AzureOpenAIClient.complete() returns
    only the response string — token counts are logged by the client itself.

    This function is best-effort: failures are logged but not re-raised.
    """
    if state_store is None:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    audit_id = f"enr:{asset_id}:{correlation_id}:{pipeline_step}"

    audit_record: Dict[str, Any] = {
        "id": audit_id,
        "entityType": entity_type,
        "assetId": asset_id,
        "sourceSystem": source_system,
        "correlationId": correlation_id,
        "contentHash": current_hash,
        "pipelineStep": pipeline_step,
        "outcome": outcome,
        "validationStatus": validation_status,
        "writebackSuccess": writeback_success,
        "model": model,
        "tokenUsage": 0,
        "executionDurationMs": execution_duration_ms,
        "advisoryFlagCount": advisory_flag_count,
        "recordType": "enrichment_audit",
        "processedAt": now_iso,
    }

    if error:
        audit_record["error"] = error
    if blocking_errors:
        audit_record["blockingErrors"] = blocking_errors

    try:
        state_store.upsert_audit(audit_record)
    except Exception as exc:
        logger.error(
            "Failed to write pipeline audit record: %s",
            exc,
            extra={
                "assetId": asset_id,
                "correlationId": correlation_id,
                "pipelineStep": pipeline_step,
            },
            exc_info=True,
        )
