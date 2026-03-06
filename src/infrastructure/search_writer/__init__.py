"""
Search Upsert Writer module for AI Metadata Enricher.

Provides controlled, single-document upsert operations into Azure AI
Search using the ``mergeOrUpload`` SDK method.

Public API:
    - upsert_search_document(): Upsert one document into the search index.
    - create_search_client(): Factory for the Azure AI Search client.

``create_search_client`` is imported lazily so that the module can be
loaded in environments where the Azure SDK is not installed (e.g. for
unit-testing the writer in isolation).
"""

from .writer import upsert_search_document

__all__ = [
    "upsert_search_document",
    "create_search_client",
]


def __getattr__(name: str):  # noqa: N807
    if name == "create_search_client":
        from .client_factory import create_search_client  # noqa: F811

        return create_search_client
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
