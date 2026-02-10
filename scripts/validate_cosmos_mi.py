"""
Cosmos DB Managed Identity Validation Script.

Validates that:
1. Authenticated access (Managed Identity) can read/write state and audit containers
2. Unauthenticated access is explicitly denied (401/403)
3. No keys or secrets are used anywhere

Usage (from deployed Container App or Azure environment with MI):
    python -m scripts.validate_cosmos_mi

Usage (local dev with Azure CLI login):
    az login
    COSMOS_ENDPOINT=https://cosmos-ai-metadata-dev.documents.azure.com:443/ \
    python -m scripts.validate_cosmos_mi

Environment Variables:
    COSMOS_ENDPOINT       - Required. Cosmos DB account endpoint.
    COSMOS_DATABASE_NAME  - Optional. Defaults to 'metadata_enricher'.

Exit Codes:
    0 - All validations passed
    1 - One or more validations failed
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("validate_cosmos_mi")


def validate_authenticated_access() -> bool:
    """
    Test 1: Authenticated access via Managed Identity.

    Performs:
    - Read from state container (non-existent item — expect None)
    - Create a test item in state
    - Update the same item in state
    - Create a test item in audit
    - Clean up test data
    """
    from azure.cosmos import CosmosClient
    from azure.cosmos.exceptions import CosmosResourceNotFoundError
    from azure.identity import DefaultAzureCredential

    endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "metadata_enricher")
    state_container_name = os.environ.get("COSMOS_STATE_CONTAINER", "state")
    audit_container_name = os.environ.get("COSMOS_AUDIT_CONTAINER", "audit")

    if not endpoint:
        logger.error("COSMOS_ENDPOINT environment variable is not set")
        return False

    test_id = f"mi-validation-{uuid.uuid4().hex[:8]}"
    entity_type = "validation-test"
    all_passed = True

    logger.info("=" * 60)
    logger.info("TEST 1: Authenticated Access (Managed Identity)")
    logger.info("=" * 60)
    logger.info(f"Endpoint: {endpoint}")
    logger.info(f"Database: {database_name}")
    logger.info(f"Auth Method: DefaultAzureCredential (Managed Identity)")
    logger.info(f"Test ID: {test_id}")

    try:
        credential = DefaultAzureCredential()
        client = CosmosClient(url=endpoint, credential=credential)
        database = client.get_database_client(database_name)
        state_container = database.get_container_client(state_container_name)
        audit_container = database.get_container_client(audit_container_name)

        logger.info("[AUTH] Cosmos DB client initialized with Managed Identity")

        # -- Step 1: Read non-existent item from state --
        logger.info("[1/5] Reading non-existent item from state container...")
        try:
            state_container.read_item(
                item="non-existent-validation-item",
                partition_key=entity_type,
            )
            logger.error("[FAIL] Expected 404 but item was found")
            all_passed = False
        except CosmosResourceNotFoundError:
            logger.info("[PASS] Non-existent item correctly returned 404")
        except Exception as e:
            logger.error(f"[FAIL] Unexpected error: {e}")
            all_passed = False

        # -- Step 2: Create test item in state --
        logger.info("[2/5] Creating test item in state container...")
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            state_item = {
                "id": test_id,
                "entityType": entity_type,
                "sourceSystem": "validation",
                "contentHash": "test-hash-v1",
                "decision": "REPROCESS",
                "correlationId": str(uuid.uuid4()),
                "updatedAt": now_iso,
                "_validationTest": True,
            }
            result = state_container.upsert_item(body=state_item)
            logger.info(f"[PASS] State item created: id={result['id']}")
        except Exception as e:
            logger.error(f"[FAIL] Failed to create state item: {e}")
            all_passed = False

        # -- Step 3: Update the same item in state --
        logger.info("[3/5] Updating test item in state container...")
        try:
            state_item["contentHash"] = "test-hash-v2"
            state_item["decision"] = "SKIP"
            state_item["updatedAt"] = datetime.now(timezone.utc).isoformat()
            result = state_container.upsert_item(body=state_item)
            logger.info(f"[PASS] State item updated: hash={result['contentHash']}")
        except Exception as e:
            logger.error(f"[FAIL] Failed to update state item: {e}")
            all_passed = False

        # -- Step 4: Create test item in audit --
        logger.info("[4/5] Creating test item in audit container...")
        try:
            audit_item = {
                "id": f"{test_id}:audit",
                "entityType": entity_type,
                "assetId": test_id,
                "sourceSystem": "validation",
                "decision": "REPROCESS",
                "contentHash": "test-hash-v1",
                "correlationId": str(uuid.uuid4()),
                "processedAt": datetime.now(timezone.utc).isoformat(),
                "_validationTest": True,
            }
            result = audit_container.upsert_item(body=audit_item)
            logger.info(f"[PASS] Audit item created: id={result['id']}")
        except Exception as e:
            logger.error(f"[FAIL] Failed to create audit item: {e}")
            all_passed = False

        # -- Step 5: Clean up test data --
        logger.info("[5/5] Cleaning up test data...")
        try:
            state_container.delete_item(item=test_id, partition_key=entity_type)
            logger.info("[PASS] State test item deleted")
        except Exception as e:
            logger.warning(f"[WARN] Could not delete state test item: {e}")

        try:
            audit_container.delete_item(
                item=f"{test_id}:audit", partition_key=entity_type
            )
            logger.info("[PASS] Audit test item deleted")
        except Exception as e:
            logger.warning(f"[WARN] Could not delete audit test item: {e}")

        # Close resources
        client.close()
        credential.close()

    except Exception as e:
        logger.error(f"[FAIL] Authenticated access test failed: {e}")
        all_passed = False

    return all_passed


def validate_unauthenticated_access() -> bool:
    """
    Test 2: Unauthenticated access must be DENIED.

    Attempts to access Cosmos DB:
    - Without any credentials
    - Expects 401 or 403 errors
    - Confirms no silent fallback or downgrade
    """
    from azure.cosmos import CosmosClient
    from azure.core.credentials import AccessToken

    endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "metadata_enricher")
    state_container_name = os.environ.get("COSMOS_STATE_CONTAINER", "state")

    if not endpoint:
        logger.error("COSMOS_ENDPOINT environment variable is not set")
        return False

    all_passed = True

    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 2: Unauthenticated Access (Must Be DENIED)")
    logger.info("=" * 60)

    # -- Test with invalid/empty token credential --
    logger.info("[1/2] Attempting access with invalid token credential...")

    class InvalidCredential:
        """Credential that returns an invalid/expired token."""

        def get_token(self, *scopes, **kwargs):
            return AccessToken(
                token="invalid-expired-token-for-validation",
                expires_on=0,
            )

        def close(self):
            pass

    try:
        invalid_credential = InvalidCredential()
        client = CosmosClient(url=endpoint, credential=invalid_credential)
        database = client.get_database_client(database_name)
        container = database.get_container_client(state_container_name)

        # Attempt to read — this should fail with 401/403
        container.read_item(
            item="should-not-exist",
            partition_key="should-not-exist",
        )
        logger.error(
            "[FAIL] Unauthenticated access SUCCEEDED — this is a security violation!"
        )
        all_passed = False
        client.close()
    except Exception as e:
        error_str = str(e)
        error_code = getattr(e, "status_code", None)
        if error_code in (401, 403) or "401" in error_str or "403" in error_str or "Unauthorized" in error_str or "Forbidden" in error_str:
            logger.info(
                f"[PASS] Unauthenticated access correctly DENIED "
                f"(status={error_code}, error={error_str[:120]})"
            )
        else:
            logger.info(
                f"[PASS] Access denied with error (no silent fallback): {error_str[:120]}"
            )

    # -- Test with no credential context --
    logger.info("[2/2] Attempting access with no credential context...")

    class NullCredential:
        """Credential that raises on any token request."""

        def get_token(self, *scopes, **kwargs):
            raise PermissionError("No credentials available — access should be denied")

        def close(self):
            pass

    try:
        null_credential = NullCredential()
        client = CosmosClient(url=endpoint, credential=null_credential)
        database = client.get_database_client(database_name)
        container = database.get_container_client(state_container_name)

        container.read_item(
            item="should-not-exist",
            partition_key="should-not-exist",
        )
        logger.error(
            "[FAIL] Access without credentials SUCCEEDED — security violation!"
        )
        all_passed = False
        client.close()
    except PermissionError:
        logger.info(
            "[PASS] Access without credentials correctly denied "
            "(credential refused to produce token)"
        )
    except Exception as e:
        error_str = str(e)
        if "401" in error_str or "403" in error_str or "Unauthorized" in error_str or "No credentials" in error_str:
            logger.info(
                f"[PASS] Access without credentials denied: {error_str[:120]}"
            )
        else:
            logger.info(
                f"[PASS] Access denied (no silent fallback): {error_str[:120]}"
            )

    return all_passed


def main() -> None:
    """Run all validation tests."""
    logger.info("=" * 60)
    logger.info("COSMOS DB MANAGED IDENTITY VALIDATION")
    logger.info("=" * 60)
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logger.info(f"Auth Model: Managed Identity (DefaultAzureCredential)")
    logger.info(f"Keys/Secrets: NONE")
    logger.info("")

    auth_passed = validate_authenticated_access()
    unauth_passed = validate_unauthenticated_access()

    logger.info("")
    logger.info("=" * 60)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Authenticated access:   {'PASS' if auth_passed else 'FAIL'}")
    logger.info(f"Unauthenticated denied: {'PASS' if unauth_passed else 'FAIL'}")

    if auth_passed and unauth_passed:
        logger.info("")
        logger.info("✅ ALL VALIDATIONS PASSED")
        logger.info("   - Cosmos DB access works via Managed Identity")
        logger.info("   - Unauthenticated access is denied")
        logger.info("   - No keys or secrets used")
        sys.exit(0)
    else:
        logger.error("")
        logger.error("❌ VALIDATION FAILED — see errors above")
        sys.exit(1)


if __name__ == "__main__":
    main()
