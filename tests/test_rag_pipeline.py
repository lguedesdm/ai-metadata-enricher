"""
Unit tests for the RAG Query Pipeline.

Tests cover:
- Configuration validation (RAGConfig)
- Data models (ContextChunk, RetrievedContext)
- Deterministic ranking (composite scoring)
- Context assembly (formatting for prompt injection)
- Pipeline integration (with mocked search client)
- Filter building
- Isolation guarantees (no LLM, Purview, or Orchestrator calls)

All tests are self-contained and do not require Azure services.
"""

import math
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.enrichment.rag.config import RAGConfig
from src.enrichment.rag.errors import RAGErrorCategory, RAGSearchError
from src.enrichment.rag.models import ContextChunk, RetrievedContext
from src.enrichment.rag.ranking import (
    compute_composite_scores,
    _compute_freshness_factor,
    _get_effective_relevance,
)
from src.enrichment.rag.context_assembly import assemble_context, _format_chunk
from src.enrichment.rag.pipeline import _build_filter


# =============================================================================
# Fixtures
# =============================================================================


def _make_chunk(
    document_id: str = "synergy.student.enrollment.table",
    source_system: str = "synergy",
    element_type: str = "table",
    element_name: str = "Student Enrollment",
    source: str = "",
    title: str = "",
    content: str = "Student enrollment records.",
    description: str = "Stores student enrollment records.",
    suggested_description: str = "Core enrollment tracking table.",
    tags: tuple = ("enrollment", "student"),
    relevance_score: float = 0.8,
    reranker_score: float | None = None,
    last_updated: datetime | None = None,
    ceds_link: str | None = None,
) -> ContextChunk:
    """Create a ContextChunk for testing."""
    return ContextChunk(
        document_id=document_id,
        source_system=source_system,
        element_type=element_type,
        element_name=element_name,
        source=source,
        title=title,
        content=content,
        description=description,
        suggested_description=suggested_description,
        tags=tags,
        ceds_link=ceds_link,
        last_updated=last_updated,
        relevance_score=relevance_score,
        reranker_score=reranker_score,
    )


def _make_config_env(**overrides: str) -> dict[str, str]:
    """Build environment variable dict for RAGConfig."""
    env = {
        "AZURE_SEARCH_ENDPOINT": "https://search-test.search.windows.net",
        "AZURE_SEARCH_INDEX_NAME": "metadata-index",
        "AZURE_SEARCH_SEMANTIC_CONFIG": "default",
        "RAG_MAX_RESULTS": "10",
        "RAG_MIN_RELEVANCE_SCORE": "0.0",
        "RAG_FRESHNESS_WEIGHT": "0.1",
        "RAG_MAX_CONTEXT_CHARS": "8000",
        "RAG_SOURCE_WEIGHTS": "synergy:1.0,zipline:1.0,documentation:0.8",
        "ENVIRONMENT": "test",
    }
    env.update(overrides)
    return env


# =============================================================================
# RAGConfig Tests
# =============================================================================


class TestRAGConfig:
    """Tests for RAGConfig validation and parsing."""

    def test_valid_config(self):
        """Config loads correctly from environment variables."""
        with patch.dict(os.environ, _make_config_env(), clear=False):
            config = RAGConfig()
            config.validate()
            assert config.search_endpoint == "https://search-test.search.windows.net"
            assert config.search_index_name == "metadata-index"
            assert config.max_results == 10
            assert config.freshness_weight == 0.1
            assert config.environment == "test"

    def test_source_weights_parsing(self):
        """Source weights are correctly parsed from comma-separated string."""
        with patch.dict(os.environ, _make_config_env(), clear=False):
            config = RAGConfig()
            weights = config.source_weights
            assert weights == {
                "synergy": 1.0,
                "zipline": 1.0,
                "documentation": 0.8,
            }

    def test_source_weights_empty(self):
        """Empty source weights string returns empty dict."""
        with patch.dict(os.environ, _make_config_env(RAG_SOURCE_WEIGHTS=""), clear=False):
            config = RAGConfig()
            assert config.source_weights == {}

    def test_source_weights_malformed(self):
        """Malformed source weights entries are skipped."""
        with patch.dict(
            os.environ,
            _make_config_env(RAG_SOURCE_WEIGHTS="synergy:1.0,bad_entry,zipline:abc"),
            clear=False,
        ):
            config = RAGConfig()
            weights = config.source_weights
            assert weights == {"synergy": 1.0}

    def test_missing_endpoint_raises(self):
        """Missing AZURE_SEARCH_ENDPOINT raises ValueError on validate."""
        with patch.dict(
            os.environ,
            _make_config_env(AZURE_SEARCH_ENDPOINT=""),
            clear=False,
        ):
            config = RAGConfig()
            with pytest.raises(ValueError, match="AZURE_SEARCH_ENDPOINT"):
                config.validate()

    def test_missing_index_name_raises(self):
        """Missing AZURE_SEARCH_INDEX_NAME raises ValueError on validate."""
        with patch.dict(
            os.environ,
            _make_config_env(AZURE_SEARCH_INDEX_NAME=""),
            clear=False,
        ):
            config = RAGConfig()
            with pytest.raises(ValueError, match="AZURE_SEARCH_INDEX_NAME"):
                config.validate()

    def test_invalid_max_results_raises(self):
        """max_results < 1 raises ValueError on validate."""
        with patch.dict(
            os.environ,
            _make_config_env(RAG_MAX_RESULTS="0"),
            clear=False,
        ):
            config = RAGConfig()
            with pytest.raises(ValueError, match="RAG_MAX_RESULTS"):
                config.validate()

    def test_invalid_relevance_score_raises(self):
        """min_relevance_score outside [0, 1] raises ValueError."""
        with patch.dict(
            os.environ,
            _make_config_env(RAG_MIN_RELEVANCE_SCORE="1.5"),
            clear=False,
        ):
            config = RAGConfig()
            with pytest.raises(ValueError, match="RAG_MIN_RELEVANCE_SCORE"):
                config.validate()

    def test_invalid_freshness_weight_raises(self):
        """freshness_weight outside [0, 1] raises ValueError."""
        with patch.dict(
            os.environ,
            _make_config_env(RAG_FRESHNESS_WEIGHT="-0.1"),
            clear=False,
        ):
            config = RAGConfig()
            with pytest.raises(ValueError, match="RAG_FRESHNESS_WEIGHT"):
                config.validate()

    def test_invalid_max_context_chars_raises(self):
        """max_context_chars < 100 raises ValueError."""
        with patch.dict(
            os.environ,
            _make_config_env(RAG_MAX_CONTEXT_CHARS="50"),
            clear=False,
        ):
            config = RAGConfig()
            with pytest.raises(ValueError, match="RAG_MAX_CONTEXT_CHARS"):
                config.validate()


# =============================================================================
# ContextChunk & RetrievedContext Model Tests
# =============================================================================


class TestModels:
    """Tests for data model immutability and properties."""

    def test_context_chunk_frozen(self):
        """ContextChunk is immutable (frozen dataclass)."""
        chunk = _make_chunk()
        with pytest.raises(AttributeError):
            chunk.document_id = "changed"  # type: ignore

    def test_context_chunk_fields(self):
        """ContextChunk stores all fields correctly."""
        dt = datetime(2026, 1, 12, 14, 30, 0, tzinfo=timezone.utc)
        chunk = _make_chunk(
            ceds_link="https://ceds.ed.gov/CEDS-00001",
            last_updated=dt,
        )
        assert chunk.document_id == "synergy.student.enrollment.table"
        assert chunk.source_system == "synergy"
        assert chunk.ceds_link == "https://ceds.ed.gov/CEDS-00001"
        assert chunk.last_updated == dt

    def test_retrieved_context_has_context_true(self):
        """has_context is True when chunks are present."""
        chunk = _make_chunk()
        ctx = RetrievedContext(
            query="test",
            chunks=(chunk,),
            formatted_context="text",
            total_results_found=1,
            results_used=1,
        )
        assert ctx.has_context is True

    def test_retrieved_context_has_context_false(self):
        """has_context is False when no chunks."""
        ctx = RetrievedContext(
            query="test",
            chunks=(),
            formatted_context="",
            total_results_found=0,
            results_used=0,
        )
        assert ctx.has_context is False

    def test_source_systems_used(self):
        """source_systems_used returns deduplicated sorted tuple."""
        c1 = _make_chunk(document_id="a", source_system="zipline")
        c2 = _make_chunk(document_id="b", source_system="synergy")
        c3 = _make_chunk(document_id="c", source_system="synergy")
        ctx = RetrievedContext(
            query="test",
            chunks=(c1, c2, c3),
            formatted_context="text",
            total_results_found=3,
            results_used=3,
        )
        assert ctx.source_systems_used == ("synergy", "zipline")


# =============================================================================
# Ranking Tests
# =============================================================================


class TestRanking:
    """Tests for deterministic composite scoring and ranking."""

    def test_basic_ranking_by_relevance(self):
        """Higher relevance scores rank higher."""
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        c_high = _make_chunk(document_id="high", relevance_score=0.9)
        c_low = _make_chunk(document_id="low", relevance_score=0.3)

        ranked = compute_composite_scores(
            [c_low, c_high],
            source_weights={"synergy": 1.0},
            freshness_weight=0.0,
            reference_time=ref_time,
        )
        assert ranked[0].document_id == "high"
        assert ranked[1].document_id == "low"

    def test_source_weight_affects_ranking(self):
        """Source weight multiplier changes relative ranking."""
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        c_syn = _make_chunk(
            document_id="syn", source_system="synergy", relevance_score=0.5
        )
        c_doc = _make_chunk(
            document_id="doc", source_system="documentation", relevance_score=0.5
        )

        ranked = compute_composite_scores(
            [c_doc, c_syn],
            source_weights={"synergy": 2.0, "documentation": 0.5},
            freshness_weight=0.0,
            reference_time=ref_time,
        )
        assert ranked[0].document_id == "syn"
        assert ranked[0].composite_score > ranked[1].composite_score

    def test_freshness_boosts_newer_documents(self):
        """Newer documents get higher freshness boost."""
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        c_new = _make_chunk(
            document_id="new",
            relevance_score=0.5,
            last_updated=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        c_old = _make_chunk(
            document_id="old",
            relevance_score=0.5,
            last_updated=datetime(2025, 1, 10, tzinfo=timezone.utc),
        )

        ranked = compute_composite_scores(
            [c_old, c_new],
            source_weights={"synergy": 1.0},
            freshness_weight=0.5,
            reference_time=ref_time,
        )
        assert ranked[0].document_id == "new"
        assert ranked[0].composite_score > ranked[1].composite_score

    def test_determinism_same_input_same_output(self):
        """Same inputs always produce identical ranking."""
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        chunks = [
            _make_chunk(document_id="a", relevance_score=0.7),
            _make_chunk(document_id="b", relevance_score=0.9),
            _make_chunk(document_id="c", relevance_score=0.8),
        ]
        weights = {"synergy": 1.0}

        result1 = compute_composite_scores(chunks, weights, 0.1, ref_time)
        result2 = compute_composite_scores(chunks, weights, 0.1, ref_time)

        assert [c.document_id for c in result1] == [c.document_id for c in result2]
        assert [c.composite_score for c in result1] == [c.composite_score for c in result2]

    def test_tie_breaking_by_document_id(self):
        """Identical composite scores are broken by document_id ascending."""
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        c_b = _make_chunk(document_id="beta", relevance_score=0.5)
        c_a = _make_chunk(document_id="alpha", relevance_score=0.5)

        ranked = compute_composite_scores(
            [c_b, c_a],
            source_weights={"synergy": 1.0},
            freshness_weight=0.0,
            reference_time=ref_time,
        )
        # Same score → alphabetical by document_id
        assert ranked[0].document_id == "alpha"
        assert ranked[1].document_id == "beta"

    def test_reranker_score_preferred_over_relevance(self):
        """When reranker_score is available, it is used instead of relevance_score."""
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        # Low relevance but high reranker score
        c_reranked = _make_chunk(
            document_id="reranked",
            relevance_score=0.1,
            reranker_score=3.5,  # ~0.875 normalized
        )
        # High relevance but no reranker score
        c_plain = _make_chunk(
            document_id="plain",
            relevance_score=0.8,
            reranker_score=None,
        )

        ranked = compute_composite_scores(
            [c_plain, c_reranked],
            source_weights={"synergy": 1.0},
            freshness_weight=0.0,
            reference_time=ref_time,
        )
        assert ranked[0].document_id == "reranked"

    def test_empty_chunks_returns_empty(self):
        """Empty input returns empty output."""
        ranked = compute_composite_scores(
            [],
            source_weights={"synergy": 1.0},
            freshness_weight=0.1,
            reference_time=datetime(2026, 1, 15, tzinfo=timezone.utc),
        )
        assert ranked == []

    def test_default_source_weight(self):
        """Unknown source system gets default weight of 1.0."""
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        chunk = _make_chunk(
            document_id="unknown",
            source_system="new_system",
            relevance_score=0.5,
        )

        ranked = compute_composite_scores(
            [chunk],
            source_weights={"synergy": 1.0},
            freshness_weight=0.0,
            reference_time=ref_time,
        )
        # default weight is 1.0, so composite = 0.5 * 1.0 = 0.5
        assert ranked[0].composite_score == 0.5


class TestFreshnessFactor:
    """Tests for the freshness decay function."""

    def test_brand_new_document(self):
        """Document updated at reference time gets factor 1.0."""
        ref = datetime(2026, 1, 15, tzinfo=timezone.utc)
        assert _compute_freshness_factor(ref, ref) == 1.0

    def test_future_document(self):
        """Document updated after reference time gets factor 1.0."""
        ref = datetime(2026, 1, 15, tzinfo=timezone.utc)
        future = datetime(2026, 1, 20, tzinfo=timezone.utc)
        assert _compute_freshness_factor(future, ref) == 1.0

    def test_90_day_old_document(self):
        """Document at half-life (90 days) gets factor ~0.5."""
        ref = datetime(2026, 4, 15, tzinfo=timezone.utc)
        old = datetime(2026, 1, 15, tzinfo=timezone.utc)
        factor = _compute_freshness_factor(old, ref)
        assert abs(factor - 0.5) < 0.01

    def test_none_timestamp_returns_neutral(self):
        """None timestamp returns neutral factor 0.5."""
        ref = datetime(2026, 1, 15, tzinfo=timezone.utc)
        assert _compute_freshness_factor(None, ref) == 0.5

    def test_very_old_document_approaches_zero(self):
        """Very old document (2+ years) approaches 0."""
        ref = datetime(2026, 1, 15, tzinfo=timezone.utc)
        old = datetime(2024, 1, 15, tzinfo=timezone.utc)
        factor = _compute_freshness_factor(old, ref)
        assert factor < 0.01


class TestEffectiveRelevance:
    """Tests for relevance score extraction."""

    def test_reranker_score_normalized(self):
        """Reranker score (0–4) is normalized to 0–1."""
        chunk = _make_chunk(reranker_score=2.0)
        assert _get_effective_relevance(chunk) == 0.5

    def test_reranker_score_capped(self):
        """Reranker score > 4 is capped at 1.0."""
        chunk = _make_chunk(reranker_score=5.0)
        assert _get_effective_relevance(chunk) == 1.0

    def test_fallback_to_relevance_score(self):
        """Without reranker, relevance_score is used."""
        chunk = _make_chunk(relevance_score=0.75, reranker_score=None)
        assert _get_effective_relevance(chunk) == 0.75

    def test_relevance_clamped(self):
        """Relevance score > 1 is clamped."""
        chunk = _make_chunk(relevance_score=1.5, reranker_score=None)
        assert _get_effective_relevance(chunk) == 1.0


# =============================================================================
# Context Assembly Tests
# =============================================================================


class TestContextAssembly:
    """Tests for context formatting and assembly."""

    def test_basic_formatting(self):
        """Single chunk is formatted correctly."""
        chunk = _make_chunk()
        formatted = _format_chunk(chunk, 1)
        assert "[Source 1]" in formatted
        assert "Student Enrollment" in formatted
        assert "table" in formatted
        assert "synergy" in formatted
        assert "Document ID: synergy.student.enrollment.table" in formatted
        assert "Content: Student enrollment records." in formatted
        assert "Suggested Description: Core enrollment tracking table." in formatted

    def test_optional_fields_included(self):
        """Optional fields are included when present."""
        chunk = _make_chunk(
            ceds_link="https://ceds.ed.gov/CEDS-00001",
        )
        formatted = _format_chunk(chunk, 1)
        assert "CEDS Link: https://ceds.ed.gov/CEDS-00001" in formatted

    def test_optional_fields_omitted_when_none(self):
        """Optional fields are omitted when None."""
        chunk = _make_chunk(ceds_link=None)
        formatted = _format_chunk(chunk, 1)
        assert "CEDS Link" not in formatted

    def test_tags_formatted(self):
        """Tags are comma-separated."""
        chunk = _make_chunk(tags=("enrollment", "student", "core"))
        formatted = _format_chunk(chunk, 1)
        assert "Tags: enrollment, student, core" in formatted

    def test_assemble_multiple_chunks(self):
        """Multiple chunks are joined with double newlines."""
        c1 = _make_chunk(document_id="a", element_name="Entity A")
        c2 = _make_chunk(document_id="b", element_name="Entity B")
        ctx = assemble_context(
            query="test",
            ranked_chunks=[c1, c2],
            max_context_chars=10000,
            total_results_found=2,
        )
        assert ctx.results_used == 2
        assert "[Source 1]" in ctx.formatted_context
        assert "[Source 2]" in ctx.formatted_context
        assert "Entity A" in ctx.formatted_context
        assert "Entity B" in ctx.formatted_context

    def test_assemble_respects_char_limit(self):
        """Context assembly stops when character limit is reached."""
        chunks = [
            _make_chunk(
                document_id=f"id-{i}",
                element_name=f"Entity {i}",
                content="X" * 200,
            )
            for i in range(20)
        ]
        ctx = assemble_context(
            query="test",
            ranked_chunks=chunks,
            max_context_chars=500,
            total_results_found=20,
        )
        assert len(ctx.formatted_context) <= 500
        assert ctx.results_used < 20

    def test_assemble_empty_chunks(self):
        """Empty chunks produce empty context."""
        ctx = assemble_context(
            query="test",
            ranked_chunks=[],
            max_context_chars=8000,
            total_results_found=0,
        )
        assert ctx.formatted_context == ""
        assert ctx.results_used == 0
        assert ctx.has_context is False

    def test_assemble_at_least_one_chunk_included(self):
        """Even with a tiny budget, at least part of the first chunk is included."""
        chunk = _make_chunk(content="X" * 1000)
        ctx = assemble_context(
            query="test",
            ranked_chunks=[chunk],
            max_context_chars=100,
            total_results_found=1,
        )
        assert ctx.results_used == 1
        assert len(ctx.formatted_context) <= 100

    def test_assemble_preserves_chunk_order(self):
        """Chunks are included in the order provided (pre-ranked)."""
        c1 = _make_chunk(document_id="first", element_name="First")
        c2 = _make_chunk(document_id="second", element_name="Second")
        c3 = _make_chunk(document_id="third", element_name="Third")
        ctx = assemble_context(
            query="test",
            ranked_chunks=[c1, c2, c3],
            max_context_chars=10000,
            total_results_found=3,
        )
        pos_first = ctx.formatted_context.index("First")
        pos_second = ctx.formatted_context.index("Second")
        pos_third = ctx.formatted_context.index("Third")
        assert pos_first < pos_second < pos_third

    def test_context_compatible_with_prompt_placeholder(self):
        """Formatted context fits the {{retrieved_context}} placeholder pattern.

        The frozen prompt (v1-suggested-description.prompt.md) expects
        'text retrieved from Azure AI Search' and the output contract
        expects used_sources citing 'Document ID' or similar identifiers.

        The context format must include:
        - Source numbering for citation
        - Document identifiers for traceability
        - Content fields for grounding
        """
        chunk = _make_chunk(
            document_id="synergy.student.enrollment.table",
            element_name="Student Enrollment",
            content="Student enrollment records including school assignments.",
        )
        ctx = assemble_context(
            query="student enrollment",
            ranked_chunks=[chunk],
            max_context_chars=8000,
            total_results_found=1,
        )
        # Must have source numbering
        assert "[Source 1]" in ctx.formatted_context
        # Must have document identifier for traceability
        assert "Document ID: synergy.student.enrollment.table" in ctx.formatted_context
        # Must have content for grounding
        assert "Student enrollment records" in ctx.formatted_context


# =============================================================================
# Filter Building Tests
# =============================================================================


class TestFilterBuilding:
    """Tests for OData filter expression construction."""

    def test_no_filters_returns_none(self):
        """No filter parameters returns None."""
        assert _build_filter() is None

    def test_entity_type_filter(self):
        """Entity type produces correct OData filter."""
        f = _build_filter(entity_type="table")
        assert f == "elementType eq 'table'"

    def test_source_system_filter(self):
        """Source system produces correct OData filter."""
        f = _build_filter(source_system="synergy")
        assert f == "sourceSystem eq 'synergy'"

    def test_multiple_filters_combined(self):
        """Multiple filters are combined with 'and'."""
        f = _build_filter(entity_type="table", source_system="synergy")
        assert "elementType eq 'table'" in f
        assert "sourceSystem eq 'synergy'" in f
        assert " and " in f

    def test_additional_filters_appended(self):
        """Additional filters are wrapped in parentheses and appended."""
        f = _build_filter(
            source_system="synergy",
            additional_filters="lastUpdated ge '2026-01-01T00:00:00Z'"
        )
        assert "sourceSystem eq 'synergy'" in f
        assert "(lastUpdated ge '2026-01-01T00:00:00Z')" in f

    def test_only_additional_filters(self):
        """Only additional filters still produces a valid expression."""
        f = _build_filter(additional_filters="entityType eq 'column'")
        assert f == "(entityType eq 'column')"


# =============================================================================
# Pipeline Integration Tests (with mocked search client)
# =============================================================================


class TestRAGQueryPipeline:
    """Integration tests for the full RAG Query Pipeline with mocked Azure AI Search."""

    def _make_pipeline_with_mock_search(self, mock_search_results: list[ContextChunk]):
        """Create a pipeline with a mocked search client."""
        from src.enrichment.rag.pipeline import RAGQueryPipeline

        with patch.dict(os.environ, _make_config_env(), clear=False):
            config = RAGConfig()

        # Mock the search client initialization to avoid Azure connection
        with patch("src.enrichment.rag.pipeline.AISearchClient") as MockSearchClient:
            mock_instance = MagicMock()
            mock_instance.search.return_value = mock_search_results
            MockSearchClient.return_value = mock_instance

            pipeline = RAGQueryPipeline.__new__(RAGQueryPipeline)
            pipeline._config = config
            pipeline._search_client = mock_instance

        return pipeline

    def test_full_retrieval_cycle(self):
        """Full cycle: search → rank → assemble produces valid context."""
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        chunks = [
            _make_chunk(
                document_id="a",
                relevance_score=0.9,
                last_updated=datetime(2026, 1, 10, tzinfo=timezone.utc),
            ),
            _make_chunk(
                document_id="b",
                relevance_score=0.5,
                last_updated=datetime(2025, 6, 1, tzinfo=timezone.utc),
            ),
        ]

        pipeline = self._make_pipeline_with_mock_search(chunks)
        context = pipeline.retrieve_context(
            query="student enrollment",
            reference_time=ref_time,
        )

        assert context.has_context
        assert context.results_used == 2
        assert context.total_results_found == 2
        assert "[Source 1]" in context.formatted_context
        assert "[Source 2]" in context.formatted_context

    def test_determinism_identical_runs(self):
        """Two runs with identical inputs produce identical outputs."""
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        chunks = [
            _make_chunk(document_id="x", relevance_score=0.7),
            _make_chunk(document_id="y", relevance_score=0.8),
            _make_chunk(document_id="z", relevance_score=0.6),
        ]

        pipeline = self._make_pipeline_with_mock_search(chunks)
        ctx1 = pipeline.retrieve_context("test query", reference_time=ref_time)
        ctx2 = pipeline.retrieve_context("test query", reference_time=ref_time)

        assert ctx1.formatted_context == ctx2.formatted_context
        assert [c.document_id for c in ctx1.chunks] == [c.document_id for c in ctx2.chunks]

    def test_no_results_returns_empty_context(self):
        """When search returns no results, context is empty."""
        pipeline = self._make_pipeline_with_mock_search([])
        context = pipeline.retrieve_context("nonexistent query")

        assert not context.has_context
        assert context.results_used == 0
        assert context.formatted_context == ""

    def test_entity_type_filter_passed(self):
        """entity_type parameter results in search with filter."""
        pipeline = self._make_pipeline_with_mock_search([])
        pipeline.retrieve_context(
            query="test",
            entity_type="table",
            source_system="synergy",
        )

        call_args = pipeline._search_client.search.call_args
        filters = call_args.kwargs.get("filters") or call_args[1].get("filters")
        assert "elementType eq 'table'" in filters
        assert "sourceSystem eq 'synergy'" in filters

    def test_search_metadata_populated(self):
        """Search metadata dict is populated in the result."""
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        pipeline = self._make_pipeline_with_mock_search([_make_chunk()])
        context = pipeline.retrieve_context("test", reference_time=ref_time)

        assert context.search_metadata["search_type"] == "hybrid_semantic"
        assert context.search_metadata["reference_time"] == ref_time.isoformat()

    def test_relevance_filter_applied(self):
        """Chunks below min_relevance_score are filtered out."""
        with patch.dict(
            os.environ,
            _make_config_env(RAG_MIN_RELEVANCE_SCORE="0.5"),
            clear=False,
        ):
            config = RAGConfig()

        chunks = [
            _make_chunk(document_id="above", relevance_score=0.8),
            _make_chunk(document_id="below", relevance_score=0.2),
        ]

        pipeline = self._make_pipeline_with_mock_search(chunks)
        pipeline._config = config

        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
        context = pipeline.retrieve_context("test", reference_time=ref_time)

        chunk_ids = [c.document_id for c in context.chunks]
        assert "above" in chunk_ids
        assert "below" not in chunk_ids


# =============================================================================
# Isolation Guarantee Tests
# =============================================================================


class TestIsolationGuarantees:
    """Tests confirming the RAG pipeline does not touch forbidden services."""

    def test_no_llm_imports_in_pipeline(self):
        """Pipeline module does not import LLM client."""
        import src.enrichment.rag.pipeline as pipeline_mod
        source = open(pipeline_mod.__file__).read()
        assert "llm_client" not in source
        assert "AzureOpenAI" not in source
        assert "openai" not in source

    def test_no_purview_imports_in_pipeline(self):
        """Pipeline module does not import Purview client."""
        import src.enrichment.rag.pipeline as pipeline_mod
        source = open(pipeline_mod.__file__).read()
        assert "purview_client" not in source
        assert "PurviewClient" not in source

    def test_no_orchestrator_imports_in_package(self):
        """RAG package does not import anything from orchestrator."""
        import src.enrichment.rag as rag_pkg
        import pkgutil
        import importlib

        rag_modules = [
            importlib.import_module(f"src.enrichment.rag.{name}")
            for _, name, _ in pkgutil.iter_modules(rag_pkg.__path__)
        ]
        for mod in rag_modules:
            source = open(mod.__file__).read()
            assert "from src.orchestrator" not in source, (
                f"Module {mod.__name__} imports from orchestrator"
            )
            assert "import src.orchestrator" not in source, (
                f"Module {mod.__name__} imports from orchestrator"
            )

    def test_no_domain_imports_in_package(self):
        """RAG package does not import anything from domain."""
        import src.enrichment.rag as rag_pkg
        import pkgutil
        import importlib

        rag_modules = [
            importlib.import_module(f"src.enrichment.rag.{name}")
            for _, name, _ in pkgutil.iter_modules(rag_pkg.__path__)
        ]
        for mod in rag_modules:
            source = open(mod.__file__).read()
            assert "from src.domain" not in source, (
                f"Module {mod.__name__} imports from domain"
            )
            assert "import src.domain" not in source, (
                f"Module {mod.__name__} imports from domain"
            )

    def test_ranking_is_pure_function(self):
        """Ranking module has no I/O operations."""
        import src.enrichment.rag.ranking as ranking_mod
        source = open(ranking_mod.__file__).read()
        assert "open(" not in source
        assert "requests" not in source
        assert "azure" not in source.lower() or "azure" not in source.split("import")[0] if "import" in source else True

    def test_context_assembly_is_pure_function(self):
        """Context assembly module has no I/O operations."""
        import src.enrichment.rag.context_assembly as assembly_mod
        source = open(assembly_mod.__file__).read()
        assert "open(" not in source
        assert "requests" not in source


# =============================================================================
# RAGSearchError Classification Tests
# =============================================================================


class TestRAGSearchError:
    """Tests for error classification and retryability."""

    def test_transient_error_is_retryable(self):
        """TRANSIENT errors are marked retryable."""
        err = RAGSearchError("timeout", RAGErrorCategory.TRANSIENT)
        assert err.is_retryable is True
        assert err.category == RAGErrorCategory.TRANSIENT

    def test_auth_error_is_not_retryable(self):
        """AUTH errors are not retryable."""
        err = RAGSearchError("403", RAGErrorCategory.AUTH)
        assert err.is_retryable is False

    def test_configuration_error_is_not_retryable(self):
        """CONFIGURATION errors are not retryable."""
        err = RAGSearchError("404", RAGErrorCategory.CONFIGURATION)
        assert err.is_retryable is False

    def test_unknown_error_is_not_retryable(self):
        """UNKNOWN errors are not retryable."""
        err = RAGSearchError("unexpected", RAGErrorCategory.UNKNOWN)
        assert err.is_retryable is False

    def test_original_error_preserved(self):
        """Original exception is attached to the error."""
        original = ValueError("boom")
        err = RAGSearchError("wrapped", RAGErrorCategory.UNKNOWN, original_error=original)
        assert err.original_error is original

    def test_correlation_id_preserved(self):
        """Correlation ID is attached to the error."""
        err = RAGSearchError(
            "fail", RAGErrorCategory.TRANSIENT, correlation_id="corr-123"
        )
        assert err.correlation_id == "corr-123"

    def test_http_401_classified_as_auth(self):
        """HTTP 401 from Azure SDK is classified as AUTH."""
        from src.enrichment.rag.search_client import _classify_http_error

        mock_exc = MagicMock()
        mock_exc.status_code = 401
        mock_exc.__str__ = lambda s: "Unauthorized"
        result = _classify_http_error(mock_exc, correlation_id="c1")
        assert result.category == RAGErrorCategory.AUTH
        assert result.correlation_id == "c1"

    def test_http_403_classified_as_auth(self):
        """HTTP 403 from Azure SDK is classified as AUTH."""
        from src.enrichment.rag.search_client import _classify_http_error

        mock_exc = MagicMock()
        mock_exc.status_code = 403
        result = _classify_http_error(mock_exc)
        assert result.category == RAGErrorCategory.AUTH

    def test_http_404_classified_as_configuration(self):
        """HTTP 404 from Azure SDK is classified as CONFIGURATION."""
        from src.enrichment.rag.search_client import _classify_http_error

        mock_exc = MagicMock()
        mock_exc.status_code = 404
        result = _classify_http_error(mock_exc)
        assert result.category == RAGErrorCategory.CONFIGURATION

    def test_http_429_classified_as_transient(self):
        """HTTP 429 from Azure SDK is classified as TRANSIENT."""
        from src.enrichment.rag.search_client import _classify_http_error

        mock_exc = MagicMock()
        mock_exc.status_code = 429
        result = _classify_http_error(mock_exc)
        assert result.category == RAGErrorCategory.TRANSIENT
        assert result.is_retryable is True

    def test_http_503_classified_as_transient(self):
        """HTTP 503 from Azure SDK is classified as TRANSIENT."""
        from src.enrichment.rag.search_client import _classify_http_error

        mock_exc = MagicMock()
        mock_exc.status_code = 503
        result = _classify_http_error(mock_exc)
        assert result.category == RAGErrorCategory.TRANSIENT

    def test_http_418_classified_as_unknown(self):
        """Unexpected HTTP status codes are classified as UNKNOWN."""
        from src.enrichment.rag.search_client import _classify_http_error

        mock_exc = MagicMock()
        mock_exc.status_code = 418
        result = _classify_http_error(mock_exc)
        assert result.category == RAGErrorCategory.UNKNOWN


# =============================================================================
# Correlation ID Propagation Tests
# =============================================================================


class TestCorrelationIdPropagation:
    """Tests for cross-service observability via correlation_id."""

    def _make_pipeline_with_mock(self, mock_results=None):
        """Create a pipeline with mocked search for correlation tests."""
        from src.enrichment.rag.pipeline import RAGQueryPipeline

        with patch.dict(os.environ, _make_config_env(), clear=False):
            config = RAGConfig()

        mock_search_client = MagicMock()
        mock_search_client.search.return_value = mock_results or []

        pipeline = RAGQueryPipeline.__new__(RAGQueryPipeline)
        pipeline._config = config
        pipeline._search_client = mock_search_client
        return pipeline, mock_search_client

    def test_correlation_id_in_search_metadata(self):
        """correlation_id appears in search_metadata when provided."""
        pipeline, _ = self._make_pipeline_with_mock([_make_chunk()])
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)

        context = pipeline.retrieve_context(
            query="test",
            correlation_id="corr-abc-123",
            reference_time=ref_time,
        )
        assert context.search_metadata["correlation_id"] == "corr-abc-123"

    def test_correlation_id_absent_when_not_provided(self):
        """correlation_id is absent from search_metadata when not provided."""
        pipeline, _ = self._make_pipeline_with_mock([_make_chunk()])
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)

        context = pipeline.retrieve_context("test", reference_time=ref_time)
        assert "correlation_id" not in context.search_metadata

    def test_correlation_id_passed_to_search_client(self):
        """correlation_id is forwarded to the search client."""
        pipeline, mock_client = self._make_pipeline_with_mock()

        pipeline.retrieve_context(
            query="test", correlation_id="corr-xyz"
        )
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["correlation_id"] == "corr-xyz"


# =============================================================================
# Convenience Method — retrieve_context_for_asset Tests
# =============================================================================


class TestRetrieveContextForAsset:
    """Tests for the asset-level convenience method."""

    def _make_pipeline_with_mock(self, mock_results=None):
        from src.enrichment.rag.pipeline import RAGQueryPipeline

        with patch.dict(os.environ, _make_config_env(), clear=False):
            config = RAGConfig()

        mock_search_client = MagicMock()
        mock_search_client.search.return_value = mock_results or []

        pipeline = RAGQueryPipeline.__new__(RAGQueryPipeline)
        pipeline._config = config
        pipeline._search_client = mock_search_client
        return pipeline, mock_search_client

    def test_uses_entity_name_as_query(self):
        """entity_name is used as the search query text."""
        pipeline, mock_client = self._make_pipeline_with_mock()

        pipeline.retrieve_context_for_asset(
            asset_id="synergy.stu_enrollment.table",
            entity_type="table",
            source_system="synergy",
            element_name="Student Enrollment",
        )
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["query"] == "Student Enrollment"

    def test_applies_entity_type_and_source_filters(self):
        """entity_type and source_system become OData filters."""
        pipeline, mock_client = self._make_pipeline_with_mock()

        pipeline.retrieve_context_for_asset(
            asset_id="id1",
            entity_type="column",
            source_system="zipline",
            element_name="GPA Score",
        )
        call_kwargs = mock_client.search.call_args.kwargs
        filters = call_kwargs["filters"]
        assert "elementType eq 'column'" in filters
        assert "sourceSystem eq 'zipline'" in filters

    def test_asset_id_in_search_metadata(self):
        """asset_id appears in search_metadata for traceability."""
        pipeline, _ = self._make_pipeline_with_mock([_make_chunk()])
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)

        context = pipeline.retrieve_context_for_asset(
            asset_id="synergy.stu_enrollment.table",
            entity_type="table",
            source_system="synergy",
            element_name="Student Enrollment",
            reference_time=ref_time,
        )
        assert context.search_metadata["asset_id"] == "synergy.stu_enrollment.table"

    def test_correlation_id_propagated(self):
        """correlation_id flows through the convenience method."""
        pipeline, _ = self._make_pipeline_with_mock([_make_chunk()])
        ref_time = datetime(2026, 1, 15, tzinfo=timezone.utc)

        context = pipeline.retrieve_context_for_asset(
            asset_id="id1",
            entity_type="table",
            source_system="synergy",
            element_name="Test",
            correlation_id="corr-999",
            reference_time=ref_time,
        )
        assert context.search_metadata["correlation_id"] == "corr-999"
        assert context.search_metadata["asset_id"] == "id1"

    def test_no_search_knowledge_required(self):
        """Caller does not need to know about OData, index fields, or query syntax."""
        pipeline, mock_client = self._make_pipeline_with_mock()

        # The caller uses only asset-level properties — no Search details
        pipeline.retrieve_context_for_asset(
            asset_id="zipline.dataset.gpa.table",
            entity_type="table",
            source_system="zipline",
            element_name="GPA Dataset",
        )
        # Verify the pipeline translated these into proper search parameters
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["query"] == "GPA Dataset"
        filters = call_kwargs["filters"]
        assert "elementType eq 'table'" in filters
        assert "sourceSystem eq 'zipline'" in filters

    def test_empty_results_returns_valid_context(self):
        """Empty search results produce a valid, inspectable context."""
        pipeline, _ = self._make_pipeline_with_mock([])

        context = pipeline.retrieve_context_for_asset(
            asset_id="id1",
            entity_type="table",
            source_system="synergy",
            element_name="Nonexistent",
        )
        assert context.has_context is False
        assert context.results_used == 0
        assert context.formatted_context == ""
