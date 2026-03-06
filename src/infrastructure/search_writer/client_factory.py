"""
Azure AI Search client factory for the Search Upsert Writer.

Provides controlled creation of ``SearchClient`` instances using
Managed Identity authentication (``DefaultAzureCredential``).

Configuration is sourced exclusively from environment variables:

- ``SEARCH_ENDPOINT``  — Azure AI Search service URL.
- ``SEARCH_INDEX_NAME`` — Target index name (default ``metadata-index-v1``).

This module does NOT:

- Create, modify, or delete search indexes.
- Manage RBAC assignments or credentials.
- Cache or pool client instances.

Security: No connection strings, API keys, or secrets.
Authentication is exclusively via Entra ID tokens.
"""

from __future__ import annotations

import logging
import os

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

logger = logging.getLogger("infrastructure.search_writer.client_factory")


def create_search_client() -> SearchClient:
    """Create an Azure AI Search ``SearchClient`` via Managed Identity.

    Reads ``SEARCH_ENDPOINT`` and ``SEARCH_INDEX_NAME`` from environment
    variables.  Authenticates with ``DefaultAzureCredential``.

    Returns:
        A ``SearchClient`` connected to the target index.

    Raises:
        KeyError: If ``SEARCH_ENDPOINT`` is not set.
    """
    endpoint: str = os.environ["SEARCH_ENDPOINT"]
    index_name: str = os.environ.get("SEARCH_INDEX_NAME", "metadata-index-v1")

    credential = DefaultAzureCredential()

    logger.info(
        "Creating Azure AI Search client with Managed Identity",
        extra={
            "endpoint": endpoint,
            "indexName": index_name,
            "authMethod": "ManagedIdentity/DefaultAzureCredential",
        },
    )

    return SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=credential,
    )
