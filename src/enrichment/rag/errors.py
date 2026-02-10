"""
Classified error types for the RAG Query Pipeline.

Provides structured error categories so that consumers (e.g. the enrichment
flow) can make informed decisions: retry, abort, or fallback — without
inspecting raw Azure SDK exceptions.

No I/O, no side effects, no external dependencies.
"""

from __future__ import annotations

from enum import Enum


class RAGErrorCategory(str, Enum):
    """Classification of RAG pipeline errors for consumer decision-making.

    Consumers should use ``is_retryable`` on ``RAGSearchError`` rather than
    inspecting the category directly, unless fine-grained control is needed.

    Values:
        TRANSIENT: Retryable — 429 throttling, 5xx server errors, network
            timeouts.  Consumer should back off and retry.
        AUTH: Credential or RBAC misconfiguration — 401 / 403.  Retrying
            without fixing the identity setup will not help.
        CONFIGURATION: Wrong index name, endpoint, or semantic configuration
            — 404 or similar.  Deployment / config correction required.
        UNKNOWN: Unexpected error that does not fit the other categories.
            Do not retry blindly.
    """

    TRANSIENT = "transient"
    AUTH = "auth"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class RAGSearchError(Exception):
    """Classified error raised by the RAG Query Pipeline.

    Wraps the underlying Azure SDK or infrastructure exception and
    attaches a ``category`` that allows the consumer to decide between
    retry, abort, or fallback without coupling to Azure SDK internals.

    Attributes:
        category: The classified error category.
        original_error: The original exception, if available.
        correlation_id: The correlation ID of the request that triggered
            the error, if available.

    Usage::

        try:
            context = pipeline.retrieve_context(query="enrollment")
        except RAGSearchError as err:
            if err.is_retryable:
                schedule_retry(...)
            elif err.category == RAGErrorCategory.AUTH:
                alert_on_call(...)
            else:
                abort_enrichment(...)
    """

    def __init__(
        self,
        message: str,
        category: RAGErrorCategory,
        original_error: Exception | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.original_error = original_error
        self.correlation_id = correlation_id

    @property
    def is_retryable(self) -> bool:
        """Whether the consumer should retry the operation."""
        return self.category == RAGErrorCategory.TRANSIENT
