"""
Phase 4 — Deterministic Validation Tests for the Enrichment Pipeline Integration.

Tests validate the deterministic behavior of the integrated enrichment pipeline:

  Test 1 — Single Asset Execution
  Test 2 — RAG Context Retrieval
  Test 3 — Context Determinism
  Test 4 — Validation Enforcement
  Test 5 — Purview Safety
  Test 6 — State Persistence
  Test 7 — Audit Traceability

All tests use mocks for external Azure services (AI Search, Azure OpenAI,
Purview, Cosmos DB).  No live Azure connections are required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, call

import pytest

from src.enrichment.pipeline.enrichment_pipeline import (
    EnrichmentPipelineResult,
    run_enrichment_pipeline,
)
from src.enrichment.llm_client import LLMCompletionResult
from src.orchestrator.message_handler import handle_message, MessageProcessingResult
from src.domain.change_detection import DecisionResult


# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

VALID_ASSET: Dict[str, Any] = {
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

VALID_LLM_OUTPUT = """\
suggested_description: "Student Enrollment table stores enrollment records for all students including enrollment date, status, and type. Used by attendance and reporting systems."
confidence: high
used_sources:
  - "Synergy export: Student Enrollment table description"
warnings: []
"""

INVALID_LLM_OUTPUT = "This is just some free text that is not valid YAML output."

# LLMCompletionResult wrappers used by all mock LLM client setups.
VALID_LLM_RESULT = LLMCompletionResult(
    text=VALID_LLM_OUTPUT,
    prompt_tokens=120,
    completion_tokens=45,
    total_tokens=165,
)
INVALID_LLM_RESULT = LLMCompletionResult(
    text=INVALID_LLM_OUTPUT,
    prompt_tokens=80,
    completion_tokens=10,
    total_tokens=90,
)

CORRELATION_ID = "test-correlation-id-00000001"
ASSET_ID = VALID_ASSET["id"]
ENTITY_TYPE = VALID_ASSET["entityType"]
SOURCE_SYSTEM = VALID_ASSET["sourceSystem"]
ELEMENT_NAME = VALID_ASSET["entityName"]
CURRENT_HASH = "a" * 64  # deterministic mock hash


def _make_mock_state_store(*, previous_hash: Optional[str] = None) -> MagicMock:
    """Build a mock CosmosStateStore with configurable previous state."""
    store = MagicMock()
    if previous_hash is not None:
        store.get_state.return_value = {
            "id": ASSET_ID,
            "entityType": ENTITY_TYPE,
            "contentHash": previous_hash,
        }
    else:
        store.get_state.return_value = None
    store.upsert_state.return_value = {}
    store.upsert_audit.return_value = {}
    # state_container and audit_container are auto-created MagicMocks by MagicMock();
    # LifecycleStore.__init__ stores them as attributes — no further setup needed.
    return store


def _make_mock_lifecycle_store() -> MagicMock:
    """Build a mock LifecycleStore that accepts all writes."""
    ls = MagicMock()
    ls.get_lifecycle_record.return_value = None
    ls.upsert_lifecycle_record.return_value = {}
    ls.write_audit_record.return_value = {}
    return ls


def _make_mock_rag_context(*, has_context: bool = True) -> MagicMock:
    """Build a mock RetrievedContext."""
    ctx = MagicMock()
    ctx.formatted_context = (
        "Source: synergy\nElement: Student Enrollment\n"
        "Description: Stores student enrollment records.\n\n"
        "Source: zipline\nElement: Enrollment\n"
        "Description: Enrollment status tracking.\n\n"
        "Source: documentation\nContent: District enrollment policy document."
        if has_context
        else "No context found for this query."
    )
    ctx.has_context = has_context
    ctx.results_used = 3 if has_context else 0
    ctx.search_metadata = {
        "search_type": "hybrid_semantic",
        "correlation_id": CORRELATION_ID,
        "source_weights": {"synergy": 1.0, "zipline": 0.9, "documentation": 0.8},
    }
    return ctx


def _make_writeback_result(*, success: bool = True) -> MagicMock:
    """Build a mock WritebackResult."""
    wr = MagicMock()
    wr.success = success
    wr.asset_id = ASSET_ID
    wr.correlation_id = CORRELATION_ID
    wr.lifecycle_status = "pending" if success else None
    wr.operation = "write_suggested_description"
    wr.error = None if success else "Purview API error"
    wr.error_category = None if success else "unknown"
    wr.purview_written = success
    return wr


# ---------------------------------------------------------------------------
# Test 1 — Single Asset Execution
# ---------------------------------------------------------------------------

class TestSingleAssetExecution:
    """Test 1: Trigger pipeline with one asset; expect exactly one LLM invocation
    and exactly one Purview writeback call."""

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_exactly_one_llm_invocation(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """Exactly one LLM call and one writeback must occur per asset."""
        # Arrange
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ) as mock_writeback:
            result = run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        # Assert: pipeline succeeded
        assert result.success is True
        assert result.validation_status == "PASS"
        assert result.writeback_success is True

        # Assert: EXACTLY ONE LLM call
        assert mock_llm.complete.call_count == 1, (
            f"Expected exactly 1 LLM call, got {mock_llm.complete.call_count}"
        )

        # Assert: EXACTLY ONE writeback call
        assert mock_writeback.call_count == 1, (
            f"Expected exactly 1 writeback call, got {mock_writeback.call_count}"
        )

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_pipeline_result_carries_asset_id_and_correlation_id(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """Pipeline result must carry asset_id and correlation_id."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ):
            result = run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        assert result.asset_id == ASSET_ID
        assert result.correlation_id == CORRELATION_ID


# ---------------------------------------------------------------------------
# Test 2 — RAG Context Retrieval
# ---------------------------------------------------------------------------

class TestRAGContextRetrieval:
    """Test 2: Hybrid search must return results from Synergy, Zipline, and
    documentation sources."""

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_rag_retrieval_called_with_correct_parameters(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """RAG pipeline must be called with correct asset parameters."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ):
            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        # Assert: RAG was called before LLM (enforced by sequential pipeline)
        call_kwargs = mock_rag.retrieve_context_for_asset.call_args.kwargs
        assert call_kwargs["asset_id"] == ASSET_ID
        assert call_kwargs["entity_type"] == ENTITY_TYPE
        assert call_kwargs["source_system"] == SOURCE_SYSTEM
        assert call_kwargs["element_name"] == ELEMENT_NAME
        assert call_kwargs["correlation_id"] == CORRELATION_ID
        # reference_time must be present (passed from orchestrator / pipeline)
        assert "reference_time" in call_kwargs

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_rag_failure_prevents_llm_invocation(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """If RAG retrieval fails, the LLM must NOT be invoked."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.side_effect = Exception(
            "AI Search unavailable"
        )
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_build_llm.return_value = mock_llm

        mock_build_purview.return_value = MagicMock()
        state_store = _make_mock_state_store()

        result = run_enrichment_pipeline(
            asset=VALID_ASSET,
            asset_id=ASSET_ID,
            entity_type=ENTITY_TYPE,
            source_system=SOURCE_SYSTEM,
            element_name=ELEMENT_NAME,
            correlation_id=CORRELATION_ID,
            current_hash=CURRENT_HASH,
            state_store=state_store,
        )

        assert result.success is False
        assert result.validation_status == "ERROR"
        # LLM was never called
        mock_llm.complete.assert_not_called()

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_context_injected_into_llm_messages(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """Formatted context from RAG must appear in the LLM messages."""
        expected_context = "Source: synergy\nStudent Enrollment data."
        ctx = _make_mock_rag_context()
        ctx.formatted_context = expected_context

        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = ctx
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ):
            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        # The messages passed to complete() should contain the context string
        call_kwargs = mock_llm.complete.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0]
        all_content = " ".join(m["content"] for m in messages)
        assert expected_context in all_content, (
            "RAG context must appear in the LLM message content"
        )


# ---------------------------------------------------------------------------
# Test 3 — Context Determinism
# ---------------------------------------------------------------------------

class TestContextDeterminism:
    """Test 3: Two runs with identical inputs must produce identical LLM messages."""

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_identical_inputs_produce_identical_messages(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """Same asset + same context → same LLM messages (determinism)."""
        fixed_context = "Source: synergy\nStudent Enrollment description."
        ctx = _make_mock_rag_context()
        ctx.formatted_context = fixed_context

        messages_seen: List[List[Dict[str, str]]] = []

        def capture_complete(messages=None, **_kwargs):
            if messages is not None:
                messages_seen.append([dict(m) for m in messages])
            return VALID_LLM_OUTPUT

        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = ctx
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.side_effect = capture_complete
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ):
            # Run 1
            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=_make_mock_state_store(),
            )
            # Run 2 — identical inputs
            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=_make_mock_state_store(),
            )

        assert len(messages_seen) == 2
        # Both runs produced identical message lists
        assert messages_seen[0] == messages_seen[1], (
            "Identical inputs must produce identical LLM messages (determinism)"
        )


# ---------------------------------------------------------------------------
# Test 4 — Validation Enforcement
# ---------------------------------------------------------------------------

class TestValidationEnforcement:
    """Test 4: Invalid LLM output must fail validation, prevent writeback,
    and produce an audit record."""

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_invalid_output_blocked_prevents_writeback(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """Invalid LLM output must be blocked and Purview must NOT be written."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = INVALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
        ) as mock_writeback:
            result = run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        # Validation must block
        assert result.validation_status == "BLOCK"
        assert result.writeback_success is False

        # Purview must NOT be written
        mock_writeback.assert_not_called()

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_validation_block_produces_audit_record(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """Validation BLOCK must write an audit record to Cosmos DB."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = INVALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_build_purview.return_value = MagicMock()

        state_store = _make_mock_state_store()

        run_enrichment_pipeline(
            asset=VALID_ASSET,
            asset_id=ASSET_ID,
            entity_type=ENTITY_TYPE,
            source_system=SOURCE_SYSTEM,
            element_name=ELEMENT_NAME,
            correlation_id=CORRELATION_ID,
            current_hash=CURRENT_HASH,
            state_store=state_store,
        )

        # Audit record must have been written
        state_store.upsert_audit.assert_called()
        # Find the validation BLOCK audit record
        audit_calls = [c.args[0] for c in state_store.upsert_audit.call_args_list]
        block_audits = [
            a for a in audit_calls
            if a.get("validationStatus") == "BLOCK" or a.get("outcome") == "BLOCKED"
        ]
        assert len(block_audits) >= 1, (
            "At least one audit record must reflect the validation BLOCK"
        )
        # The audit record must contain the correlation_id
        for audit in block_audits:
            assert audit.get("correlationId") == CORRELATION_ID

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_validation_block_message_is_completed_not_abandoned(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """Validation BLOCK returns success=True so message is completed.

        A BLOCK is not a transient error — retrying the same unchanged asset
        immediately would produce the same invalid output.
        """
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = INVALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_build_purview.return_value = MagicMock()
        state_store = _make_mock_state_store()

        result = run_enrichment_pipeline(
            asset=VALID_ASSET,
            asset_id=ASSET_ID,
            entity_type=ENTITY_TYPE,
            source_system=SOURCE_SYSTEM,
            element_name=ELEMENT_NAME,
            correlation_id=CORRELATION_ID,
            current_hash=CURRENT_HASH,
            state_store=state_store,
        )

        assert result.success is True
        assert result.validation_status == "BLOCK"


# ---------------------------------------------------------------------------
# Test 5 — Purview Safety
# ---------------------------------------------------------------------------

class TestPurviewSafety:
    """Test 5: Suggested Description must be updated; Official Description
    must remain unchanged."""

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_writeback_targets_suggested_description_only(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """write_suggested_description must be called with the validated description."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ) as mock_wb:
            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        # write_suggested_description was called (not any official description method)
        mock_wb.assert_called_once()
        call_kwargs = mock_wb.call_args

        # The call must include entity_guid and correlation_id
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        args = call_kwargs.args if call_kwargs.args else ()

        # Accept both positional and keyword arguments
        all_args = {**kwargs}
        if args:
            param_names = ["entity_guid", "entity_type", "suggested_description", "correlation_id"]
            for i, v in enumerate(args):
                if i < len(param_names):
                    all_args[param_names[i]] = v

        assert "entity_guid" in all_args or len(args) >= 1
        assert "correlation_id" in all_args or len(args) >= 4

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_no_official_description_write_method_called(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """The official description (description field) must never be targeted.

        PurviewWritebackService.write_suggested_description() internally
        enforces this. This test verifies only write_suggested_description
        is used — not any other write method.
        """
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService",
        ) as MockService:
            mock_service_instance = MagicMock()
            mock_service_instance.write_suggested_description.return_value = (
                _make_writeback_result(success=True)
            )
            MockService.return_value = mock_service_instance

            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        # Only write_suggested_description should have been called on the service
        mock_service_instance.write_suggested_description.assert_called_once()
        # approve() and reject() must not be called
        mock_service_instance.approve.assert_not_called()
        mock_service_instance.reject.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6 — State Persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:
    """Test 6: State store must be updated only after successful writeback."""

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_state_updated_after_successful_writeback(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """State must be written to Cosmos AFTER Purview writeback succeeds."""
        call_order: List[str] = []

        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()

        def record_state_write(item):
            call_order.append("state_write")
            return {}

        state_store.upsert_state.side_effect = record_state_write

        def record_writeback(**kwargs):
            call_order.append("purview_writeback")
            return _make_writeback_result(success=True)

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            side_effect=record_writeback,
        ):
            result = run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        assert result.success is True

        # State write must occur AFTER writeback
        assert "purview_writeback" in call_order
        assert "state_write" in call_order
        wb_idx = call_order.index("purview_writeback")
        st_idx = call_order.index("state_write")
        assert wb_idx < st_idx, (
            f"State write (idx={st_idx}) must occur AFTER writeback (idx={wb_idx})"
        )

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_state_not_updated_on_writeback_failure(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """If Purview writeback fails, the state store must NOT be updated."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=False),
        ):
            result = run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        assert result.success is False
        # upsert_state must NOT have been called (no writeback succeeded)
        state_store.upsert_state.assert_not_called()

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_state_not_updated_on_validation_block(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """If validation is BLOCKED, the state store must NOT be updated."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = INVALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_build_purview.return_value = MagicMock()
        state_store = _make_mock_state_store()

        run_enrichment_pipeline(
            asset=VALID_ASSET,
            asset_id=ASSET_ID,
            entity_type=ENTITY_TYPE,
            source_system=SOURCE_SYSTEM,
            element_name=ELEMENT_NAME,
            correlation_id=CORRELATION_ID,
            current_hash=CURRENT_HASH,
            state_store=state_store,
        )

        # upsert_state must NOT be called (no writeback occurred)
        state_store.upsert_state.assert_not_called()

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_state_record_contains_correct_hash(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """The state record written after successful writeback must contain
        the current_hash passed into the pipeline."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()
        written_states: List[Dict] = []

        def capture_state(item):
            written_states.append(dict(item))
            return {}

        state_store.upsert_state.side_effect = capture_state

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ):
            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        # The pipeline writes exactly one state record (after writeback)
        assert len(written_states) == 1
        assert written_states[0]["contentHash"] == CURRENT_HASH
        # correlationId and enrichmentStatus must NOT be in the state record (schema violation)
        assert "correlationId" not in written_states[0]
        assert "enrichmentStatus" not in written_states[0]


# ---------------------------------------------------------------------------
# Test 6b — Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Tests verifying that duplicate Purview writebacks are suppressed when
    the asset was already successfully enriched at the current hash.

    This protects against Service Bus at-least-once redelivery after a crash
    between Step 5 (writeback) and Step 6 (state update).
    """

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_skips_writeback_when_already_enriched_at_same_hash(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """When state has enrichmentStatus=success and matching hash, writeback must be skipped."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        # State already records a prior enrichment at the current hash
        state_store = _make_mock_state_store()
        state_store.get_state.return_value = {
            "id": ASSET_ID,
            "entityType": ENTITY_TYPE,
            "contentHash": CURRENT_HASH,
            "decision": "REPROCESS",
        }

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
        ) as mock_writeback:
            result = run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        assert result.success is True
        assert result.writeback_success is True
        assert result.validation_status == "PASS"
        # Writeback must NOT have been called — idempotent skip
        mock_writeback.assert_not_called()

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_proceeds_with_writeback_when_hash_differs(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """When state hash differs from current hash, writeback must proceed normally."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        # State has a DIFFERENT hash — asset has changed since last enrichment
        state_store = _make_mock_state_store()
        state_store.get_state.return_value = {
            "id": ASSET_ID,
            "entityType": ENTITY_TYPE,
            "contentHash": "different-hash-from-previous-enrichment",
            "decision": "REPROCESS",
        }

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ) as mock_writeback:
            result = run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        assert result.success is True
        mock_writeback.assert_called_once()

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_proceeds_with_writeback_when_no_prior_state(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """When get_state returns None (first-time enrichment), writeback must proceed."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        # No state record exists — asset has never been enriched before
        state_store = _make_mock_state_store()
        state_store.get_state.return_value = None

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ) as mock_writeback:
            result = run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        assert result.success is True
        mock_writeback.assert_called_once()

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_idempotency_state_read_failure_proceeds_with_writeback(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """When the idempotency state read raises, pipeline must proceed with writeback."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()
        # First get_state call (change detection in orchestrator) returns None;
        # second call (idempotency check inside pipeline) raises
        call_count = {"n": 0}

        def flaky_get_state(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None  # change-detection read (no previous state)
            raise RuntimeError("Cosmos transient failure")

        state_store.get_state.side_effect = flaky_get_state

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ) as mock_writeback:
            result = run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        assert result.success is True
        # Writeback proceeds despite idempotency read failure
        mock_writeback.assert_called_once()


# ---------------------------------------------------------------------------
# Test 7 — Audit Traceability
# ---------------------------------------------------------------------------

class TestAuditTraceability:
    """Test 7: Audit record must contain correlation_id, model, token_usage,
    and validation_status.  The same correlation_id must appear across
    orchestrator logs, audit record, and Purview writeback logs."""

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_enrichment_audit_contains_required_fields(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """Enrichment audit record must contain correlationId, model,
        tokenUsage, and validationStatus."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()
        audit_records: List[Dict] = []

        def capture_audit(item):
            audit_records.append(dict(item))
            return {}

        state_store.upsert_audit.side_effect = capture_audit

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ):
            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        # Find enrichment audit records (exclude lifecycle/writeback records)
        enr_audits = [
            r for r in audit_records
            if r.get("recordType") == "enrichment_audit"
        ]
        assert len(enr_audits) >= 1, "At least one enrichment audit record must be written"

        # Check the final audit record (outcome=SUCCESS)
        success_audit = next(
            (r for r in enr_audits if r.get("outcome") == "SUCCESS"), None
        )
        assert success_audit is not None, "A SUCCESS enrichment audit record must exist"

        # Required fields per Phase 4 spec
        assert "correlationId" in success_audit, "correlationId missing from audit"
        assert "model" in success_audit, "model missing from audit"
        assert "tokenUsage" in success_audit, "tokenUsage missing from audit"
        assert "validationStatus" in success_audit, "validationStatus missing from audit"

        # Values
        assert success_audit["correlationId"] == CORRELATION_ID
        assert success_audit["validationStatus"] == "PASS"
        assert success_audit["writebackSuccess"] is True

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_correlation_id_propagated_to_rag_and_writeback(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """The correlation_id must appear in the RAG call and writeback call."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ) as mock_wb:
            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        # correlation_id passed to RAG
        rag_call = mock_rag.retrieve_context_for_asset.call_args
        assert rag_call.kwargs.get("correlation_id") == CORRELATION_ID

        # correlation_id passed to writeback
        wb_call = mock_wb.call_args
        wb_kwargs = wb_call.kwargs if wb_call.kwargs else {}
        wb_args = wb_call.args if wb_call.args else ()
        # Accept positional or keyword
        if "correlation_id" in wb_kwargs:
            assert wb_kwargs["correlation_id"] == CORRELATION_ID
        else:
            assert CORRELATION_ID in wb_args


# ---------------------------------------------------------------------------
# Integration Test — handle_message REPROCESS triggers pipeline
# ---------------------------------------------------------------------------

class TestHandleMessagePipelineIntegration:
    """Verify that handle_message correctly calls the enrichment pipeline
    on a REPROCESS decision and propagates the result."""

    def test_reprocess_triggers_pipeline(self) -> None:
        """handle_message with no previous state must invoke the pipeline.

        run_enrichment_pipeline is imported lazily inside handle_message, so
        we patch it at the source module (enrichment_pipeline) rather than on
        the message_handler namespace.
        """
        body = json.dumps(VALID_ASSET)

        with patch(
            "src.enrichment.pipeline.enrichment_pipeline.run_enrichment_pipeline",
        ) as mock_pipeline:
            mock_pipeline.return_value = EnrichmentPipelineResult(
                success=True,
                asset_id=ASSET_ID,
                correlation_id=CORRELATION_ID,
                validation_status="PASS",
                writeback_success=True,
            )
            result = handle_message(body, state_store=None)

        assert result.success is True
        assert result.decision == DecisionResult.REPROCESS.value
        mock_pipeline.assert_called_once()

    def test_skip_does_not_trigger_pipeline(self) -> None:
        """handle_message with matching previous state must NOT invoke the pipeline."""
        body = json.dumps(VALID_ASSET)

        from src.domain.change_detection import compute_asset_hash
        matching_hash = compute_asset_hash(VALID_ASSET)

        state_store = _make_mock_state_store(previous_hash=matching_hash)

        with patch(
            "src.enrichment.pipeline.enrichment_pipeline.run_enrichment_pipeline",
        ) as mock_pipeline:
            result = handle_message(body, state_store=state_store)

        assert result.decision == DecisionResult.SKIP.value
        assert result.success is True
        mock_pipeline.assert_not_called()

    def test_pipeline_failure_propagates_to_handler(self) -> None:
        """If the pipeline returns success=False, the handler must also return
        success=False (so the consumer abandons the message)."""
        body = json.dumps(VALID_ASSET)

        with patch(
            "src.enrichment.pipeline.enrichment_pipeline.run_enrichment_pipeline",
        ) as mock_pipeline:
            mock_pipeline.return_value = EnrichmentPipelineResult(
                success=False,
                asset_id=ASSET_ID,
                correlation_id=CORRELATION_ID,
                validation_status="ERROR",
                writeback_success=False,
                error="RAG service unavailable",
            )
            result = handle_message(body, state_store=None)

        assert result.success is False
        assert result.error == "RAG service unavailable"


# ---------------------------------------------------------------------------
# Prompt Builder — unit tests
# ---------------------------------------------------------------------------

class TestPromptBuilder:
    """Verify that build_llm_messages produces deterministic, contract-compliant
    message lists."""

    def test_returns_system_and_user_messages(self) -> None:
        """build_llm_messages must return exactly 2 messages: system and user."""
        from src.enrichment.llm.prompt_builder import build_llm_messages

        messages = build_llm_messages(
            asset=VALID_ASSET,
            entity_type=ENTITY_TYPE,
            formatted_context="Test context.",
        )

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_context_appears_in_user_message(self) -> None:
        """Formatted context must be injected into the user message."""
        from src.enrichment.llm.prompt_builder import build_llm_messages

        context = "Source: synergy\nUnique context marker: XYZ-12345"
        messages = build_llm_messages(
            asset=VALID_ASSET,
            entity_type=ENTITY_TYPE,
            formatted_context=context,
        )

        assert "XYZ-12345" in messages[1]["content"]

    def test_entity_type_appears_in_user_message(self) -> None:
        """Entity type must appear in the user message."""
        from src.enrichment.llm.prompt_builder import build_llm_messages

        messages = build_llm_messages(
            asset=VALID_ASSET,
            entity_type="dataset",
            formatted_context="Some context.",
        )

        assert "dataset" in messages[1]["content"]

    def test_deterministic_output_same_inputs(self) -> None:
        """Same inputs must produce identical messages (determinism)."""
        from src.enrichment.llm.prompt_builder import build_llm_messages

        m1 = build_llm_messages(
            asset=VALID_ASSET, entity_type=ENTITY_TYPE, formatted_context="ctx"
        )
        m2 = build_llm_messages(
            asset=VALID_ASSET, entity_type=ENTITY_TYPE, formatted_context="ctx"
        )

        assert m1 == m2

    def test_output_format_instruction_present(self) -> None:
        """Output format instruction (YAML) must appear in user message."""
        from src.enrichment.llm.prompt_builder import build_llm_messages

        messages = build_llm_messages(
            asset=VALID_ASSET,
            entity_type=ENTITY_TYPE,
            formatted_context="ctx",
        )

        user_content = messages[1]["content"]
        assert "suggested_description" in user_content
        assert "confidence" in user_content
        assert "used_sources" in user_content


# ---------------------------------------------------------------------------
# Completion Criteria Tests — Test 3 (State Schema) & Test 4 (Execution Duration)
# ---------------------------------------------------------------------------


class TestStateSchemaCompliance:
    """Test 3 — State Schema Compliance (completion criterion).

    State records written by the pipeline must contain ONLY the five frozen
    fields defined in STATE_RECORD_FIELDS.  No extra fields are permitted.
    """

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_state_record_contains_only_frozen_fields(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """State record must contain exactly: id, entityType, sourceSystem,
        contentHash, lastProcessed — nothing else."""
        from src.infrastructure.state_store.models import STATE_RECORD_FIELDS

        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()
        written_states: List[Dict] = []

        def capture_state(item):
            written_states.append(dict(item))
            return {}

        state_store.upsert_state.side_effect = capture_state

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ):
            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        assert len(written_states) == 1
        actual_fields = set(written_states[0].keys())
        unexpected = actual_fields - STATE_RECORD_FIELDS
        assert not unexpected, (
            f"State record contains forbidden fields: {unexpected}. "
            f"Only {STATE_RECORD_FIELDS} are allowed."
        )
        missing = STATE_RECORD_FIELDS - actual_fields
        assert not missing, (
            f"State record is missing required fields: {missing}."
        )

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_orchestrator_skip_state_record_contains_only_frozen_fields(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """SKIP path: orchestrator state record must also contain only frozen fields."""
        from src.infrastructure.state_store.models import STATE_RECORD_FIELDS
        from src.orchestrator.message_handler import handle_message
        import json

        # Provide a previous state with the same hash so SKIP fires
        mock_store = MagicMock()
        written_states: List[Dict] = []

        def capture_state(item):
            written_states.append(dict(item))
            return {}

        # We need to know the hash the orchestrator will compute for VALID_ASSET.
        # Use the domain hasher to get the exact hash.
        from src.domain.element_splitter import ContextElement
        from src.domain.element_hashing import compute_element_hash_result

        element = ContextElement(
            source_system=VALID_ASSET["sourceSystem"],
            element_name=VALID_ASSET["entityName"],
            element_type=VALID_ASSET["entityType"],
            description=VALID_ASSET.get("description", ""),
            raw_payload=VALID_ASSET,
        )
        hash_result = compute_element_hash_result(element)
        expected_hash = hash_result.content_hash

        mock_store.get_state.return_value = {
            "id": hash_result.element_id,
            "entityType": ENTITY_TYPE,
            "contentHash": expected_hash,  # same hash → SKIP
        }
        mock_store.upsert_state.side_effect = capture_state
        mock_store.upsert_audit.return_value = {}

        _handler_pipeline_patch = "src.enrichment.pipeline.enrichment_pipeline.run_enrichment_pipeline"
        with patch(_handler_pipeline_patch) as mock_pipeline:
            handle_message(json.dumps(VALID_ASSET), state_store=mock_store)
            mock_pipeline.assert_not_called()

        assert len(written_states) == 1
        actual_fields = set(written_states[0].keys())
        unexpected = actual_fields - STATE_RECORD_FIELDS
        assert not unexpected, (
            f"SKIP state record contains forbidden fields: {unexpected}. "
            f"Only {STATE_RECORD_FIELDS} are allowed."
        )


class TestExecutionDurationAudit:
    """Test 4 — Execution Duration (completion criterion).

    The pipeline audit record must contain executionDurationMs capturing the
    LLM inference wall-clock duration in milliseconds.
    """

    @patch("src.enrichment.pipeline.enrichment_pipeline._build_rag_pipeline")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_llm_client")
    @patch("src.enrichment.pipeline.enrichment_pipeline._build_purview_client")
    def test_audit_record_contains_execution_duration_ms(
        self,
        mock_build_purview,
        mock_build_llm,
        mock_build_rag,
    ) -> None:
        """Successful pipeline run: audit record must have executionDurationMs >= 0."""
        mock_rag = MagicMock()
        mock_rag.retrieve_context_for_asset.return_value = _make_mock_rag_context()
        mock_build_rag.return_value = mock_rag

        mock_llm = MagicMock()
        mock_llm.complete.return_value = VALID_LLM_RESULT
        mock_build_llm.return_value = mock_llm

        mock_purview = MagicMock()
        mock_build_purview.return_value = mock_purview

        state_store = _make_mock_state_store()
        audit_records: List[Dict] = []

        def capture_audit(item):
            audit_records.append(dict(item))
            return {}

        state_store.upsert_audit.side_effect = capture_audit

        with patch(
            "src.enrichment.purview_writeback.PurviewWritebackService.write_suggested_description",
            return_value=_make_writeback_result(success=True),
        ):
            run_enrichment_pipeline(
                asset=VALID_ASSET,
                asset_id=ASSET_ID,
                entity_type=ENTITY_TYPE,
                source_system=SOURCE_SYSTEM,
                element_name=ELEMENT_NAME,
                correlation_id=CORRELATION_ID,
                current_hash=CURRENT_HASH,
                state_store=state_store,
            )

        # Find the pipeline enrichment audit record (not the orchestrator decision audit)
        pipeline_audits = [
            r for r in audit_records
            if r.get("recordType") == "enrichment_audit"
        ]
        assert pipeline_audits, (
            "No enrichment_audit audit record found. "
            f"Audit records written: {[r.get('recordType') for r in audit_records]}"
        )
        audit = pipeline_audits[0]
        assert "executionDurationMs" in audit, (
            "executionDurationMs missing from pipeline audit record"
        )
        assert isinstance(audit["executionDurationMs"], int), (
            "executionDurationMs must be an int"
        )
        assert audit["executionDurationMs"] >= 0
