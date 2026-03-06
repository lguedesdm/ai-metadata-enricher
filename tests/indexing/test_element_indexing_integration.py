"""
Deterministic integration tests for the element-level indexing pipeline.

Validates that the full pipeline — split → identity → hash → state comparison
→ build search document → upsert → state update — behaves deterministically
when exercised with in-memory mocks.

Test categories
===============

1. ``element_split_integrity`` — blob → N elements → N documents
2. ``identity_determinism`` — same data always yields same IDs
3. ``hash_stability`` — same content always yields same SHA-256
4. ``state_comparison`` — new=REPROCESS, unchanged=no-op, changed=REPROCESS
5. ``selective_reprocessing`` — only modified elements reprocessed
6. ``document_mapping_integrity`` — documents contain only SCHEMA_FIELDS keys
7. ``search_upsert_behavior`` — in-memory index records every upsert
8. ``integration_determinism`` — end-to-end pipeline is fully deterministic

All tests use ``DeterministicRunner`` and ``IntegrationValidator`` so that
Azure SDK and network calls are never made.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Dict, List

import pytest

from src.domain.element_splitter import split_elements, generate_element_id
from src.domain.element_hashing import compute_element_hash
from src.domain.element_state import compare_element_state, StateDecision
from src.domain.search_document.models import SCHEMA_FIELDS, SCHEMA_VERSION
from src.indexing.validation.deterministic_runner import (
    DeterministicRunner,
    InMemoryStateStore,
    InMemorySearchIndex,
    PipelineResult,
    ElementResult,
)
from src.indexing.validation.integration_validator import IntegrationValidator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_element(
    *,
    name: str = "Student Enrollment",
    entity_type: str = "table",
    source: str = "synergy",
    description: str = "Stores student enrollment records.",
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a single element dict for embedding in a blob fixture."""
    el = {
        "id": f"{source}.{entity_type}.{name.lower().replace(' ', '.')}",
        "sourceSystem": source,
        "entityType": entity_type,
        "entityName": name,
        "entityPath": f"{source}.{entity_type}.{name.lower().replace(' ', '.')}",
        "description": description,
        "businessMeaning": f"Business meaning for {name}.",
        "domain": "Student Information",
        "tags": ["tag1", "tag2"],
        "content": f"Content for {name}.",
        "lastUpdated": "2026-02-02T12:00:00Z",
        "schemaVersion": "1.0.0",
    }
    if extra:
        el.update(extra)
    return el


def _make_blob(elements: List[Dict[str, Any]], source: str = "synergy") -> Dict[str, Any]:
    """Build a blob JSON structure wrapping the given elements."""
    return {
        "sourceSystem": source,
        "schemaVersion": "1.0.0",
        "elements": elements,
    }


def _five_element_blob() -> Dict[str, Any]:
    """Blob with five distinct elements."""
    return _make_blob([
        _make_element(name="Student Enrollment", entity_type="table"),
        _make_element(name="Ethnicity", entity_type="column", extra={
            "dataType": "VARCHAR(50)", "sourceTable": "STU_DEMOGRAPHICS",
        }),
        _make_element(name="Grade Level", entity_type="column", extra={
            "dataType": "INT", "sourceTable": "STU_ENROLLMENT",
        }),
        _make_element(name="Attendance Record", entity_type="table"),
        _make_element(name="School Year", entity_type="column", extra={
            "dataType": "CHAR(4)", "sourceTable": "STU_ENROLLMENT",
        }),
    ])


def _single_element_blob() -> Dict[str, Any]:
    """Blob with one element."""
    return _make_blob([
        _make_element(name="Assessment Score", entity_type="column"),
    ])


# ===========================================================================
# Category 1: element_split_integrity
# ===========================================================================


class TestElementSplitIntegrity:
    """Verify that the splitter produces the correct number of elements."""

    def test_five_elements_produce_five_results(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        assert result.elements_processed == 5

    def test_single_element_produces_one_result(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        assert result.elements_processed == 1

    def test_each_element_has_result_entry(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        assert len(result.element_results) == 5

    def test_element_count_matches_blob(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        assert result.elements_processed == len(blob["elements"])


# ===========================================================================
# Category 2: identity_determinism
# ===========================================================================


class TestIdentityDeterminism:
    """Verify that element IDs are deterministic and correctly formatted."""

    def test_id_format_source_type_name(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        eid = result.element_results[0].element_id
        parts = eid.split("::")
        assert len(parts) == 3
        assert parts[0] == "synergy"
        assert parts[1] == "column"
        assert parts[2] == "assessment score"

    def test_ids_are_unique_across_elements(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        ids = [er.element_id for er in result.element_results]
        assert len(set(ids)) == 5

    def test_same_data_yields_same_ids_across_runs(self) -> None:
        blob = _five_element_blob()
        r1 = DeterministicRunner().run(blob)
        r2 = DeterministicRunner().run(blob)
        ids1 = [er.element_id for er in r1.element_results]
        ids2 = [er.element_id for er in r2.element_results]
        assert ids1 == ids2

    def test_id_is_lowercase(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        eid = result.element_results[0].element_id
        assert eid == eid.lower()

    def test_field_reorder_preserves_identity(self) -> None:
        """Reordering dict keys in elements must produce the same IDs."""
        blob = _five_element_blob()
        reordered = copy.deepcopy(blob)
        reordered["elements"] = [
            dict(reversed(list(el.items()))) for el in reordered["elements"]
        ]
        ids_orig = [er.element_id for er in DeterministicRunner().run(blob).element_results]
        ids_reord = [er.element_id for er in DeterministicRunner().run(reordered).element_results]
        assert ids_orig == ids_reord

    def test_whitespace_collapsed_in_identity(self) -> None:
        """Extra spaces in entityName should collapse to single space."""
        blob = _make_blob([
            _make_element(name="  Student   Enrollment  ", entity_type="table"),
        ])
        runner = DeterministicRunner()
        result = runner.run(blob)
        eid = result.element_results[0].element_id
        assert "  " not in eid


# ===========================================================================
# Category 3: hash_stability
# ===========================================================================


class TestHashStability:
    """Verify that hashing is deterministic and SHA-256 formatted."""

    def test_hash_is_64_char_hex(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        h = result.element_results[0].element_hash
        assert len(h) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", h)

    def test_same_content_same_hash(self) -> None:
        blob = _single_element_blob()
        h1 = DeterministicRunner().run(blob).element_results[0].element_hash
        h2 = DeterministicRunner().run(blob).element_results[0].element_hash
        assert h1 == h2

    def test_different_content_different_hash(self) -> None:
        blob1 = _single_element_blob()
        blob2 = copy.deepcopy(blob1)
        blob2["elements"][0]["description"] = "Changed description."
        h1 = DeterministicRunner().run(blob1).element_results[0].element_hash
        h2 = DeterministicRunner().run(blob2).element_results[0].element_hash
        assert h1 != h2

    def test_volatile_fields_excluded_from_hash(self) -> None:
        """Changing lastUpdated or schemaVersion should not alter hash."""
        blob1 = _single_element_blob()
        blob2 = copy.deepcopy(blob1)
        blob2["elements"][0]["lastUpdated"] = "2099-01-01T00:00:00Z"
        blob2["elements"][0]["schemaVersion"] = "99.99.99"
        h1 = DeterministicRunner().run(blob1).element_results[0].element_hash
        h2 = DeterministicRunner().run(blob2).element_results[0].element_hash
        assert h1 == h2

    def test_five_elements_produce_five_distinct_hashes(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        hashes = [er.element_hash for er in result.element_results]
        assert len(set(hashes)) == 5


# ===========================================================================
# Category 4: state_comparison
# ===========================================================================


class TestStateComparison:
    """Verify REPROCESS/no-op decisions via the state comparator."""

    def test_new_element_triggers_reprocess(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        assert result.element_results[0].decision == "REPROCESS"

    def test_unchanged_element_triggers_no_reprocess(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        result2 = runner.run(blob)
        assert result2.element_results[0].decision != "REPROCESS"

    def test_changed_element_triggers_reprocess(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        modified = copy.deepcopy(blob)
        modified["elements"][0]["description"] = "Modified."
        result2 = runner.run(modified)
        assert result2.element_results[0].decision == "REPROCESS"

    def test_all_new_elements_reprocess(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        assert result.elements_reprocessed == 5
        assert result.elements_skipped == 0

    def test_all_unchanged_elements_are_not_reprocessed(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        result2 = runner.run(blob)
        assert result2.elements_skipped == 5
        assert result2.elements_reprocessed == 0


# ===========================================================================
# Category 5: selective_reprocessing
# ===========================================================================


class TestSelectiveReprocessing:
    """Verify that only modified elements are reprocessed."""

    def test_one_of_five_changed(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)

        modified = copy.deepcopy(blob)
        modified["elements"][2]["description"] = "Changed grade level."
        result = runner.run(modified)

        assert result.elements_reprocessed == 1
        assert result.elements_skipped == 4
        assert result.documents_upserted == 1

    def test_two_of_five_changed(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)

        modified = copy.deepcopy(blob)
        modified["elements"][0]["description"] = "Changed enrollment."
        modified["elements"][4]["description"] = "Changed school year."
        result = runner.run(modified)

        assert result.elements_reprocessed == 2
        assert result.elements_skipped == 3
        assert result.documents_upserted == 2

    def test_only_changed_id_reprocessed(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        run1 = runner.run(blob)

        changed_idx = 1
        changed_id = run1.element_results[changed_idx].element_id

        modified = copy.deepcopy(blob)
        modified["elements"][changed_idx]["description"] = "Changed ethnicity."
        run2 = runner.run(modified)

        reprocessed_ids = [
            er.element_id for er in run2.element_results if er.decision == "REPROCESS"
        ]
        assert reprocessed_ids == [changed_id]

    def test_state_updated_only_for_reprocessed(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)

        modified = copy.deepcopy(blob)
        modified["elements"][3]["description"] = "Changed attendance."
        run2 = runner.run(modified)

        state_writes = [er for er in run2.element_results if er.state_write]
        assert len(state_writes) == 1
        assert state_writes[0].decision == "REPROCESS"

    def test_unchanged_elements_do_not_upsert(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)

        # Reset upsert counter after initial run
        runner.search_index.reset_count()

        result = runner.run(blob)
        assert runner.search_index.upsert_count == 0
        assert result.documents_upserted == 0


# ===========================================================================
# Category 6: document_mapping_integrity
# ===========================================================================


class TestDocumentMappingIntegrity:
    """Verify that search documents conform to SCHEMA_FIELDS."""

    def test_document_keys_within_schema(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        for doc in runner.search_index.documents.values():
            assert set(doc.keys()).issubset(SCHEMA_FIELDS), (
                f"Extra keys: {set(doc.keys()) - SCHEMA_FIELDS}"
            )

    def test_every_document_has_id(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        for doc in runner.search_index.documents.values():
            assert "id" in doc
            assert doc["id"]  # non-empty

    def test_document_id_matches_element_id(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        element_ids = {er.element_id for er in result.element_results}
        document_ids = set(runner.search_index.documents.keys())
        assert element_ids == document_ids

    def test_schema_version_in_document(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        doc = list(runner.search_index.documents.values())[0]
        assert doc.get("schemaVersion") == SCHEMA_VERSION

    def test_source_system_in_document(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        doc = list(runner.search_index.documents.values())[0]
        assert doc.get("sourceSystem") == "synergy"

    def test_entity_type_in_document(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        doc = list(runner.search_index.documents.values())[0]
        assert doc.get("entityType") == "column"

    def test_schema_field_count_frozen_at_19(self) -> None:
        assert len(SCHEMA_FIELDS) == 19


# ===========================================================================
# Category 7: search_upsert_behavior
# ===========================================================================


class TestSearchUpsertBehavior:
    """Verify the in-memory search index correctly records upserts."""

    def test_initial_run_upserts_all(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        result = runner.run(blob)
        assert runner.search_index.document_count == 5
        assert result.documents_upserted == 5

    def test_rerun_upserts_zero(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        runner.search_index.reset_count()
        result = runner.run(blob)
        assert result.documents_upserted == 0

    def test_partial_change_upserts_only_changed(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        runner.search_index.reset_count()

        modified = copy.deepcopy(blob)
        modified["elements"][0]["description"] = "Changed."
        result = runner.run(modified)
        # Only 1 upsert for the changed element
        assert runner.search_index.upsert_count == 1
        assert result.documents_upserted == 1

    def test_upsert_overwrites_existing_document(self) -> None:
        blob = _single_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)

        doc1 = list(runner.search_index.documents.values())[0]
        desc1 = doc1.get("description")

        modified = copy.deepcopy(blob)
        modified["elements"][0]["description"] = "Updated description."
        runner.run(modified)

        doc2 = list(runner.search_index.documents.values())[0]
        desc2 = doc2.get("description")
        assert desc1 != desc2
        assert desc2 == "Updated description."

    def test_document_count_stable_after_rerun(self) -> None:
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        assert runner.search_index.document_count == 5
        runner.run(blob)
        assert runner.search_index.document_count == 5  # same documents, no new entries


# ===========================================================================
# Category 8: integration_determinism
# ===========================================================================


class TestIntegrationDeterminism:
    """End-to-end determinism assertions — pipeline produces identical
    results across repeated runs with the same input."""

    def test_full_pipeline_idempotent_first_run(self) -> None:
        """First run processes all elements."""
        blob = _five_element_blob()
        result = DeterministicRunner().run(blob)
        assert result.elements_processed == 5
        assert result.elements_reprocessed == 5
        assert result.elements_skipped == 0
        assert result.documents_upserted == 5
        assert result.documents_unchanged == 0

    def test_full_pipeline_idempotent_second_run(self) -> None:
        """Second run with identical input produces zero reprocessing."""
        blob = _five_element_blob()
        runner = DeterministicRunner()
        runner.run(blob)
        result = runner.run(blob)
        assert result.elements_processed == 5
        assert result.elements_reprocessed == 0
        assert result.elements_skipped == 5
        assert result.documents_upserted == 0
        assert result.documents_unchanged == 5

    def test_three_consecutive_runs_converge(self) -> None:
        """Three runs: only the first produces upserts."""
        blob = _five_element_blob()
        runner = DeterministicRunner()
        r1 = runner.run(blob)
        r2 = runner.run(blob)
        r3 = runner.run(blob)

        assert r1.documents_upserted == 5
        assert r2.documents_upserted == 0
        assert r3.documents_upserted == 0

    def test_element_results_frozen(self) -> None:
        blob = _single_element_blob()
        result = DeterministicRunner().run(blob)
        er = result.element_results[0]
        with pytest.raises(AttributeError):
            er.element_id = "tampered"  # type: ignore[misc]

    def test_pipeline_result_frozen(self) -> None:
        blob = _single_element_blob()
        result = DeterministicRunner().run(blob)
        with pytest.raises(AttributeError):
            result.elements_processed = 999  # type: ignore[misc]

    def test_hashes_align_between_runner_and_direct_call(self) -> None:
        """Hashes from the runner must match direct compute_element_hash."""
        blob = _single_element_blob()
        elements = split_elements(blob)
        direct_hash = compute_element_hash(elements[0])
        runner_hash = DeterministicRunner().run(blob).element_results[0].element_hash
        assert direct_hash == runner_hash

    def test_ids_align_between_runner_and_direct_call(self) -> None:
        """IDs from the runner must match direct generate_element_id."""
        blob = _single_element_blob()
        elements = split_elements(blob)
        direct_id = generate_element_id(elements[0])
        runner_id = DeterministicRunner().run(blob).element_results[0].element_id
        assert direct_id == runner_id


# ===========================================================================
# Validator scenario tests
# ===========================================================================


class TestValidatorMultiElementSplit:
    """Tests for IntegrationValidator.validate_multi_element_split."""

    def test_scenario_passes(self) -> None:
        result = IntegrationValidator.validate_multi_element_split(
            _five_element_blob()
        )
        assert result["passed"] is True

    def test_scenario_metrics(self) -> None:
        result = IntegrationValidator.validate_multi_element_split(
            _five_element_blob()
        )
        assert result["element_count"] == 5
        assert result["documents_indexed"] == 5
        assert result["unique_ids"] == 5
        assert result["all_ids_unique"] is True
        assert result["id_format_valid"] is True


class TestValidatorRerunWithoutChanges:
    """Tests for IntegrationValidator.validate_rerun_without_changes."""

    def test_scenario_passes(self) -> None:
        result = IntegrationValidator.validate_rerun_without_changes(
            _five_element_blob()
        )
        assert result["passed"] is True

    def test_run2_all_skipped(self) -> None:
        result = IntegrationValidator.validate_rerun_without_changes(
            _five_element_blob()
        )
        assert result["run2_skipped"] == 5
        assert result["run2_reprocessed"] == 0
        assert result["run2_index_updates"] == 0


class TestValidatorSingleElementChange:
    """Tests for IntegrationValidator.validate_single_element_change."""

    def test_scenario_passes(self) -> None:
        result = IntegrationValidator.validate_single_element_change(
            _five_element_blob()
        )
        assert result["passed"] is True

    def test_selective_reprocessing_metrics(self) -> None:
        result = IntegrationValidator.validate_single_element_change(
            _five_element_blob()
        )
        assert result["skipped"] == 4
        assert result["reprocessed"] == 1
        assert result["documents_updated"] == 1
        assert result["id_stable"] is True

    def test_change_at_different_index(self) -> None:
        result = IntegrationValidator.validate_single_element_change(
            _five_element_blob(), change_index=3
        )
        assert result["passed"] is True
        assert result["skipped"] == 4
        assert result["reprocessed"] == 1


class TestValidatorIdentityStability:
    """Tests for IntegrationValidator.validate_identity_stability."""

    def test_scenario_passes(self) -> None:
        result = IntegrationValidator.validate_identity_stability(
            _five_element_blob()
        )
        assert result["passed"] is True

    def test_ids_match_across_runs(self) -> None:
        result = IntegrationValidator.validate_identity_stability(
            _five_element_blob()
        )
        assert result["ids_run1"] == result["ids_run2"]
        assert result["ids_run2"] == result["ids_run3"]


class TestSchemaContractVerification:
    """Tests for IntegrationValidator.verify_schema_contract."""

    def test_schema_matches_frozen_contract(self) -> None:
        result = IntegrationValidator.verify_schema_contract()
        assert result["passed"] is True

    def test_field_counts_align(self) -> None:
        result = IntegrationValidator.verify_schema_contract()
        assert result["expected_count"] == 19
        assert result["actual_count"] == 19

    def test_no_extra_or_missing_fields(self) -> None:
        result = IntegrationValidator.verify_schema_contract()
        assert result["extra_fields"] == []
        assert result["missing_fields"] == []


class TestSafetyGuardrails:
    """Tests for IntegrationValidator.verify_safety_guardrails."""

    def test_safety_checks_pass(self) -> None:
        result = IntegrationValidator.verify_safety_guardrails()
        assert result["passed"] is True

    def test_no_destructive_operations(self) -> None:
        result = IntegrationValidator.verify_safety_guardrails()
        checks = result["checks"]
        assert checks["no_delete_documents"] is True
        assert checks["no_create_index"] is True
        assert checks["no_delete_index"] is True
        assert checks["no_reset_index"] is True

    def test_allowed_operation_present(self) -> None:
        result = IntegrationValidator.verify_safety_guardrails()
        assert result["checks"]["allowed_operation_present"] is True


# ===========================================================================
# In-memory stub unit tests
# ===========================================================================


class TestInMemoryStateStore:
    """Validate the in-memory state store stub itself."""

    def test_get_returns_none_for_unknown(self) -> None:
        store = InMemoryStateStore()
        assert store.get_state("unknown", "table") is None

    def test_upsert_and_retrieve(self) -> None:
        store = InMemoryStateStore()
        item = {"id": "e1", "entityType": "table", "contentHash": "abc"}
        store.upsert_state(item)
        assert store.get_state("e1", "table") == item

    def test_get_stored_hash(self) -> None:
        store = InMemoryStateStore()
        store.upsert_state({"id": "e1", "entityType": "table", "contentHash": "abc"})
        assert store.get_stored_hash("e1", "table") == "abc"

    def test_get_stored_hash_none_for_missing(self) -> None:
        store = InMemoryStateStore()
        assert store.get_stored_hash("e1", "table") is None

    def test_upsert_overwrites(self) -> None:
        store = InMemoryStateStore()
        store.upsert_state({"id": "e1", "entityType": "table", "contentHash": "v1"})
        store.upsert_state({"id": "e1", "entityType": "table", "contentHash": "v2"})
        assert store.get_stored_hash("e1", "table") == "v2"

    def test_clear(self) -> None:
        store = InMemoryStateStore()
        store.upsert_state({"id": "e1", "entityType": "table", "contentHash": "abc"})
        store.clear()
        assert store.get_state("e1", "table") is None

    def test_records_property(self) -> None:
        store = InMemoryStateStore()
        store.upsert_state({"id": "e1", "entityType": "table", "contentHash": "abc"})
        assert len(store.records) == 1


class TestInMemorySearchIndex:
    """Validate the in-memory search index stub itself."""

    def test_merge_or_upload(self) -> None:
        index = InMemorySearchIndex()
        index.merge_or_upload({"id": "doc1", "content": "hello"})
        assert index.get_document("doc1") == {"id": "doc1", "content": "hello"}

    def test_upsert_count(self) -> None:
        index = InMemorySearchIndex()
        index.merge_or_upload({"id": "doc1"})
        index.merge_or_upload({"id": "doc2"})
        assert index.upsert_count == 2

    def test_reset_count(self) -> None:
        index = InMemorySearchIndex()
        index.merge_or_upload({"id": "doc1"})
        index.reset_count()
        assert index.upsert_count == 0

    def test_document_count(self) -> None:
        index = InMemorySearchIndex()
        index.merge_or_upload({"id": "doc1"})
        index.merge_or_upload({"id": "doc2"})
        assert index.document_count == 2

    def test_overwrite_same_id(self) -> None:
        index = InMemorySearchIndex()
        index.merge_or_upload({"id": "doc1", "v": 1})
        index.merge_or_upload({"id": "doc1", "v": 2})
        assert index.document_count == 1
        assert index.get_document("doc1")["v"] == 2
        # Count reflects both calls
        assert index.upsert_count == 2

    def test_get_nonexistent_document(self) -> None:
        index = InMemorySearchIndex()
        assert index.get_document("nope") is None

    def test_documents_property_is_copy(self) -> None:
        index = InMemorySearchIndex()
        index.merge_or_upload({"id": "doc1"})
        docs = index.documents
        docs["doc1"] = {"id": "tampered"}
        assert index.get_document("doc1") == {"id": "doc1"}
