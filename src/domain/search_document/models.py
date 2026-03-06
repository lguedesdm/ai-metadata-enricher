"""
Schema-aligned constants for the Search Document Builder.

Defines the **frozen** set of field names permitted in an Azure AI Search
document (v1.1.0) and the deterministic content-template used to build the
``content`` field.

No field may be emitted by the builder unless it appears in
``SCHEMA_FIELDS``.  The validation gate in ``builder.py`` enforces this
invariant at build time.

Design constraints
==================

- Constants only — no I/O, no Azure, no global mutable state.
- ``SCHEMA_FIELDS`` is derived exclusively from the frozen index
  design documented in ``docs/search-index-design.md`` and the
  traceability fields added in ADR-0004 (v1.1.0).
"""

from __future__ import annotations

# -----------------------------------------------------------------------
# Frozen index schema v1.1.0 — authoritative field list
# Source: docs/search-index-design.md + docs/adr/0004-…
# -----------------------------------------------------------------------

SCHEMA_FIELDS: frozenset[str] = frozenset(
    {
        # Core identity
        "id",
        "sourceSystem",
        "entityType",
        "schemaVersion",
        # Descriptive
        "entityName",
        "entityPath",
        "description",
        "businessMeaning",
        # Semantic enrichment
        "domain",
        "tags",
        # RAG-critical
        "content",
        "contentVector",
        # Technical metadata
        "dataType",
        "sourceTable",
        "cedsReference",
        # Lineage and temporal
        "lineage",
        "lastUpdated",
        # Traceability (v1.1.0, ADR-0004)
        "blobPath",
        "originalSourceFile",
    }
)
"""All field names permitted in an Azure AI Search document (v1.1.0)."""

SCHEMA_VERSION: str = "1.1.0"
"""Current schema version stamped into every emitted document."""

MAX_CONTENT_LENGTH: int = 5_000
"""Safe upper bound (characters) for the ``content`` field."""

# -----------------------------------------------------------------------
# Deterministic content template
# -----------------------------------------------------------------------

CONTENT_TEMPLATE: str = (
    "Entity Type: {entity_type}\n"
    "Entity Name: {entity_name}\n"
    "Source System: {source_system}\n"
    "\n"
    "Description:\n"
    "{description}\n"
    "\n"
    "Business Meaning:\n"
    "{business_meaning}\n"
    "\n"
    "Domain:\n"
    "{domain}\n"
    "\n"
    "Tags:\n"
    "{tags}\n"
    "\n"
    "Additional Content:\n"
    "{additional_content}"
)
"""Template used to build the ``content`` field deterministically."""
