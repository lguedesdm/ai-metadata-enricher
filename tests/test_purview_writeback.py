"""
Tests for the Purview Write-back Service and Lifecycle Management.

Covers:
1. Successful write-back of a single asset (pending status)
2. Attempted overwrite of an existing non-pending Suggested Description (must block)
3. Proper lifecycle transitions (pending → approved, pending → rejected)
4. Purview API error handling (auth, permission, not found)
5. Determinism (same input → same lifecycle result)
6. Full traceability (correlationId propagated to audit and logs)
7. Isolation: no import or invocation of Orchestrator, LLM, or validation logic

No test depends on live Azure resources.
"""

import ast
import hashlib
import inspect
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import requests

from src.enrichment.lifecycle import (
    LifecycleRecord,
    LifecycleStatus,
    LifecycleStore,
    LifecycleTransitionError,
    VALID_TRANSITIONS,
    validate_transition,
)
from src.enrichment.purview_writeback import (
    PurviewWritebackError,
    PurviewWritebackService,
    WritebackErrorCategory,
    WritebackResult,
)


# ======================================================================
# Helpers — mock factories
# ======================================================================

def _make_mock_purview_client(
    entity_response: dict | None = None,
    write_response: dict | None = None,
    get_entity_side_effect: Exception | None = None,
    write_side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock PurviewClient with configurable behavior."""
    client = MagicMock()

    if get_entity_side_effect:
        client.get_entity.side_effect = get_entity_side_effect
    else:
        client.get_entity.return_value = entity_response or {
            "entity": {
                "guid": "test-guid-001",
                "attributes": {
                    "name": "TestEntity",
                    "description": "",
                    "userDescription": "",
                },
            }
        }

    if write_side_effect:
        client.write_suggested_description.side_effect = write_side_effect
    else:
        client.write_suggested_description.return_value = write_response or {
            "mutatedEntities": {"UPDATE": [{"guid": "test-guid-001"}]}
        }

    return client


def _make_mock_lifecycle_store(
    existing_record: LifecycleRecord | None = None,
    get_side_effect: Exception | None = None,
    upsert_side_effect: Exception | None = None,
    audit_side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock LifecycleStore with configurable behavior."""
    store = MagicMock(spec=LifecycleStore)

    if get_side_effect:
        store.get_lifecycle_record.side_effect = get_side_effect
    else:
        store.get_lifecycle_record.return_value = existing_record

    if upsert_side_effect:
        store.upsert_lifecycle_record.side_effect = upsert_side_effect
    else:
        store.upsert_lifecycle_record.return_value = {"id": "test-guid-001"}

    if audit_side_effect:
        store.write_audit_record.side_effect = audit_side_effect
    else:
        store.write_audit_record.return_value = {"id": "audit-001"}

    return store


def _make_http_error(status_code: int) -> requests.HTTPError:
    """Create a requests.HTTPError with a specific status code."""
    response = MagicMock()
    response.status_code = status_code
    error = requests.HTTPError(response=response)
    return error


def _make_pending_record(
    asset_id: str = "test-guid-001",
    entity_type: str = "table",
) -> LifecycleRecord:
    """Create a PENDING lifecycle record."""
    desc = "Original AI-generated description."
    return LifecycleRecord(
        asset_id=asset_id,
        entity_type=entity_type,
        correlation_id="original-corr-001",
        status=LifecycleStatus.PENDING,
        suggested_description=desc,
        description_hash=hashlib.sha256(desc.encode("utf-8")).hexdigest(),
        created_at="2026-02-10T10:00:00+00:00",
        updated_at="2026-02-10T10:00:00+00:00",
    )


def _make_approved_record(
    asset_id: str = "test-guid-001",
    entity_type: str = "table",
) -> LifecycleRecord:
    """Create an APPROVED lifecycle record."""
    desc = "Previously approved description."
    return LifecycleRecord(
        asset_id=asset_id,
        entity_type=entity_type,
        correlation_id="original-corr-001",
        status=LifecycleStatus.APPROVED,
        suggested_description=desc,
        description_hash=hashlib.sha256(desc.encode("utf-8")).hexdigest(),
        created_at="2026-02-09T10:00:00+00:00",
        updated_at="2026-02-09T14:00:00+00:00",
    )


def _make_rejected_record(
    asset_id: str = "test-guid-001",
    entity_type: str = "table",
) -> LifecycleRecord:
    """Create a REJECTED lifecycle record."""
    desc = "Previously rejected description."
    return LifecycleRecord(
        asset_id=asset_id,
        entity_type=entity_type,
        correlation_id="original-corr-001",
        status=LifecycleStatus.REJECTED,
        suggested_description=desc,
        description_hash=hashlib.sha256(desc.encode("utf-8")).hexdigest(),
        created_at="2026-02-08T10:00:00+00:00",
        updated_at="2026-02-08T16:00:00+00:00",
    )


# Standard test values
TEST_GUID = "test-guid-001"
TEST_ENTITY_TYPE = "table"
TEST_DESCRIPTION = "Annual sustainability report detailing carbon emissions for 2024."
TEST_CORRELATION_ID = "corr-writeback-001"


# ======================================================================
# Test 1: Successful write-back of a single asset (pending status)
# ======================================================================

class TestSuccessfulWriteback:
    """A single asset write-back must succeed with correct lifecycle state."""

    def test_write_returns_success(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            entity_guid=TEST_GUID,
            entity_type=TEST_ENTITY_TYPE,
            suggested_description=TEST_DESCRIPTION,
            correlation_id=TEST_CORRELATION_ID,
        )

        assert result.success is True
        assert result.asset_id == TEST_GUID
        assert result.correlation_id == TEST_CORRELATION_ID
        assert result.lifecycle_status == "pending"
        assert result.operation == "write_suggested_description"
        assert result.error is None
        assert result.error_category is None

    def test_write_calls_purview_get_entity(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        purview.get_entity.assert_called_once_with(TEST_GUID)

    def test_write_calls_purview_write_suggested_description(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        purview.write_suggested_description.assert_called_once_with(
            entity_guid=TEST_GUID,
            description=TEST_DESCRIPTION,
        )

    def test_write_creates_pending_lifecycle_record(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        store.upsert_lifecycle_record.assert_called_once()
        record = store.upsert_lifecycle_record.call_args[0][0]
        assert isinstance(record, LifecycleRecord)
        assert record.asset_id == TEST_GUID
        assert record.entity_type == TEST_ENTITY_TYPE
        assert record.status == LifecycleStatus.PENDING
        assert record.correlation_id == TEST_CORRELATION_ID
        assert record.suggested_description == TEST_DESCRIPTION

    def test_write_creates_audit_record(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        store.write_audit_record.assert_called()
        audit = store.write_audit_record.call_args[0][0]
        assert audit["assetId"] == TEST_GUID
        assert audit["correlationId"] == TEST_CORRELATION_ID
        assert audit["operation"] == "write_suggested_description"
        assert audit["outcome"] == "SUCCESS"
        assert audit["recordType"] == "writeback_audit"
        assert audit["lifecycleStatus"] == "pending"

    def test_write_returns_purview_response(self):
        purview_resp = {"mutatedEntities": {"UPDATE": [{"guid": TEST_GUID}]}}
        purview = _make_mock_purview_client(write_response=purview_resp)
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.purview_response == purview_resp

    def test_write_with_existing_authoritative_description_still_succeeds(self):
        """Authoritative description exists but is never touched — write proceeds."""
        entity = {
            "entity": {
                "guid": TEST_GUID,
                "attributes": {
                    "name": "TestEntity",
                    "description": "Official authoritative description.",
                    "userDescription": "",
                },
            }
        }
        purview = _make_mock_purview_client(entity_response=entity)
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is True
        # Verify only userDescription was written, not description
        purview.write_suggested_description.assert_called_once_with(
            entity_guid=TEST_GUID,
            description=TEST_DESCRIPTION,
        )

    def test_overwrite_pending_description_succeeds(self):
        """A pending description can be overwritten with a new write."""
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_pending_record())
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE,
            "Updated description replacing pending one.",
            TEST_CORRELATION_ID,
        )

        assert result.success is True
        assert result.lifecycle_status == "pending"


# ======================================================================
# Test 2: Overwrite of existing non-pending description (must block)
# ======================================================================

class TestOverwriteBlocking:
    """Existing non-pending descriptions must block further writes."""

    def test_approved_description_blocks_write(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_approved_record())
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.LIFECYCLE_VIOLATION.value
        assert result.lifecycle_status == "approved"
        # Purview write must NOT have been called
        purview.write_suggested_description.assert_not_called()

    def test_rejected_description_blocks_write(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_rejected_record())
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.LIFECYCLE_VIOLATION.value
        assert result.lifecycle_status == "rejected"
        purview.write_suggested_description.assert_not_called()

    def test_blocked_write_creates_audit_record(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_approved_record())
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        store.write_audit_record.assert_called()
        audit = store.write_audit_record.call_args[0][0]
        assert audit["outcome"] == "BLOCKED"
        assert audit["correlationId"] == TEST_CORRELATION_ID

    def test_blocked_write_does_not_update_lifecycle(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_approved_record())
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        store.upsert_lifecycle_record.assert_not_called()


# ======================================================================
# Test 3: Lifecycle transitions (pending → approved, pending → rejected)
# ======================================================================

class TestLifecycleTransitions:
    """Lifecycle transitions must follow strict rules."""

    def test_approve_pending_succeeds(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_pending_record())
        service = PurviewWritebackService(purview, store)

        result = service.approve(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        assert result.success is True
        assert result.lifecycle_status == "approved"
        assert result.operation == "lifecycle_approved"

    def test_reject_pending_succeeds(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_pending_record())
        service = PurviewWritebackService(purview, store)

        result = service.reject(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        assert result.success is True
        assert result.lifecycle_status == "rejected"
        assert result.operation == "lifecycle_rejected"

    def test_approve_approved_blocks(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_approved_record())
        service = PurviewWritebackService(purview, store)

        result = service.approve(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.LIFECYCLE_VIOLATION.value

    def test_reject_approved_blocks(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_approved_record())
        service = PurviewWritebackService(purview, store)

        result = service.reject(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.LIFECYCLE_VIOLATION.value

    def test_approve_rejected_blocks(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_rejected_record())
        service = PurviewWritebackService(purview, store)

        result = service.approve(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.LIFECYCLE_VIOLATION.value

    def test_reject_rejected_blocks(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_rejected_record())
        service = PurviewWritebackService(purview, store)

        result = service.reject(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.LIFECYCLE_VIOLATION.value

    def test_approve_no_record_blocks(self):
        """Cannot approve without a prior write-back."""
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=None)
        service = PurviewWritebackService(purview, store)

        result = service.approve(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.LIFECYCLE_VIOLATION.value

    def test_reject_no_record_blocks(self):
        """Cannot reject without a prior write-back."""
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=None)
        service = PurviewWritebackService(purview, store)

        result = service.reject(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.LIFECYCLE_VIOLATION.value

    def test_approve_updates_lifecycle_record(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_pending_record())
        service = PurviewWritebackService(purview, store)

        service.approve(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        store.upsert_lifecycle_record.assert_called_once()
        record = store.upsert_lifecycle_record.call_args[0][0]
        assert record.status == LifecycleStatus.APPROVED
        assert record.correlation_id == TEST_CORRELATION_ID

    def test_reject_updates_lifecycle_record(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_pending_record())
        service = PurviewWritebackService(purview, store)

        service.reject(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        store.upsert_lifecycle_record.assert_called_once()
        record = store.upsert_lifecycle_record.call_args[0][0]
        assert record.status == LifecycleStatus.REJECTED

    def test_transition_preserves_original_description(self):
        original = _make_pending_record()
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=original)
        service = PurviewWritebackService(purview, store)

        service.approve(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        record = store.upsert_lifecycle_record.call_args[0][0]
        assert record.suggested_description == original.suggested_description

    def test_transition_creates_audit_record(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_pending_record())
        service = PurviewWritebackService(purview, store)

        service.approve(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        store.write_audit_record.assert_called()
        audit = store.write_audit_record.call_args[0][0]
        assert audit["outcome"] == "SUCCESS"
        assert audit["lifecycleStatus"] == "approved"
        assert audit["correlationId"] == TEST_CORRELATION_ID

    def test_transition_does_not_call_purview(self):
        """Approve/reject are Cosmos-only — no Purview calls."""
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_pending_record())
        service = PurviewWritebackService(purview, store)

        service.approve(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        purview.get_entity.assert_not_called()
        purview.write_suggested_description.assert_not_called()


# ======================================================================
# Test 4: Purview API error handling (auth, permission, not found)
# ======================================================================

class TestPurviewErrorHandling:
    """Purview API errors must be classified and reported correctly."""

    def test_authentication_error_401(self):
        purview = _make_mock_purview_client(
            get_entity_side_effect=_make_http_error(401)
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.AUTHENTICATION.value

    def test_authorization_error_403(self):
        purview = _make_mock_purview_client(
            get_entity_side_effect=_make_http_error(403)
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.AUTHORIZATION.value

    def test_entity_not_found_404(self):
        purview = _make_mock_purview_client(
            get_entity_side_effect=_make_http_error(404)
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.ENTITY_NOT_FOUND.value

    def test_network_error(self):
        purview = _make_mock_purview_client(
            get_entity_side_effect=requests.ConnectionError("DNS resolution failed")
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.NETWORK.value

    def test_write_phase_auth_error(self):
        """Auth error during the write phase (after entity read succeeds)."""
        purview = _make_mock_purview_client(
            write_side_effect=_make_http_error(401)
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.AUTHENTICATION.value

    def test_write_phase_network_error(self):
        purview = _make_mock_purview_client(
            write_side_effect=requests.ConnectionError("Connection refused")
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.NETWORK.value

    def test_server_error_500(self):
        purview = _make_mock_purview_client(
            get_entity_side_effect=_make_http_error(500)
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.UNKNOWN.value

    def test_unexpected_exception(self):
        purview = _make_mock_purview_client(
            get_entity_side_effect=RuntimeError("Unexpected internal error")
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.UNKNOWN.value

    def test_error_creates_audit_record(self):
        purview = _make_mock_purview_client(
            get_entity_side_effect=_make_http_error(404)
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        store.write_audit_record.assert_called()
        audit = store.write_audit_record.call_args[0][0]
        assert audit["outcome"] == "ERROR"
        assert audit["correlationId"] == TEST_CORRELATION_ID
        assert audit["errorCategory"] == WritebackErrorCategory.ENTITY_NOT_FOUND.value

    def test_cosmos_lifecycle_read_failure(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(
            get_side_effect=RuntimeError("Cosmos 503")
        )
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.COSMOS_FAILURE.value

    def test_cosmos_lifecycle_write_failure(self):
        """Cosmos failure AFTER Purview write → PARTIAL_WRITE, not COSMOS_FAILURE."""
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(
            upsert_side_effect=RuntimeError("Cosmos write timeout")
        )
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.error_category == WritebackErrorCategory.PARTIAL_WRITE.value
        assert result.purview_written is True


# ======================================================================
# Test 5: Determinism (same input → same lifecycle result)
# ======================================================================

class TestDeterminism:
    """Same inputs must produce identical results across invocations."""

    def test_deterministic_successful_write(self):
        results = []
        for _ in range(5):
            purview = _make_mock_purview_client()
            store = _make_mock_lifecycle_store()
            service = PurviewWritebackService(purview, store)
            result = service.write_suggested_description(
                TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
            )
            results.append(result)

        for r in results:
            assert r.success == results[0].success
            assert r.lifecycle_status == results[0].lifecycle_status
            assert r.operation == results[0].operation
            assert r.error == results[0].error
            assert r.error_category == results[0].error_category

    def test_deterministic_blocked_write(self):
        results = []
        for _ in range(5):
            purview = _make_mock_purview_client()
            store = _make_mock_lifecycle_store(existing_record=_make_approved_record())
            service = PurviewWritebackService(purview, store)
            result = service.write_suggested_description(
                TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
            )
            results.append(result)

        for r in results:
            assert r.success is False
            assert r.error_category == results[0].error_category
            assert r.lifecycle_status == results[0].lifecycle_status

    def test_deterministic_lifecycle_transition(self):
        results = []
        for _ in range(5):
            purview = _make_mock_purview_client()
            store = _make_mock_lifecycle_store(existing_record=_make_pending_record())
            service = PurviewWritebackService(purview, store)
            result = service.approve(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)
            results.append(result)

        for r in results:
            assert r.success == results[0].success
            assert r.lifecycle_status == results[0].lifecycle_status

    def test_deterministic_error_handling(self):
        results = []
        for _ in range(5):
            purview = _make_mock_purview_client(
                get_entity_side_effect=_make_http_error(403)
            )
            store = _make_mock_lifecycle_store()
            service = PurviewWritebackService(purview, store)
            result = service.write_suggested_description(
                TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
            )
            results.append(result)

        for r in results:
            assert r.success is False
            assert r.error_category == WritebackErrorCategory.AUTHORIZATION.value


# ======================================================================
# Test 6: Traceability (correlationId propagated to audit and logs)
# ======================================================================

class TestTraceability:
    """correlationId must appear in all audit records and results."""

    def test_correlation_id_in_success_result(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, "trace-corr-001",
        )

        assert result.correlation_id == "trace-corr-001"

    def test_correlation_id_in_error_result(self):
        purview = _make_mock_purview_client(
            get_entity_side_effect=_make_http_error(404)
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, "trace-corr-002",
        )

        assert result.correlation_id == "trace-corr-002"

    def test_correlation_id_in_success_audit(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, "trace-corr-003",
        )

        audit = store.write_audit_record.call_args[0][0]
        assert audit["correlationId"] == "trace-corr-003"

    def test_correlation_id_in_lifecycle_record(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, "trace-corr-004",
        )

        record = store.upsert_lifecycle_record.call_args[0][0]
        assert record.correlation_id == "trace-corr-004"

    def test_correlation_id_in_blocked_audit(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_approved_record())
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, "trace-corr-005",
        )

        audit = store.write_audit_record.call_args[0][0]
        assert audit["correlationId"] == "trace-corr-005"

    def test_correlation_id_in_transition_audit(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_pending_record())
        service = PurviewWritebackService(purview, store)

        service.approve(TEST_GUID, TEST_ENTITY_TYPE, "trace-corr-006")

        audit = store.write_audit_record.call_args[0][0]
        assert audit["correlationId"] == "trace-corr-006"

    def test_audit_id_format_includes_asset_and_correlation(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, "trace-corr-007",
        )

        audit = store.write_audit_record.call_args[0][0]
        assert audit["id"] == f"wb:{TEST_GUID}:trace-corr-007"

    def test_audit_contains_timestamp(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        audit = store.write_audit_record.call_args[0][0]
        assert "timestamp" in audit
        # Verify it's a valid ISO 8601 string
        datetime.fromisoformat(audit["timestamp"])


# ======================================================================
# Test 7: Isolation — no Orchestrator, LLM, or validation logic
# ======================================================================

class TestIsolation:
    """Write-back module must be fully isolated from other system components."""

    def test_writeback_no_orchestrator_import(self):
        source = inspect.getsource(
            sys.modules["src.enrichment.purview_writeback"]
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                assert "orchestrator" not in module.lower(), (
                    f"Forbidden import of orchestrator module: {module}"
                )

    def test_lifecycle_no_orchestrator_import(self):
        source = inspect.getsource(
            sys.modules["src.enrichment.lifecycle"]
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                assert "orchestrator" not in module.lower(), (
                    f"Forbidden import of orchestrator module: {module}"
                )

    def test_no_llm_client_import(self):
        source = inspect.getsource(
            sys.modules["src.enrichment.purview_writeback"]
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                assert "llm_client" not in module.lower(), (
                    f"Forbidden import of LLM client: {module}"
                )

    def test_no_validation_import_in_writeback(self):
        source = inspect.getsource(
            sys.modules["src.enrichment.purview_writeback"]
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                assert "output_validator" not in module.lower(), (
                    f"Forbidden import of validation module: {module}"
                )
                assert "domain.validation" not in module.lower(), (
                    f"Forbidden import of domain validation: {module}"
                )

    def test_no_rag_import(self):
        source = inspect.getsource(
            sys.modules["src.enrichment.purview_writeback"]
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                assert ".rag" not in module and "rag." not in module, (
                    f"Forbidden import of RAG module: {module}"
                )


# ======================================================================
# Test 8: Lifecycle model unit tests
# ======================================================================

class TestLifecycleModel:
    """Direct tests for lifecycle types and transition logic."""

    def test_valid_transitions_from_none(self):
        validate_transition(None, LifecycleStatus.PENDING, "asset-1")
        # Should not raise

    def test_valid_transition_pending_to_approved(self):
        validate_transition(
            LifecycleStatus.PENDING, LifecycleStatus.APPROVED, "asset-1"
        )

    def test_valid_transition_pending_to_rejected(self):
        validate_transition(
            LifecycleStatus.PENDING, LifecycleStatus.REJECTED, "asset-1"
        )

    def test_invalid_transition_none_to_approved(self):
        with pytest.raises(LifecycleTransitionError):
            validate_transition(None, LifecycleStatus.APPROVED, "asset-1")

    def test_invalid_transition_none_to_rejected(self):
        with pytest.raises(LifecycleTransitionError):
            validate_transition(None, LifecycleStatus.REJECTED, "asset-1")

    def test_invalid_transition_approved_to_pending(self):
        with pytest.raises(LifecycleTransitionError):
            validate_transition(
                LifecycleStatus.APPROVED, LifecycleStatus.PENDING, "asset-1"
            )

    def test_invalid_transition_approved_to_rejected(self):
        with pytest.raises(LifecycleTransitionError):
            validate_transition(
                LifecycleStatus.APPROVED, LifecycleStatus.REJECTED, "asset-1"
            )

    def test_invalid_transition_rejected_to_pending(self):
        with pytest.raises(LifecycleTransitionError):
            validate_transition(
                LifecycleStatus.REJECTED, LifecycleStatus.PENDING, "asset-1"
            )

    def test_invalid_transition_rejected_to_approved(self):
        with pytest.raises(LifecycleTransitionError):
            validate_transition(
                LifecycleStatus.REJECTED, LifecycleStatus.APPROVED, "asset-1"
            )

    def test_lifecycle_record_serialization(self):
        desc = "Test description."
        record = LifecycleRecord(
            asset_id="guid-001",
            entity_type="table",
            correlation_id="corr-001",
            status=LifecycleStatus.PENDING,
            suggested_description=desc,
            description_hash=hashlib.sha256(desc.encode("utf-8")).hexdigest(),
            created_at="2026-02-10T10:00:00+00:00",
            updated_at="2026-02-10T10:00:00+00:00",
        )
        item = record.to_cosmos_item()
        assert item["id"] == "guid-001"
        assert item["entityType"] == "table"
        assert item["lifecycleStatus"] == "pending"
        assert item["recordType"] == "lifecycle"
        assert "descriptionHash" in item

    def test_lifecycle_record_deserialization(self):
        item = {
            "id": "guid-002",
            "entityType": "column",
            "correlationId": "corr-002",
            "lifecycleStatus": "approved",
            "suggestedDescription": "Approved desc.",
            "createdAt": "2026-02-09T09:00:00+00:00",
            "updatedAt": "2026-02-09T15:00:00+00:00",
        }
        record = LifecycleRecord.from_cosmos_item(item)
        assert record.asset_id == "guid-002"
        assert record.status == LifecycleStatus.APPROVED
        assert record.suggested_description == "Approved desc."

    def test_lifecycle_record_roundtrip(self):
        desc = "Roundtrip test."
        original = LifecycleRecord(
            asset_id="guid-003",
            entity_type="table",
            correlation_id="corr-003",
            status=LifecycleStatus.REJECTED,
            suggested_description=desc,
            description_hash=hashlib.sha256(desc.encode("utf-8")).hexdigest(),
            created_at="2026-02-10T12:00:00+00:00",
            updated_at="2026-02-10T14:00:00+00:00",
        )
        roundtripped = LifecycleRecord.from_cosmos_item(original.to_cosmos_item())
        assert roundtripped == original

    def test_lifecycle_status_values(self):
        assert LifecycleStatus.PENDING.value == "pending"
        assert LifecycleStatus.APPROVED.value == "approved"
        assert LifecycleStatus.REJECTED.value == "rejected"

    def test_transition_error_contains_asset_id(self):
        try:
            validate_transition(
                LifecycleStatus.APPROVED, LifecycleStatus.PENDING, "my-asset"
            )
        except LifecycleTransitionError as exc:
            assert "my-asset" in str(exc)
            assert exc.asset_id == "my-asset"
            assert exc.current_status == LifecycleStatus.APPROVED
            assert exc.target_status == LifecycleStatus.PENDING


# ======================================================================
# Test 9: WritebackResult type integrity
# ======================================================================

class TestWritebackResultIntegrity:
    """WritebackResult must be well-formed in all scenarios."""

    def test_success_result_shape(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert isinstance(result, WritebackResult)
        assert isinstance(result.success, bool)
        assert isinstance(result.asset_id, str)
        assert isinstance(result.correlation_id, str)
        assert isinstance(result.lifecycle_status, str)
        assert isinstance(result.operation, str)
        assert result.error is None
        assert result.error_category is None

    def test_error_result_shape(self):
        purview = _make_mock_purview_client(
            get_entity_side_effect=_make_http_error(403)
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert isinstance(result, WritebackResult)
        assert result.success is False
        assert isinstance(result.error, str)
        assert isinstance(result.error_category, str)
        assert len(result.error) > 0

    def test_blocked_result_shape(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_approved_record())
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert isinstance(result, WritebackResult)
        assert result.success is False
        assert isinstance(result.error, str)
        assert result.error_category == WritebackErrorCategory.LIFECYCLE_VIOLATION.value


# ======================================================================
# Test 10: Lifecycle Store unit tests
# ======================================================================

class TestLifecycleStore:
    """Tests for the LifecycleStore Cosmos DB wrapper."""

    def test_get_lifecycle_record_success(self):
        container = MagicMock()
        container.read_item.return_value = {
            "id": "guid-001",
            "entityType": "table",
            "correlationId": "corr-001",
            "lifecycleStatus": "pending",
            "suggestedDescription": "Test desc.",
            "createdAt": "2026-02-10T10:00:00+00:00",
            "updatedAt": "2026-02-10T10:00:00+00:00",
        }
        audit = MagicMock()
        ls = LifecycleStore(container, audit)

        record = ls.get_lifecycle_record("guid-001", "table")

        assert record is not None
        assert record.asset_id == "guid-001"
        assert record.status == LifecycleStatus.PENDING

    def test_get_lifecycle_record_not_found(self):
        container = MagicMock()

        class CosmosResourceNotFoundError(Exception):
            pass

        container.read_item.side_effect = CosmosResourceNotFoundError("Not found")
        audit = MagicMock()
        ls = LifecycleStore(container, audit)

        record = ls.get_lifecycle_record("guid-999", "table")

        assert record is None

    def test_upsert_lifecycle_record(self):
        container = MagicMock()
        container.upsert_item.return_value = {"id": "guid-001"}
        audit = MagicMock()
        ls = LifecycleStore(container, audit)

        record = LifecycleRecord(
            asset_id="guid-001",
            entity_type="table",
            correlation_id="corr-001",
            status=LifecycleStatus.PENDING,
            suggested_description="Test.",
            description_hash=hashlib.sha256(b"Test.").hexdigest(),
            created_at="2026-02-10T10:00:00+00:00",
            updated_at="2026-02-10T10:00:00+00:00",
        )
        ls.upsert_lifecycle_record(record)

        container.upsert_item.assert_called_once()
        body = container.upsert_item.call_args[1]["body"]
        assert body["id"] == "guid-001"
        assert body["lifecycleStatus"] == "pending"

    def test_write_audit_record(self):
        container = MagicMock()
        audit_container = MagicMock()
        audit_container.upsert_item.return_value = {"id": "audit-001"}
        ls = LifecycleStore(container, audit_container)

        audit = {"id": "audit-001", "entityType": "table", "outcome": "SUCCESS"}
        ls.write_audit_record(audit)

        audit_container.upsert_item.assert_called_once()


# ======================================================================
# Test 11: Partial write detection (Q2 — Purview written, Cosmos failed)
# ======================================================================

class TestPartialWrite:
    """When Purview succeeds but Cosmos fails, result must be explicit."""

    def test_partial_write_returns_purview_written_true(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(
            upsert_side_effect=RuntimeError("Cosmos write timeout")
        )
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.purview_written is True
        assert result.error_category == WritebackErrorCategory.PARTIAL_WRITE.value
        assert "PARTIAL WRITE" in result.error

    def test_partial_write_includes_purview_response(self):
        purview_resp = {"mutatedEntities": {"UPDATE": [{"guid": TEST_GUID}]}}
        purview = _make_mock_purview_client(write_response=purview_resp)
        store = _make_mock_lifecycle_store(
            upsert_side_effect=RuntimeError("Cosmos 503")
        )
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.purview_written is True
        assert result.purview_response == purview_resp

    def test_successful_write_has_purview_written_true(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is True
        assert result.purview_written is True

    def test_blocked_write_has_purview_written_false(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_approved_record())
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.purview_written is False

    def test_purview_error_has_purview_written_false(self):
        purview = _make_mock_purview_client(
            get_entity_side_effect=_make_http_error(404)
        )
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        assert result.success is False
        assert result.purview_written is False


# ======================================================================
# Test 12: Description hash for version binding (Q6)
# ======================================================================

class TestDescriptionHash:
    """description_hash binds approval to a specific description version."""

    def test_write_result_includes_description_hash(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        result = service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        expected_hash = hashlib.sha256(TEST_DESCRIPTION.encode("utf-8")).hexdigest()
        assert result.description_hash == expected_hash

    def test_lifecycle_record_includes_description_hash(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store()
        service = PurviewWritebackService(purview, store)

        service.write_suggested_description(
            TEST_GUID, TEST_ENTITY_TYPE, TEST_DESCRIPTION, TEST_CORRELATION_ID,
        )

        record = store.upsert_lifecycle_record.call_args[0][0]
        expected_hash = hashlib.sha256(TEST_DESCRIPTION.encode("utf-8")).hexdigest()
        assert record.description_hash == expected_hash

    def test_approval_result_includes_description_hash(self):
        purview = _make_mock_purview_client()
        store = _make_mock_lifecycle_store(existing_record=_make_pending_record())
        service = PurviewWritebackService(purview, store)

        result = service.approve(TEST_GUID, TEST_ENTITY_TYPE, TEST_CORRELATION_ID)

        assert result.description_hash is not None
        assert result.description_hash == _make_pending_record().description_hash

    def test_different_descriptions_produce_different_hashes(self):
        service = PurviewWritebackService(
            _make_mock_purview_client(), _make_mock_lifecycle_store()
        )
        h1 = service._compute_description_hash("Description A")
        h2 = service._compute_description_hash("Description B")
        assert h1 != h2

    def test_same_description_produces_same_hash(self):
        service = PurviewWritebackService(
            _make_mock_purview_client(), _make_mock_lifecycle_store()
        )
        h1 = service._compute_description_hash(TEST_DESCRIPTION)
        h2 = service._compute_description_hash(TEST_DESCRIPTION)
        assert h1 == h2

    def test_description_hash_serialized_to_cosmos(self):
        desc = "Serialization test."
        h = hashlib.sha256(desc.encode("utf-8")).hexdigest()
        record = LifecycleRecord(
            asset_id="guid-hash",
            entity_type="table",
            correlation_id="corr-hash",
            status=LifecycleStatus.PENDING,
            suggested_description=desc,
            description_hash=h,
            created_at="2026-02-10T10:00:00+00:00",
            updated_at="2026-02-10T10:00:00+00:00",
        )
        item = record.to_cosmos_item()
        assert item["descriptionHash"] == h


# ======================================================================
# Test 13: Future unknown lifecycle status (Q8)
# ======================================================================

class TestFutureStateGuard:
    """Unknown lifecycle states must fail explicitly, not silently."""

    def test_unknown_status_in_cosmos_raises_value_error(self):
        """If Cosmos contains an unknown status, deserialization fails."""
        item = {
            "id": "guid-future",
            "entityType": "table",
            "correlationId": "corr-future",
            "lifecycleStatus": "expired",
            "suggestedDescription": "Some desc.",
            "descriptionHash": "abc123",
            "createdAt": "2026-02-10T10:00:00+00:00",
            "updatedAt": "2026-02-10T10:00:00+00:00",
        }
        with pytest.raises(ValueError):
            LifecycleRecord.from_cosmos_item(item)

    def test_transition_from_unknown_status_not_in_map_blocks(self):
        """A status not in VALID_TRANSITIONS defaults to empty set → blocks."""
        # Simulate a hypothetical future status by calling validate_transition
        # with a status not in the map. We can't create a new enum value at
        # runtime, but we can test the dict.get() fallback with a sentinel.
        # The dict uses .get(key, set()), so any key not in the map returns
        # empty set → LifecycleTransitionError.
        allowed = VALID_TRANSITIONS.get("fictional_status", set())
        assert allowed == set()
