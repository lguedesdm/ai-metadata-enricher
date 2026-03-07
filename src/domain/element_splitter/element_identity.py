"""
Deterministic identity generation for context elements.

Produces stable, deterministic document IDs for ``ContextElement`` instances
using base64 encoding of the element name.  The generated ID is used as the
document key in Azure AI Search and as the identity anchor for incremental
indexing.

ID format::

    base64Encode(element_name)

This matches the ID generation strategy used by the Azure AI Search
indexers (synergy-elements-indexer, zipline-elements-indexer), ensuring
that enrichment updates target existing indexed documents rather than
creating duplicates.

Design constraints:
    - Pure function — no I/O, no logging, no Azure, no global state.
    - Deterministic — same input always yields the same ID.
    - Idempotent — calling multiple times has no side effect.
    - No dependency on hashing, time, or external state.
    - ID must match the base64Encode mapping function used by indexers.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.element_splitter.models import ContextElement

# Allowed sourceSystem values (lowercase-normalised).
_ALLOWED_SOURCE_SYSTEMS: frozenset[str] = frozenset(
    {"synergy", "zipline", "documentation"}
)


def generate_element_id(element: "ContextElement") -> str:
    """Return a stable, deterministic ID for *element*.

    The ID is the base64 encoding of the ``element_name``,
    matching the ``base64Encode`` mapping function used by Azure AI
    Search indexers.

    Args:
        element: A ``ContextElement`` whose ``element_name`` will be
            used to derive the document ID.

    Returns:
        Base64-encoded string suitable for use as an Azure AI Search
        document key.

    Raises:
        ValueError: If ``element_name`` is empty or contains only
            whitespace, or if the encoded ID exceeds 1024 characters
            (Azure AI Search key limit).
    """
    name = element.element_name
    if not name or not name.strip():
        raise ValueError(
            f"Identity field 'element_name' is empty after normalisation "
            f"(original value: {name!r})"
        )

    document_id = _base64_encode(name)

    if len(document_id) > 1024:
        raise ValueError(
            f"Generated document ID exceeds Azure AI Search limit "
            f"(length={len(document_id)}, max=1024). "
            f"Original element_name: {name!r}"
        )

    return document_id


def normalise_source_system(value: str) -> str:
    """Normalise a ``sourceSystem`` value to lowercase.

    Ensures consistency across all enrichment documents.  Only the
    allowed values ``synergy``, ``zipline``, and ``documentation``
    are accepted.

    Args:
        value: Raw sourceSystem string (e.g. ``"Synergy"``, ``"ZIPLINE"``).

    Returns:
        Lowercase normalised string.

    Raises:
        ValueError: If the normalised value is not in the allowed set.
    """
    normalised = value.strip().lower()
    if normalised not in _ALLOWED_SOURCE_SYSTEMS:
        raise ValueError(
            f"sourceSystem '{value}' normalises to '{normalised}' which "
            f"is not in the allowed set: {sorted(_ALLOWED_SOURCE_SYSTEMS)}"
        )
    return normalised


def _base64_encode(value: str) -> str:
    """Encode *value* using the same base64 scheme as Azure AI Search.

    Azure AI Search ``base64Encode`` uses standard base64 encoding
    (RFC 4648) of the UTF-8 bytes, with ``+`` and ``/`` characters
    and ``=`` padding.
    """
    return base64.b64encode(value.encode("utf-8")).decode("ascii")
