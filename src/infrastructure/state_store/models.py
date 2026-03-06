"""
Schema-aligned constants for the Element State Writer.

Defines the **frozen** set of field names permitted in an element state
record.  The validation gate in ``state_writer.py`` enforces that no
unexpected field is ever persisted.

Design constraints
==================

- Constants only — no I/O, no Azure, no global mutable state.
- ``STATE_RECORD_FIELDS`` is derived from the existing state schema
  used by the orchestrator (``cosmos_state_store.py``).
"""

from __future__ import annotations

# -----------------------------------------------------------------------
# Element state record — authoritative field list
# -----------------------------------------------------------------------

STATE_RECORD_FIELDS: frozenset[str] = frozenset(
    {
        # Identity
        "id",
        "entityType",
        "sourceSystem",
        # Content fingerprint
        "contentHash",
        # Temporal
        "lastProcessed",
    }
)
"""All field names permitted in an element state record."""
