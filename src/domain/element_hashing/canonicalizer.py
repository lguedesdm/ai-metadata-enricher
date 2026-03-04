"""
Canonical JSON normalisation for ``ContextElement`` payloads.

Transforms the ``raw_payload`` of a ``ContextElement`` into a deterministic
canonical JSON string suitable for SHA-256 hashing.

Normalisation guarantees
========================

1. **Volatile field exclusion** — fields that change between runs without
   representing a logical content change (timestamps, scan IDs, schema
   versions, processing metadata, ``_``-prefixed internal fields) are
   stripped before serialisation.

2. **Collection sorting** — arrays that carry set-like semantics
   (``tags``, ``relationships``, ``columns``, ``lineage``) are sorted
   deterministically so that order differences do not affect the hash.

3. **Deterministic JSON** — keys are sorted, compact separators are used
   (``(",",":")``), and ``ensure_ascii=False`` keeps Unicode stable.
   Whitespace, field order, and non-material formatting differences are
   eliminated.

4. **Deep-copy isolation** — the input dictionary is deep-copied before
   mutation so the caller's data is never modified.

Design constraints
==================

- Pure function — no I/O, no logging, no Azure, no global state.
- Deterministic — same input always yields the same canonical string.
- Idempotent — calling multiple times causes no side effect.
- Infrastructure-free — only standard-library imports.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.element_splitter.models import ContextElement

# ---------------------------------------------------------------------------
# Volatile fields — excluded from canonical representation
# ---------------------------------------------------------------------------

#: Fields that represent transient or environment-dependent metadata.
#: Their presence / absence / value must never influence the content hash.
VOLATILE_FIELDS: frozenset[str] = frozenset(
    {
        "lastUpdated",
        "schemaVersion",
        "auditInfo",
        "scanId",
        "ingestionTime",
    }
)


def _is_volatile(field_name: str) -> bool:
    """Return ``True`` if *field_name* is volatile.

    A field is volatile if it is in the explicit ``VOLATILE_FIELDS`` set
    **or** begins with an underscore (internal / processing metadata).
    """
    return field_name in VOLATILE_FIELDS or field_name.startswith("_")


# ---------------------------------------------------------------------------
# Collection normalisers
# ---------------------------------------------------------------------------


def _sort_tags(tags: Any) -> List[str]:
    """Sort tags alphabetically (case-insensitive), dedup, preserve case."""
    if not isinstance(tags, list):
        return tags  # leave non-list values untouched
    return sorted(set(tags), key=str.lower)


def _sort_relationships(relationships: Any) -> List[Dict[str, Any]]:
    """Sort relationship dicts by ``id``, dedup by ``id``."""
    if not isinstance(relationships, list):
        return relationships
    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for rel in relationships:
        if not isinstance(rel, dict):
            unique.append(rel)
            continue
        rel_id = rel.get("id")
        if rel_id is not None and rel_id in seen:
            continue
        if rel_id is not None:
            seen.add(rel_id)
        unique.append(rel)
    return sorted(unique, key=lambda r: r.get("id", ""))


def _sort_columns(columns: Any) -> List[Dict[str, Any]]:
    """Sort column dicts by ``name``, dedup by ``name``."""
    if not isinstance(columns, list):
        return columns
    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for col in columns:
        if not isinstance(col, dict):
            unique.append(col)
            continue
        col_name = col.get("name")
        if col_name is not None and col_name in seen:
            continue
        if col_name is not None:
            seen.add(col_name)
        unique.append(col)
    return sorted(unique, key=lambda c: c.get("name", ""))


def _sort_lineage(lineage: Any) -> List[str]:
    """Sort lineage entries alphabetically for determinism."""
    if not isinstance(lineage, list):
        return lineage
    return sorted(lineage)


# Mapping from collection field names to their normaliser functions.
_COLLECTION_NORMALISERS = {
    "tags": _sort_tags,
    "relationships": _sort_relationships,
    "columns": _sort_columns,
    "lineage": _sort_lineage,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def canonicalize_element(element: "ContextElement") -> str:
    """Return a deterministic canonical JSON string for *element*.

    The canonical representation is derived from ``element.raw_payload``:

    1. Deep-copy the payload (isolation).
    2. Strip volatile fields.
    3. Sort known collections.
    4. Serialise with sorted keys + compact separators.

    Args:
        element: A ``ContextElement`` whose ``raw_payload`` will be
            canonicalised.

    Returns:
        Compact, deterministic JSON string.

    Raises:
        TypeError: If ``element.raw_payload`` is not a ``dict``.
        ValueError: If serialisation fails.
    """
    payload = element.raw_payload
    if not isinstance(payload, dict):
        raise TypeError(
            f"raw_payload must be a dict, got {type(payload).__name__}"
        )

    canonical = _strip_volatile(deepcopy(payload))
    canonical = _normalise_collections(canonical)
    return _to_canonical_json(canonical)


def extract_canonical_payload(element: "ContextElement") -> Dict[str, Any]:
    """Return the normalised dict (pre-serialisation) for debugging.

    Useful for inspecting exactly which fields contribute to the hash
    without performing serialisation or hashing.
    """
    payload = element.raw_payload
    if not isinstance(payload, dict):
        raise TypeError(
            f"raw_payload must be a dict, got {type(payload).__name__}"
        )

    canonical = _strip_volatile(deepcopy(payload))
    return _normalise_collections(canonical)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_volatile(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return *data* with all volatile keys removed (in-place)."""
    keys_to_remove = [k for k in data if _is_volatile(k)]
    for key in keys_to_remove:
        del data[key]
    return data


def _normalise_collections(data: Dict[str, Any]) -> Dict[str, Any]:
    """Sort known collection fields in *data* (in-place)."""
    for field_name, normaliser in _COLLECTION_NORMALISERS.items():
        if field_name in data:
            data[field_name] = normaliser(data[field_name])
    return data


def _to_canonical_json(obj: Any) -> str:
    """Serialise *obj* to compact, deterministic JSON.

    Properties of the canonical form:

    - Keys sorted alphabetically.
    - Compact separators — no trailing spaces.
    - ``ensure_ascii=False`` — Unicode preserved.
    - UTF-8 encoding assumed downstream.

    Raises:
        ValueError: If *obj* contains non-JSON-serialisable types.
    """
    try:
        return json.dumps(
            obj,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Failed to produce canonical JSON: {exc}"
        ) from exc
