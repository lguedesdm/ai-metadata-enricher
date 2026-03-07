"""
Deterministic tests for the element-level state comparison module.

Test categories
===============

1. **New element detection** — ``stored_hash is None`` → ``REPROCESS``.
2. **Unchanged element detection** — hashes match → ``SKIP``.
3. **Modified element detection** — hashes differ → ``REPROCESS``.
4. **Deterministic execution** — identical inputs always yield identical results.
5. **Non-mutation guarantee** — the input ``ContextElement`` is never modified.
6. **Result structure** — ``StateComparisonResult`` is populated correctly.
"""

from __future__ import annotations

import copy

import pytest

from src.domain.change_detection.decision import DecisionResult
from src.domain.element_hashing import compute_element_hash
from src.domain.element_splitter.element_identity import generate_element_id
from src.domain.element_splitter.models import ContextElement
from src.domain.element_state import (
    StateComparisonResult,
    StateDecision,
    compare_element_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_element(
    *,
    source_system: str = "synergy",
    element_name: str = "Student Enrollment",
    element_type: str = "table",
    description: str = "Stores student enrollment records.",
    raw_payload: dict | None = None,
) -> ContextElement:
    """Create a ``ContextElement`` with sensible defaults."""
    if raw_payload is None:
        raw_payload = {
            "id": "synergy.student.enrollment.table",
            "sourceSystem": source_system,
            "entityType": element_type,
            "entityName": element_name,
            "entityPath": "synergy.student.enrollment",
            "description": description,
            "businessMeaning": "Core enrollment information for all students.",
            "domain": "Student Information",
            "tags": ["enrollment", "student", "core"],
            "content": "Student Enrollment table in Synergy.",
        }
    return ContextElement(
        source_system=source_system,
        element_name=element_name,
        element_type=element_type,
        description=description,
        raw_payload=raw_payload,
    )


def _stored_hash_for(element: ContextElement) -> str:
    """Return the current hash of *element*, simulating a stored hash."""
    return compute_element_hash(element)


# ===================================================================
# 1. New element detection — stored_hash is None → REPROCESS
# ===================================================================

class TestNewElement:
    """When no stored hash exists, the element must be reprocessed."""

    def test_none_stored_hash_yields_reprocess(self):
        elem = _make_element()
        result = compare_element_state(elem, stored_hash=None)
        assert result.decision == DecisionResult.REPROCESS

    def test_none_stored_hash_result_contains_none(self):
        elem = _make_element()
        result = compare_element_state(elem, stored_hash=None)
        assert result.stored_hash is None

    def test_none_stored_hash_still_computes_current_hash(self):
        elem = _make_element()
        result = compare_element_state(elem, stored_hash=None)
        expected_hash = compute_element_hash(elem)
        assert result.current_hash == expected_hash

    def test_none_stored_hash_populates_element_id(self):
        elem = _make_element()
        result = compare_element_state(elem, stored_hash=None)
        expected_id = generate_element_id(elem)
        assert result.element_id == expected_id


# ===================================================================
# 2. Unchanged element detection — hashes match → SKIP
# ===================================================================

class TestUnchangedElement:
    """When stored hash equals current hash, element should be skipped."""

    def test_matching_hashes_yield_skip(self):
        elem = _make_element()
        stored = _stored_hash_for(elem)
        result = compare_element_state(elem, stored_hash=stored)
        assert result.decision == DecisionResult.SKIP

    def test_skip_result_contains_matching_hashes(self):
        elem = _make_element()
        stored = _stored_hash_for(elem)
        result = compare_element_state(elem, stored_hash=stored)
        assert result.current_hash == result.stored_hash

    def test_skip_preserves_element_id(self):
        elem = _make_element()
        stored = _stored_hash_for(elem)
        result = compare_element_state(elem, stored_hash=stored)
        assert result.element_id == generate_element_id(elem)


# ===================================================================
# 3. Modified element detection — hashes differ → REPROCESS
# ===================================================================

class TestModifiedElement:
    """When hashes differ, the element must be reprocessed."""

    def test_different_hashes_yield_reprocess(self):
        elem = _make_element()
        result = compare_element_state(elem, stored_hash="0" * 64)
        assert result.decision == DecisionResult.REPROCESS

    def test_reprocess_result_contains_both_hashes(self):
        elem = _make_element()
        fake_stored = "a" * 64
        result = compare_element_state(elem, stored_hash=fake_stored)
        assert result.current_hash != result.stored_hash
        assert result.stored_hash == fake_stored

    def test_description_change_triggers_reprocess(self):
        """Simulate a real content change that produces a different hash."""
        original = _make_element()
        stored = _stored_hash_for(original)

        modified = _make_element(description="Updated enrollment description.")
        result = compare_element_state(modified, stored_hash=stored)
        assert result.decision == DecisionResult.REPROCESS

    def test_payload_change_triggers_reprocess(self):
        """Changing raw_payload fields should trigger reprocessing."""
        original = _make_element()
        stored = _stored_hash_for(original)

        payload = {
            "id": "synergy.student.enrollment.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Student Enrollment",
            "entityPath": "synergy.student.enrollment",
            "description": "Stores student enrollment records.",
            "businessMeaning": "CHANGED meaning.",
            "domain": "Student Information",
            "tags": ["enrollment", "student", "core"],
            "content": "Student Enrollment table in Synergy.",
        }
        modified = _make_element(raw_payload=payload)
        result = compare_element_state(modified, stored_hash=stored)
        assert result.decision == DecisionResult.REPROCESS


# ===================================================================
# 4. Deterministic execution
# ===================================================================

class TestDeterministicExecution:
    """Multiple executions with identical inputs must produce identical results."""

    def test_repeated_calls_produce_identical_results(self):
        elem = _make_element()
        stored = _stored_hash_for(elem)
        results = [compare_element_state(elem, stored_hash=stored) for _ in range(50)]
        decisions = {r.decision for r in results}
        hashes = {r.current_hash for r in results}
        assert len(decisions) == 1
        assert len(hashes) == 1

    def test_new_element_deterministic_across_runs(self):
        elem = _make_element()
        results = [compare_element_state(elem, stored_hash=None) for _ in range(50)]
        decisions = {r.decision for r in results}
        assert decisions == {DecisionResult.REPROCESS}

    def test_modified_element_deterministic_across_runs(self):
        elem = _make_element()
        fake_stored = "f" * 64
        results = [compare_element_state(elem, stored_hash=fake_stored) for _ in range(50)]
        decisions = {r.decision for r in results}
        assert decisions == {DecisionResult.REPROCESS}

    def test_independent_elements_with_same_content_yield_same_decision(self):
        elem_a = _make_element()
        elem_b = _make_element()
        stored = _stored_hash_for(elem_a)
        result_a = compare_element_state(elem_a, stored_hash=stored)
        result_b = compare_element_state(elem_b, stored_hash=stored)
        assert result_a.decision == result_b.decision
        assert result_a.current_hash == result_b.current_hash


# ===================================================================
# 5. Non-mutation guarantee
# ===================================================================

class TestNonMutation:
    """The original ContextElement must remain unchanged after comparison."""

    def test_element_unchanged_after_skip(self):
        elem = _make_element()
        snapshot = copy.deepcopy(elem)
        compare_element_state(elem, stored_hash=_stored_hash_for(elem))
        assert elem == snapshot

    def test_element_unchanged_after_reprocess_new(self):
        elem = _make_element()
        snapshot = copy.deepcopy(elem)
        compare_element_state(elem, stored_hash=None)
        assert elem == snapshot

    def test_element_unchanged_after_reprocess_modified(self):
        elem = _make_element()
        snapshot = copy.deepcopy(elem)
        compare_element_state(elem, stored_hash="0" * 64)
        assert elem == snapshot

    def test_raw_payload_unchanged_after_comparison(self):
        elem = _make_element()
        payload_snapshot = copy.deepcopy(elem.raw_payload)
        compare_element_state(elem, stored_hash=None)
        assert elem.raw_payload == payload_snapshot


# ===================================================================
# 6. Result structure
# ===================================================================

class TestResultStructure:
    """StateComparisonResult must be correctly populated."""

    def test_result_is_immutable(self):
        elem = _make_element()
        result = compare_element_state(elem, stored_hash=None)
        with pytest.raises(AttributeError):
            result.decision = DecisionResult.SKIP  # type: ignore[misc]

    def test_result_str_representation(self):
        elem = _make_element()
        result = compare_element_state(elem, stored_hash=None)
        text = str(result)
        assert "REPROCESS" in text
        assert result.element_id in text

    def test_result_str_with_stored_hash(self):
        elem = _make_element()
        stored = _stored_hash_for(elem)
        result = compare_element_state(elem, stored_hash=stored)
        text = str(result)
        assert "SKIP" in text

    def test_state_decision_alias_matches_decision_result(self):
        """StateDecision should be the same type as DecisionResult."""
        assert StateDecision is DecisionResult
        assert StateDecision.SKIP == DecisionResult.SKIP
        assert StateDecision.REPROCESS == DecisionResult.REPROCESS

    def test_result_has_all_required_fields(self):
        elem = _make_element()
        result = compare_element_state(elem, stored_hash=None)
        assert hasattr(result, "element_id")
        assert hasattr(result, "current_hash")
        assert hasattr(result, "stored_hash")
        assert hasattr(result, "decision")


# ===================================================================
# 7. Edge cases
# ===================================================================

class TestEdgeCases:
    """Boundary conditions and edge cases."""

    def test_empty_string_stored_hash_is_not_none(self):
        """An empty string is not None — should compare and yield REPROCESS."""
        elem = _make_element()
        result = compare_element_state(elem, stored_hash="")
        assert result.decision == DecisionResult.REPROCESS
        assert result.stored_hash == ""

    def test_stored_hash_with_whitespace_does_not_match(self):
        """A stored hash with leading/trailing whitespace should not match."""
        elem = _make_element()
        real_hash = compute_element_hash(elem)
        result = compare_element_state(elem, stored_hash=f" {real_hash} ")
        assert result.decision == DecisionResult.REPROCESS

    def test_case_sensitive_comparison(self):
        """Hash comparison must be case-sensitive."""
        elem = _make_element()
        real_hash = compute_element_hash(elem)
        upper_hash = real_hash.upper()
        # SHA-256 hex is lowercase; uppercase should not match
        if upper_hash != real_hash:
            result = compare_element_state(elem, stored_hash=upper_hash)
            assert result.decision == DecisionResult.REPROCESS

    def test_different_source_systems_same_name_produce_same_ids(self):
        """ID depends only on element_name, not source_system."""
        elem_syn = _make_element(source_system="synergy")
        elem_zip = _make_element(source_system="zipline")
        result_syn = compare_element_state(elem_syn, stored_hash=None)
        result_zip = compare_element_state(elem_zip, stored_hash=None)
        assert result_syn.element_id == result_zip.element_id
