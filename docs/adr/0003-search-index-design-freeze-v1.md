# ADR 0003 — Azure AI Search Index Design Freeze v1.0.0

## Status

Accepted

## Date

2026-01-14

## Decision Makers

- Architecture Team
- Data Engineering Team
- AI/ML Team
- Search & Discovery Team

## Context

The AI Metadata Enricher platform uses Azure AI Search as the primary discovery and retrieval mechanism for metadata. The search index serves multiple critical purposes:

1. **RAG Context Retrieval**: Provides grounded context for AI enrichment via vector search and semantic ranking
2. **Metadata Discovery**: Enables users to search and explore metadata across Synergy and Zipline
3. **Hybrid Search**: Combines keyword, vector, and semantic ranking for optimal relevance
4. **Audit & Compliance**: Indexed metadata serves as searchable record for governance

### Search Index Requirements

**Field Design**: Index fields are derived from frozen schemas (see ADR-0002):
- Core metadata fields from Synergy/Zipline exports
- Vector field for embeddings (text-embedding-ada-002, 1536 dimensions)
- Semantic configuration for L2 ranking

**RAG-First Architecture**: The index is the single source of truth for AI context. All AI enrichment queries retrieve context exclusively from this index (no direct access to Synergy/Zipline).

**Incremental Indexing**: Index supports incremental updates via `id` + `lastUpdated` fields for deterministic hash-based change detection.

**Public-Sector Compliance**: Index design must be stable, auditable, and documented for FedRAMP, FERPA, and GDPR compliance.

### Current State

- Index design documented: [docs/search-index-design.md](../search-index-design.md)
- Design frozen at v1.0.0 as of 2026-01-12 (per design doc)
- 16 fields defined (core + enrichment + technical + vector)
- Vector search configured (HNSW, cosine similarity, 1536 dimensions)
- Semantic ranking profile defined (entityName as title, content/description as content, tags/domain as keywords)

### Problem Statement

Without formal ADR governance:
- Index design could be modified without impact analysis
- Field changes could break AI contracts (prompts reference specific fields)
- Schema-to-index mapping could drift
- No clear process for index evolution
- Reindexing consequences not formally assessed
- Compliance auditability gaps

## Considered Options

### Option 1: Freeze Index Design v1.0.0 with Formal Governance

**Description**: Declare search index design v1.0.0 as frozen. Prohibit field changes, semantic configuration changes, or vector configuration changes without ADR approval. Require formal impact analysis for any modifications.

**Pros**:
- Stable foundation for RAG context retrieval
- Protects AI contracts from breaking field changes
- Clear governance for schema-to-index alignment
- Auditability for compliance
- Prevents unintended reindexing (costly operation)
- Stable API for search clients

**Cons**:
- Less flexibility for search improvements
- Formal process required for new fields
- May slow feature development

### Option 2: Allow Index Schema Evolution Without Governance

**Description**: Treat index as flexible. Allow field additions, deletions, or modifications without formal approval.

**Pros**:
- Faster iteration on search features
- No governance overhead

**Cons**:
- **Breaking changes to AI contracts** (prompts/validation rules reference fields)
- **Unplanned reindexing** (expensive, time-consuming)
- **Schema drift** from frozen JSON schemas (ADR-0002)
- No audit trail for compliance
- Risk of breaking existing search queries
- Unpredictable behavior for RAG context retrieval

### Option 3: Version Index But No Formal Governance

**Description**: Use versioned index names (e.g., metadata-index-v1) but allow changes without ADR.

**Pros**:
- Versioning provides some stability
- Can run multiple index versions in parallel

**Cons**:
- No decision audit trail
- Unclear when to create new version
- Risk of premature version bumps
- Insufficient for public-sector governance

## Decision

**Azure AI Search Index Design v1.0.0 is formally frozen.**

The index design documented in [docs/search-index-design.md](../search-index-design.md) is **frozen as of 2026-01-14** and serves as the authoritative specification for the production search index.

### Freeze Rules

1. **No Field Modifications**: Existing fields (name, type, searchable/filterable/sortable flags) MUST NOT be changed without ADR approval and major version bump.

2. **No Field Deletions**: Fields cannot be removed from v1 index. Deprecated fields must remain until v2.

3. **New Fields Require ADR**: Adding fields requires minor version ADR documenting:
   - Reason for addition
   - Impact on AI contracts
   - Reindexing strategy
   - Approval from Architecture and AI/ML teams

4. **Vector Configuration Frozen**: `contentVector` field configuration (dimensions, algorithm, metric) is frozen. Changes require major version.

5. **Semantic Configuration Frozen**: Semantic ranking profile (title/content/keywords mapping) is frozen. Changes require major version.

6. **Schema Alignment**: Index fields MUST remain aligned with frozen schemas (ADR-0002). Schema changes trigger index version review.

7. **Versioning**:
   - **Minor (1.X.0)**: Backward-compatible additions (new optional fields, new analyzers)
   - **Major (X.0.0)**: Breaking changes (removed fields, changed types, vector config changes, semantic config changes)

8. **Deployment**: Production index name is `metadata-index-v1`. Major version creates new index (`metadata-index-v2`).

### Validation

- Index design implementability tested via Azure AI Search REST API (future: automated test)
- Field definitions validated against frozen schemas (ADR-0002)
- AI contracts validated against index field availability

## Consequences

### Positive Consequences

- **Stable RAG Context**: AI enrichment has predictable, reliable context retrieval
- **Protected AI Contracts**: Prompts and validation rules won't break due to field changes
- **Schema Alignment**: Index remains synchronized with frozen external schemas
- **Audit Trail**: All changes documented via ADR for compliance
- **Reindexing Control**: Expensive reindexing operations are planned and approved
- **Search API Stability**: Client applications have stable field names and types
- **Compliance Confidence**: Immutable design meets public-sector governance requirements

### Negative Consequences

- **Slower Search Improvements**: New fields or config changes require formal process
- **Process Overhead**: Even minor improvements need governance approval
- **Initial Design Pressure**: v1 must be "production-ready" from day one

### Neutral Consequences

- **Parallel Indexes for Testing**: Non-production indexes can experiment with new designs before ADR
- **Documentation Burden**: All changes require comprehensive ADRs

## Implementation

### Immediate Actions

- [x] Document index design freeze in [docs/search-index-design.md](../search-index-design.md#L364-L378)
- [x] Create this ADR documenting freeze governance
- [ ] Create index deployment script (Bicep) implementing frozen design
- [ ] Create automated test validating index schema against design doc
- [ ] Add index validation to CI/CD pipeline

### Follow-up Actions

- [ ] Create index change request ADR template
- [ ] Document reindexing strategy for major version upgrades
- [ ] Establish search review board (Architecture + AI/ML + Data Engineering)
- [ ] Create monitoring for index schema drift detection
- [ ] Document rollback procedure for failed index changes

## Related Decisions

- [ADR-0002: Schema Contract Freeze v1.0.0](0002-schema-contract-freeze-v1.md) — Index fields derived from frozen schemas
- [Contracts FREEZE v1.0.0](../../contracts/FREEZE-v1.0.0.md) — AI behavior contracts reference index fields
- [ADR-0001: Use Bicep as Exclusive IaC](0001-use-bicep-as-exclusive-iac.md) — Index deployed via Bicep templates

## References

- [Search Index Design v1.0.0](../search-index-design.md)
- [Synergy Export Schema v1.0.0](../../contracts/schemas/synergy-export.schema.json)
- [Zipline Export Schema v1.0.0](../../contracts/schemas/zipline-export.schema.json)
- [AI Behavior Contracts v1.0.0](../../contracts/FREEZE-v1.0.0.md)
- [Azure AI Search Documentation](https://learn.microsoft.com/en-us/azure/search/)
- [Architecture Documentation](../architecture.md)
