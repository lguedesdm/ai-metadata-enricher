# Incremental Indexing Strategy Definition (Blob → Azure AI Search)

**Version**: v1.0.0 (Conceptual Contract)  
**Status**: Consolidated from existing freezes; no new commitments

## Purpose and Scope

This document consolidates the minimal conceptual contract for incremental indexing from Azure Blob Storage to Azure AI Search, aligned with the existing design-time artifacts and the Execution Plan. It makes explicit behaviors that were previously implicit. It does not introduce operational specifics.

References:
- Search index design: [docs/search-index-design.md](docs/search-index-design.md)
- Architecture overview: [docs/architecture.md](docs/architecture.md)
- ADR (Search index design freeze): [docs/adr/0003-search-index-design-freeze-v1.md](docs/adr/0003-search-index-design-freeze-v1.md)
- Blob path lookup (conceptual routing): [contracts/lookups/lookup.json](contracts/lookups/lookup.json)

## Incremental Signal and Eligibility

- **Change signal**: `lastUpdated` (ISO 8601 date-time) as provided by the source system, per frozen schemas.
- **Eligibility for reindex**:
  - New documents: not yet present in the index → eligible.
  - Modified documents: `lastUpdated` indicates a newer change than the last indexed run → eligible.
  - Unchanged documents: `lastUpdated` not newer than the last indexed run → ignored in incremental runs.

## Index Update Behavior (Incremental)

- **Incremental-only by default**: Normal executions update the index for eligible items (new/modified) without recreating the entire index.
- **No full rebuild in normal runs**: The index is not dropped/recreated during routine incremental processing.
- **Document continuity**: Documents already present and not eligible (unchanged) remain retrievable and searchable.

## Full Rebuild Conditions (Explicit Only)

Full index rebuilds are permitted only under explicit, pre-defined conditions, consistent with the frozen search index design:
- **Breaking design changes** to the index schema/properties (e.g., field removals/renames, type changes, primary key changes, vector dimension changes), as governed in [docs/search-index-design.md](docs/search-index-design.md) and [docs/adr/0003-search-index-design-freeze-v1.md](docs/adr/0003-search-index-design-freeze-v1.md).
- **Schema contract changes** that invalidate existing indexed representation (major version updates to source schemas) per governance processes documented elsewhere.

Routine content updates or additions do not trigger full rebuilds.

## RAG Compatibility Guarantees

- **Retrievability preserved**: Incremental updates do not delete or hide previously indexed, valid documents. Older documents remain available for RAG retrieval unless explicitly archived by upstream processes (see conceptual routing in [contracts/lookups/lookup.json](contracts/lookups/lookup.json)).
- **Field alignment**: RAG-critical fields (`content`, semantic configuration, vector field) remain consistent with the frozen search index design; incremental updates populate these fields for eligible documents without affecting others.

## Alignment to Execution Plan

This conceptual contract prepares, but does not anticipate, the following Execution Plan tasks:
- Delta ingestion and indexer behavior validation.
- Compatibility validation with the RAG retrieval strategy.

## Explicit Exclusions (Out of Scope Here)

This document intentionally does not define operational details. The following topics are out of scope and will be covered by dedicated tasks:
- Persistent state design (e.g., Cosmos DB containers, partition keys, TTL).
- Upsert semantics at API/SDK level (e.g., `mergeOrUpload`).
- Idempotence, hashing, deduplication, or reprocessing policies.
- Backfill strategies, retries, dead-letter queues, observability.
- New freezes, versioning changes, or ADRs.
- Any implementation in Bicep, code, or Azure Portal.

---

**Summary**: Incremental indexing uses `lastUpdated` to include only new/modified blobs in normal runs, preserves existing indexed documents for RAG, and permits full rebuilds only under explicit, governed breaking-change scenarios. This consolidates existing design references into a single, clear conceptual contract for engineers.
