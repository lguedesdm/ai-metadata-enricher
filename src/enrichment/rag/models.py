"""
Data models for the RAG Query Pipeline.

Defines immutable, structured representations for search results and
assembled context. These models are designed to be compatible with
the frozen prompt contracts (v1-metadata-enrichment.prompt.yaml and
v1-suggested-description.prompt.md).

No I/O, no side effects, no external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class ContextChunk:
    """A single context chunk retrieved from Azure AI Search.

    Represents one search result with its metadata, relevance score,
    and deterministic ranking factors.

    Attributes:
        document_id: Unique identifier from the search index (``id`` field).
        source_system: Source system identifier (synergy, zipline, documentation).
        element_type: Type of element (table, column, dataset, element).
        element_name: Human-readable element name.
        source: Source dataset or schema name.
        title: Display title for the element.
        content: Consolidated text for RAG context (primary search field).
        description: Technical description from source system.
        suggested_description: Business-oriented suggested description.
        tags: Categorization tags.
        ceds_link: CEDS reference link, if applicable.
        last_updated: Timestamp of last update in source system.
        relevance_score: Search relevance score (from Azure AI Search).
        reranker_score: Semantic reranker score (from Azure AI Search), if available.
        composite_score: Deterministic composite score after ranking.
    """

    document_id: str
    source_system: str
    element_type: str
    element_name: str
    source: str = ""
    title: str = ""
    content: str = ""
    description: str = ""
    suggested_description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    ceds_link: Optional[str] = None
    last_updated: Optional[datetime] = None
    relevance_score: float = 0.0
    reranker_score: Optional[float] = None
    composite_score: float = 0.0


@dataclass(frozen=True)
class RetrievedContext:
    """Structured context assembled from Azure AI Search results.

    This is the output of the RAG Query Pipeline and is designed to be
    directly compatible with the frozen prompt template placeholders:
    - ``{{retrieved_context}}`` receives ``formatted_context``
    - ``{{asset_metadata}}`` is supplied by the caller

    Attributes:
        query: The original query string used for retrieval.
        chunks: Ordered list of context chunks, ranked deterministically.
        formatted_context: Pre-formatted string ready for prompt injection,
            compatible with the frozen prompt contract.
        total_results_found: Total number of results returned by search
            before filtering and truncation.
        results_used: Number of results actually included in the context.
        search_metadata: Additional metadata about the search operation
            (e.g., search type, configuration used).
    """

    query: str
    chunks: tuple[ContextChunk, ...]
    formatted_context: str
    total_results_found: int
    results_used: int
    search_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_context(self) -> bool:
        """Whether any context was retrieved."""
        return len(self.chunks) > 0

    @property
    def source_systems_used(self) -> tuple[str, ...]:
        """Deduplicated, sorted list of source systems in the context."""
        return tuple(sorted(set(c.source_system for c in self.chunks)))
