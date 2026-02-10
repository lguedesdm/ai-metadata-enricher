"""
Validation script — Azure OpenAI Client.

Performs a single, explicit test call to verify:
1. DefaultAzureCredential can acquire a token for Azure OpenAI
2. The configured deployment accepts a chat completion request
3. A valid response is returned

Prerequisites:
    - AZURE_OPENAI_ENDPOINT env var set
    - AZURE_OPENAI_DEPLOYMENT_NAME env var set
    - Managed Identity (or local Azure CLI auth) has
      "Cognitive Services OpenAI User" role on the resource

Usage:
    python -m scripts.validate_llm_client

This script is for manual validation only.
It does NOT trigger enrichment or modify any state.
"""

import logging
import sys
import traceback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
# Enable DEBUG for azure-identity to surface credential chain diagnostics
logging.getLogger("azure.identity").setLevel(logging.DEBUG)
logger = logging.getLogger("validate_llm_client")


def main() -> None:
    logger.info("=" * 60)
    logger.info("Azure OpenAI Client — Validation")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Load configuration
    # ------------------------------------------------------------------
    logger.info("Step 1: Loading enrichment configuration...")
    try:
        from src.enrichment.config import EnrichmentConfig

        config = EnrichmentConfig()
        config.validate_llm()
        logger.info(
            "Configuration loaded — endpoint=%s, deployment=%s",
            config.azure_openai_endpoint,
            config.azure_openai_deployment_name,
        )
    except Exception as exc:
        logger.error("Configuration error [%s]: %s", type(exc).__name__, exc)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2: Initialize client
    # ------------------------------------------------------------------
    logger.info("Step 2: Initializing Azure OpenAI client...")
    try:
        from src.enrichment.llm_client import AzureOpenAIClient

        client = AzureOpenAIClient(config)
        logger.info("Client initialized successfully")
    except Exception as exc:
        logger.error(
            "Client initialization failed [%s]: %s",
            type(exc).__name__, exc,
        )
        logger.debug(traceback.format_exc())
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 3: Perform a test call
    # ------------------------------------------------------------------
    logger.info("Step 3: Sending test completion request...")
    try:
        response = client.complete(
            prompt="Respond with exactly: VALIDATION_SUCCESS",
            system_message="You are a validation assistant. Respond concisely.",
        )
        logger.info("Response received: %s", response.strip())
    except Exception as exc:
        logger.error(
            "Completion call failed [%s]: %s",
            type(exc).__name__, exc,
        )
        logger.debug(traceback.format_exc())
        sys.exit(1)
    finally:
        client.close()

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("RESULT: Azure OpenAI client validation PASSED")
    logger.info("  - Authentication: Managed Identity / DefaultAzureCredential")
    logger.info("  - Endpoint: %s", config.azure_openai_endpoint)
    logger.info("  - Deployment: %s", config.azure_openai_deployment_name)
    logger.info("  - Response length: %d chars", len(response))
    logger.info("  - No enrichment triggered")
    logger.info("  - No orchestration modified")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
