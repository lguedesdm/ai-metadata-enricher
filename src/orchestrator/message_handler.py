"""
Message handler for the Orchestrator.

Processes a single Service Bus message by:
1. Parsing the JSON payload
2. Extracting asset identifiers
3. Computing the asset hash
4. Reading previous state from Cosmos DB (via Managed Identity)
5. Calling the domain-level decision logic (SKIP / REPROCESS)
6. On SKIP  — writing state and audit records to Cosmos DB
7. On REPROCESS — invoking the enrichment pipeline (RAG → LLM →
   Validation → Purview Writeback → State Update → Audit)
8. Logging the result with correlationId

Cosmos DB access uses Managed Identity exclusively — no keys or secrets.

Pipeline integration contract:
- The orchestrator does NOT contain enrichment logic.
- Enrichment logic lives exclusively in src/enrichment/pipeline/.
- State is updated only after successful Purview writeback (REPROCESS path).
- On SKIP the state is confirmed immediately (no writeback needed).
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.domain.change_detection import (
    DecisionResult,
    compute_asset_hash,
    decide_reprocess_or_skip,
)

if TYPE_CHECKING:
    from .cosmos_state_store import CosmosStateStore

logger = logging.getLogger("orchestrator.handler")


class MessageProcessingResult:
    """Immutable result of processing a single message."""

    __slots__ = ("correlation_id", "asset_id", "decision", "success", "error")

    def __init__(
        self,
        correlation_id: str,
        asset_id: str,
        decision: str | None,
        success: bool,
        error: str | None = None,
    ) -> None:
        self.correlation_id = correlation_id
        self.asset_id = asset_id
        self.decision = decision
        self.success = success
        self.error = error


def handle_message(
    message_body: str | bytes,
    state_store: Optional["CosmosStateStore"] = None,
) -> MessageProcessingResult:
    """
    Process a single Service Bus message.

    The message body is expected to be a JSON object conforming to one of
    the frozen asset schemas (synergy-export or zipline-export).

    If a CosmosStateStore is provided, the handler will:
    - Read previous state from the 'state' container
    - Write updated state after computing the hash
    - Write an audit record to the 'audit' container

    All Cosmos DB access uses Managed Identity — no keys or secrets.

    Args:
        message_body: Raw message body (str or bytes).
        state_store:  Optional Cosmos DB state store (Managed Identity).

    Returns:
        MessageProcessingResult with the decision outcome.
    """
    correlation_id = str(uuid.uuid4())

    logger.info(
        "Processing started",
        extra={
            "correlationId": correlation_id,
            "phase": "START",
        },
    )

    try:
        # -- Parse payload --------------------------------------------------
        body_str = (
            message_body.decode("utf-8")
            if isinstance(message_body, (bytes, bytearray))
            else message_body
        )
        asset: Dict[str, Any] = json.loads(body_str)

        # -- Extract identifiers -------------------------------------------
        asset_id: str = asset.get("id", "unknown")
        source_system: str = asset.get("sourceSystem", "unknown")
        entity_type: str = asset.get("entityType", "unknown")

        logger.info(
            "Asset identified",
            extra={
                "correlationId": correlation_id,
                "assetId": asset_id,
                "sourceSystem": source_system,
                "entityType": entity_type,
            },
        )

        # -- Compute hash --------------------------------------------------
        current_hash: str = compute_asset_hash(asset)

        # -- Read previous state from Cosmos DB (if available) -------------
        # Domain contract: if previous state cannot be determined for ANY
        # reason (no store, not found, Cosmos failure), default to
        # previous_state = None → REPROCESS.  Cosmos read failures must
        # never cause message ABANDON.
        previous_state = None
        if state_store is not None:
            try:
                previous_item = state_store.get_state(
                    asset_id=asset_id,
                    entity_type=entity_type,
                )
                if previous_item is not None:
                    previous_state = previous_item.get("contentHash")
                    logger.info(
                        "Previous state loaded from Cosmos DB",
                        extra={
                            "correlationId": correlation_id,
                            "assetId": asset_id,
                            "authMethod": "ManagedIdentity",
                        },
                    )
            except Exception as cosmos_read_exc:
                # Deterministic fallback: treat as no previous state → REPROCESS.
                # This covers 429 throttling, 403 auth errors, timeouts, and
                # any other transient or permanent Cosmos failure.
                logger.warning(
                    "Cosmos DB state read failed — falling back to REPROCESS: %s",
                    cosmos_read_exc,
                    extra={
                        "correlationId": correlation_id,
                        "assetId": asset_id,
                        "entityType": entity_type,
                        "cosmosError": type(cosmos_read_exc).__name__,
                        "fallbackDecision": "REPROCESS",
                    },
                )
                # previous_state remains None → REPROCESS

        # -- Domain decision -----------------------------------------------
        decision: DecisionResult = decide_reprocess_or_skip(
            current_hash=current_hash,
            previous_state=previous_state,
        )

        logger.info(
            "Decision: %s",
            decision.value,
            extra={
                "correlationId": correlation_id,
                "assetId": asset_id,
                "sourceSystem": source_system,
                "entityType": entity_type,
                "decision": decision.value,
                "currentHash": current_hash[:16] + "...",
            },
        )

        # -- Branch on decision -------------------------------------------
        now_iso = datetime.now(timezone.utc).isoformat()

        if decision == DecisionResult.SKIP:
            # SKIP: asset unchanged — write state confirmation + audit.
            # No enrichment pipeline invocation.
            if state_store is not None:
                state_store.upsert_state({
                    "id": asset_id,
                    "entityType": entity_type,
                    "sourceSystem": source_system,
                    "contentHash": current_hash,
                    "decision": decision.value,
                    "correlationId": correlation_id,
                    "updatedAt": now_iso,
                })
                audit_id = f"orch:{asset_id}:{correlation_id}"
                state_store.upsert_audit({
                    "id": audit_id,
                    "entityType": entity_type,
                    "assetId": asset_id,
                    "sourceSystem": source_system,
                    "decision": decision.value,
                    "contentHash": current_hash,
                    "correlationId": correlation_id,
                    "processedAt": now_iso,
                    "recordType": "orchestrator_decision",
                })
                logger.info(
                    "SKIP — state and audit written to Cosmos DB",
                    extra={
                        "correlationId": correlation_id,
                        "assetId": asset_id,
                        "authMethod": "ManagedIdentity",
                    },
                )

            return MessageProcessingResult(
                correlation_id=correlation_id,
                asset_id=asset_id,
                decision=decision.value,
                success=True,
            )

        # REPROCESS: asset new or changed — invoke enrichment pipeline.
        # Write orchestrator decision audit before handing off.
        # State is written by the pipeline AFTER successful Purview writeback.
        if state_store is not None:
            orch_audit_id = f"orch:{asset_id}:{correlation_id}"
            state_store.upsert_audit({
                "id": orch_audit_id,
                "entityType": entity_type,
                "assetId": asset_id,
                "sourceSystem": source_system,
                "decision": decision.value,
                "contentHash": current_hash,
                "correlationId": correlation_id,
                "processedAt": now_iso,
                "recordType": "orchestrator_decision",
            })

        logger.info(
            "REPROCESS — invoking enrichment pipeline",
            extra={
                "correlationId": correlation_id,
                "assetId": asset_id,
                "entityType": entity_type,
                "sourceSystem": source_system,
            },
        )

        from src.enrichment.pipeline.enrichment_pipeline import (  # noqa: PLC0415
            run_enrichment_pipeline,
        )

        pipeline_result = run_enrichment_pipeline(
            asset=asset,
            asset_id=asset_id,
            entity_type=entity_type,
            source_system=source_system,
            element_name=asset.get("entityName", asset_id),
            correlation_id=correlation_id,
            current_hash=current_hash,
            state_store=state_store,
        )

        logger.info(
            "Enrichment pipeline returned",
            extra={
                "correlationId": correlation_id,
                "assetId": asset_id,
                "pipelineSuccess": pipeline_result.success,
                "validationStatus": pipeline_result.validation_status,
                "writebackSuccess": pipeline_result.writeback_success,
            },
        )

        return MessageProcessingResult(
            correlation_id=correlation_id,
            asset_id=asset_id,
            decision=decision.value,
            success=pipeline_result.success,
            error=pipeline_result.error,
        )

    except Exception as exc:
        logger.error(
            "Processing failed: %s",
            exc,
            extra={
                "correlationId": correlation_id,
                "phase": "ERROR",
                "error": str(exc),
            },
            exc_info=True,
        )

        return MessageProcessingResult(
            correlation_id=correlation_id,
            asset_id="unknown",
            decision=None,
            success=False,
            error=str(exc),
        )
