"""
Search Document Builder — deterministic mapping from ``ContextElement``
to an Azure AI Search document dictionary.

Converts a single ``ContextElement`` (plus its pre-computed identity)
into a flat ``dict`` whose keys are a strict subset of the frozen index
schema (v1.1.0).

Pipeline position::

    Blob → Splitter → Identity → Hash → State Comparison
        → **Search Document Builder** → Upsert Writer → State Update

Design constraints
==================

- **Pure function** — no I/O, no logging, no Azure SDK, no global state.
- **Deterministic** — identical inputs always produce identical output.
- **Idempotent** — calling multiple times has no side effect.
- **Schema-safe** — output keys validated against ``SCHEMA_FIELDS``.
- **No mutation** — the input ``ContextElement`` is never modified.
- **No embedding** — ``contentVector`` is always ``None``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .models import (
    CONTENT_TEMPLATE,
    MAX_CONTENT_LENGTH,
    SCHEMA_FIELDS,
    SCHEMA_VERSION,
)

if TYPE_CHECKING:
    from src.domain.element_splitter.models import ContextElement


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------


def build_search_document(
    element: "ContextElement",
    element_id: str,
) -> Dict[str, Any]:
    """Build an Azure AI Search document from *element*.

    The returned dictionary contains **only** keys defined in the frozen
    index schema (v1.1.0).  A schema-validation gate runs before the
    document is returned; any extra key triggers a ``ValueError``.

    Args:
        element: An immutable ``ContextElement`` produced by the
            Element Splitter.
        element_id: The deterministic document ID produced by
            ``generate_element_id()``.

    Returns:
        A ``dict`` ready for Azure AI Search upsert.  The
        ``contentVector`` key is always ``None`` (embedding is
        generated later in the enrichment pipeline).

    Raises:
        ValueError: If the assembled document contains keys outside
            ``SCHEMA_FIELDS``.
    """
    payload: Dict[str, Any] = element.raw_payload

    content_text = _build_content(
        entity_type=element.element_type,
        entity_name=element.element_name,
        source_system=element.source_system,
        description=element.description,
        business_meaning=payload.get("businessMeaning"),
        domain=payload.get("domain"),
        tags=payload.get("tags"),
        additional_content=payload.get("content"),
    )

    document: Dict[str, Any] = {
        # Core identity
        "id": element_id,
        "sourceSystem": element.source_system,
        "entityType": element.element_type,
        "schemaVersion": SCHEMA_VERSION,
        # Descriptive
        "entityName": element.element_name,
        "entityPath": payload.get("entityPath"),
        "description": element.description,
        "businessMeaning": payload.get("businessMeaning"),
        # Semantic enrichment
        "domain": payload.get("domain"),
        "tags": _safe_tags(payload.get("tags")),
        # RAG-critical
        "content": content_text,
        "contentVector": None,
        # Technical metadata
        "dataType": payload.get("dataType"),
        "sourceTable": payload.get("sourceTable"),
        "cedsReference": payload.get("cedsReference"),
        # Lineage and temporal
        "lineage": _safe_lineage(payload.get("lineage")),
        "lastUpdated": payload.get("lastUpdated"),
        # Traceability (v1.1.0)
        "blobPath": payload.get("blobPath"),
        "originalSourceFile": payload.get("originalSourceFile"),
    }

    _validate_document_fields(document)
    return document


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------


def _build_content(
    *,
    entity_type: str,
    entity_name: str,
    source_system: str,
    description: str,
    business_meaning: Optional[str],
    domain: Optional[str],
    tags: Optional[List[str]],
    additional_content: Optional[str],
) -> str:
    """Render the deterministic content string and enforce size limit.

    Missing optional values are replaced with an empty string so that
    the template structure is always identical.  If the rendered text
    exceeds ``MAX_CONTENT_LENGTH`` it is truncated deterministically.
    """
    tags_str = ", ".join(tags) if tags else ""

    rendered = CONTENT_TEMPLATE.format(
        entity_type=entity_type,
        entity_name=entity_name,
        source_system=source_system,
        description=description or "",
        business_meaning=business_meaning or "",
        domain=domain or "",
        tags=tags_str,
        additional_content=additional_content or "",
    )

    if len(rendered) > MAX_CONTENT_LENGTH:
        rendered = rendered[:MAX_CONTENT_LENGTH]

    return rendered


def _safe_tags(value: Any) -> Optional[List[str]]:
    """Return *value* unchanged if it is a list, otherwise ``None``."""
    return value if isinstance(value, list) else None


def _safe_lineage(value: Any) -> Optional[List[str]]:
    """Return *value* unchanged if it is a list, otherwise ``None``."""
    return value if isinstance(value, list) else None


def _validate_document_fields(document: Dict[str, Any]) -> None:
    """Raise ``ValueError`` if *document* contains unknown fields.

    Enforces the invariant::

        document.keys() ⊆ SCHEMA_FIELDS

    This prevents schema drift and ensures that no field is emitted
    unless it is defined in the frozen index schema.
    """
    extra = set(document.keys()) - SCHEMA_FIELDS
    if extra:
        raise ValueError(
            f"Search document contains fields not defined in the "
            f"frozen index schema v1.1.0: {sorted(extra)}"
        )
