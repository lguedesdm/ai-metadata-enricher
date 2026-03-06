"""
Search Upsert Writer — controlled single-document upsert into Azure AI Search.

Performs exactly one ``mergeOrUpload`` operation per call.  This writer
is the **only** component in the pipeline that writes to the search index.

Pipeline position::

    … → Search Document Builder → **Search Upsert Writer** → State Update

Design constraints
==================

- **Single-document granularity** — one call = one ``mergeOrUpload``.
- **No deletions** — ``delete_documents`` is never called.
- **No index management** — no create / delete / rebuild / schema changes.
- **No mutation** — the document payload is sent as-is; never modified.
- **No recomputation** — identity, hash, and state comparison are upstream.
- **Idempotent** — ``mergeOrUpload`` is inherently idempotent.
- **Observable** — logs document ID and operation type, never full payload.
- **Fail-loud** — Azure API errors are raised, never swallowed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from azure.search.documents import SearchClient

logger = logging.getLogger("infrastructure.search_writer")


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------


def upsert_search_document(
    document: Dict[str, Any],
    *,
    client: "SearchClient",
) -> None:
    """Upsert a single search document via ``mergeOrUpload``.

    Sends exactly one document to Azure AI Search using the
    ``merge_or_upload_documents`` SDK method.  The operation is
    idempotent: repeated calls with an identical document converge
    to the same index state.

    Args:
        document: A search document dictionary produced by the
            Search Document Builder.  Must contain an ``"id"`` key.
        client: An Azure AI Search ``SearchClient`` obtained from
            ``create_search_client()``.

    Raises:
        TypeError: If *document* is not a ``dict``.
        ValueError: If *document* is missing the ``"id"`` key or its
            value is empty.
        RuntimeError: If the Azure API reports a per-document failure
            (status ``False`` in the result).
        azure.core.exceptions.HttpResponseError: Propagated on
            HTTP-level failures from the Azure SDK.
    """
    _validate_document(document)

    document_id: str = document["id"]

    logger.info(
        "Upserting search document",
        extra={
            "documentId": document_id,
            "operation": "mergeOrUpload",
        },
    )

    result = client.merge_or_upload_documents(documents=[document])

    # The SDK returns a list of IndexingResult objects — one per document.
    # Each has .succeeded (bool), .key (str), .status_code (int),
    # and .error_message (str | None).
    for item in result:
        if not item.succeeded:
            raise RuntimeError(
                f"Azure AI Search upsert failed for document "
                f"'{document_id}': status_code={item.status_code}, "
                f"error={item.error_message}"
            )

    logger.info(
        "Search document upserted successfully",
        extra={
            "documentId": document_id,
            "operation": "mergeOrUpload",
        },
    )


# -----------------------------------------------------------------------
# Internal validation
# -----------------------------------------------------------------------


def _validate_document(document: Any) -> None:
    """Raise if *document* is not a valid search document dict.

    Checks:
        1. Must be a ``dict``.
        2. Must contain a non-empty ``"id"`` key.
    """
    if not isinstance(document, dict):
        raise TypeError(
            f"Expected a dict for the search document, "
            f"got {type(document).__name__}"
        )

    doc_id = document.get("id")
    if not doc_id or not isinstance(doc_id, str) or not doc_id.strip():
        raise ValueError(
            "Search document must contain a non-empty 'id' key"
        )
