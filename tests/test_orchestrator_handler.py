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
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.domain.change_detection import DecisionResult
from src.orchestrator.message_handler import MessageProcessingResult, handle_message
from src.enrichment.pipeline.enrichment_pipeline import EnrichmentPipelineResult

# Reusable mock pipeline result for REPROCESS tests that verify handler-level
# behavior (decision logic, payload parsing) rather than enrichment behavior.
_MOCK_PIPELINE_SUCCESS = EnrichmentPipelineResult(
    success=True,
    asset_id="synergy.student.enrollment.table",
    correlation_id="mock-correlation-id",
    validation_status="PASS",
    writeback_success=True,
)

_PIPELINE_PATCH = "src.enrichment.pipeline.enrichment_pipeline.run_enrichment_pipeline"


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
        with patch(_PIPELINE_PATCH, return_value=_MOCK_PIPELINE_SUCCESS):
            result = handle_message(body)

        assert isinstance(result, MessageProcessingResult)
        assert result.success is True
        assert result.decision == DecisionResult.REPROCESS.value
        assert result.asset_id == "synergy.student.enrollment.table"
        assert result.error is None

    def test_minimal_asset_returns_reprocess(self) -> None:
        """Minimal asset should also return REPROCESS (no previous state)."""
        body = json.dumps(MINIMAL_ASSET)
        mock_result = EnrichmentPipelineResult(
            success=True,
            asset_id="test.minimal",
            correlation_id="mock-corr",
            validation_status="PASS",
            writeback_success=True,
        )
        with patch(_PIPELINE_PATCH, return_value=mock_result):
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
        with patch(_PIPELINE_PATCH, return_value=_MOCK_PIPELINE_SUCCESS):
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
        mock_result = EnrichmentPipelineResult(
            success=True,
            asset_id="unknown",
            correlation_id="mock-corr",
            validation_status="PASS",
            writeback_success=True,
        )
        with patch(_PIPELINE_PATCH, return_value=mock_result):
            result = handle_message(json.dumps(asset_no_id))

        assert result.success is True
        assert result.asset_id == "unknown"
        assert result.decision == "REPROCESS"


class TestCosmosReadFallback:
    """Tests verifying deterministic REPROCESS fallback on Cosmos read failure."""

    def test_cosmos_read_failure_returns_reprocess(self) -> None:
        """When state_store.get_state() raises, handler must return REPROCESS — not fail."""
        mock_store = MagicMock()
        mock_store.get_state.side_effect = RuntimeError("Cosmos 503 Service Unavailable")
        mock_store.upsert_audit.return_value = None
        # run_enrichment_pipeline is patched — lifecycle store is never built

        body = json.dumps(VALID_ASSET)
        with patch(_PIPELINE_PATCH, return_value=_MOCK_PIPELINE_SUCCESS):
            result = handle_message(body, state_store=mock_store)

        assert result.success is True
        assert result.decision == "REPROCESS"
        assert result.asset_id == "synergy.student.enrollment.table"
        assert result.error is None

    def test_cosmos_read_timeout_returns_reprocess(self) -> None:
        """Timeout during Cosmos read should also produce REPROCESS."""
        mock_store = MagicMock()
        mock_store.get_state.side_effect = TimeoutError("Cosmos request timed out")
        mock_store.upsert_audit.return_value = None
        # run_enrichment_pipeline is patched — lifecycle store is never built

        body = json.dumps(VALID_ASSET)
        with patch(_PIPELINE_PATCH, return_value=_MOCK_PIPELINE_SUCCESS):
            result = handle_message(body, state_store=mock_store)

        assert result.success is True
        assert result.decision == "REPROCESS"

    def test_cosmos_read_failure_still_writes_audit(self) -> None:
        """After read failure fallback, handler must write the orchestrator decision
        audit record before delegating to the enrichment pipeline.

        Note: In the integrated pipeline, the handler writes AUDIT (not state)
        for REPROCESS decisions. State is written by the pipeline after
        successful Purview writeback — enforcing the architectural invariant
        that state is only updated after successful writeback.
        """
        mock_store = MagicMock()
        mock_store.get_state.side_effect = ConnectionError("Transient failure")
        mock_store.upsert_audit.return_value = None
        # run_enrichment_pipeline is patched — lifecycle store is never built

        body = json.dumps(VALID_ASSET)
        with patch(_PIPELINE_PATCH, return_value=_MOCK_PIPELINE_SUCCESS):
            result = handle_message(body, state_store=mock_store)

        assert result.success is True
        assert result.decision == "REPROCESS"
        # Handler writes the orchestrator decision audit before calling pipeline
        mock_store.upsert_audit.assert_called_once()


class TestHandleMessageDeterminism:
    """Tests verifying deterministic behavior of the handler."""

    def test_same_asset_produces_same_decision(self) -> None:
        """Same asset payload should always produce the same decision."""
        body = json.dumps(VALID_ASSET)

        with patch(_PIPELINE_PATCH, return_value=_MOCK_PIPELINE_SUCCESS):
            results = [handle_message(body) for _ in range(5)]

        decisions = {r.decision for r in results}
        assert decisions == {"REPROCESS"}  # All REPROCESS (no previous state)

    def test_different_assets_both_reprocess(self) -> None:
        """Different assets should both be REPROCESS (no previous state)."""
        minimal_result = EnrichmentPipelineResult(
            success=True,
            asset_id="test.minimal",
            correlation_id="mock-corr",
            validation_status="PASS",
            writeback_success=True,
        )
        with patch(_PIPELINE_PATCH, return_value=_MOCK_PIPELINE_SUCCESS):
            result1 = handle_message(json.dumps(VALID_ASSET))
        with patch(_PIPELINE_PATCH, return_value=minimal_result):
            result2 = handle_message(json.dumps(MINIMAL_ASSET))

        assert result1.decision == "REPROCESS"
        assert result2.decision == "REPROCESS"


# ---- Completion Criteria Tests -----------------------------------------------


class TestElementLevelExecution:
    """Test 1 — Element-Level Execution (completion criterion).

    An asset with N elements must produce exactly N independent pipeline
    invocations, each with its own element identity and content hash.
    """

    def test_n_elements_produce_n_pipeline_calls(self) -> None:
        """Asset with 3 elements → run_enrichment_pipeline called 3 times."""
        multi_element_asset = {
            "id": "synergy.multi.asset",
            "sourceSystem": "synergy",
            "elements": [
                {
                    "sourceSystem": "synergy",
                    "entityName": "Table A",
                    "entityType": "table",
                    "description": "First element.",
                },
                {
                    "sourceSystem": "synergy",
                    "entityName": "Table B",
                    "entityType": "table",
                    "description": "Second element.",
                },
                {
                    "sourceSystem": "synergy",
                    "entityName": "Table C",
                    "entityType": "table",
                    "description": "Third element.",
                },
            ],
        }

        mock_element_result = EnrichmentPipelineResult(
            success=True,
            asset_id="el-id",
            correlation_id="mock-corr",
            validation_status="PASS",
            writeback_success=True,
        )

        with patch(_PIPELINE_PATCH, return_value=mock_element_result) as mock_pipeline:
            result = handle_message(json.dumps(multi_element_asset))

        assert result.success is True
        assert result.decision == "REPROCESS"
        assert mock_pipeline.call_count == 3

    def test_each_element_receives_same_correlation_id(self) -> None:
        """All elements within one message share the same correlation_id."""
        multi_element_asset = {
            "id": "synergy.multi.asset",
            "sourceSystem": "synergy",
            "elements": [
                {
                    "sourceSystem": "synergy",
                    "entityName": "Table A",
                    "entityType": "table",
                },
                {
                    "sourceSystem": "synergy",
                    "entityName": "Table B",
                    "entityType": "table",
                },
            ],
        }

        mock_element_result = EnrichmentPipelineResult(
            success=True,
            asset_id="el-id",
            correlation_id="mock-corr",
            validation_status="PASS",
            writeback_success=True,
        )

        captured_correlation_ids = []

        def capture(**kwargs):
            captured_correlation_ids.append(kwargs.get("correlation_id"))
            return mock_element_result

        with patch(_PIPELINE_PATCH, side_effect=capture):
            handle_message(json.dumps(multi_element_asset))

        assert len(captured_correlation_ids) == 2
        assert captured_correlation_ids[0] == captured_correlation_ids[1], (
            "All elements in one message must share the same correlation_id"
        )


class TestDeterministicReferenceTime:
    """Test 2 — Deterministic Reference Time (completion criterion).

    reference_time is generated once per message and propagated to every
    element pipeline call.  All elements within a single message share the
    same temporal context so retries are deterministic.
    """

    def test_reference_time_propagated_to_pipeline(self) -> None:
        """run_enrichment_pipeline must receive reference_time kwarg."""
        mock_element_result = EnrichmentPipelineResult(
            success=True,
            asset_id="el-id",
            correlation_id="mock-corr",
            validation_status="PASS",
            writeback_success=True,
        )

        captured_times = []

        def capture(**kwargs):
            captured_times.append(kwargs.get("reference_time"))
            return mock_element_result

        with patch(_PIPELINE_PATCH, side_effect=capture):
            handle_message(json.dumps(VALID_ASSET))

        assert len(captured_times) == 1
        from datetime import datetime
        assert isinstance(captured_times[0], datetime), (
            "reference_time must be a datetime object"
        )

    def test_all_elements_share_same_reference_time(self) -> None:
        """All elements within one message receive the identical reference_time."""
        multi_element_asset = {
            "id": "synergy.multi.asset",
            "sourceSystem": "synergy",
            "elements": [
                {
                    "sourceSystem": "synergy",
                    "entityName": "Table A",
                    "entityType": "table",
                },
                {
                    "sourceSystem": "synergy",
                    "entityName": "Table B",
                    "entityType": "table",
                },
                {
                    "sourceSystem": "synergy",
                    "entityName": "Table C",
                    "entityType": "table",
                },
            ],
        }

        mock_element_result = EnrichmentPipelineResult(
            success=True,
            asset_id="el-id",
            correlation_id="mock-corr",
            validation_status="PASS",
            writeback_success=True,
        )

        captured_times = []

        def capture(**kwargs):
            captured_times.append(kwargs.get("reference_time"))
            return mock_element_result

        with patch(_PIPELINE_PATCH, side_effect=capture):
            handle_message(json.dumps(multi_element_asset))

        assert len(captured_times) == 3
        assert captured_times[0] == captured_times[1] == captured_times[2], (
            "All elements within one message must receive the same reference_time"
        )


class TestRetryDeterminism:
    """Tests verifying that reference_time is stable across Service Bus retries.

    When the consumer derives reference_time from ServiceBusMessage.enqueued_time_utc
    and passes it to handle_message(), the same physical message produces the same
    reference_time on every delivery attempt — making RAG freshness scoring
    deterministic across retries.
    """

    def test_handle_message_accepts_reference_time_parameter(self) -> None:
        """handle_message must accept and propagate an externally supplied reference_time."""
        fixed_time = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)
        body = json.dumps(VALID_ASSET)

        captured_times = []

        def capture(**kwargs):
            captured_times.append(kwargs.get("reference_time"))
            return _MOCK_PIPELINE_SUCCESS

        with patch(_PIPELINE_PATCH, side_effect=capture):
            handle_message(body, reference_time=fixed_time)

        assert len(captured_times) == 1
        assert captured_times[0] == fixed_time, (
            "handle_message must forward the supplied reference_time to the pipeline"
        )

    def test_same_reference_time_produces_identical_pipeline_args(self) -> None:
        """Two executions with the same reference_time produce identical pipeline call args.

        This simulates two Service Bus redeliveries of the same message:
        both receive the same enqueued_time_utc → same reference_time →
        same RAG query parameters → deterministic enrichment.
        """
        fixed_time = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)
        body = json.dumps(VALID_ASSET)

        captured_calls = []

        def capture(**kwargs):
            captured_calls.append(kwargs)
            return _MOCK_PIPELINE_SUCCESS

        with patch(_PIPELINE_PATCH, side_effect=capture):
            handle_message(body, reference_time=fixed_time)

        with patch(_PIPELINE_PATCH, side_effect=capture):
            handle_message(body, reference_time=fixed_time)

        assert len(captured_calls) == 2
        assert captured_calls[0]["reference_time"] == captured_calls[1]["reference_time"], (
            "Both retries must produce the same reference_time"
        )
        assert captured_calls[0]["asset_id"] == captured_calls[1]["asset_id"]
        assert captured_calls[0]["entity_type"] == captured_calls[1]["entity_type"]

    def test_different_reference_times_are_forwarded_independently(self) -> None:
        """Different messages with different enqueue times produce different reference_times."""
        time_a = datetime(2026, 3, 7, 10, 0, 0, tzinfo=timezone.utc)
        time_b = datetime(2026, 3, 7, 11, 0, 0, tzinfo=timezone.utc)
        body = json.dumps(VALID_ASSET)

        captured_times = []

        def capture(**kwargs):
            captured_times.append(kwargs.get("reference_time"))
            return _MOCK_PIPELINE_SUCCESS

        with patch(_PIPELINE_PATCH, side_effect=capture):
            handle_message(body, reference_time=time_a)

        with patch(_PIPELINE_PATCH, side_effect=capture):
            handle_message(body, reference_time=time_b)

        assert captured_times[0] == time_a
        assert captured_times[1] == time_b
        assert captured_times[0] != captured_times[1]

    def test_fallback_when_reference_time_not_provided(self) -> None:
        """When reference_time is not supplied (test mode), handler falls back to datetime.now()."""
        body = json.dumps(VALID_ASSET)

        captured_times = []

        def capture(**kwargs):
            captured_times.append(kwargs.get("reference_time"))
            return _MOCK_PIPELINE_SUCCESS

        with patch(_PIPELINE_PATCH, side_effect=capture):
            handle_message(body)

        assert len(captured_times) == 1
        assert isinstance(captured_times[0], datetime), (
            "Fallback reference_time must be a datetime object"
        )
        assert captured_times[0].tzinfo is not None, (
            "Fallback reference_time must be timezone-aware"
        )
