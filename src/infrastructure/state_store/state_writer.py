"""
Element State Writer — persists element processing state after indexing.

Records the current element state so that future pipeline executions can
determine whether an element must be reprocessed or skipped.

Pipeline position::

    … → Search Upsert Writer → **Element State Update** (end of pipeline)

Design constraints
==================

- **Single-element granularity** — one call = one state persistence.
- **Post-upsert only** — must be called only after Search upsert succeeds.
- **No recomputation** — identity, hash, and state comparison are upstream.
- **No domain logic** — pure infrastructure adapter.
- **No deletions** — state records are never deleted.
- **No batch updates** — one element per call.
- **Observable** — logs element ID and operation type, never full payload.
- **Fail-loud** — persistence errors are raised, never swallowed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, TYPE_CHECKING

from .models import STATE_RECORD_FIELDS

if TYPE_CHECKING:
    from src.orchestrator.cosmos_state_store import CosmosStateStore

logger = logging.getLogger("infrastructure.state_store")


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------


def update_element_state(
    element_id: str,
    content_hash: str,
    source_system: str,
    *,
    state_store: "CosmosStateStore",
) -> None:
    """Persist the processing state of a single element.

    Writes a state record containing the element's identity, content
    hash, source system, and processing timestamp.  This record enables
    future pipeline executions to determine whether the element has
    changed (via hash comparison in the state comparator).

    Must be called **only** after the Search upsert operation succeeds.
    Must **not** be called for unchanged elements (those that were
    skipped by the state comparator).

    Args:
        element_id: Deterministic element identity from upstream
            (format: ``"{source}::{type}::{name}"``).
        content_hash: SHA-256 hex digest of the element content,
            computed upstream by the hashing module.
        source_system: Source system identifier (e.g. ``"synergy"``).
        state_store: A state store instance with an ``upsert_state``
            method (typically ``CosmosStateStore``).

    Raises:
        TypeError: If any required argument is not a string.
        ValueError: If any required argument is empty or whitespace,
            or if the element_id format is invalid.
        Exception: Propagated from the state store on persistence failure.
    """
    _validate_inputs(element_id, content_hash, source_system)

    entity_type = _extract_entity_type(element_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    record: Dict[str, Any] = {
        "id": element_id,
        "entityType": entity_type,
        "sourceSystem": source_system,
        "contentHash": content_hash,
        "lastProcessed": now_iso,
    }

    _validate_record_fields(record)

    logger.info(
        "Updating element state",
        extra={
            "elementId": element_id,
            "operation": "state_update",
        },
    )

    state_store.upsert_state(record)

    logger.info(
        "Element state updated successfully",
        extra={
            "elementId": element_id,
            "operation": "state_update",
        },
    )


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------


def _validate_inputs(
    element_id: str,
    content_hash: str,
    source_system: str,
) -> None:
    """Raise if any required input is invalid.

    Checks:
        1. Each argument must be a ``str``.
        2. Each argument must be non-empty after stripping whitespace.
    """
    for name, value in [
        ("element_id", element_id),
        ("content_hash", content_hash),
        ("source_system", source_system),
    ]:
        if not isinstance(value, str):
            raise TypeError(
                f"{name} must be a str, got {type(value).__name__}"
            )
        if not value.strip():
            raise ValueError(
                f"{name} must be a non-empty string"
            )


def _extract_entity_type(element_id: str) -> str:
    """Extract the entity type component from a deterministic element ID.

    Element IDs follow the format ``"{source}::{type}::{name}"``.
    The entity type is the second ``"::"``-delimited component.

    Raises:
        ValueError: If the element_id does not contain at least two
            ``"::"``-separated components, or the type component is
            empty.
    """
    parts = element_id.split("::")
    if len(parts) < 2 or not parts[1].strip():
        raise ValueError(
            f"Cannot extract entity type from element_id: {element_id!r}. "
            f"Expected format: '{{source}}::{{type}}::{{name}}'"
        )
    return parts[1]


def _validate_record_fields(record: Dict[str, Any]) -> None:
    """Raise ``ValueError`` if *record* contains unexpected fields.

    Enforces the invariant::

        record.keys() ⊆ STATE_RECORD_FIELDS

    This prevents schema drift in the state store.
    """
    extra = set(record.keys()) - STATE_RECORD_FIELDS
    if extra:
        raise ValueError(
            f"State record contains unexpected fields: {sorted(extra)}"
        )
