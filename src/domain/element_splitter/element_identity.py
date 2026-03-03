"""
Deterministic identity generation for context elements.

Produces stable, deterministic document IDs for ``ContextElement`` instances
using a pure normalisation-and-concatenation approach.  The generated ID
is used as the document key in Azure AI Search and as the identity anchor
for incremental indexing.

ID format::

    "{source_system}::{element_type}::{element_name}"

Each segment is normalised identically:

1. Strip leading / trailing whitespace.
2. Collapse multiple internal spaces to a single space.
3. Convert to lowercase.
4. Reject if empty after normalisation (``ValueError``).
5. Reject if the normalised value contains the reserved separator
   ``"::"`` (``ValueError``) — prevents structural ambiguity.

Design constraints:
    - Pure function — no I/O, no logging, no Azure, no global state.
    - Deterministic — same input always yields the same ID.
    - Idempotent — calling multiple times has no side effect.
    - No dependency on hashing, time, or external state.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.element_splitter.models import ContextElement

# Pre-compiled pattern: two or more whitespace characters.
_MULTI_SPACE_RE = re.compile(r"\s+")

# Reserved separator used to delimit identity segments.
_SEPARATOR = "::"


def generate_element_id(element: "ContextElement") -> str:
    """Return a stable, deterministic ID for *element*.

    The ID is constructed from three normalised segments joined by
    ``"::"``::

        "{source_system}::{element_type}::{element_name}"

    Args:
        element: A ``ContextElement`` whose identity fields will be
            normalised and concatenated.

    Returns:
        Lowercase, whitespace-collapsed, ``"::"``-delimited string.

    Raises:
        ValueError: If any identity field is empty or contains only
            whitespace after normalisation, or if the normalised value
            contains the reserved separator ``"::"``, or if the
            final ID exceeds 1024 characters (Azure AI Search key limit).
            The error message includes the original raw value for
            diagnostics.
    """
    source = _normalise_field(element.source_system, "source_system")
    etype = _normalise_field(element.element_type, "element_type")
    ename = _normalise_field(element.element_name, "element_name")

    document_id = f"{source}::{etype}::{ename}"

    if len(document_id) > 1024:
        raise ValueError(
            f"Generated document ID exceeds Azure AI Search limit "
            f"(length={len(document_id)}, max=1024). "
            f"Original values: source={element.source_system!r}, "
            f"type={element.element_type!r}, "
            f"name={element.element_name!r}"
        )

    return document_id


def _normalise_field(value: str, field_name: str) -> str:
    """Normalise a single identity field.

    Steps:
        1. Strip leading/trailing whitespace.
        2. Collapse runs of internal whitespace to a single space.
        3. Convert to lowercase.
        4. Reject if result is empty.
        5. Reject if result contains the reserved separator ``"::"``.

    Raises:
        ValueError: With the original raw value in the message.
    """
    normalised = _MULTI_SPACE_RE.sub(" ", value.strip()).lower()

    if not normalised:
        raise ValueError(
            f"Identity field '{field_name}' is empty after normalisation "
            f"(original value: {value!r})"
        )

    if _SEPARATOR in normalised:
        raise ValueError(
            f"Identity field '{field_name}' contains reserved separator "
            f"'{_SEPARATOR}' (original value: {value!r})"
        )

    return normalised
