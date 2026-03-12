"""
Message handler for the Orchestrator.

Processes a single Service Bus message by:
1. Parsing the JSON payload
2. Generating a single reference_time for the entire message (determinism)
3. Splitting the asset into ContextElement objects (element splitter)
4. For each element independently:
   a. Computing the element hash
   b. Reading previous element state from Cosmos DB
   c. Calling the domain-level decision logic (SKIP / REPROCESS)
   d. On SKIP  — writing schema-compliant state and audit to Cosmos DB
   e. On REPROCESS — invoking the enrichment pipeline (RAG → LLM →
      Validation → Purview Writeback → State Update → Audit)
5. Aggregating per-element results into a single MessageProcessingResult
6. Logging the result with correlationId

Cosmos DB access uses Managed Identity exclusively — no keys or secrets.

Pipeline integration contract:
- The orchestrator does NOT contain enrichment logic.
- Enrichment logic lives exclusively in src/enrichment/pipeline/.
- State is updated only after successful Purview writeback (REPROCESS path).
- On SKIP the state is confirmed immediately (no writeback needed).
- reference_time is generated once per message and propagated to every
  element so retries use the same temporal context.
- State records contain only frozen schema fields:
    id, entityType, sourceSystem, contentHash, lastProcessed
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.domain.change_detection import (
    DecisionResult,
    decide_reprocess_or_skip,
)
from src.domain.element_splitter import ContextElement, split_elements
from src.domain.element_hashing import compute_element_hash_result

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
    reference_time: Optional[datetime] = None,
    correlation_id: Optional[str] = None,
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
        message_body:   Raw message body (str or bytes).
        state_store:    Optional Cosmos DB state store (Managed Identity).
        reference_time: Stable reference time for RAG freshness scoring.
            Must be derived from a stable message attribute (e.g.
            ServiceBusReceivedMessage.enqueued_time_utc) so that the same
            message produces the same reference_time on every retry.
            Falls back to datetime.now(utc) when not provided (test mode).

    Returns:
        MessageProcessingResult with the decision outcome.
    """
    # Use correlationId from the upstream pipeline (Bridge → Router → Orchestrator).
    # Generate a fallback UUID only when the caller did not supply one.
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
        logger.info(
            "correlationId_missing_generated",
            extra={
                "event": "correlationId_missing_generated",
                "correlationId": correlation_id,
                "stage": "orchestrator",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    logger.info(
        "Processing started",
        extra={
            "assetId": None,
            "correlationId": correlation_id,
            "stage": "orchestrator",
            "event": "message_received",
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
        if not isinstance(asset, dict):
            raise ValueError(
                f"Message body must be a JSON object, got {type(asset).__name__}"
            )

        # -- Message-level identifier (for result reporting) ---------------
        asset_id: str = asset.get("id", "unknown")

        logger.info(
            "Asset payload parsed",
            extra={
                "assetId": asset_id,
                "correlationId": correlation_id,
                "stage": "orchestrator",
                "event": "metadata_fetched",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # -- Reference time — anchored to message enqueue time -------------
        # Derived from ServiceBusReceivedMessage.enqueued_time_utc by the
        # consumer so the same physical message always produces the same
        # reference_time, even across Service Bus redeliveries.
        # This makes RAG freshness scoring deterministic across retries.
        # Falls back to datetime.now(utc) only in test mode (no consumer).
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        # -- Element split --------------------------------------------------
        # Decompose the asset payload into individual ContextElement objects.
        # If the payload has no 'elements' array, the whole asset is treated
        # as a single element (backward compat with flat asset payloads).
        elements: List[ContextElement] = _split_asset_elements(asset)

        logger.info(
            "Asset split into %d element(s)",
            len(elements),
            extra={
                "correlationId": correlation_id,
                "assetId": asset_id,
                "elementCount": len(elements),
            },
        )

        # -- Per-element processing loop -----------------------------------
        # Each element is processed independently: hash → state check →
        # decision → SKIP/REPROCESS.  All elements in this message share
        # the same correlation_id and reference_time.
        element_successes: List[bool] = []
        element_decisions: List[str] = []
        first_error: Optional[str] = None

        from src.enrichment.pipeline.enrichment_pipeline import (  # noqa: PLC0415
            run_enrichment_pipeline,
        )

        for element in elements:
            # -- Element hash ----------------------------------------------
            hash_result = compute_element_hash_result(element)
            element_id: str = hash_result.element_id
            element_hash: str = hash_result.content_hash

            # -- Read previous element state (Cosmos DB) -------------------
            # Domain contract: any Cosmos failure → default REPROCESS.
            previous_state: Optional[str] = None
            if state_store is not None:
                try:
                    previous_item = state_store.get_state(
                        asset_id=element_id,
                        entity_type=element.element_type,
                    )
                    if previous_item is not None:
                        previous_state = previous_item.get("contentHash")
                        logger.info(
                            "Previous element state loaded",
                            extra={
                                "correlationId": correlation_id,
                                "elementId": element_id,
                                "authMethod": "ManagedIdentity",
                            },
                        )
                except Exception as cosmos_read_exc:
                    logger.warning(
                        "Cosmos state read failed for element %s — REPROCESS: %s",
                        element_id,
                        cosmos_read_exc,
                        extra={
                            "correlationId": correlation_id,
                            "elementId": element_id,
                            "cosmosError": type(cosmos_read_exc).__name__,
                            "fallbackDecision": "REPROCESS",
                        },
                    )

            # -- Domain decision -------------------------------------------
            decision: DecisionResult = decide_reprocess_or_skip(
                current_hash=element_hash,
                previous_state=previous_state,
            )

            # Timestamps derived from reference_time for temporal consistency
            now_iso: str = reference_time.isoformat()

            obs_event = "hash_skipped" if decision == DecisionResult.SKIP else "hash_changed"
            logger.info(
                "Element decision: %s",
                decision.value,
                extra={
                    "assetId": element_id,
                    "correlationId": correlation_id,
                    "stage": "orchestrator",
                    "event": obs_event,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "elementName": element.element_name,
                    "elementType": element.element_type,
                    "decision": decision.value,
                    "contentHash": element_hash[:16] + "...",
                },
            )

            element_decisions.append(decision.value)

            if decision == DecisionResult.SKIP:
                # SKIP: element unchanged — write schema-compliant state + audit.
                if state_store is not None:
                    state_store.upsert_state({
                        "id": element_id,
                        "entityType": element.element_type,
                        "sourceSystem": element.source_system,
                        "contentHash": element_hash,
                        "lastProcessed": now_iso,
                    })
                    state_store.upsert_audit({
                        "id": f"orch:{element_id}:{correlation_id}",
                        "entityType": element.element_type,
                        "assetId": element_id,
                        "sourceSystem": element.source_system,
                        "decision": decision.value,
                        "contentHash": element_hash,
                        "correlationId": correlation_id,
                        "processedAt": now_iso,
                        "recordType": "orchestrator_decision",
                    })
                element_successes.append(True)

            else:
                # REPROCESS: element new or changed — invoke enrichment pipeline.
                # Write orchestrator decision audit before handing off.
                # Element state is written by the pipeline AFTER writeback.
                if state_store is not None:
                    state_store.upsert_audit({
                        "id": f"orch:{element_id}:{correlation_id}",
                        "entityType": element.element_type,
                        "assetId": element_id,
                        "sourceSystem": element.source_system,
                        "decision": decision.value,
                        "contentHash": element_hash,
                        "correlationId": correlation_id,
                        "processedAt": now_iso,
                        "recordType": "orchestrator_decision",
                    })

                logger.info(
                    "REPROCESS — invoking enrichment pipeline for element",
                    extra={
                        "correlationId": correlation_id,
                        "elementId": element_id,
                        "elementName": element.element_name,
                    },
                )

                pipeline_result = run_enrichment_pipeline(
                    asset=element.raw_payload,
                    asset_id=element_id,
                    entity_type=element.element_type,
                    source_system=element.source_system,
                    element_name=element.element_name,
                    correlation_id=correlation_id,
                    current_hash=element_hash,
                    state_store=state_store,
                    reference_time=reference_time,
                )

                logger.info(
                    "Enrichment pipeline returned for element",
                    extra={
                        "correlationId": correlation_id,
                        "elementId": element_id,
                        "pipelineSuccess": pipeline_result.success,
                        "validationStatus": pipeline_result.validation_status,
                        "writebackSuccess": pipeline_result.writeback_success,
                    },
                )

                element_successes.append(pipeline_result.success)
                if not pipeline_result.success and first_error is None:
                    first_error = pipeline_result.error

        # -- Aggregate results across all elements -------------------------
        overall_success = all(element_successes) if element_successes else True
        overall_decision = (
            "REPROCESS" if "REPROCESS" in element_decisions
            else ("SKIP" if element_decisions else None)
        )

        return MessageProcessingResult(
            correlation_id=correlation_id,
            asset_id=asset_id,
            decision=overall_decision,
            success=overall_success,
            error=first_error,
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


def _split_asset_elements(asset: Dict[str, Any]) -> List[ContextElement]:
    """Decompose an asset payload into ContextElement objects.

    If the payload contains an 'elements' array, delegates to the domain
    element splitter.  If there is no 'elements' key (flat asset payload),
    wraps the whole asset as a single ContextElement — preserving backward
    compatibility with assets that do not carry sub-elements.

    Args:
        asset: Full asset metadata dict from the Service Bus message.

    Returns:
        Ordered list of ContextElement objects, one per element.

    Raises:
        ValueError: If 'elements' is present but contains invalid entries.
        TypeError:  If 'elements' is present but is not a list.
    """
    try:
        return split_elements(asset)
    except KeyError:
        # No 'elements' key — treat whole asset as a single element.
        return [
            ContextElement(
                source_system=asset.get("sourceSystem", "unknown"),
                element_name=asset.get("entityName", asset.get("id", "unknown")),
                element_type=asset.get("entityType", "unknown"),
                description=asset.get("description", ""),
                raw_payload=asset,
            )
        ]
