"""
Azure AI Search client adapter for the RAG Query Pipeline.

Provides a minimal wrapper around the Azure AI Search SDK for executing
hybrid search queries (keyword + semantic ranking) using Managed Identity.

This module does NOT:
- Create or modify search indexes
- Generate embeddings
- Invoke any LLM
- Write data to any service

Authentication: DefaultAzureCredential (Managed Identity) exclusively.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from azure.core.credentials import TokenCredential
from azure.core.exceptions import (
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import QueryType

from .config import RAGConfig
from .errors import RAGErrorCategory, RAGSearchError
from .models import ContextChunk

logger = logging.getLogger("enrichment.rag.search_client")

# Fields to retrieve from the Azure AI Search index.
# Aligned with deployed index metadata-context-index-v1 (13 fields).
_RETRIEVABLE_FIELDS: list[str] = [
    "id",
    "sourceSystem",
    "source",
    "elementType",
    "elementName",
    "title",
    "description",
    "suggestedDescription",
    "content",
    "tags",
    "cedsLink",
    "lastUpdated",
]


class AISearchClient:
    """Minimal Azure AI Search client for hybrid search queries.

    Executes keyword + semantic ranking queries against the frozen
    search index (v1.0.0). Does not modify the index or generate
    embeddings.

    Lifecycle:
        client = AISearchClient(config)
        chunks = client.search("student enrollment")
        client.close()
    """

    def __init__(
        self,
        config: RAGConfig,
        credential: TokenCredential | None = None,
    ) -> None:
        """Initialize the search client.

        Args:
            config: RAG pipeline configuration.
            credential: Optional credential for testing. Defaults to
                DefaultAzureCredential (Managed Identity).
        """
        config.validate()

        self._config = config
        self._credential = credential or DefaultAzureCredential()

        logger.info(
            "Initializing Azure AI Search client with Managed Identity",
            extra={
                "endpoint": config.search_endpoint,
                "indexName": config.search_index_name,
                "semanticConfig": config.semantic_configuration_name,
                "authMethod": "ManagedIdentity/DefaultAzureCredential",
            },
        )

        self._client = SearchClient(
            endpoint=config.search_endpoint,
            index_name=config.search_index_name,
            credential=self._credential,
        )

    def search(
        self,
        query: str,
        filters: str | None = None,
        top: int | None = None,
    ) -> list[ContextChunk]:
        """Execute a hybrid search query (keyword + semantic ranking).

        Performs a search using Azure AI Search with:
        - Full-text keyword search on searchable fields
        - Semantic ranking (L2 reranking) using the configured semantic profile

        The search does NOT use vector queries because this pipeline
        does not generate embeddings. Vector search is available in the
        index but requires an embedding to be supplied, which is a
        responsibility of a future indexing pipeline.

        Args:
            query: The search query text.
            filters: Optional OData filter expression for pre-filtering
                (e.g., ``"sourceSystem eq 'synergy'"``).
            top: Maximum number of results to return. Defaults to
                config.max_results.

        Returns:
            List of ContextChunk objects with relevance and reranker scores.
        """
        effective_top = top or self._config.max_results

        logger.info(
            "Executing hybrid search",
            extra={
                "query": query,
                "top": effective_top,
                "filter": filters,
                "semanticConfig": self._config.semantic_configuration_name,
            },
        )

        results = self._client.search(
            search_text=query,
            query_type=QueryType.SEMANTIC,
            semantic_configuration_name=self._config.semantic_configuration_name,
            select=_RETRIEVABLE_FIELDS,
            filter=filters,
            top=effective_top,
            include_total_count=True,
        )

        chunks: list[ContextChunk] = []
        total_count: int = 0

        for result in results:
            if total_count == 0:
                # Capture total count from the first iteration
                total_count = getattr(results, "get_count", lambda: 0)()

            chunk = _map_result_to_chunk(result)
            if chunk is not None:
                chunks.append(chunk)

        logger.info(
            "Search completed: %d results retrieved",
            len(chunks),
            extra={
                "query": query,
                "resultsRetrieved": len(chunks),
                "totalCount": total_count,
            },
        )

        return chunks

    def get_total_count(self, query: str, filters: str | None = None) -> int:
        """Get the total count of matching documents without retrieving them.

        Useful for diagnostic purposes.

        Args:
            query: The search query text.
            filters: Optional OData filter expression.

        Returns:
            Total count of matching documents.
        """
        results = self._client.search(
            search_text=query,
            filter=filters,
            top=0,
            include_total_count=True,
        )
        # Force iteration to populate count
        for _ in results:
            break
        return getattr(results, "get_count", lambda: 0)()

    def close(self) -> None:
        """Release underlying HTTP resources."""
        self._client.close()
        logger.info("Azure AI Search client closed")


def _map_result_to_chunk(result: dict[str, Any]) -> ContextChunk | None:
    """Map a raw Azure AI Search result to a ContextChunk.

    Returns None if the result lacks required fields.

    Args:
        result: Raw search result dictionary from the SDK.

    Returns:
        ContextChunk or None if the result is invalid.
    """
    # Required fields — skip result if missing
    document_id = result.get("id")
    source_system = result.get("sourceSystem", "")
    element_type = result.get("elementType", "")
    element_name = result.get("elementName", "")

    if not document_id or not element_name:
        logger.warning(
            "Skipping search result with missing required fields",
            extra={"result_keys": list(result.keys())},
        )
        return None

    # Parse lastUpdated timestamp
    last_updated = _parse_datetime(result.get("lastUpdated"))

    # Extract search scores
    relevance_score = result.get("@search.score", 0.0) or 0.0
    reranker_score = result.get("@search.reranker_score")

    # Tags: ensure tuple for immutability
    tags_raw = result.get("tags") or []
    tags = tuple(tags_raw) if isinstance(tags_raw, list) else ()

    return ContextChunk(
        document_id=document_id,
        source_system=source_system,
        element_type=element_type,
        element_name=element_name,
        source=result.get("source", "") or "",
        title=result.get("title", "") or "",
        content=result.get("content", "") or "",
        description=result.get("description", "") or "",
        suggested_description=result.get("suggestedDescription", "") or "",
        tags=tags,
        ceds_link=result.get("cedsLink"),
        last_updated=last_updated,
        relevance_score=float(relevance_score),
        reranker_score=float(reranker_score) if reranker_score is not None else None,
    )


def _classify_http_error(
    exc: HttpResponseError,
    correlation_id: str | None = None,
) -> RAGSearchError:
    """Map an Azure SDK HttpResponseError to a classified RAGSearchError."""
    status = exc.status_code or 0

    if status in (401, 403):
        return RAGSearchError(
            f"Authentication/authorization error (HTTP {status}): {exc}",
            RAGErrorCategory.AUTH,
            original_error=exc,
            correlation_id=correlation_id,
        )
    if status == 404:
        return RAGSearchError(
            f"Resource not found (HTTP 404): {exc}",
            RAGErrorCategory.CONFIGURATION,
            original_error=exc,
            correlation_id=correlation_id,
        )
    if status in (429, 500, 502, 503, 504):
        return RAGSearchError(
            f"Transient Azure AI Search error (HTTP {status}): {exc}",
            RAGErrorCategory.TRANSIENT,
            original_error=exc,
            correlation_id=correlation_id,
        )
    return RAGSearchError(
        f"Azure AI Search error (HTTP {status}): {exc}",
        RAGErrorCategory.UNKNOWN,
        original_error=exc,
        correlation_id=correlation_id,
    )


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a datetime value from search results.

    Handles ISO 8601 strings and datetime objects.
    Returns None if parsing fails.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # Handle ISO 8601 with timezone
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.warning(
                "Failed to parse lastUpdated: %s", value
            )
            return None
    return None
