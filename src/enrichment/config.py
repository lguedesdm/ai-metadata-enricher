"""
Configuration for the Enrichment layer.

All configuration is sourced from environment variables.
No secrets are stored in code — authentication uses Managed Identity.

This configuration is independent of OrchestratorConfig and is consumed
only by the enrichment clients (llm_client, purview_client).
It is NOT loaded or referenced by the Orchestrator.
"""

import os


class EnrichmentConfig:
    """Immutable configuration for enrichment clients, sourced from environment variables."""

    def __init__(self) -> None:
        # -----------------------------------------------------------------
        # Azure OpenAI
        # -----------------------------------------------------------------
        # Fully qualified endpoint, e.g. "https://oai-ai-metadata-dev.openai.azure.com/"
        self.azure_openai_endpoint: str = os.environ.get(
            "AZURE_OPENAI_ENDPOINT", ""
        )

        # Deployment name for the chat completion model
        self.azure_openai_deployment_name: str = os.environ.get(
            "AZURE_OPENAI_DEPLOYMENT_NAME", ""
        )

        # API version for Azure OpenAI
        self.azure_openai_api_version: str = os.environ.get(
            "AZURE_OPENAI_API_VERSION", "2024-06-01"
        )

        # -----------------------------------------------------------------
        # Microsoft Purview
        # -----------------------------------------------------------------
        # Purview account name, e.g. "purview-ai-metadata-dev"
        # Used to construct the endpoint: https://{account}.purview.azure.com
        self.purview_account_name: str = os.environ.get(
            "PURVIEW_ACCOUNT_NAME", ""
        )

        # -----------------------------------------------------------------
        # Runtime
        # -----------------------------------------------------------------
        self.environment: str = os.environ.get("ENVIRONMENT", "dev")

    def validate_llm(self) -> None:
        """Raise ValueError if LLM configuration is incomplete."""
        if not self.azure_openai_endpoint:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT environment variable is required "
                "for Azure OpenAI client initialization."
            )
        if not self.azure_openai_deployment_name:
            raise ValueError(
                "AZURE_OPENAI_DEPLOYMENT_NAME environment variable is required "
                "for Azure OpenAI client initialization."
            )

    def validate_purview(self) -> None:
        """Raise ValueError if Purview configuration is incomplete."""
        if not self.purview_account_name:
            raise ValueError(
                "PURVIEW_ACCOUNT_NAME environment variable is required "
                "for Purview client initialization."
            )
