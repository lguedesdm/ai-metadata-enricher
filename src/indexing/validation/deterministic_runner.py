"""
Deterministic Pipeline Runner — executes the element-level ingestion
pipeline end-to-end using in-memory mocks for external services.

Runs the following stages sequentially for each element:

    Blob JSON → Element Splitter → Identity → Hash → State Comparison
        → Search Document Builder → Search Upsert Writer → State Update

External dependencies (Azure Search, Cosmos DB) are replaced with
in-memory stubs so that the pipeline can be validated deterministically
without any Azure SDK or network calls.

Design constraints
==================

- **No Azure calls** — uses in-memory state store and search index stubs.
- **No randomness** — no uuid4, random, or non-UTC timestamps.
- **Observable** — every element emits a structured ``ElementResult``.
- **Immutable results** — ``PipelineResult`` and ``ElementResult`` are frozen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.domain.element_splitter import split_elements, generate_element_id
from src.domain.element_hashing import compute_element_hash
from src.domain.element_state import compare_element_state, StateDecision
from src.domain.search_document.builder import build_search_document
from src.domain.search_document.models import SCHEMA_FIELDS

logger = logging.getLogger("indexing.validation.runner")


# -----------------------------------------------------------------------
# Result containers
# -----------------------------------------------------------------------


@dataclass(frozen=True)
class ElementResult:
    """Immutable result of processing one element through the pipeline.

    Attributes:
        element_id: Deterministic identity (``{source}::{type}::{name}``).
        element_hash: SHA-256 hex digest of the canonical payload.
        decision: ``"REPROCESS"`` or ``"SKIP"``.
        index_operation: ``"UPSERT"`` if indexed, ``"NONE"`` if skipped.
        state_write: ``True`` if state was persisted.
    """

    element_id: str
    element_hash: str
    decision: str
    index_operation: str
    state_write: bool


@dataclass(frozen=True)
class PipelineResult:
    """Immutable result of a full pipeline execution.

    Attributes:
        elements_processed: Total number of elements evaluated.
        elements_skipped: Number of elements with decision SKIP.
        elements_reprocessed: Number of elements with decision REPROCESS.
        documents_upserted: Number of documents sent to the search index.
        documents_unchanged: Number of elements that were not re-indexed.
        element_results: Per-element detailed results.
    """

    elements_processed: int
    elements_skipped: int
    elements_reprocessed: int
    documents_upserted: int
    documents_unchanged: int
    element_results: List[ElementResult] = field(default_factory=list)


# -----------------------------------------------------------------------
# In-memory stubs
# -----------------------------------------------------------------------


class InMemoryStateStore:
    """In-memory replacement for CosmosStateStore.

    Stores state records keyed by ``(id, entityType)`` to mirror
    Cosmos DB's composite key behaviour.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    def get_state(self, asset_id: str, entity_type: str) -> Optional[Dict[str, Any]]:
        return self._store.get(f"{asset_id}|{entity_type}")

    def upsert_state(self, item: Dict[str, Any]) -> Dict[str, Any]:
        key = f"{item['id']}|{item['entityType']}"
        self._store[key] = item
        return item

    def get_stored_hash(self, element_id: str, entity_type: str) -> Optional[str]:
        """Convenience: return the stored contentHash or None."""
        item = self.get_state(element_id, entity_type)
        return item.get("contentHash") if item else None

    @property
    def records(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._store)

    def clear(self) -> None:
        self._store.clear()


class InMemorySearchIndex:
    """In-memory replacement for Azure AI Search index.

    Records every upserted document, keyed by document ``id``.
    """

    def __init__(self) -> None:
        self._documents: Dict[str, Dict[str, Any]] = {}
        self._upsert_count: int = 0

    def merge_or_upload(self, document: Dict[str, Any]) -> None:
        self._documents[document["id"]] = document
        self._upsert_count += 1

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        return self._documents.get(doc_id)

    @property
    def documents(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._documents)

    @property
    def upsert_count(self) -> int:
        return self._upsert_count

    def reset_count(self) -> None:
        self._upsert_count = 0

    @property
    def document_count(self) -> int:
        return len(self._documents)


# -----------------------------------------------------------------------
# Pipeline runner
# -----------------------------------------------------------------------


class DeterministicRunner:
    """Execute the full element-level ingestion pipeline deterministically.

    Uses ``InMemoryStateStore`` and ``InMemorySearchIndex`` to validate
    pipeline behaviour without Azure infrastructure.

    Usage::

        runner = DeterministicRunner()
        result = runner.run(blob_json)
        # result.elements_processed == 5
    """

    def __init__(
        self,
        state_store: Optional[InMemoryStateStore] = None,
        search_index: Optional[InMemorySearchIndex] = None,
    ) -> None:
        self.state_store = state_store or InMemoryStateStore()
        self.search_index = search_index or InMemorySearchIndex()

    def run(self, blob_json: Dict[str, Any]) -> PipelineResult:
        """Execute the full pipeline on *blob_json*.

        Stages per element:
            1. Split → ContextElement
            2. generate_element_id()
            3. compute_element_hash()
            4. compare_element_state() using stored hash
            5. If REPROCESS: build_search_document() → upsert → state update
            6. If SKIP: record as unchanged

        Returns:
            ``PipelineResult`` with aggregate metrics and per-element details.
        """
        # Stage 1: Element Splitter
        elements = split_elements(blob_json)

        element_results: List[ElementResult] = []
        skipped = 0
        reprocessed = 0
        upserted = 0
        unchanged = 0

        for element in elements:
            # Stage 2: Deterministic Identity
            element_id = generate_element_id(element)

            # Stage 3: Deterministic Hash
            content_hash = compute_element_hash(element)

            # Stage 4: State Comparison
            entity_type = element.element_type
            stored_hash = self.state_store.get_stored_hash(
                element_id, entity_type
            )
            comparison = compare_element_state(element, stored_hash)

            decision = comparison.decision.value  # "SKIP" or "REPROCESS"

            if comparison.decision == StateDecision.SKIP:
                # Element unchanged — do not index or update state
                skipped += 1
                unchanged += 1

                element_results.append(ElementResult(
                    element_id=element_id,
                    element_hash=content_hash,
                    decision=decision,
                    index_operation="NONE",
                    state_write=False,
                ))

                logger.info(
                    "Element skipped (unchanged)",
                    extra={
                        "elementId": element_id,
                        "hash": content_hash[:16] + "...",
                        "decision": "SKIP",
                        "indexOperation": "NONE",
                    },
                )

            else:
                # REPROCESS — build, upsert, update state
                # Stage 5: Search Document Builder
                search_doc = build_search_document(element, element_id)

                # Stage 6: Search Upsert (in-memory)
                self.search_index.merge_or_upload(search_doc)
                upserted += 1

                # Stage 7: State Update (in-memory)
                self.state_store.upsert_state({
                    "id": element_id,
                    "entityType": entity_type,
                    "sourceSystem": element.source_system,
                    "contentHash": content_hash,
                    "lastProcessed": "deterministic-run",
                })

                reprocessed += 1

                element_results.append(ElementResult(
                    element_id=element_id,
                    element_hash=content_hash,
                    decision=decision,
                    index_operation="UPSERT",
                    state_write=True,
                ))

                logger.info(
                    "Element reprocessed",
                    extra={
                        "elementId": element_id,
                        "hash": content_hash[:16] + "...",
                        "decision": "REPROCESS",
                        "indexOperation": "UPSERT",
                    },
                )

        return PipelineResult(
            elements_processed=len(elements),
            elements_skipped=skipped,
            elements_reprocessed=reprocessed,
            documents_upserted=upserted,
            documents_unchanged=unchanged,
            element_results=element_results,
        )
