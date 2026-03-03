"""
Element splitter logic.

Splits a Synergy/Zipline export JSON (containing an ``elements[]`` array)
into a deterministic, ordered list of ``ContextElement`` domain objects.

Design constraints:
    - Pure domain logic — no I/O, no persistence, no Azure calls.
    - The original JSON is never mutated; ``raw_payload`` is a deep copy.
    - Order of the returned list matches the order of ``elements[]``.
    - Deterministic: same input always produces the same output.
    - Required fields (sourceSystem, entityName, entityType) are strictly
      validated: missing, empty, or whitespace-only values are rejected
      with an explicit ``ValueError`` that includes the element index.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Sequence, Tuple

from .models import ContextElement

# Fields that MUST be present and non-blank in every element.
# Tuple of (JSON key, ContextElement attribute name) for error messages.
_REQUIRED_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("sourceSystem", "source_system"),
    ("entityName", "element_name"),
    ("entityType", "element_type"),
)


def split_elements(blob_json: dict) -> List[ContextElement]:
    """Transform export JSON into a list of ``ContextElement``.

    Args:
        blob_json: Full JSON payload loaded from blob storage.  Must
            contain an ``elements`` key whose value is a list of element
            dictionaries.

    Returns:
        Ordered list of ``ContextElement`` objects, one per entry in
        ``elements``.

    Raises:
        TypeError: If *blob_json* is not a ``dict``.
        KeyError: If the ``elements`` key is missing from *blob_json*.
        TypeError: If ``elements`` is not a list.
        ValueError: If any element is missing a required field, or if
            a required field is empty / whitespace-only.
    """
    if not isinstance(blob_json, dict):
        raise TypeError(
            f"blob_json must be a dict, got {type(blob_json).__name__}"
        )

    if "elements" not in blob_json:
        raise KeyError(
            "blob_json is missing the required 'elements' key"
        )

    elements = blob_json["elements"]

    if not isinstance(elements, list):
        raise TypeError(
            f"'elements' must be a list, got {type(elements).__name__}"
        )

    return [
        _to_context_element(index, element)
        for index, element in enumerate(elements)
    ]


def _validate_required_fields(
    index: int,
    element: Dict[str, Any],
) -> None:
    """Validate that all required fields are present and non-blank.

    Raises:
        ValueError: With an explicit message including the element index
            and the offending field name.
    """
    for json_key, attr_name in _REQUIRED_FIELDS:
        if json_key not in element:
            raise ValueError(
                f"Element at index {index} missing required field "
                f"'{attr_name}'"
            )
        value = element[json_key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Element at index {index} has empty or whitespace-only "
                f"value for required field '{attr_name}'"
            )


def _to_context_element(
    index: int,
    element: Dict[str, Any],
) -> ContextElement:
    """Map a single raw element dict to a ``ContextElement``.

    Validates required fields first, then maps to the domain object.
    ``description`` is optional and defaults to an empty string.

    Architectural note — ``raw_payload``:
        ``raw_payload`` is intentionally preserved as a **mutable** dict
        (via ``copy.deepcopy``).  It is NOT wrapped in
        ``types.MappingProxyType`` or recursively frozen.  This is a
        deliberate design choice:

        1. The deep copy guarantees isolation from the original JSON
           so that the caller's data is never mutated.
        2. Downstream stages (e.g. the hashing / identity layer) that
           consume ``raw_payload`` **must defensively copy before
           normalization** — this is their responsibility, not the
           splitter's.
        3. Introducing deep immutability here would add runtime cost
           and complexity without meaningful safety gain, because the
           identity/hashing layer already normalises via its own
           ``normalize_asset()`` pipeline.

        This contract is documented and intentional.
    """
    _validate_required_fields(index, element)

    return ContextElement(
        source_system=element["sourceSystem"],
        element_name=element["entityName"],
        element_type=element["entityType"],
        description=element.get("description", ""),
        # raw_payload: mutable deep copy — see architectural note above.
        raw_payload=copy.deepcopy(element),
    )
