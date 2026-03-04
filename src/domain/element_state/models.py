"""
Domain models for element-level state comparison.

Provides the immutable result container for state comparison operations.
The decision enum is reused from ``src.domain.change_detection.decision``
to avoid duplication.

All types are pure value objects — no I/O, no logging, no infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.domain.change_detection.decision import DecisionResult


@dataclass(frozen=True)
class StateComparisonResult:
    """Immutable value object capturing the outcome of an element state comparison.

    Attributes:
        element_id: Deterministic identity of the element
            (``"{source}::{type}::{name}"``).
        current_hash: SHA-256 hex digest computed from the current element payload.
        stored_hash: SHA-256 hex digest previously persisted in the state store,
            or ``None`` if the element has never been indexed.
        decision: ``DecisionResult.SKIP`` when hashes match,
            ``DecisionResult.REPROCESS`` otherwise (including first-time elements).
    """

    element_id: str
    current_hash: str
    stored_hash: Optional[str]
    decision: DecisionResult

    def __str__(self) -> str:
        return (
            f"{self.element_id}: {self.decision.value} "
            f"(current={self.current_hash[:12]}… "
            f"stored={self.stored_hash[:12] + '…' if self.stored_hash else 'None'})"
        )
