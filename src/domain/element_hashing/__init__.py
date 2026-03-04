"""
Element hashing module for AI Metadata Enricher.

Provides deterministic SHA-256 hashing of ``ContextElement`` payloads for
incremental indexing and state comparison.  Volatile metadata is stripped
and collections are sorted before hashing so that two logically identical
elements always produce the same hash.

Public API:
    - compute_element_hash(): SHA-256 hex digest of a ContextElement.
    - compute_element_hash_result(): Hash + deterministic element ID.
    - canonicalize_element(): Canonical JSON string (pre-hash).
    - extract_canonical_payload(): Normalised dict for debugging.
    - ElementHashResult: Immutable value object pairing ID and hash.
    - VOLATILE_FIELDS: Fields excluded from hashing.
"""

from .hasher import compute_element_hash, compute_element_hash_result
from .canonicalizer import (
    canonicalize_element,
    extract_canonical_payload,
    VOLATILE_FIELDS,
)
from .models import ElementHashResult

__all__ = [
    "compute_element_hash",
    "compute_element_hash_result",
    "canonicalize_element",
    "extract_canonical_payload",
    "ElementHashResult",
    "VOLATILE_FIELDS",
]
