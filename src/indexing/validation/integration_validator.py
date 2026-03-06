"""
Integration Validator — validates deterministic pipeline behaviour.

Provides high-level validation scenarios that confirm the element-level
ingestion pipeline behaves deterministically:

    1. Multi-element split correctness
    2. Re-run-without-changes produces zero reprocessing
    3. Single-element change triggers selective reprocessing
    4. Document identity stability across formatting variations

Each scenario returns a structured result dictionary suitable for
automated assertion in the test suite.

Design constraints
==================

- **Read-only** — does not modify any frozen module or contract.
- **No Azure calls** — uses ``DeterministicRunner`` with in-memory stubs.
- **No forbidden imports** — does not import LLM, Purview, or RAG modules.
- **Observable** — emits structured logs per validation step.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List

from src.domain.search_document.models import SCHEMA_FIELDS
from src.domain.element_hashing import compute_element_hash
from src.domain.element_splitter import split_elements, generate_element_id

from .deterministic_runner import DeterministicRunner, PipelineResult

logger = logging.getLogger("indexing.validation.validator")


class IntegrationValidator:
    """Validate deterministic behaviour of the element-level indexing pipeline."""

    # -------------------------------------------------------------------
    # Scenario 1: Multi-element split
    # -------------------------------------------------------------------

    @staticmethod
    def validate_multi_element_split(blob_json: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that a blob with N elements produces N indexed documents.

        Checks:
            - documents_indexed == len(elements)
            - each document has a unique deterministic ID
            - IDs follow ``{source}::{type}::{name}`` format
            - each document maps to exactly one element
        """
        runner = DeterministicRunner()
        result = runner.run(blob_json)

        element_count = len(blob_json["elements"])

        ids = [er.element_id for er in result.element_results]
        unique_ids = set(ids)

        id_format_valid = all(
            len(eid.split("::")) >= 3 for eid in ids
        )

        return {
            "scenario": "multi_element_split",
            "element_count": element_count,
            "documents_indexed": result.documents_upserted,
            "unique_ids": len(unique_ids),
            "all_ids_unique": len(unique_ids) == element_count,
            "id_format_valid": id_format_valid,
            "passed": (
                result.documents_upserted == element_count
                and len(unique_ids) == element_count
                and id_format_valid
            ),
        }

    # -------------------------------------------------------------------
    # Scenario 2: Re-run without changes
    # -------------------------------------------------------------------

    @staticmethod
    def validate_rerun_without_changes(
        blob_json: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate that re-running the pipeline without changes skips all.

        Run 1: all elements are REPROCESS (new).
        Run 2: all elements are SKIP (unchanged).
        """
        runner = DeterministicRunner()

        run1 = runner.run(blob_json)
        run2 = runner.run(blob_json)

        element_count = len(blob_json["elements"])

        return {
            "scenario": "rerun_without_changes",
            "run1_processed": run1.elements_processed,
            "run1_indexed": run1.documents_upserted,
            "run2_processed": run2.elements_processed,
            "run2_skipped": run2.elements_skipped,
            "run2_reprocessed": run2.elements_reprocessed,
            "run2_index_updates": run2.documents_upserted,
            "passed": (
                run1.documents_upserted == element_count
                and run2.elements_skipped == element_count
                and run2.elements_reprocessed == 0
                and run2.documents_upserted == 0
            ),
        }

    # -------------------------------------------------------------------
    # Scenario 3: Single element change
    # -------------------------------------------------------------------

    @staticmethod
    def validate_single_element_change(
        blob_json: Dict[str, Any],
        change_index: int = 0,
        change_field: str = "description",
        change_value: str = "MODIFIED BY VALIDATION SCENARIO",
    ) -> Dict[str, Any]:
        """Validate that changing one element reindexes only that element.

        Steps:
            1. Run pipeline on original data (all REPROCESS).
            2. Modify a single element's description.
            3. Run pipeline on modified data.
            4. Expect exactly 1 REPROCESS, rest SKIP.
        """
        runner = DeterministicRunner()

        # Run 1: initial indexing
        run1 = runner.run(blob_json)

        # Get the ID of the element we'll change
        changed_element_id = run1.element_results[change_index].element_id

        # Modify one element
        modified_json = copy.deepcopy(blob_json)
        modified_json["elements"][change_index][change_field] = change_value

        # Run 2: only the modified element should reprocess
        run2 = runner.run(modified_json)

        element_count = len(blob_json["elements"])
        expected_skip = element_count - 1

        # Verify the changed element was reprocessed
        reprocessed_ids = [
            er.element_id for er in run2.element_results
            if er.decision == "REPROCESS"
        ]
        skipped_ids = [
            er.element_id for er in run2.element_results
            if er.decision == "SKIP"
        ]

        # The changed element's ID should remain the same
        id_stable = changed_element_id in reprocessed_ids

        return {
            "scenario": "single_element_change",
            "elements_evaluated": run2.elements_processed,
            "skipped": run2.elements_skipped,
            "reprocessed": run2.elements_reprocessed,
            "documents_updated": run2.documents_upserted,
            "changed_element_id": changed_element_id,
            "id_stable": id_stable,
            "passed": (
                run2.elements_skipped == expected_skip
                and run2.elements_reprocessed == 1
                and run2.documents_upserted == 1
                and id_stable
            ),
        }

    # -------------------------------------------------------------------
    # Scenario 4: Document identity stability
    # -------------------------------------------------------------------

    @staticmethod
    def validate_identity_stability(
        blob_json: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate that identity is stable across formatting variations.

        Runs the pipeline three times with:
            - Original JSON
            - Reordered JSON fields
            - Extra whitespace in JSON fields (within values is not added —
              only structural field reordering is tested)

        All runs must produce identical document IDs.
        """
        runner = DeterministicRunner()

        # Run 1: Original
        run1 = runner.run(blob_json)
        ids_run1 = [er.element_id for er in run1.element_results]

        # Run 2: Reordered fields
        reordered = _reorder_element_fields(blob_json)
        runner2 = DeterministicRunner()
        run2 = runner2.run(reordered)
        ids_run2 = [er.element_id for er in run2.element_results]

        # Run 3: Same data again (fresh runner)
        runner3 = DeterministicRunner()
        run3 = runner3.run(blob_json)
        ids_run3 = [er.element_id for er in run3.element_results]

        ids_stable = ids_run1 == ids_run2 == ids_run3

        return {
            "scenario": "identity_stability",
            "ids_run1": ids_run1,
            "ids_run2": ids_run2,
            "ids_run3": ids_run3,
            "ids_stable": ids_stable,
            "passed": ids_stable,
        }

    # -------------------------------------------------------------------
    # Contract verification
    # -------------------------------------------------------------------

    @staticmethod
    def verify_schema_contract() -> Dict[str, Any]:
        """Verify that the frozen schema fields are unchanged.

        Checks the builder's SCHEMA_FIELDS against the expected v1.1.0
        field list.  If schema drift is detected, returns passed=False.
        """
        expected_fields = frozenset({
            "id", "sourceSystem", "entityType", "schemaVersion",
            "entityName", "entityPath", "description", "businessMeaning",
            "domain", "tags", "content", "contentVector",
            "dataType", "sourceTable", "cedsReference",
            "lineage", "lastUpdated",
            "blobPath", "originalSourceFile",
        })

        fields_match = SCHEMA_FIELDS == expected_fields
        extra = SCHEMA_FIELDS - expected_fields
        missing = expected_fields - SCHEMA_FIELDS

        return {
            "check": "schema_contract_verification",
            "expected_count": len(expected_fields),
            "actual_count": len(SCHEMA_FIELDS),
            "fields_match": fields_match,
            "extra_fields": sorted(extra) if extra else [],
            "missing_fields": sorted(missing) if missing else [],
            "passed": fields_match,
        }

    # -------------------------------------------------------------------
    # Safety checks
    # -------------------------------------------------------------------

    @staticmethod
    def verify_safety_guardrails() -> Dict[str, Any]:
        """Verify that forbidden operations are absent from pipeline modules.

        Checks source code of writer and state_writer for:
            - No index rebuild
            - No document deletes
            - No schema mutation
        """
        import src.infrastructure.search_writer.writer as writer_mod
        import src.infrastructure.state_store.state_writer as state_mod
        import re

        writer_source = open(writer_mod.__file__, "r", encoding="utf-8").read()
        state_source = open(state_mod.__file__, "r", encoding="utf-8").read()

        combined = writer_source + state_source

        checks = {
            "no_delete_documents": re.search(
                r'\.delete_documents\s*\(', combined
            ) is None,
            "no_create_index": "create_index" not in combined,
            "no_delete_index": "delete_index" not in combined,
            "no_reset_index": "reset_index" not in combined,
            "no_search_index_client": "SearchIndexClient" not in combined,
            "no_schema_mutation": "create_or_update_index" not in combined,
            "allowed_operation_present": "merge_or_upload_documents" in writer_source,
        }

        all_passed = all(checks.values())

        return {
            "check": "safety_guardrails",
            "checks": checks,
            "passed": all_passed,
        }


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------


def _reorder_element_fields(blob_json: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep copy of *blob_json* with element dict fields reversed.

    This simulates formatting/ordering differences in the source JSON
    while keeping the logical content identical.
    """
    output = copy.deepcopy(blob_json)
    reordered_elements = []
    for el in output["elements"]:
        reordered = dict(reversed(list(el.items())))
        reordered_elements.append(reordered)
    output["elements"] = reordered_elements
    return output
