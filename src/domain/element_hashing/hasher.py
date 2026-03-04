"""
Deterministic SHA-256 hashing for ``ContextElement`` objects.

Computes a stable content hash that represents the *logical* state of an
element, excluding volatile metadata.  Two elements with identical logical
content will always produce the same hash regardless of field ordering,
whitespace, or transient metadata differences.

Usage::

    from src.domain.element_hashing import compute_element_hash

    h = compute_element_hash(element)   # returns 64-char hex string

Design constraints
==================

- Pure function — no I/O, no logging, no Azure, no global state.
- Deterministic — same input always yields the same hash.
- Idempotent — calling multiple times causes no side effect.
- Infrastructure-free — only standard-library imports.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from .canonicalizer import canonicalize_element
from .models import ElementHashResult

if TYPE_CHECKING:
    from src.domain.element_splitter.models import ContextElement


def compute_element_hash(element: "ContextElement") -> str:
    """Return a deterministic SHA-256 hex digest for *element*.

    The hash is derived from the canonical JSON representation of the
    element's ``raw_payload`` (volatile fields stripped, collections
    sorted, keys ordered).

    Args:
        element: A ``ContextElement`` instance.

    Returns:
        64-character lowercase hexadecimal SHA-256 digest.

    Raises:
        TypeError: If the element's ``raw_payload`` is not a ``dict``.
        ValueError: If canonical serialisation fails.
    """
    canonical_json = canonicalize_element(element)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_element_hash_result(element: "ContextElement") -> ElementHashResult:
    """Return an ``ElementHashResult`` combining identity and content hash.

    This is a convenience wrapper that pairs the element's deterministic
    identity (``{source}::{type}::{name}``) with its content hash.

    Args:
        element: A ``ContextElement`` instance.

    Returns:
        ``ElementHashResult`` with ``element_id`` and ``content_hash``.
    """
    from src.domain.element_splitter.element_identity import generate_element_id

    element_id = generate_element_id(element)
    content_hash = compute_element_hash(element)
    return ElementHashResult(element_id=element_id, content_hash=content_hash)
