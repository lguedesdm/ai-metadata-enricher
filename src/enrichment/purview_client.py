"""
Microsoft Purview Client — Managed Identity Authentication Only.

Provides a minimal, isolated client for writing the "Suggested Description"
attribute to Microsoft Purview entities via the Atlas REST API.

Authentication uses DefaultAzureCredential (Managed Identity) to acquire
an Entra ID token scoped to the Purview data plane.

Security guarantees:
- NO API keys, secrets, or connection strings
- Authentication is exclusively via Entra ID (AAD) tokens
- Requires "Purview Data Curator" RBAC on the Purview account

This module does NOT:
- Know about orchestration, message handling, or domain logic
- Perform lifecycle management (approve/reject)
- Perform retries, batching, or optimization
- Trigger enrichment automatically
- Process assets end-to-end

Usage (manual / validation only):
    from src.enrichment.config import EnrichmentConfig
    from src.enrichment.purview_client import PurviewClient

    config = EnrichmentConfig()
    client = PurviewClient(config)
    client.write_suggested_description(
        entity_guid="12345-abcde-...",
        description="AI-generated description of the asset."
    )
"""

import logging
from typing import Any, Dict

import requests
from azure.identity import DefaultAzureCredential

from .config import EnrichmentConfig

logger = logging.getLogger("enrichment.purview_client")

# Purview data-plane scope for Entra ID token acquisition
_PURVIEW_SCOPE = "https://purview.azure.net/.default"


class PurviewClient:
    """
    Minimal Purview client for writing Suggested Description.

    Uses the Atlas REST API (Entity partial update) with Managed Identity.
    No lifecycle logic, no retries, no orchestration awareness.

    Lifecycle:
        client = PurviewClient(config)
        client.write_suggested_description(guid, description)
        client.close()
    """

    def __init__(self, config: EnrichmentConfig) -> None:
        config.validate_purview()

        self._account_name: str = config.purview_account_name
        self._base_url: str = (
            f"https://{config.purview_account_name}.purview.azure.com"
        )

        logger.info(
            "Initializing Purview client with Managed Identity",
            extra={
                "purviewAccount": config.purview_account_name,
                "baseUrl": self._base_url,
                "authMethod": "ManagedIdentity/DefaultAzureCredential",
            },
        )

        self._credential = DefaultAzureCredential()
        self._session = requests.Session()

    def _get_auth_headers(self) -> Dict[str, str]:
        """Acquire a fresh Entra ID token and return authorization headers."""
        token = self._credential.get_token(_PURVIEW_SCOPE)
        return {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
        }

    def write_suggested_description(
        self, entity_guid: str, description: str
    ) -> Dict[str, Any]:
        """
        Write the userDescription (Suggested Description) attribute on a
        Purview entity using the Atlas Entity CreateOrUpdate API.

        This performs a PUT to:
            /catalog/api/atlas/v2/entity

        The payload contains ONLY the entity GUID and the single attribute
        being updated (userDescription). The Atlas API performs a partial
        update — only attributes present in the payload are modified.
        No other attributes are affected.

        Args:
            entity_guid: The GUID of the Purview entity to update.
            description: The suggested description text to write.

        Returns:
            The JSON response from the Purview API.

        Raises:
            requests.HTTPError: If the API call fails.
        """
        url = f"{self._base_url}/catalog/api/atlas/v2/entity"

        # Atlas CreateOrUpdate with minimal body — only userDescription is set.
        # The API performs a partial update; attributes NOT in the payload
        # are left untouched. This guarantees no accidental overwrites.
        payload: Dict[str, Any] = {
            "entity": {
                "guid": entity_guid,
                "attributes": {
                    "userDescription": description,
                },
            },
        }

        logger.info(
            "Writing Suggested Description to Purview",
            extra={
                "entityGuid": entity_guid,
                "descriptionLength": len(description),
                "purviewAccount": self._account_name,
            },
        )

        headers = self._get_auth_headers()
        response = self._session.put(url, json=payload, headers=headers)
        response.raise_for_status()

        result = response.json()

        logger.info(
            "Suggested Description written successfully",
            extra={
                "entityGuid": entity_guid,
                "purviewAccount": self._account_name,
            },
        )

        return result

    def get_entity(self, entity_guid: str) -> Dict[str, Any]:
        """
        Retrieve a Purview entity by GUID (read-only, for validation).

        Args:
            entity_guid: The GUID of the Purview entity.

        Returns:
            The entity JSON from the Purview API.

        Raises:
            requests.HTTPError: If the API call fails.
        """
        url = f"{self._base_url}/catalog/api/atlas/v2/entity/guid/{entity_guid}"

        logger.info(
            "Reading entity from Purview",
            extra={
                "entityGuid": entity_guid,
                "purviewAccount": self._account_name,
            },
        )

        headers = self._get_auth_headers()
        response = self._session.get(url, headers=headers)
        response.raise_for_status()

        return response.json()

    def close(self) -> None:
        """Release underlying HTTP resources."""
        self._session.close()
        logger.info("Purview client closed")
