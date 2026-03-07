"""
RAG Query Pipeline — Main pipeline for context retrieval.

Provides a single entry point for retrieving and assembling context
from Azure AI Search for use in the metadata enrichment prompt.

This module coordinates:
1. Search execution (via AISearchClient)
2. Deterministic ranking (via ranking module)
3. Context assembly (via context_assembly module)

The pipeline is stateless, importable, testable, and inert.
It does NOT invoke any LLM, write to Purview, or trigger enrichment.

Usage:
    from src.enrichment.rag import RAGQueryPipeline, RAGConfig

    config = RAGConfig()
    pipeline = RAGQueryPipeline(config)
    context = pipeline.retrieve_context(
        query="student enrollment",
        entity_type="table",
        source_system="synergy",
    )
    print(context.formatted_context)
    pipeline.close()
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from azure.core.credentials import TokenCredential

from .config import RAGConfig
from .context_assembly import assemble_context
from .models import ContextChunk, RetrievedContext
from .ranking import compute_composite_scores
from .search_client import AISearchClient

logger = logging.getLogger("enrichment.rag.pipeline")


class RAGQueryPipeline:
    """Isolated RAG context retrieval pipeline.

    Retrieves context from Azure AI Search using hybrid search
    (keyword + semantic ranking), applies deterministic composite
    ranking, and assembles structured context compatible with the
    frozen prompt contracts.

    The pipeline is:
    - **Isolated**: No dependency on Orchestrator, Domain, or Validation
    - **Deterministic**: Same inputs → same ranked context output
    - **Inert**: Does not invoke LLM, write to Purview, or trigger enrichment
    - **Importable**: Can be used standalone or integrated by future callers
    - **Testable**: Accepts injectable credential and fixed reference time

    Lifecycle:
        pipeline = RAGQueryPipeline(config)
        context = pipeline.retrieve_context("query text")
        pipeline.close()
    """

    def __init__(
        self,
        config: RAGConfig,
        credential: TokenCredential | None = None,
    ) -> None:
        """Initialize the RAG Query Pipeline.

        Args:
            config: RAG pipeline configuration (from environment variables).
            credential: Optional credential override for testing.
                Defaults to DefaultAzureCredential (Managed Identity).
        """
        config.validate()
        self._config = config
        self._search_client = AISearchClient(config, credential=credential)

        logger.info(
            "RAG Query Pipeline initialized",
            extra={
                "endpoint": config.search_endpoint,
                "indexName": config.search_index_name,
                "maxResults": config.max_results,
                "freshnessWeight": config.freshness_weight,
                "sourceWeights": config.source_weights,
            },
        )

    def retrieve_context_for_asset(
        self,
        asset_id: str,
        entity_type: str,
        source_system: str,
        element_name: str,
        correlation_id: str | None = None,
        reference_time: datetime | None = None,
    ) -> RetrievedContext:
        """Retrieve context for a specific asset without Search knowledge.

        This is the recommended entry point for enrichment-flow callers.
        The caller provides only asset-level properties; the pipeline
        takes care of constructing the search query, building OData
        filters, and assembling prompt-ready context.

        The search query is derived from ``entity_name``.  The
        ``entity_type`` and ``source_system`` are applied as OData
        equality filters so that only matching index documents are
        returned.

        Args:
            asset_id: Unique asset identifier (for traceability in logs
                and ``search_metadata``, not sent as a search term).
            entity_type: Asset entity type (e.g. "table", "column").
            source_system: Asset source system (e.g. "synergy").
            element_name: Human-readable element name — used as the search
                query text.
            correlation_id: Optional correlation ID propagated into every
                log entry and into ``search_metadata`` for cross-service
                tracing with Orchestrator, LLM, and Purview.
            reference_time: Fixed reference time for deterministic
                freshness calculation (defaults to current UTC).

        Returns:
            RetrievedContext with formatted context and metadata.
            ``search_metadata`` includes the ``asset_id`` and
            ``correlation_id`` for end-to-end traceability.
        """
        context = self.retrieve_context(
            query=element_name,
            entity_type=entity_type,
            source_system=source_system,
            correlation_id=correlation_id,
            reference_time=reference_time,
        )

        # Attach asset_id to search_metadata for downstream traceability.
        # RetrievedContext is frozen, so we must build a new instance if
        # we want to add to the dict.  Because the dict itself is mutable
        # (only the dataclass fields are frozen), we can safely mutate it.
        context.search_metadata["asset_id"] = asset_id

        return context

    def retrieve_context(
        self,
        query: str,
        entity_type: str | None = None,
        source_system: str | None = None,
        additional_filters: str | None = None,
        correlation_id: str | None = None,
        reference_time: datetime | None = None,
    ) -> RetrievedContext:
        """Retrieve and assemble context for a metadata enrichment request.

        This is the primary entry point for the RAG Query Pipeline.
        It executes a complete context retrieval cycle:

        1. Build OData filter from optional parameters
        2. Execute hybrid search (keyword + semantic) via Azure AI Search
        3. Filter out results below minimum relevance threshold
        4. Compute deterministic composite scores (relevance × source weight × freshness)
        5. Assemble formatted context string for prompt injection

        The returned RetrievedContext contains:
        - ``formatted_context``: Ready for ``{{retrieved_context}}`` placeholder
        - ``chunks``: Ordered ContextChunk objects for inspection
        - ``search_metadata``: Diagnostic information

        Raises:
            RAGSearchError: Classified error when Azure AI Search is
                unavailable or misconfigured.  The ``category`` field
                tells the consumer whether to retry (TRANSIENT), fix
                credentials (AUTH), fix deployment config (CONFIGURATION),
                or abort (UNKNOWN).

        Args:
            query: Search query text (typically asset name or description).
            entity_type: Optional filter by elementType field
                (e.g., "table", "column", "dataset", "element").
            source_system: Optional filter by source system
                (e.g., "synergy", "zipline").
            additional_filters: Optional raw OData filter expression
                appended to auto-generated filters.
            correlation_id: Optional correlation ID propagated into every
                log entry and into ``search_metadata`` for cross-service
                tracing with Orchestrator, LLM, and Purview.
            reference_time: Fixed reference time for freshness calculation.
                Defaults to current UTC time. Pass a fixed value for
                deterministic testing.

        Returns:
            RetrievedContext with formatted context and metadata.
        """
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        # Step 1: Build filter
        odata_filter = _build_filter(
            entity_type=entity_type,
            source_system=source_system,
            additional_filters=additional_filters,
        )

        log_extra: dict[str, object] = {
            "query": query,
            "entityType": entity_type,
            "sourceSystem": source_system,
            "filter": odata_filter,
        }
        if correlation_id:
            log_extra["correlationId"] = correlation_id

        logger.info("Retrieving context", extra=log_extra)

        # Step 2: Execute search
        raw_chunks = self._search_client.search(
            query=query,
            filters=odata_filter,
        )

        total_found = len(raw_chunks)

        # Step 3: Filter by minimum relevance
        filtered_chunks = self._apply_relevance_filter(raw_chunks)

        # Step 4: Compute composite scores and rank
        ranked_chunks = compute_composite_scores(
            chunks=filtered_chunks,
            source_weights=self._config.source_weights,
            freshness_weight=self._config.freshness_weight,
            reference_time=reference_time,
        )

        # Step 5: Assemble context
        search_metadata: dict[str, Any] = {
            "search_type": "hybrid_semantic",
            "semantic_configuration": self._config.semantic_configuration_name,
            "max_results_requested": self._config.max_results,
            "min_relevance_score": self._config.min_relevance_score,
            "freshness_weight": self._config.freshness_weight,
            "source_weights": self._config.source_weights,
            "filter_applied": odata_filter,
            "reference_time": reference_time.isoformat(),
        }
        if correlation_id:
            search_metadata["correlation_id"] = correlation_id

        context = assemble_context(
            query=query,
            ranked_chunks=ranked_chunks,
            max_context_chars=self._config.max_context_chars,
            total_results_found=total_found,
            search_metadata=search_metadata,
        )

        complete_extra: dict[str, object] = {
            "query": query,
            "totalFound": total_found,
            "afterFiltering": len(filtered_chunks),
            "resultsUsed": context.results_used,
            "contextLength": len(context.formatted_context),
            "hasContext": context.has_context,
        }
        if correlation_id:
            complete_extra["correlationId"] = correlation_id

        logger.info("Context retrieval complete", extra=complete_extra)

        return context

    def _apply_relevance_filter(
        self, chunks: list[ContextChunk]
    ) -> list[ContextChunk]:
        """Filter chunks below the minimum relevance score threshold.

        Uses reranker_score if available, otherwise falls back to
        relevance_score.

        Args:
            chunks: Raw chunks from search.

        Returns:
            Filtered list of chunks above the threshold.
        """
        min_score = self._config.min_relevance_score
        if min_score <= 0.0:
            return chunks

        filtered = []
        for chunk in chunks:
            effective_score = chunk.reranker_score if chunk.reranker_score is not None else chunk.relevance_score
            if effective_score >= min_score:
                filtered.append(chunk)

        if len(filtered) < len(chunks):
            logger.info(
                "Relevance filter removed %d chunks below threshold %.3f",
                len(chunks) - len(filtered),
                min_score,
            )

        return filtered

    def close(self) -> None:
        """Release underlying HTTP resources."""
        self._search_client.close()
        logger.info("RAG Query Pipeline closed")


def _build_filter(
    entity_type: str | None = None,
    source_system: str | None = None,
    additional_filters: str | None = None,
) -> str | None:
    """Build an OData filter expression from optional parameters.

    Combines multiple filter conditions with 'and'. Returns None
    if no filters are specified.

    Args:
        entity_type: Filter by elementType field.
        source_system: Filter by sourceSystem field.
        additional_filters: Raw OData filter expression to append.

    Returns:
        OData filter string or None.
    """
    conditions: list[str] = []

    if entity_type:
        # OData string comparison — value must be quoted
        conditions.append(f"elementType eq '{entity_type}'")

    if source_system:
        conditions.append(f"sourceSystem eq '{source_system}'")

    if additional_filters:
        conditions.append(f"({additional_filters})")

    if not conditions:
        return None

    return " and ".join(conditions)
