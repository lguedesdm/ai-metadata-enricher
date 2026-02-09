"""
Unit tests for the Orchestrator message handler.

These tests verify that the handler:
- Correctly parses asset payloads
- Calls domain-level decision logic
- Returns proper results for valid and invalid messages
- Generates correlationId for every message
- Does NOT call any external service
"""

import json
import uuid

from src.domain.change_detection import DecisionResult
from src.orchestrator.message_handler import MessageProcessingResult, handle_message


# ---- Sample payloads -------------------------------------------------------

VALID_ASSET = {
    "id": "synergy.student.enrollment.table",
    "sourceSystem": "synergy",
    "entityType": "table",
    "entityName": "Student Enrollment",
    "entityPath": "synergy.student.enrollment",
    "description": "Stores student enrollment records.",
    "domain": "Student Information",
    "tags": ["enrollment", "student"],
    "content": "Student Enrollment table in Synergy.",
    "lastUpdated": "2026-02-02T12:00:00Z",
    "schemaVersion": "1.0.0",
}

MINIMAL_ASSET = {
    "id": "test.minimal",
    "sourceSystem": "test",
    "entityType": "table",
    "entityName": "Minimal",
    "entityPath": "test.minimal",
    "content": "Minimal test asset.",
    "lastUpdated": "2026-01-01T00:00:00Z",
    "schemaVersion": "1.0.0",
}


# ---- Tests ------------------------------------------------------------------


class TestHandleMessage:
    """Tests for the handle_message function."""

    def test_valid_asset_returns_reprocess(self) -> None:
        """Valid asset with no previous state should return REPROCESS."""
        body = json.dumps(VALID_ASSET)
        result = handle_message(body)

        assert isinstance(result, MessageProcessingResult)
        assert result.success is True
        assert result.decision == DecisionResult.REPROCESS.value
        assert result.asset_id == "synergy.student.enrollment.table"
        assert result.error is None

    def test_minimal_asset_returns_reprocess(self) -> None:
        """Minimal asset should also return REPROCESS (no previous state)."""
        body = json.dumps(MINIMAL_ASSET)
        result = handle_message(body)

        assert result.success is True
        assert result.decision == "REPROCESS"
        assert result.asset_id == "test.minimal"

    def test_generates_correlation_id(self) -> None:
        """Every message should get a unique correlationId (valid UUID)."""
        body = json.dumps(VALID_ASSET)
        result = handle_message(body)

        # Verify it's a valid UUID
        parsed = uuid.UUID(result.correlation_id)
        assert str(parsed) == result.correlation_id

    def test_unique_correlation_ids(self) -> None:
        """Each invocation should produce a different correlationId."""
        body = json.dumps(VALID_ASSET)
        result1 = handle_message(body)
        result2 = handle_message(body)

        assert result1.correlation_id != result2.correlation_id

    def test_bytes_body(self) -> None:
        """Handler should accept bytes as message body."""
        body = json.dumps(VALID_ASSET).encode("utf-8")
        result = handle_message(body)

        assert result.success is True
        assert result.decision == "REPROCESS"

    def test_invalid_json_returns_error(self) -> None:
        """Invalid JSON should return a failed result, not raise."""
        result = handle_message("not valid json {{{")

        assert result.success is False
        assert result.decision is None
        assert result.error is not None
        assert result.asset_id == "unknown"

    def test_empty_body_returns_error(self) -> None:
        """Empty body should return a failed result."""
        result = handle_message("")

        assert result.success is False
        assert result.decision is None

    def test_non_dict_json_returns_error(self) -> None:
        """JSON that is not a dict should fail (asset must be a dict)."""
        result = handle_message(json.dumps([1, 2, 3]))

        assert result.success is False
        assert result.decision is None

    def test_missing_id_uses_unknown(self) -> None:
        """Asset without 'id' should use 'unknown' as asset_id."""
        asset_no_id = {
            "sourceSystem": "test",
            "entityType": "table",
            "entityName": "NoId",
            "entityPath": "test.noid",
            "content": "Asset without id.",
            "lastUpdated": "2026-01-01T00:00:00Z",
            "schemaVersion": "1.0.0",
        }
        result = handle_message(json.dumps(asset_no_id))

        assert result.success is True
        assert result.asset_id == "unknown"
        assert result.decision == "REPROCESS"


class TestHandleMessageDeterminism:
    """Tests verifying deterministic behavior of the handler."""

    def test_same_asset_produces_same_decision(self) -> None:
        """Same asset payload should always produce the same decision."""
        body = json.dumps(VALID_ASSET)

        results = [handle_message(body) for _ in range(5)]

        decisions = {r.decision for r in results}
        assert decisions == {"REPROCESS"}  # All REPROCESS (no previous state)

    def test_different_assets_both_reprocess(self) -> None:
        """Different assets should both be REPROCESS (no previous state)."""
        result1 = handle_message(json.dumps(VALID_ASSET))
        result2 = handle_message(json.dumps(MINIMAL_ASSET))

        assert result1.decision == "REPROCESS"
        assert result2.decision == "REPROCESS"
