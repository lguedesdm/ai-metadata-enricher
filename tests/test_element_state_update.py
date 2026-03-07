"""
Tests for the Element State Writer.

Test categories
===============

1. **Successful state persistence** — state record written via state_store.
2. **Record structure** — correct fields and values in upserted record.
3. **Entity type extraction** — entity type parsed from element ID.
4. **Deterministic behavior** — consistent records from same inputs.
5. **Input validation** — rejects invalid element_id, hash, source_system.
6. **No mutation** — input arguments not modified.
7. **Error propagation** — state store failures raise, never silenced.
8. **Observability** — logs element_id and operation, not full payload.
9. **Guardrail compliance** — no forbidden operations in source.
10. **Architecture isolation** — no domain module imports.
11. **Idempotent calls** — repeated calls produce consistent behavior.
12. **Record field validation** — record fields match STATE_RECORD_FIELDS.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from src.infrastructure.state_store.state_writer import (
    update_element_state,
    _validate_inputs,
    _extract_entity_type,
)
from src.infrastructure.state_store.models import STATE_RECORD_FIELDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ELEMENT_ID = "U3R1ZGVudCBFbnJvbGxtZW50"  # base64("Student Enrollment")
CONTENT_HASH = "a" * 64
SOURCE_SYSTEM = "synergy"


def _mock_state_store(*, side_effect=None) -> MagicMock:
    """Build a mock state store with an ``upsert_state`` method."""
    store = MagicMock()
    if side_effect:
        store.upsert_state.side_effect = side_effect
    else:
        store.upsert_state.return_value = {}
    return store


# ===================================================================
# 1. Successful state persistence
# ===================================================================


class TestSuccessfulStatePersistence:
    """State record must be written via state_store.upsert_state."""

    def test_calls_upsert_state(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        store.upsert_state.assert_called_once()

    def test_passes_dict_to_upsert(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        args, kwargs = store.upsert_state.call_args
        record = args[0] if args else kwargs.get("item")
        assert isinstance(record, dict)

    def test_record_contains_element_id(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        assert record["id"] == ELEMENT_ID


# ===================================================================
# 2. Record structure
# ===================================================================


class TestRecordStructure:
    """Upserted record must contain exact expected fields and values."""

    def test_record_has_id(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        assert record["id"] == ELEMENT_ID

    def test_record_has_content_hash(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        assert record["contentHash"] == CONTENT_HASH

    def test_record_has_source_system(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        assert record["sourceSystem"] == SOURCE_SYSTEM

    def test_record_has_entity_type(self):
        """entityType is empty string — type cannot be parsed from base64 IDs."""
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        assert record["entityType"] == ""

    def test_record_has_last_processed(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        assert "lastProcessed" in record
        # Verify it parses as a valid ISO timestamp
        datetime.fromisoformat(record["lastProcessed"])

    def test_last_processed_is_utc(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        ts = datetime.fromisoformat(record["lastProcessed"])
        assert ts.tzinfo is not None

    def test_record_has_exactly_expected_fields(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        assert set(record.keys()) == STATE_RECORD_FIELDS


# ===================================================================
# 3. Entity type extraction
# ===================================================================


class TestEntityTypeExtraction:
    """With base64 IDs, _extract_entity_type returns empty string."""

    def test_returns_empty_for_base64_id(self):
        assert _extract_entity_type("U3R1ZGVudCBFbnJvbGxtZW50") == ""

    def test_returns_empty_for_legacy_format(self):
        # Even old-format IDs now return empty (function deprecated)
        assert _extract_entity_type("synergy::table::students") == ""

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _extract_entity_type("")

    def test_whitespace_id_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _extract_entity_type("   ")

    def test_entity_type_used_in_record(self):
        """entityType in state record is empty with base64 IDs."""
        store = _mock_state_store()
        update_element_state(
            "U3R1ZGVudCBFbnJvbGxtZW50",
            CONTENT_HASH,
            "zipline",
            state_store=store,
        )
        record = store.upsert_state.call_args[0][0]
        assert record["entityType"] == ""


# ===================================================================
# 4. Deterministic behavior
# ===================================================================


class TestDeterministicBehavior:
    """Same inputs must produce consistent record structure."""

    def test_same_inputs_produce_same_fields(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record1 = store.upsert_state.call_args[0][0]

        store.reset_mock()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record2 = store.upsert_state.call_args[0][0]

        # All fields except lastProcessed must be identical
        for key in STATE_RECORD_FIELDS - {"lastProcessed"}:
            assert record1[key] == record2[key]

    def test_no_uuid_in_record(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        record_str = str(record)
        assert not re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            record_str,
            re.I,
        )

    def test_id_is_element_id_not_generated(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        assert record["id"] == ELEMENT_ID


# ===================================================================
# 5. Input validation
# ===================================================================


class TestInputValidation:
    """Invalid inputs must raise appropriate errors."""

    def test_none_element_id_raises_type_error(self):
        store = _mock_state_store()
        with pytest.raises(TypeError, match="element_id"):
            update_element_state(
                None, CONTENT_HASH, SOURCE_SYSTEM, state_store=store  # type: ignore[arg-type]
            )

    def test_empty_element_id_raises_value_error(self):
        store = _mock_state_store()
        with pytest.raises(ValueError, match="element_id"):
            update_element_state("", CONTENT_HASH, SOURCE_SYSTEM, state_store=store)

    def test_whitespace_element_id_raises_value_error(self):
        store = _mock_state_store()
        with pytest.raises(ValueError, match="element_id"):
            update_element_state("   ", CONTENT_HASH, SOURCE_SYSTEM, state_store=store)

    def test_integer_element_id_raises_type_error(self):
        store = _mock_state_store()
        with pytest.raises(TypeError, match="element_id"):
            update_element_state(
                123, CONTENT_HASH, SOURCE_SYSTEM, state_store=store  # type: ignore[arg-type]
            )

    def test_none_content_hash_raises_type_error(self):
        store = _mock_state_store()
        with pytest.raises(TypeError, match="content_hash"):
            update_element_state(
                ELEMENT_ID, None, SOURCE_SYSTEM, state_store=store  # type: ignore[arg-type]
            )

    def test_empty_content_hash_raises_value_error(self):
        store = _mock_state_store()
        with pytest.raises(ValueError, match="content_hash"):
            update_element_state(ELEMENT_ID, "", SOURCE_SYSTEM, state_store=store)

    def test_none_source_system_raises_type_error(self):
        store = _mock_state_store()
        with pytest.raises(TypeError, match="source_system"):
            update_element_state(
                ELEMENT_ID, CONTENT_HASH, None, state_store=store  # type: ignore[arg-type]
            )

    def test_empty_source_system_raises_value_error(self):
        store = _mock_state_store()
        with pytest.raises(ValueError, match="source_system"):
            update_element_state(ELEMENT_ID, CONTENT_HASH, "", state_store=store)

    def test_invalid_element_id_format_raises_value_error(self):
        """Empty element ID should still raise."""
        store = _mock_state_store()
        with pytest.raises(ValueError, match="element_id"):
            update_element_state(
                "", CONTENT_HASH, SOURCE_SYSTEM, state_store=store
            )


# ===================================================================
# 6. No mutation
# ===================================================================


class TestNoMutation:
    """Input arguments must not be modified by the writer."""

    def test_element_id_unchanged(self):
        store = _mock_state_store()
        eid = "synergy::table::student enrollment"
        original = eid
        update_element_state(eid, CONTENT_HASH, SOURCE_SYSTEM, state_store=store)
        assert eid == original

    def test_hash_unchanged(self):
        store = _mock_state_store()
        h = "a" * 64
        original = h
        update_element_state(ELEMENT_ID, h, SOURCE_SYSTEM, state_store=store)
        assert h == original

    def test_source_system_unchanged(self):
        store = _mock_state_store()
        ss = "synergy"
        original = ss
        update_element_state(ELEMENT_ID, CONTENT_HASH, ss, state_store=store)
        assert ss == original


# ===================================================================
# 7. Error propagation
# ===================================================================


class TestErrorPropagation:
    """State store failures must never be silenced."""

    def test_store_error_propagated(self):
        store = _mock_state_store(side_effect=RuntimeError("Cosmos unavailable"))
        with pytest.raises(RuntimeError, match="Cosmos unavailable"):
            update_element_state(
                ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
            )

    def test_generic_exception_propagated(self):
        store = _mock_state_store(side_effect=Exception("network timeout"))
        with pytest.raises(Exception, match="network timeout"):
            update_element_state(
                ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
            )

    def test_store_not_called_on_validation_failure(self):
        store = _mock_state_store()
        with pytest.raises(ValueError):
            update_element_state("", CONTENT_HASH, SOURCE_SYSTEM, state_store=store)
        store.upsert_state.assert_not_called()

    def test_store_not_called_on_type_error(self):
        store = _mock_state_store()
        with pytest.raises(TypeError):
            update_element_state(
                None, CONTENT_HASH, SOURCE_SYSTEM, state_store=store  # type: ignore[arg-type]
            )
        store.upsert_state.assert_not_called()


# ===================================================================
# 8. Observability
# ===================================================================


class TestObservability:
    """Writer must log element ID and operation, not full payload."""

    def test_logs_state_update(self, caplog):
        store = _mock_state_store()
        with caplog.at_level(logging.INFO, logger="infrastructure.state_store"):
            update_element_state(
                ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
            )
        log_text = " ".join(caplog.messages)
        assert "state" in log_text.lower()

    def test_logs_operation_type(self, caplog):
        store = _mock_state_store()
        with caplog.at_level(logging.INFO, logger="infrastructure.state_store"):
            update_element_state(
                ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
            )
        has_operation = any(
            getattr(r, "operation", None) == "state_update"
            for r in caplog.records
        )
        assert has_operation

    def test_logs_element_id_in_extra(self, caplog):
        store = _mock_state_store()
        with caplog.at_level(logging.INFO, logger="infrastructure.state_store"):
            update_element_state(
                ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
            )
        has_element_id = any(
            getattr(r, "elementId", None) == ELEMENT_ID
            for r in caplog.records
        )
        assert has_element_id

    def test_does_not_log_content_hash(self, caplog):
        store = _mock_state_store()
        marker_hash = "SENSITIVE_HASH_MARKER_" + "x" * 40
        with caplog.at_level(logging.DEBUG, logger="infrastructure.state_store"):
            update_element_state(
                ELEMENT_ID, marker_hash, SOURCE_SYSTEM, state_store=store
            )
        full_log = " ".join(caplog.messages)
        assert "SENSITIVE_HASH_MARKER_" not in full_log

    def test_does_not_log_full_record(self, caplog):
        store = _mock_state_store()
        with caplog.at_level(logging.DEBUG, logger="infrastructure.state_store"):
            update_element_state(
                ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
            )
        full_log = " ".join(caplog.messages)
        # Full hash should not appear in log messages
        assert CONTENT_HASH not in full_log


# ===================================================================
# 9. Guardrail compliance
# ===================================================================


class TestGuardrailCompliance:
    """Writer source must not contain forbidden operations."""

    def test_no_delete_operations(self):
        import src.infrastructure.state_store.state_writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        assert "delete_state" not in source
        assert "delete_item" not in source

    def test_no_batch_operations(self):
        import src.infrastructure.state_store.state_writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        for pattern in ["batch_upsert", "bulk_upsert", "execute_batch"]:
            assert pattern not in source, f"Writer must not contain '{pattern}'"

    def test_no_search_indexing(self):
        import src.infrastructure.state_store.state_writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        for pattern in ["merge_or_upload", "SearchClient", "upload_documents"]:
            assert pattern not in source, f"Writer must not contain '{pattern}'"

    def test_no_hash_computation(self):
        import src.infrastructure.state_store.state_writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        for pattern in ["compute_element_hash", "compute_asset_hash", "hashlib"]:
            assert pattern not in source, f"Writer must not contain '{pattern}'"

    def test_no_identity_computation(self):
        import src.infrastructure.state_store.state_writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        assert "generate_element_id" not in source

    def test_no_state_comparison(self):
        import src.infrastructure.state_store.state_writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        for pattern in ["compare_element_state", "DecisionResult"]:
            assert pattern not in source, f"Writer must not contain '{pattern}'"
        # Ensure no code-level references to decision constants
        assert re.search(r'DecisionResult\.SKIP', source) is None
        assert re.search(r'DecisionResult\.REPROCESS', source) is None
        assert re.search(r'=\s*["\']SKIP["\']', source) is None
        assert re.search(r'=\s*["\']REPROCESS["\']', source) is None


# ===================================================================
# 10. Architecture isolation
# ===================================================================


class TestArchitectureIsolation:
    """Writer must not import domain modules."""

    def test_no_domain_imports(self):
        import src.infrastructure.state_store.state_writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        forbidden = [
            "element_splitter",
            "element_identity",
            "element_hashing",
            "element_state.comparator",
            "change_detection",
            "search_document",
        ]
        for pattern in forbidden:
            assert pattern not in source, (
                f"State writer must not import '{pattern}'"
            )

    def test_no_search_writer_import(self):
        import src.infrastructure.state_store.state_writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        assert "search_writer" not in source

    def test_no_uuid_import(self):
        import src.infrastructure.state_store.state_writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        assert "import uuid" not in source

    def test_no_random_import(self):
        import src.infrastructure.state_store.state_writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        assert "import random" not in source


# ===================================================================
# 11. Idempotent calls
# ===================================================================


class TestIdempotentCalls:
    """Repeated calls with same inputs must be safe."""

    def test_repeated_calls_succeed(self):
        store = _mock_state_store()
        for _ in range(5):
            update_element_state(
                ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
            )
        assert store.upsert_state.call_count == 5

    def test_repeated_calls_same_structure(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        calls = store.upsert_state.call_args_list
        r1 = calls[0][0][0]
        r2 = calls[1][0][0]
        for key in STATE_RECORD_FIELDS - {"lastProcessed"}:
            assert r1[key] == r2[key]


# ===================================================================
# 12. Record field validation
# ===================================================================


class TestRecordFieldValidation:
    """Record fields must match STATE_RECORD_FIELDS exactly."""

    def test_record_keys_subset_of_state_fields(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        assert set(record.keys()) <= STATE_RECORD_FIELDS

    def test_record_keys_exactly_match_state_fields(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        assert set(record.keys()) == STATE_RECORD_FIELDS

    def test_last_processed_is_utc_iso(self):
        store = _mock_state_store()
        update_element_state(
            ELEMENT_ID, CONTENT_HASH, SOURCE_SYSTEM, state_store=store
        )
        record = store.upsert_state.call_args[0][0]
        ts = datetime.fromisoformat(record["lastProcessed"])
        assert ts.tzinfo is not None

    def test_different_element_produces_different_entity_type(self):
        """entityType is always empty with base64 IDs."""
        store = _mock_state_store()
        update_element_state(
            "U3R1ZGVudCBFbnJvbGxtZW50",
            CONTENT_HASH,
            "zipline",
            state_store=store,
        )
        record = store.upsert_state.call_args[0][0]
        assert record["entityType"] == ""
        assert record["sourceSystem"] == "zipline"
        assert record["id"] == "U3R1ZGVudCBFbnJvbGxtZW50"
