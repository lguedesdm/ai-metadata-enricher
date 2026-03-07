"""
Schema-aligned constants for the Search Document Builder.

Defines the **authoritative** set of field names permitted in an Azure
AI Search document, derived from the deployed index
``metadata-context-index-v1``.

The deployed index and its indexers are the source of truth.  The
enrichment pipeline adapts to this contract.

No field may be emitted by the builder unless it appears in
``SCHEMA_FIELDS``.  The validation gate in ``builder.py`` enforces this
invariant at build time.

Design constraints
==================

- Constants only — no I/O, no Azure, no global mutable state.
- ``SCHEMA_FIELDS`` is derived from the deployed index schema.
"""

from __future__ import annotations

# -----------------------------------------------------------------------
# Deployed index schema — authoritative field list
# Source: deployed metadata-context-index-v1 on aime-dev-search
# -----------------------------------------------------------------------

SCHEMA_FIELDS: frozenset[str] = frozenset(
    {
        # Core identity
        "id",
        "sourceSystem",
        "source",
        # Classification
        "elementType",
        "elementName",
        # Descriptive
        "title",
        "description",
        "suggestedDescription",
        # RAG-critical
        "content",
        "contentVector",
        # Enrichment
        "tags",
        "cedsLink",
        # Temporal
        "lastUpdated",
    }
)
"""All field names permitted in an Azure AI Search document."""

MAX_CONTENT_LENGTH: int = 5_000
"""Safe upper bound (characters) for the ``content`` field."""

# -----------------------------------------------------------------------
# Deterministic content template
# -----------------------------------------------------------------------

CONTENT_TEMPLATE: str = (
    "Element Type: {element_type}\n"
    "Element Name: {element_name}\n"
    "Source System: {source_system}\n"
    "\n"
    "Description:\n"
    "{description}\n"
    "\n"
    "Suggested Description:\n"
    "{suggested_description}\n"
    "\n"
    "Tags:\n"
    "{tags}\n"
    "\n"
    "Additional Content:\n"
    "{additional_content}"
)
"""Template used to build the ``content`` field deterministically."""
