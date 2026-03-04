"""
Deterministic element-level state comparator.

Compares the current content hash of a ``ContextElement`` with a previously
stored hash to produce a deterministic ``SKIP`` / ``REPROCESS`` decision.

Usage::

    from src.domain.element_state import compare_element_state

    result = compare_element_state(element, stored_hash="abc123…")
    if result.decision == StateDecision.SKIP:
        ...  # element is unchanged

Design constraints
==================

- Pure function — no I/O, no logging, no Azure, no global state.
- Deterministic — same inputs always yield the same decision.
- Idempotent — calling multiple times causes no side effect.
- No mutation — the input ``ContextElement`` is never modified.
- Infrastructure-free — only project-internal domain imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from src.domain.change_detection.decision import DecisionResult
from src.domain.element_hashing import compute_element_hash
from src.domain.element_splitter.element_identity import generate_element_id

from .models import StateComparisonResult

if TYPE_CHECKING:
    from src.domain.element_splitter.models import ContextElement


def compare_element_state(
    element: "ContextElement",
    stored_hash: Optional[str],
) -> StateComparisonResult:
    """Compare the current element hash against a stored hash.

    Decision rules (strict equality, no partial matching):

    1. ``stored_hash is None``  →  ``REPROCESS``  (new element)
    2. ``current_hash == stored_hash``  →  ``SKIP``  (unchanged)
    3. ``current_hash != stored_hash``  →  ``REPROCESS``  (modified)

    The function computes the element's identity and content hash using the
    existing ``element_identity`` and ``element_hashing`` modules.  Exceptions
    raised by those modules (e.g. ``TypeError``, ``ValueError``) are
    propagated to the caller.

    Args:
        element: A ``ContextElement`` whose state should be evaluated.
        stored_hash: The SHA-256 hex digest previously persisted in the
            state store, or ``None`` if the element has never been indexed.

    Returns:
        A ``StateComparisonResult`` capturing the element identity, both
        hashes, and the deterministic decision.

    Raises:
        TypeError: Propagated from ``compute_element_hash`` when the
            element's ``raw_payload`` is not a ``dict``.
        ValueError: Propagated from ``compute_element_hash`` or
            ``generate_element_id`` on invalid input.
    """
    element_id = generate_element_id(element)
    current_hash = compute_element_hash(element)

    if stored_hash is None:
        decision = DecisionResult.REPROCESS
    elif current_hash == stored_hash:
        decision = DecisionResult.SKIP
    else:
        decision = DecisionResult.REPROCESS

    return StateComparisonResult(
        element_id=element_id,
        current_hash=current_hash,
        stored_hash=stored_hash,
        decision=decision,
    )
