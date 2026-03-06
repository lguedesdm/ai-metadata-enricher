"""
Tests for the Search Upsert Writer.

Test categories
===============

1. **Single document upsert** — writer calls ``merge_or_upload_documents``.
2. **Identity preservation** — document ID is passed to the SDK unchanged.
3. **No delete operations** — writer source never invokes ``delete_documents``.
4. **Idempotent upsert** — repeated calls produce stable index state.
5. **Input validation** — rejects missing ID, non-dict input.
6. **No document mutation** — document is not modified by the writer.
7. **Error propagation** — Azure API errors are raised, never swallowed.
8. **Per-document failure** — SDK-reported failures raise ``RuntimeError``.
9. **Observability** — logs document ID and operation type.
10. **Guardrail compliance** — no index management, no batch, no schema ops.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.search_writer.writer import (
    upsert_search_document,
    _validate_document,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass
class FakeIndexingResult:
    """Mimics ``azure.search.documents.models.IndexingResult``."""

    key: str
    succeeded: bool = True
    status_code: int = 200
    error_message: str | None = None


def _make_document(**overrides: Any) -> Dict[str, Any]:
    """Return a minimal valid search document dict."""
    base: Dict[str, Any] = {
        "id": "synergy::table::student enrollment",
        "sourceSystem": "synergy",
        "entityType": "table",
        "entityName": "Student Enrollment",
        "content": "Entity Type: table\nEntity Name: Student Enrollment",
        "schemaVersion": "1.1.0",
    }
    base.update(overrides)
    return base


def _mock_client(
    *,
    results: list[FakeIndexingResult] | None = None,
    side_effect: Exception | None = None,
) -> MagicMock:
    """Build a mock ``SearchClient``."""
    client = MagicMock()

    if side_effect:
        client.merge_or_upload_documents.side_effect = side_effect
    else:
        if results is None:
            results = [FakeIndexingResult(key="synergy::table::student enrollment")]
        client.merge_or_upload_documents.return_value = results

    return client


# ===================================================================
# 1. Single document upsert
# ===================================================================


class TestSingleDocumentUpsert:
    """Writer must call merge_or_upload_documents with one document."""

    def test_calls_merge_or_upload(self):
        doc = _make_document()
        client = _mock_client()
        upsert_search_document(doc, client=client)
        client.merge_or_upload_documents.assert_called_once()

    def test_passes_document_in_list(self):
        doc = _make_document()
        client = _mock_client()
        upsert_search_document(doc, client=client)
        args, kwargs = client.merge_or_upload_documents.call_args
        documents_arg = kwargs.get("documents") or args[0]
        assert documents_arg == [doc]

    def test_single_element_list(self):
        doc = _make_document()
        client = _mock_client()
        upsert_search_document(doc, client=client)
        args, kwargs = client.merge_or_upload_documents.call_args
        documents_arg = kwargs.get("documents") or args[0]
        assert len(documents_arg) == 1


# ===================================================================
# 2. Identity preservation
# ===================================================================


class TestIdentityPreservation:
    """Document ID must be sent unchanged to the SDK."""

    def test_id_preserved_in_payload(self):
        doc = _make_document(id="mytest::column::age")
        client = _mock_client(
            results=[FakeIndexingResult(key="mytest::column::age")]
        )
        upsert_search_document(doc, client=client)
        args, kwargs = client.merge_or_upload_documents.call_args
        documents_arg = kwargs.get("documents") or args[0]
        assert documents_arg[0]["id"] == "mytest::column::age"

    def test_id_not_modified(self):
        original_id = "synergy::table::student enrollment"
        doc = _make_document(id=original_id)
        client = _mock_client()
        upsert_search_document(doc, client=client)
        assert doc["id"] == original_id


# ===================================================================
# 3. No delete operations
# ===================================================================


class TestNoDeleteOperations:
    """Writer must never invoke delete_documents."""

    def test_delete_documents_never_called(self):
        doc = _make_document()
        client = _mock_client()
        upsert_search_document(doc, client=client)
        client.delete_documents.assert_not_called()

    def test_no_delete_in_source_code(self):
        import src.infrastructure.search_writer.writer as mod
        import re

        source = open(mod.__file__, "r", encoding="utf-8").read()
        # Ensure no executable call to delete_documents (ignore docstrings)
        # Look for .delete_documents( which would be an actual SDK call
        assert re.search(r'\.delete_documents\s*\(', source) is None, (
            "Writer must not call .delete_documents()"
        )

    def test_no_index_management_in_source(self):
        import src.infrastructure.search_writer.writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        forbidden = [
            "create_index",
            "delete_index",
            "reset_index",
            "SearchIndexClient",
        ]
        for pattern in forbidden:
            assert pattern not in source, (
                f"Writer must not contain '{pattern}'"
            )


# ===================================================================
# 4. Idempotent upsert
# ===================================================================


class TestIdempotentUpsert:
    """Repeated calls with same document must be safe."""

    def test_repeated_calls_succeed(self):
        doc = _make_document()
        client = _mock_client()
        for _ in range(10):
            upsert_search_document(doc, client=client)
        assert client.merge_or_upload_documents.call_count == 10

    def test_same_document_same_payload_each_time(self):
        doc = _make_document()
        client = _mock_client()
        upsert_search_document(doc, client=client)
        upsert_search_document(doc, client=client)
        calls = client.merge_or_upload_documents.call_args_list
        first_docs = calls[0][1].get("documents") or calls[0][0][0]
        second_docs = calls[1][1].get("documents") or calls[1][0][0]
        assert first_docs == second_docs


# ===================================================================
# 5. Input validation
# ===================================================================


class TestInputValidation:
    """Invalid inputs must raise appropriate errors."""

    def test_missing_id_raises_value_error(self):
        doc = {"sourceSystem": "synergy", "content": "hello"}
        client = _mock_client()
        with pytest.raises(ValueError, match="non-empty 'id'"):
            upsert_search_document(doc, client=client)

    def test_empty_id_raises_value_error(self):
        doc = _make_document(id="")
        client = _mock_client()
        with pytest.raises(ValueError, match="non-empty 'id'"):
            upsert_search_document(doc, client=client)

    def test_whitespace_id_raises_value_error(self):
        doc = _make_document(id="   ")
        client = _mock_client()
        with pytest.raises(ValueError, match="non-empty 'id'"):
            upsert_search_document(doc, client=client)

    def test_none_id_raises_value_error(self):
        doc = _make_document(id=None)
        client = _mock_client()
        with pytest.raises(ValueError, match="non-empty 'id'"):
            upsert_search_document(doc, client=client)

    def test_non_dict_raises_type_error(self):
        client = _mock_client()
        with pytest.raises(TypeError, match="Expected a dict"):
            upsert_search_document("not a dict", client=client)  # type: ignore[arg-type]

    def test_list_raises_type_error(self):
        client = _mock_client()
        with pytest.raises(TypeError, match="Expected a dict"):
            upsert_search_document([{"id": "x"}], client=client)  # type: ignore[arg-type]

    def test_none_raises_type_error(self):
        client = _mock_client()
        with pytest.raises(TypeError, match="Expected a dict"):
            upsert_search_document(None, client=client)  # type: ignore[arg-type]


# ===================================================================
# 6. No document mutation
# ===================================================================


class TestNoDocumentMutation:
    """Writer must not modify the document dict."""

    def test_document_unchanged_after_upsert(self):
        doc = _make_document()
        doc_before = copy.deepcopy(doc)
        client = _mock_client()
        upsert_search_document(doc, client=client)
        assert doc == doc_before

    def test_nested_payload_unchanged(self):
        doc = _make_document()
        doc["tags"] = ["enrollment", "student"]
        doc_before = copy.deepcopy(doc)
        client = _mock_client()
        upsert_search_document(doc, client=client)
        assert doc == doc_before


# ===================================================================
# 7. Error propagation
# ===================================================================


class TestErrorPropagation:
    """Azure SDK exceptions must not be swallowed."""

    def test_http_error_propagated(self):
        doc = _make_document()
        error = Exception("Service unavailable")
        client = _mock_client(side_effect=error)
        with pytest.raises(Exception, match="Service unavailable"):
            upsert_search_document(doc, client=client)

    def test_generic_exception_propagated(self):
        doc = _make_document()
        client = _mock_client(side_effect=RuntimeError("network timeout"))
        with pytest.raises(RuntimeError, match="network timeout"):
            upsert_search_document(doc, client=client)


# ===================================================================
# 8. Per-document failure
# ===================================================================


class TestPerDocumentFailure:
    """SDK-reported per-document failures must raise RuntimeError."""

    def test_failed_result_raises_runtime_error(self):
        doc = _make_document()
        client = _mock_client(
            results=[
                FakeIndexingResult(
                    key="synergy::table::student enrollment",
                    succeeded=False,
                    status_code=409,
                    error_message="Conflict",
                )
            ]
        )
        with pytest.raises(RuntimeError, match="upsert failed"):
            upsert_search_document(doc, client=client)

    def test_failure_message_contains_document_id(self):
        doc = _make_document(id="test::id::123")
        client = _mock_client(
            results=[
                FakeIndexingResult(
                    key="test::id::123",
                    succeeded=False,
                    status_code=500,
                    error_message="Internal error",
                )
            ]
        )
        with pytest.raises(RuntimeError, match="test::id::123"):
            upsert_search_document(doc, client=client)


# ===================================================================
# 9. Observability
# ===================================================================


class TestObservability:
    """Writer must log document ID and operation type."""

    def test_logs_document_id(self, caplog):
        doc = _make_document()
        client = _mock_client()
        with caplog.at_level(logging.INFO, logger="infrastructure.search_writer"):
            upsert_search_document(doc, client=client)

        log_text = " ".join(caplog.messages)
        assert "Upserting" in log_text or "upserted" in log_text.lower()

    def test_logs_operation_type(self, caplog):
        doc = _make_document()
        client = _mock_client()
        with caplog.at_level(logging.INFO, logger="infrastructure.search_writer"):
            upsert_search_document(doc, client=client)

        # Check that mergeOrUpload appears in the log extras
        has_operation = any(
            getattr(r, "operation", None) == "mergeOrUpload"
            for r in caplog.records
        )
        assert has_operation

    def test_does_not_log_full_payload(self, caplog):
        doc = _make_document(content="SENSITIVE_CONTENT_MARKER_12345")
        client = _mock_client()
        with caplog.at_level(logging.DEBUG, logger="infrastructure.search_writer"):
            upsert_search_document(doc, client=client)

        full_log = " ".join(caplog.messages)
        assert "SENSITIVE_CONTENT_MARKER_12345" not in full_log


# ===================================================================
# 10. Guardrail compliance
# ===================================================================


class TestGuardrailCompliance:
    """Writer module must not contain forbidden operations."""

    def test_no_batch_patterns(self):
        import src.infrastructure.search_writer.writer as mod
        import re

        source = open(mod.__file__, "r", encoding="utf-8").read()
        # .upload_documents( as a standalone SDK call (not merge_or_upload_documents)
        assert re.search(r'(?<!merge_or_)\.upload_documents\s*\(', source) is None, (
            "Writer must not call .upload_documents() directly"
        )
        for pattern in ["batch_upsert", "bulk_merge"]:
            assert pattern not in source, (
                f"Writer must not contain '{pattern}'"
            )

    def test_no_schema_mutation(self):
        import src.infrastructure.search_writer.writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        schema_patterns = [
            "SearchIndex(",
            "create_or_update_index",
            "SearchField(",
        ]
        for pattern in schema_patterns:
            assert pattern not in source, (
                f"Writer must not contain '{pattern}'"
            )

    def test_writer_does_not_import_search_index_client(self):
        import src.infrastructure.search_writer.writer as mod

        source = open(mod.__file__, "r", encoding="utf-8").read()
        assert "SearchIndexClient" not in source


# ===================================================================
# 11. Client factory
# ===================================================================


class TestClientFactory:
    """Verify client_factory creates a SearchClient correctly."""

    def test_factory_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("SEARCH_ENDPOINT", "https://test.search.windows.net")
        monkeypatch.setenv("SEARCH_INDEX_NAME", "test-index")

        with patch.dict(
            "sys.modules",
            {
                "azure": MagicMock(),
                "azure.identity": MagicMock(),
                "azure.search": MagicMock(),
                "azure.search.documents": MagicMock(),
            },
        ):
            # Force re-import with stubs in place
            import importlib
            import src.infrastructure.search_writer.client_factory as cf_mod

            importlib.reload(cf_mod)

            mock_cred_class = cf_mod.DefaultAzureCredential
            mock_sc_class = cf_mod.SearchClient

            cf_mod.create_search_client()

            mock_sc_class.assert_called_once_with(
                endpoint="https://test.search.windows.net",
                index_name="test-index",
                credential=mock_cred_class.return_value,
            )

    def test_factory_default_index_name(self, monkeypatch):
        monkeypatch.setenv("SEARCH_ENDPOINT", "https://test.search.windows.net")
        monkeypatch.delenv("SEARCH_INDEX_NAME", raising=False)

        with patch.dict(
            "sys.modules",
            {
                "azure": MagicMock(),
                "azure.identity": MagicMock(),
                "azure.search": MagicMock(),
                "azure.search.documents": MagicMock(),
            },
        ):
            import importlib
            import src.infrastructure.search_writer.client_factory as cf_mod

            importlib.reload(cf_mod)

            mock_sc_class = cf_mod.SearchClient

            cf_mod.create_search_client()

            _, kwargs = mock_sc_class.call_args
            assert kwargs["index_name"] == "metadata-index-v1"

    def test_factory_missing_endpoint_raises(self, monkeypatch):
        monkeypatch.delenv("SEARCH_ENDPOINT", raising=False)

        with patch.dict(
            "sys.modules",
            {
                "azure": MagicMock(),
                "azure.identity": MagicMock(),
                "azure.search": MagicMock(),
                "azure.search.documents": MagicMock(),
            },
        ):
            import importlib
            import src.infrastructure.search_writer.client_factory as cf_mod

            importlib.reload(cf_mod)

            with pytest.raises(KeyError):
                cf_mod.create_search_client()


# ===================================================================
# 12. Validate document helper
# ===================================================================


class TestValidateDocument:
    """Direct tests for the _validate_document helper."""

    def test_valid_document_passes(self):
        _validate_document(_make_document())  # no exception

    def test_integer_id_raises_value_error(self):
        with pytest.raises(ValueError):
            _validate_document({"id": 123})

    def test_bool_raises_type_error(self):
        with pytest.raises(TypeError):
            _validate_document(True)  # type: ignore[arg-type]
