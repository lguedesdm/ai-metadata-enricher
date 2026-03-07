"""
Search Document Builder — deterministic mapping from ``ContextElement``
to an Azure AI Search document dictionary.

Converts a single ``ContextElement`` (plus its pre-computed identity)
into a flat ``dict`` whose keys match the deployed index schema
``metadata-context-index-v1``.

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
- **Index-aligned** — field names match the deployed index, not the
  frozen design document.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .models import (
    CONTENT_TEMPLATE,
    MAX_CONTENT_LENGTH,
    SCHEMA_FIELDS,
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

    The returned dictionary contains **only** keys defined in the
    deployed index schema ``metadata-context-index-v1``.  A schema-
    validation gate runs before the document is returned; any extra
    key triggers a ``ValueError``.

    Field mapping from source payload to index fields:

    - ``entityType`` / ``element_type`` → ``elementType``
    - ``entityName`` / ``element_name`` → ``elementName``
    - ``businessMeaning`` → ``suggestedDescription``
    - ``cedsReference`` → ``cedsLink``

    The ``sourceSystem`` value is normalised to lowercase.

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

    # Normalise sourceSystem to lowercase
    source_system = element.source_system.strip().lower()

    content_text = _build_content(
        element_type=element.element_type,
        element_name=element.element_name,
        source_system=source_system,
        description=element.description,
        suggested_description=payload.get("businessMeaning") or payload.get("suggestedDescription"),
        tags=payload.get("tags"),
        additional_content=payload.get("content"),
    )

    document: Dict[str, Any] = {
        # Core identity
        "id": element_id,
        "sourceSystem": source_system,
        "source": payload.get("source"),
        # Classification
        "elementType": element.element_type,
        "elementName": element.element_name,
        # Descriptive
        "title": element.element_name,
        "description": element.description,
        "suggestedDescription": payload.get("businessMeaning") or payload.get("suggestedDescription"),
        # RAG-critical
        "content": content_text,
        "contentVector": None,
        # Enrichment
        "tags": _safe_tags(payload.get("tags")),
        "cedsLink": payload.get("cedsReference") or payload.get("cedsLink"),
        # Temporal
        "lastUpdated": payload.get("lastUpdated"),
    }

    _validate_document_fields(document)
    return document


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------


def _build_content(
    *,
    element_type: str,
    element_name: str,
    source_system: str,
    description: str,
    suggested_description: Optional[str],
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
        element_type=element_type,
        element_name=element_name,
        source_system=source_system,
        description=description or "",
        suggested_description=suggested_description or "",
        tags=tags_str,
        additional_content=additional_content or "",
    )

    if len(rendered) > MAX_CONTENT_LENGTH:
        rendered = rendered[:MAX_CONTENT_LENGTH]

    return rendered


def _safe_tags(value: Any) -> Optional[List[str]]:
    """Return *value* unchanged if it is a list, otherwise ``None``."""
    return value if isinstance(value, list) else None


def _validate_document_fields(document: Dict[str, Any]) -> None:
    """Raise ``ValueError`` if *document* contains unknown fields.

    Enforces the invariant::

        document.keys() ⊆ SCHEMA_FIELDS

    This prevents schema drift and ensures that no field is emitted
    unless it is defined in the deployed index schema.
    """
    extra = set(document.keys()) - SCHEMA_FIELDS
    if extra:
        raise ValueError(
            f"Search document contains fields not defined in the "
            f"deployed index schema: {sorted(extra)}"
        )
