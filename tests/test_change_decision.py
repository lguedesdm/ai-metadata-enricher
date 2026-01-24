"""
Unit tests for deterministic state comparison (skip vs reprocess).

Validates:
- New asset (no previous state) → REPROCESS
- Unchanged asset → SKIP
- Changed asset → REPROCESS
- Invalid or incomplete previous state → REPROCESS
"""

import pytest

from src.domain.change_detection import (
    DecisionResult,
    decide_reprocess_or_skip,
)


class TestDecision:
    def test_new_asset_no_previous_state(self):
        assert (
            decide_reprocess_or_skip("abc123", None) == DecisionResult.REPROCESS
        )

    def test_unchanged_asset_same_hash(self):
        current = "deadbeef" * 8  # 64 chars
        previous = current
        assert decide_reprocess_or_skip(current, previous) == DecisionResult.SKIP

    def test_changed_asset_different_hash(self):
        current = "0" * 64
        previous = "1" * 64
        assert (
            decide_reprocess_or_skip(current, previous) == DecisionResult.REPROCESS
        )

    def test_previous_state_object_with_hash_key(self):
        current = "a" * 64
        previous_obj = {"hash": current}
        assert decide_reprocess_or_skip(current, previous_obj) == DecisionResult.SKIP

    def test_previous_state_object_with_previous_hash_key(self):
        current = "b" * 64
        previous_obj = {"previousHash": current}
        assert decide_reprocess_or_skip(current, previous_obj) == DecisionResult.SKIP

    def test_invalid_previous_state_missing_hash(self):
        current = "c" * 64
        previous_obj = {}
        assert (
            decide_reprocess_or_skip(current, previous_obj)
            == DecisionResult.REPROCESS
        )

    def test_invalid_previous_state_non_string_hash(self):
        current = "d" * 64
        previous_obj = {"hash": 12345}
        assert (
            decide_reprocess_or_skip(current, previous_obj)
            == DecisionResult.REPROCESS
        )

    def test_invalid_previous_state_empty_string_hash(self):
        current = "e" * 64
        previous_obj = {"hash": ""}
        assert (
            decide_reprocess_or_skip(current, previous_obj)
            == DecisionResult.REPROCESS
        )

    def test_unsupported_previous_state_type_defaults_reprocess(self):
        current = "f" * 64
        previous_state = ["not supported"]
        assert (
            decide_reprocess_or_skip(current, previous_state)
            == DecisionResult.REPROCESS
        )

    def test_type_error_on_non_string_current_hash(self):
        with pytest.raises(TypeError):
            decide_reprocess_or_skip(123, None)
