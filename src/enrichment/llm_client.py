"""
Azure OpenAI Client — Managed Identity Authentication Only.

Provides a minimal, isolated client for invoking Azure OpenAI chat completions
using DefaultAzureCredential (Managed Identity).

Security guarantees:
- NO API keys, secrets, or connection strings
- Authentication is exclusively via Entra ID (AAD) tokens
- Requires "Cognitive Services OpenAI User" RBAC on the Azure OpenAI resource

This module does NOT:
- Know about orchestration, message handling, or domain logic
- Perform retries, batching, or optimization
- Implement RAG, AI Search, or embedding generation
- Trigger enrichment automatically
- Process assets end-to-end

Usage (manual / validation only):
    from src.enrichment.config import EnrichmentConfig
    from src.enrichment.llm_client import AzureOpenAIClient

    config = EnrichmentConfig()
    client = AzureOpenAIClient(config)
    response = client.complete("What is metadata governance?")
    print(response)
"""

import logging
from typing import Dict, List, Optional

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from .config import EnrichmentConfig

logger = logging.getLogger("enrichment.llm_client")


class AzureOpenAIClient:
    """
    Minimal Azure OpenAI client using Managed Identity authentication.

    Provides a single `complete()` method for chat completions.
    No retries, no batching, no orchestration awareness.

    Lifecycle:
        client = AzureOpenAIClient(config)
        response = client.complete("prompt text")
        client.close()
    """

    def __init__(self, config: EnrichmentConfig) -> None:
        config.validate_llm()

        self._deployment_name: str = config.azure_openai_deployment_name

        logger.info(
            "Initializing Azure OpenAI client with Managed Identity",
            extra={
                "endpoint": config.azure_openai_endpoint,
                "deployment": config.azure_openai_deployment_name,
                "apiVersion": config.azure_openai_api_version,
                "authMethod": "ManagedIdentity/DefaultAzureCredential",
            },
        )

        # Acquire Entra ID token for Azure OpenAI scope
        self._credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            self._credential, "https://cognitiveservices.azure.com/.default"
        )

        self._client = AzureOpenAI(
            azure_endpoint=config.azure_openai_endpoint,
            azure_deployment=config.azure_openai_deployment_name,
            api_version=config.azure_openai_api_version,
            azure_ad_token_provider=token_provider,
        )

    def complete(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Perform a single chat completion call.

        Args:
            prompt: The user message to send to the model.
            system_message: Optional system message for context.
            messages: Optional pre-built message list. When provided,
                      ``prompt`` and ``system_message`` are ignored and
                      these messages are sent as-is.  This allows callers
                      (e.g. a future RAG pipeline) to supply a fully
                      constructed conversation without changing the client
                      signature.

        Returns:
            The model's response text.
        """
        if messages is not None:
            # Caller provided an explicit message list — use as-is.
            chat_messages = list(messages)
        else:
            chat_messages = []
            if system_message:
                chat_messages.append({"role": "system", "content": system_message})
            chat_messages.append({"role": "user", "content": prompt})

        logger.info(
            "Sending chat completion request",
            extra={
                "deployment": self._deployment_name,
                "messageCount": len(chat_messages),
            },
        )

        response = self._client.chat.completions.create(
            model=self._deployment_name,
            messages=chat_messages,
        )

        result = response.choices[0].message.content or ""

        logger.info(
            "Chat completion received",
            extra={
                "deployment": self._deployment_name,
                "responseLength": len(result),
                "finishReason": response.choices[0].finish_reason,
            },
        )

        return result

    def close(self) -> None:
        """Release underlying HTTP resources."""
        self._client.close()
        logger.info("Azure OpenAI client closed")
