"""
Validation script — Purview Client.

Performs a controlled test to verify:
1. DefaultAzureCredential can acquire a token for Purview
2. The client can authenticate against the Purview Atlas API
3. A read operation (entity retrieval) succeeds

NOTE: This script performs a READ-ONLY validation by default.
      A write test (Suggested Description) requires a valid entity GUID
      and must be explicitly enabled via the --write flag.

Prerequisites:
    - PURVIEW_ACCOUNT_NAME env var set
    - Managed Identity (or local Azure CLI auth) has
      Data Curator role in the Purview collection

Usage:
    # Read-only validation (auth + entity read):
    python -m scripts.validate_purview_client --entity-guid <guid>

    # Write validation (writes Suggested Description):
    python -m scripts.validate_purview_client --entity-guid <guid> --write

This script is for manual validation only.
It does NOT trigger enrichment or modify orchestration state.
"""

import argparse
import logging
import sys
import traceback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
# Enable DEBUG for azure-identity to surface credential chain diagnostics
logging.getLogger("azure.identity").setLevel(logging.DEBUG)
logger = logging.getLogger("validate_purview_client")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Purview client authentication and operations."
    )
    parser.add_argument(
        "--entity-guid",
        required=True,
        help="GUID of a Purview entity to use for validation.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help="If set, also performs a controlled Suggested Description write.",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Purview Client — Validation")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Load configuration
    # ------------------------------------------------------------------
    logger.info("Step 1: Loading enrichment configuration...")
    try:
        from src.enrichment.config import EnrichmentConfig

        config = EnrichmentConfig()
        config.validate_purview()
        logger.info(
            "Configuration loaded — account=%s",
            config.purview_account_name,
        )
    except Exception as exc:
        logger.error("Configuration error [%s]: %s", type(exc).__name__, exc)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2: Initialize client
    # ------------------------------------------------------------------
    logger.info("Step 2: Initializing Purview client...")
    try:
        from src.enrichment.purview_client import PurviewClient

        client = PurviewClient(config)
        logger.info("Client initialized successfully")
    except Exception as exc:
        logger.error(
            "Client initialization failed [%s]: %s",
            type(exc).__name__, exc,
        )
        logger.debug(traceback.format_exc())
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 3: Read entity (auth validation)
    # ------------------------------------------------------------------
    logger.info("Step 3: Reading entity %s (auth validation)...", args.entity_guid)
    try:
        entity = client.get_entity(args.entity_guid)
        entity_name = (
            entity.get("entity", {}).get("attributes", {}).get("name", "N/A")
        )
        entity_type = entity.get("entity", {}).get("typeName", "N/A")
        logger.info(
            "Entity retrieved — name=%s, type=%s",
            entity_name,
            entity_type,
        )
    except Exception as exc:
        logger.error(
            "Entity read failed [%s]: %s",
            type(exc).__name__, exc,
        )
        logger.debug(traceback.format_exc())
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 4 (optional): Write Suggested Description
    # ------------------------------------------------------------------
    if args.write:
        test_description = (
            "[VALIDATION] AI Metadata Enricher — Purview client write test. "
            "This description was written by the validation script and can "
            "be safely removed."
        )
        logger.info("Step 4: Writing Suggested Description...")
        try:
            result = client.write_suggested_description(
                entity_guid=args.entity_guid,
                description=test_description,
            )
            logger.info("Write succeeded — response: %s", result)
        except Exception as exc:
            logger.error(
                "Suggested Description write failed [%s]: %s",
                type(exc).__name__, exc,
            )
            logger.debug(traceback.format_exc())
            sys.exit(1)
    else:
        logger.info("Step 4: Write test SKIPPED (use --write to enable)")

    client.close()

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("RESULT: Purview client validation PASSED")
    logger.info("  - Authentication: Managed Identity / DefaultAzureCredential")
    logger.info("  - Account: %s", config.purview_account_name)
    logger.info("  - Entity read: SUCCESS (name=%s)", entity_name)
    if args.write:
        logger.info("  - Suggested Description write: SUCCESS")
    else:
        logger.info("  - Suggested Description write: SKIPPED")
    logger.info("  - No enrichment triggered")
    logger.info("  - No orchestration modified")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
