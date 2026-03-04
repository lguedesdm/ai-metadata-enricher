"""
Element-level state comparison module for AI Metadata Enricher.

Provides deterministic comparison of element hashes to decide whether a
``ContextElement`` should be reprocessed or skipped during incremental
ingestion.  The comparison is a pure, side-effect-free function that
operates solely on the element's content hash and a previously stored hash.

Public API:
    - compare_element_state(): Compare current vs. stored hash → decision.
    - StateComparisonResult: Immutable result of a state comparison.
    - StateDecision: Re-exported alias for ``DecisionResult`` (SKIP / REPROCESS).
"""

from .comparator import compare_element_state
from .models import StateComparisonResult

# Re-export DecisionResult under the domain-appropriate alias.
from src.domain.change_detection.decision import DecisionResult as StateDecision

__all__ = [
    "compare_element_state",
    "StateComparisonResult",
    "StateDecision",
]
