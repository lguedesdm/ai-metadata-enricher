"""
Microsoft Purview Client — Managed Identity Authentication Only.

Provides a minimal, isolated client for writing the AI_Enrichment
Business Metadata attribute to Microsoft Purview entities via the Atlas REST API.

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
from datetime import datetime, timezone
from typing import Any, Dict

import requests
from azure.identity import DefaultAzureCredential

from .config import EnrichmentConfig

logger = logging.getLogger("enrichment.purview_client")

# Purview data-plane scope for Entra ID token acquisition
_PURVIEW_SCOPE = "https://purview.azure.net/.default"


class PurviewClient:
    """
    Minimal Purview client for writing AI_Enrichment Business Metadata.

    Uses the Atlas REST API (Business Metadata POST) with Managed Identity.
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
        self,
        entity_guid: str,
        description: str,
        confidence_score: float = 0.0,
        model_version: str = "",
        generated_at: str = "",
    ) -> Dict[str, Any]:
        """
        Write the AI-generated description to the AI_Enrichment Business
        Metadata attribute on a Purview entity.

        This performs a POST to:
            /datamap/api/atlas/v2/entity/guid/{guid}/businessmetadata

        Only AI_Enrichment.suggested_description (and companion attributes)
        are written. Native entity attributes — including description and
        userDescription — are never touched.

        Args:
            entity_guid:      The GUID of the Purview entity to update.
            description:      The AI-generated description text to write.
            confidence_score: Validation confidence score (0.0–1.0).
            model_version:    LLM model identifier (reserved for future use).
            generated_at:     ISO-8601 generation timestamp. Defaults to now.

        Returns:
            Empty dict on success (API returns HTTP 204 No Content).

        Raises:
            requests.HTTPError: If the API call fails.
        """
        url = (
            f"{self._base_url}/datamap/api/atlas/v2/entity/guid/{entity_guid}"
            "/businessmetadata?isOverwrite=true"
        )

        # Write only to the AI_Enrichment Business Metadata namespace.
        # Native attributes (description, userDescription) are never modified.
        payload: Dict[str, Any] = {
            "AI_Enrichment": {
                "suggested_description": description,
                "confidence_score": confidence_score,
                "review_status": "PENDING",
            },
        }

        logger.info(
            "Writing AI_Enrichment Business Metadata to Purview",
            extra={
                "entityGuid": entity_guid,
                "confidenceScore": confidence_score,
                "descriptionLength": len(description),
                "purviewAccount": self._account_name,
            },
        )

        headers = self._get_auth_headers()
        response = self._session.post(url, json=payload, headers=headers)
        response.raise_for_status()

        # Business Metadata API returns HTTP 204 No Content on success.
        result: Dict[str, Any] = {}
        if response.status_code != 204 and response.content:
            try:
                result = response.json()
            except Exception:
                pass

        logger.info(
            "AI_Enrichment Business Metadata written successfully",
            extra={
                "entityGuid": entity_guid,
                "purviewAccount": self._account_name,
                "httpStatus": response.status_code,
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
        url = (
            f"{self._base_url}/datamap/api/atlas/v2/entity/guid/{entity_guid}"
            "?api-version=2023-09-01"
        )

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
