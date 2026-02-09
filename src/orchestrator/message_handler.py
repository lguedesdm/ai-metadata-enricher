"""
Message handler for the Orchestrator.

Processes a single Service Bus message by:
1. Parsing the JSON payload
2. Extracting asset identifiers
3. Computing the asset hash
4. Calling the domain-level decision logic (SKIP / REPROCESS)
5. Logging the result with correlationId

This handler does NOT:
- Call any LLM or AI service
- Persist state to Cosmos DB or any store
- Write to Purview or AI Search
- Generate embeddings or prompts
"""

import json
import logging
import uuid
from typing import Any, Dict

from src.domain.change_detection import (
    DecisionResult,
    compute_asset_hash,
    decide_reprocess_or_skip,
)

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


def handle_message(message_body: str | bytes) -> MessageProcessingResult:
    """
    Process a single Service Bus message.

    The message body is expected to be a JSON object conforming to one of
    the frozen asset schemas (synergy-export or zipline-export).

    Args:
        message_body: Raw message body (str or bytes).

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

        # -- Domain decision -----------------------------------------------
        # NOTE: previous_state is None because this minimal orchestrator
        # does NOT read from Cosmos DB. All decisions will be REPROCESS.
        # This is expected and correct for the structural proof-of-life.
        decision: DecisionResult = decide_reprocess_or_skip(
            current_hash=current_hash,
            previous_state=None,
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

        return MessageProcessingResult(
            correlation_id=correlation_id,
            asset_id=asset_id,
            decision=decision.value,
            success=True,
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
