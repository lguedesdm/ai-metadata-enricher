"""
Domain models for element-level hashing.

Provides a lightweight result container for element hash computations.
All types are pure value objects — no I/O, no logging, no infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ElementHashResult:
    """Immutable value object pairing an element identity with its content hash.

    Attributes:
        element_id: Deterministic identity of the element
            (``"{source}::{type}::{name}"``).
        content_hash: SHA-256 hex digest of the canonicalized element payload.
    """

    element_id: str
    content_hash: str

    def __str__(self) -> str:
        return f"{self.element_id} -> {self.content_hash}"
