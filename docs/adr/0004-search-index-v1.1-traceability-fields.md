# ADR 0004 — Search Index v1.1.0: Add Traceability and Hashing Fields

## Status

Proposed

## Date

2026-03-06

## Decision Makers

- Architecture Team
- Data Engineering Team
- AI/ML Team
- Search & Discovery Team

## Context

### Problem Statement

The Search Document Builder (Task 5 in the ingestion pipeline) is responsible for converting `ContextElement` objects into Azure AI Search documents aligned with the frozen unified index schema (v1.0.0, per ADR-0003).

During implementation of the builder, three fields required by the pipeline design were identified as **absent** from the frozen index schema:

| Required Field | Purpose | Present in Schema v1.0.0? |
|----------------|---------|---------------------------|
| `hash` | Content hash for deterministic change detection. The pipeline's `compute_element_hash()` produces a SHA-256 digest that must persist in the search document to enable hash-based comparisons without Cosmos DB lookup. | **No** |
| `blobPath` | Path to the originating Azure Blob Storage file. Required for traceability from indexed document back to the raw ingestion source. | **No** |
| `originalSourceFile` | Original filename of the source export (e.g., `synergy-export-2026-03-01.json`). Required for audit, lineage, and incident investigation. | **No** |

### Why This Decision Is Needed Now

- Task 5 (Search Document Builder) cannot be implemented without these fields because the schema validation gate (`document_fields ⊆ schema_fields`) would reject documents containing them.
- The pipeline's deterministic change detection relies on storing `hash` alongside the indexed document.
- Public-sector compliance (FERPA, FedRAMP) requires full traceability from indexed metadata back to original source files.
- The schema freeze governance (ADR-0003) explicitly requires an ADR before adding new fields.

### Forces

- **Schema stability**: The frozen schema exists to prevent uncontrolled drift and protect AI contracts.
- **Pipeline correctness**: The deterministic pipeline requires `hash` to be persisted for state comparison without external state store queries.
- **Traceability**: Audit and compliance require `blobPath` and `originalSourceFile` for lineage from search documents to raw ingestion blobs.
- **ADR governance**: ADR-0003 mandates that new fields require a minor version ADR with impact analysis.

### Compatibility Analysis

Per ADR-0003 Section "Non-Breaking Changes":
> Adding new optional fields (from new schema fields) — may be added in minor versions (v1.1.0)

All three proposed fields are **optional** and **additive**. They do not modify existing fields, types, or behaviors. This qualifies as a non-breaking minor version change.

## Considered Options

### Option 1: Add Three Optional Fields to Schema v1.1.0

**Description**: Add `hash`, `blobPath`, and `originalSourceFile` as optional, non-searchable fields to the index schema. Bump schema version to v1.1.0.

**Proposed Field Definitions**:

| Field Name | Type | Searchable | Filterable | Facetable | Sortable | Retrievable | Purpose |
|------------|------|------------|------------|-----------|----------|-------------|---------|
| `hash` | `Edm.String` | No | Yes | No | No | Yes | SHA-256 content hash for deterministic change detection. Filterable for exact-match state lookups. |
| `blobPath` | `Edm.String` | No | Yes | No | No | Yes | Azure Blob Storage path of the original ingestion file. Filterable for source tracing. |
| `originalSourceFile` | `Edm.String` | No | Yes | No | No | Yes | Original source export filename. Filterable for audit and incident investigation. |

**Pros**:
- Enables deterministic hash-based change detection within the search index
- Provides full traceability from indexed documents to raw source blobs
- Satisfies FERPA/FedRAMP audit requirements
- Non-breaking change under ADR-0003 governance rules
- Unblocks Task 5 (Search Document Builder) implementation
- All three fields are non-searchable, adding no overhead to full-text or semantic search
- Filterable flag enables precise lookups for compliance and debugging

**Cons**:
- Slightly increases index storage per document (three additional string fields)
- Requires reindexing existing documents to populate new fields (manageable during initial deployment since no production data exists yet)
- Adds governance documentation overhead

### Option 2: Store Hash and Traceability in Cosmos DB Only

**Description**: Do not add these fields to the search index. Store `hash`, `blobPath`, and `originalSourceFile` exclusively in Cosmos DB state records.

**Pros**:
- No schema change required
- Index remains minimal

**Cons**:
- Breaks the self-contained traceability requirement for search documents
- Hash-based filtering requires cross-referencing Cosmos DB on every query
- Compliance auditors cannot trace indexed documents to source files without a separate system join
- Increases operational complexity for incident investigation
- Search documents lose provenance information

### Option 3: Defer and Build Without These Fields

**Description**: Implement the Search Document Builder using only existing v1.0.0 fields. Omit hash and traceability information from search documents entirely.

**Pros**:
- No schema change required
- Fastest implementation path

**Cons**:
- Pipeline loses deterministic hash persistence in search documents
- No traceability from search results to source blobs
- Fails compliance requirements for audit lineage
- Future addition would still require this same ADR process

## Decision

**Proposed: Option 1 — Add three optional fields to schema v1.1.0.**

The search index schema should be updated from v1.0.0 to v1.1.0 with the addition of `hash`, `blobPath`, and `originalSourceFile` as optional, non-searchable, filterable fields.

### Rationale

1. **Non-breaking**: Adding optional fields is explicitly permitted as a minor version change under ADR-0003.
2. **Pipeline integrity**: The deterministic ingestion pipeline requires `hash` persistence for state comparison.
3. **Compliance**: Public-sector governance requires full traceability from indexed documents to source files.
4. **No search impact**: All three fields are non-searchable, adding zero overhead to keyword, vector, or semantic search operations.
5. **Pre-production timing**: No existing production documents require backfill — the fields will be populated from the initial deployment.

### Updated Schema Summary (v1.1.0)

v1.0.0 fields (17) remain unchanged. Three new optional fields added:

| # | Field | Category |
|---|-------|----------|
| 18 | `hash` | Change Detection |
| 19 | `blobPath` | Traceability |
| 20 | `originalSourceFile` | Traceability |

Total: 20 fields.

## Consequences

### Positive Consequences

- **Unblocks Task 5**: Search Document Builder can be implemented with full field coverage
- **Deterministic pipeline**: Hash persistence enables self-contained change detection
- **Audit compliance**: Full traceability chain from search document → blob → source file
- **Minimal impact**: Non-searchable fields add no query performance overhead
- **Governance compliance**: Change follows established ADR process

### Negative Consequences

- **Minor storage increase**: Three additional string fields per document (negligible for expected dataset sizes)
- **Schema version management**: `schemaVersion` field in documents should reflect `1.1.0`

### Neutral Consequences

- **Reindexing**: Not applicable — no production data exists at time of this decision
- **AI contracts**: Not affected — no AI prompts or validation rules reference these fields

## Implementation

Upon approval of this ADR:

1. Update [docs/search-index-design.md](../search-index-design.md) to add the three new fields under a new "Traceability and Change Detection Fields" section
2. Bump the design version from v1.0.0 to v1.1.0
3. Update Bicep templates in `infrastructure/bicep/` to include the new fields in the index definition
4. Proceed with Task 5 (Search Document Builder) implementation using all 20 schema fields

## Follow-up Actions

- [ ] Obtain Architecture Team approval for this ADR
- [ ] Obtain AI/ML Team approval for this ADR
- [ ] Update search-index-design.md with new fields (v1.1.0)
- [ ] Update Bicep index definition to include new fields
- [ ] Implement Task 5: Search Document Builder
- [ ] Add schema validation test ensuring builder output matches v1.1.0 schema

## Related Decisions

- [ADR-0003: Search Index Design Freeze v1.0.0](0003-search-index-design-freeze-v1.md) — Governs changes to the frozen index schema
- [ADR-0002: Schema Contract Freeze v1.0.0](0002-schema-contract-freeze-v1.md) — Source schemas from which index fields are derived
- [ADR-0001: Use Bicep as Exclusive IaC](0001-use-bicep-as-exclusive-iac.md) — Index deployed via Bicep templates

## References

- [Search Index Design v1.0.0](../search-index-design.md)
- [Synergy Export Schema v1.0.0](../../contracts/schemas/synergy-export.schema.json)
- [Zipline Export Schema v1.0.0](../../contracts/schemas/zipline-export.schema.json)
- [AI Behavior Contracts v1.0.0](../../contracts/FREEZE-v1.0.0.md)

## Notes

- All three proposed fields are **not present** in the source export schemas (synergy/zipline). They are pipeline-generated metadata added during ingestion.
- The `hash` field stores the output of `compute_element_hash()` (SHA-256 hex digest, 64 characters).
- The `blobPath` field stores the Azure Blob Storage URI or relative path (e.g., `exports/synergy/synergy-export-2026-03-01.json`).
- The `originalSourceFile` field stores the filename only (e.g., `synergy-export-2026-03-01.json`).

---

**Review Date**: 2026-03-13  
**Last Updated**: 2026-03-06  
**Version**: 0004-v1
