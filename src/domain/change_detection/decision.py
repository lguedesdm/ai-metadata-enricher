"""
Deterministic state comparison for change detection.

Provides a pure, domain-level decision mechanism to determine whether an asset
should be REPROCESSed or SKIPped based on hash comparison. No side effects,
no persistence, no Azure dependencies.
"""
from enum import Enum
from typing import Any, Dict, Optional, Union


class DecisionResult(str, Enum):
    """Explicit decision result for change detection.

    - REPROCESS: The asset is new or has materially changed
    - SKIP: The asset is unchanged
    """

    REPROCESS = "REPROCESS"
    SKIP = "SKIP"


def decide_reprocess_or_skip(
    current_hash: str,
    previous_state: Optional[Union[str, Dict[str, Any]]] = None,
) -> DecisionResult:
    """
    Decide whether to REPROCESS or SKIP based on hash comparison.

    Rules:
    - If no previous state exists → REPROCESS
    - If previous hash equals current hash → SKIP
    - If previous hash differs from current hash → REPROCESS
    - Invalid/incomplete previous state → REPROCESS (safe default)

    Args:
        current_hash: The current asset hash (64-char lowercase hex expected)
        previous_state: Either a previous hash string, a dict containing a
            previous hash (e.g., {'hash': '...'} or {'previousHash': '...'}),
            or None if no prior state exists

    Returns:
        DecisionResult: REPROCESS or SKIP

    Raises:
        TypeError: If current_hash is not a string
    """
    if not isinstance(current_hash, str):
        raise TypeError(
            f"current_hash must be a str, got {type(current_hash).__name__}"
        )

    # No previous state → REPROCESS
    if previous_state is None:
        return DecisionResult.REPROCESS

    # Extract previous hash from supported shapes
    if isinstance(previous_state, str):
        previous_hash = previous_state
    elif isinstance(previous_state, dict):
        # Look for common keys; ignore non-string values
        candidate = previous_state.get("hash")
        if not isinstance(candidate, str) or not candidate:
            candidate = previous_state.get("previousHash")
        previous_hash = candidate if isinstance(candidate, str) else None
    else:
        # Unsupported type → safe default
        previous_hash = None

    # Invalid or missing previous hash → REPROCESS (safe default)
    if not previous_hash:
        return DecisionResult.REPROCESS

    # Compare
    if previous_hash == current_hash:
        return DecisionResult.SKIP
    return DecisionResult.REPROCESS
