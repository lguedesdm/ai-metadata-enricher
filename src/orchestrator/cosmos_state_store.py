"""
Cosmos DB State Store — Managed Identity Authentication Only.

Provides read/write access to the Cosmos DB state and audit containers
using Azure Managed Identity via DefaultAzureCredential.

Security guarantees:
- NO connection strings, keys, or secrets
- Authentication is exclusively via Entra ID (AAD) tokens
- Requires Cosmos DB Built-in Data Contributor RBAC at database scope

This module does NOT:
- Create or delete databases or containers
- Modify throughput, TTL, or indexing policies
- Manage network configuration
- Use Key Vault or any secret store
"""

import logging
from typing import Any, Dict, Optional

from azure.cosmos import CosmosClient, ContainerProxy, DatabaseProxy
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential

from .config import OrchestratorConfig

logger = logging.getLogger("orchestrator.cosmos_state_store")


class CosmosStateStore:
    """
    Cosmos DB state store using Managed Identity authentication.

    Provides CRUD operations for the state and audit containers.
    All operations use DefaultAzureCredential — no keys or secrets.

    Lifecycle:
        store = CosmosStateStore(config)
        store.get_state(asset_id, entity_type)
        store.upsert_state(item)
        store.upsert_audit(item)
        store.close()
    """

    def __init__(self, config: OrchestratorConfig) -> None:
        if not config.cosmos_endpoint:
            raise ValueError(
                "COSMOS_ENDPOINT environment variable is required. "
                "Cosmos DB access requires a valid endpoint URL."
            )

        self._credential = DefaultAzureCredential()

        logger.info(
            "Initializing Cosmos DB state store with Managed Identity",
            extra={
                "cosmosEndpoint": config.cosmos_endpoint,
                "cosmosDatabase": config.cosmos_database_name,
                "stateContainer": config.cosmos_state_container,
                "auditContainer": config.cosmos_audit_container,
                "authMethod": "ManagedIdentity/DefaultAzureCredential",
            },
        )

        self._client: CosmosClient = CosmosClient(
            url=config.cosmos_endpoint,
            credential=self._credential,
        )

        self._database: DatabaseProxy = self._client.get_database_client(
            config.cosmos_database_name
        )

        self._state_container: ContainerProxy = self._database.get_container_client(
            config.cosmos_state_container
        )

        self._audit_container: ContainerProxy = self._database.get_container_client(
            config.cosmos_audit_container
        )

        logger.info(
            "Cosmos DB state store initialized — authentication: Managed Identity",
            extra={
                "authMethod": "ManagedIdentity/DefaultAzureCredential",
            },
        )

    # ------------------------------------------------------------------
    # State Container Operations
    # ------------------------------------------------------------------

    def get_state(
        self, asset_id: str, entity_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Read an item from the state container.

        Args:
            asset_id:    The document id.
            entity_type: Partition key value (/entityType).

        Returns:
            The item dict if found, None if not found.
        """
        try:
            item = self._state_container.read_item(
                item=asset_id,
                partition_key=entity_type,
            )
            logger.debug(
                "State item read successfully",
                extra={
                    "assetId": asset_id,
                    "entityType": entity_type,
                    "authMethod": "ManagedIdentity",
                },
            )
            return item
        except CosmosResourceNotFoundError:
            logger.debug(
                "State item not found (expected for new assets)",
                extra={
                    "assetId": asset_id,
                    "entityType": entity_type,
                },
            )
            return None

    def upsert_state(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create or update an item in the state container.

        The item must include 'id' and 'entityType' (partition key).

        Args:
            item: Document to upsert.

        Returns:
            The upserted item (with system properties).
        """
        result = self._state_container.upsert_item(body=item)
        logger.info(
            "State item upserted",
            extra={
                "assetId": item.get("id"),
                "entityType": item.get("entityType"),
                "authMethod": "ManagedIdentity",
            },
        )
        return result

    # ------------------------------------------------------------------
    # Audit Container Operations
    # ------------------------------------------------------------------

    def upsert_audit(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create or update an item in the audit container.

        The item must include 'id' and 'entityType' (partition key).

        Args:
            item: Document to upsert.

        Returns:
            The upserted item (with system properties).
        """
        result = self._audit_container.upsert_item(body=item)
        logger.info(
            "Audit item upserted",
            extra={
                "assetId": item.get("id"),
                "entityType": item.get("entityType"),
                "authMethod": "ManagedIdentity",
            },
        )
        return result

    # ------------------------------------------------------------------
    # Container Accessors (infrastructure layer — for enrichment layer use)
    # ------------------------------------------------------------------

    @property
    def state_container(self) -> ContainerProxy:
        """The Cosmos DB container proxy for state records.

        Exposed as a public property so the enrichment layer can construct
        its own LifecycleStore without crossing the dependency boundary.
        The enrichment layer must NOT import from the orchestrator layer;
        it receives this infrastructure-layer object directly.
        """
        return self._state_container

    @property
    def audit_container(self) -> ContainerProxy:
        """The Cosmos DB container proxy for audit records.

        Exposed as a public property so the enrichment layer can construct
        its own LifecycleStore without crossing the dependency boundary.
        """
        return self._audit_container

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the Cosmos DB client and credential."""
        try:
            self._client.close()
            self._credential.close()
            logger.info("Cosmos DB state store closed")
        except Exception as exc:
            logger.warning("Error closing Cosmos DB state store: %s", exc)
