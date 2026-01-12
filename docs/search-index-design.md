# Azure AI Search Index Design — v1 (Frozen)

**Status**: FROZEN  
**Version**: 1.0.0  
**Effective Date**: 2026-01-12  
**Owner**: Platform Architecture Team  
**Approvers**: Architecture Team Lead, Security Team Lead  

---

## Purpose and Scope

This document defines the **frozen design** of the Azure AI Search index for the AI Metadata Enrichment platform. The index supports:

1. **RAG-first semantic search** over metadata entities from external source systems
2. **Faceted navigation** and filtering for metadata discovery
3. **Incremental indexing** using deterministic identifiers
4. **Vector search** for semantic similarity matching
5. **Hybrid search** combining keyword, semantic, and vector retrieval

This design is derived **exclusively** from the frozen external contracts and represents a **PRODUCTION CONTRACT**. Any modification requires a new major version, ADR, and formal approval.

---

## Source Artifacts (Immutable Inputs)

This index design is derived from:

1. **contracts/schemas/synergy-export.schema.json** (v1.0.0)
2. **contracts/schemas/zipline-export.schema.json** (v1.0.0)
3. **contracts/lookups/lookup.json** (v1.0.0)

Both schemas share identical field structures. The index is designed to accommodate metadata from **both source systems** in a unified index.

---

## Index Field Definitions

### Core Identity Fields

| Field Name | Type | Searchable | Filterable | Facetable | Sortable | Retrievable | Purpose |
|-----------|------|------------|------------|-----------|----------|-------------|---------|
| `id` | `Edm.String` | No | Yes | No | Yes | Yes | **Primary key**. Globally unique identifier for deterministic indexing and updates. |
| `sourceSystem` | `Edm.String` | No | Yes | Yes | Yes | Yes | Identifies the source system (synergy, zipline). Used for filtering and faceting. |
| `entityType` | `Edm.String` | No | Yes | Yes | Yes | Yes | Type of entity (table, column, dataset, element). Supports faceted navigation. |
| `schemaVersion` | `Edm.String` | No | Yes | Yes | No | Yes | Schema version for contract compatibility validation. |

### Descriptive Fields

| Field Name | Type | Searchable | Filterable | Facetable | Sortable | Retrievable | Purpose |
|-----------|------|------------|------------|-----------|----------|-------------|---------|
| `entityName` | `Edm.String` | Yes | No | No | Yes | Yes | Human-readable entity name. Searchable for keyword matching. Used as semantic title. |
| `entityPath` | `Edm.String` | Yes | Yes | No | No | Yes | Hierarchical path for navigation and lineage. Searchable and filterable. |
| `description` | `Edm.String` | Yes | No | No | No | Yes | Technical description. Searchable for keyword discovery. |
| `businessMeaning` | `Edm.String` | Yes | No | No | No | Yes | Business-oriented explanation. Searchable for semantic understanding. |

### Semantic Enrichment Fields

| Field Name | Type | Searchable | Filterable | Facetable | Sortable | Retrievable | Purpose |
|-----------|------|------------|------------|-----------|----------|-------------|---------|
| `domain` | `Edm.String` | Yes | Yes | Yes | Yes | Yes | Business domain (e.g., "Student Information"). Searchable, filterable, and facetable. |
| `tags` | `Collection(Edm.String)` | Yes | Yes | Yes | No | Yes | Multi-valued tags for categorization. Supports faceted search and keyword filtering. |

### RAG-Critical Field

| Field Name | Type | Searchable | Filterable | Facetable | Sortable | Retrievable | Purpose |
|-----------|------|------------|------------|-----------|----------|-------------|---------|
| `content` | `Edm.String` | Yes | No | No | No | Yes | **Consolidated text for RAG context**. Includes description, businessMeaning, and other key fields. Primary field for semantic search. |
| `contentVector` | `Collection(Edm.Single)` | No | No | No | No | No | **Vector embedding of content field**. Used for vector similarity search. Dimensions: 1536 (conceptual, Azure OpenAI text-embedding-ada-002 compatible). |

### Technical Metadata Fields

| Field Name | Type | Searchable | Filterable | Facetable | Sortable | Retrievable | Purpose |
|-----------|------|------------|------------|-----------|----------|-------------|---------|
| `dataType` | `Edm.String` | Yes | Yes | Yes | No | Yes | Data type (e.g., VARCHAR, INTEGER). Searchable and filterable for schema queries. |
| `sourceTable` | `Edm.String` | Yes | Yes | No | No | Yes | Source table name for column-level entities. Searchable and filterable. |
| `cedsReference` | `Edm.String` | Yes | Yes | No | No | Yes | CEDS (Common Education Data Standards) reference. Searchable and filterable for compliance mapping. |

### Lineage and Temporal Fields

| Field Name | Type | Searchable | Filterable | Facetable | Sortable | Retrievable | Purpose |
|-----------|------|------------|------------|-----------|----------|-------------|---------|
| `lineage` | `Collection(Edm.String)` | No | Yes | No | No | Yes | Ordered list of upstream entity IDs. Filterable for lineage traversal queries. |
| `lastUpdated` | `Edm.DateTimeOffset` | No | Yes | No | Yes | Yes | Timestamp of last update in source system. Used for incremental indexing and sorting by recency. |

---

## Vector Search Configuration

### Vector Field

- **Field Name**: `contentVector`
- **Type**: `Collection(Edm.Single)`
- **Dimensions**: 1536 (conceptual; aligned with Azure OpenAI text-embedding-ada-002)
- **Source**: Embedding generated from `content` field during ingestion
- **Purpose**: Enables semantic similarity search for RAG retrieval

### Vector Search Profile (Conceptual)

- **Algorithm**: HNSW (Hierarchical Navigable Small World)
- **Metric**: Cosine similarity
- **Parameters** (conceptual, not set in this design document):
  - `m`: 4 (number of bi-directional links per node)
  - `efConstruction`: 400 (search effort during index construction)
  - `efSearch`: 500 (search effort during query time)

**Note**: Actual vector configuration and embedding model selection will be defined in infrastructure code (Bicep) and runtime configuration, not in this design document.

---

## Semantic Configuration

### Semantic Ranking Profile

Azure AI Search semantic ranking uses the following field mappings:

| Semantic Role | Field(s) | Justification |
|--------------|---------|---------------|
| **Title** | `entityName` | Primary human-readable identifier for the entity. |
| **Content** | `content`, `description`, `businessMeaning` | Consolidated text fields for semantic understanding. `content` is primary; `description` and `businessMeaning` provide fallback context. |
| **Keywords** | `tags`, `domain`, `entityPath` | Categorical and hierarchical context for semantic boosting. |

### Semantic Search Behavior

- **L2 Reranking**: Top keyword/vector results are reranked using semantic models
- **Captions**: Automatically extracted from `content` field
- **Answers**: Extracted from `content` and `description` fields when query has question intent

---

## Incremental Indexing Strategy

### Primary Key

- **Field**: `id`
- **Behavior**: Deterministic, stable identifier from source systems
- **Update Logic**: If document with same `id` exists, **merge/update**; otherwise, **insert new**

### Change Detection

- **Field**: `lastUpdated`
- **Strategy**: Incremental indexing uses `lastUpdated` timestamp from source system
- **Query Pattern**: Only index documents where `lastUpdated > last_indexed_timestamp`

### Hash-Based Validation (Future)

- **Conceptual**: Cosmos DB stores hash of (`id` + `lastUpdated`)
- **Purpose**: Detect duplicate ingestion attempts and avoid redundant indexing
- **Status**: Not part of index schema; handled at orchestration layer

---

## Exclusions and Rationale

The following fields from the source schemas are **EXCLUDED** from the index:

| Excluded Field | Reason for Exclusion |
|---------------|---------------------|
| `$schema` | JSON Schema metadata, not domain data |
| `$id` | JSON Schema metadata, not domain data |

**No other exclusions**. All domain fields from the source schemas are indexed to maximize search coverage and avoid premature optimization.

---

## Field Design Rationale

### Why `content` is Searchable but Not Filterable

`content` is designed for **full-text and semantic search**, not exact matching. Filtering on large text fields degrades performance and is semantically meaningless.

### Why `id` is Not Searchable

`id` is a technical identifier (e.g., `synergy.student.enrollment.table`). Users search for entity names or descriptions, not IDs. `id` is filterable for exact lookups in lineage or API queries.

### Why `tags` and `domain` are Facetable

Faceting enables **metadata discovery UI patterns** like:
- "Show all entities in the 'Student Information' domain"
- "Filter by tags: 'PII', 'Demographics', 'Attendance'"

### Why `lastUpdated` is Sortable

Enables "most recently updated" queries, critical for data governance and change tracking.

### Why `lineage` is Not Searchable

Lineage is a structured list of entity IDs. Searching within lineage is better handled by explicit filtering on specific parent IDs, not full-text search.

---

## Sanity Checks (Validation Criteria)

### ✅ No Technical Fields as Embeddings

- `id`, `sourceSystem`, `schemaVersion` are **NOT** used for vector embeddings
- Only `content` (consolidated human-readable text) is embedded

### ✅ No Duplicated Semantic Purpose

- `content` is the **primary** field for RAG and semantic search
- `description` and `businessMeaning` are searchable independently but also feed into `content`
- No redundant fields with overlapping semantic roles

### ✅ No "Maybe Useful Later" Fields

- Every field in the index exists in the source schemas
- Every field has a defined search behavior (searchable, filterable, facetable, sortable)
- No speculative fields added "just in case"

### ✅ Supports Incremental Indexing

- `id` is the stable primary key
- `lastUpdated` enables change detection
- Index design is merge-friendly (updates do not require full reindex)

### ✅ Deterministic Behavior

- Field mappings are explicit and unambiguous
- No dynamic field generation
- No runtime schema changes

---

## Governance and Change Management

### Freeze Protocol

**Status**: This index design is **FROZEN** as of 2026-01-12.

### Breaking Changes

The following changes are considered **BREAKING** and require a new major version (v2.0.0):

1. Removing or renaming any field
2. Changing field types (e.g., `Edm.String` → `Edm.Int32`)
3. Changing searchable/filterable/facetable flags (if it breaks existing queries)
4. Changing primary key field
5. Changing vector dimensions

### Non-Breaking Changes

The following changes are **NON-BREAKING** and may be added in minor versions (v1.1.0):

1. Adding new optional fields (from new schema fields)
2. Adding new semantic configurations
3. Tuning vector search parameters (does not change field schema)

### Change Process

All changes to this design require:

1. **Architecture Decision Record (ADR)** documenting the change and rationale
2. **Approval** from Architecture Team Lead and Security Team Lead
3. **Impact analysis** on existing queries, dashboards, and consuming applications
4. **Migration plan** if breaking changes affect production data

---

## Integration with Platform Components

### Azure Functions (Ingestion Pipeline)

- Reads documents from Blob Storage
- Validates against source schemas
- Extracts fields and maps to index schema
- Calls Azure OpenAI to generate `contentVector` from `content` field
- Submits documents to Azure AI Search via REST API or SDK

### Cosmos DB (State Management)

- Stores hash of (`id` + `lastUpdated`) for deduplication
- Tracks indexing status (pending, indexed, failed)
- Enables incremental indexing queries

### Azure AI Search (Index)

- Receives documents from ingestion pipeline
- Applies vector search, keyword search, and semantic ranking
- Serves queries from UI, API, and RAG workflows

---

## Example Document (Conceptual)

```json
{
  "id": "synergy.student.enrollment.table",
  "sourceSystem": "synergy",
  "entityType": "table",
  "entityName": "Student Enrollment",
  "entityPath": "synergy.student_info.enrollment",
  "description": "Table containing student enrollment records including school, grade level, and enrollment dates.",
  "businessMeaning": "Core table for tracking which students are enrolled in which schools and programs. Used for state reporting and funding calculations.",
  "domain": "Student Information",
  "tags": ["enrollment", "student", "state-reporting"],
  "content": "Student Enrollment table in the Synergy Student Information System. Contains student enrollment records including school assignments, grade levels, enrollment dates, and program participation. Critical for state reporting, funding calculations, and operational tracking of student placements.",
  "contentVector": [0.023, -0.015, 0.041, ...],  // 1536 dimensions
  "dataType": null,
  "sourceTable": null,
  "cedsReference": null,
  "lineage": [],
  "lastUpdated": "2026-01-12T14:30:00Z",
  "schemaVersion": "1.0.0"
}
```

---

## Compliance and Security Considerations

### PII and Sensitive Data

- **Metadata only**: This index contains **metadata about data structures**, not actual student/personnel records
- **No PII in index**: Entity names, descriptions, and paths are technical/structural, not personally identifiable
- **RBAC enforcement**: Access to index requires Azure AD authentication and role-based permissions
- **Audit logging**: All search queries logged to Azure Monitor for compliance auditing

### Data Retention

- **Index retention**: Unlimited (metadata is retained as long as source systems exist)
- **Deletion policy**: Documents removed from index when corresponding source entities are deleted or archived
- **Compliance alignment**: FERPA, GDPR (metadata-level data minimization)

---

## Future Considerations

### Multi-Tenant Support

Future versions may include:
- `tenantId` field for filtering and RBAC isolation
- Tenant-specific indexes or partitioned indexes

### AI-Generated Enrichments

Future schema versions may add fields for:
- `aiGeneratedSummary` (LLM-generated summary)
- `aiGeneratedTags` (LLM-extracted tags)
- `relatedEntities` (AI-discovered relationships)

These fields are **NOT INCLUDED** in v1 to maintain alignment with frozen source schemas.

### Geospatial Search

If future schemas include location data:
- Add `Edm.GeographyPoint` fields for school/district locations
- Enable geo-filtering and distance-based search

**Status**: Not applicable to current source schemas.

---

## References

- [Synergy Export Schema](../contracts/schemas/synergy-export.schema.json)
- [Zipline Export Schema](../contracts/schemas/zipline-export.schema.json)
- [Blob Path Lookup Configuration](../contracts/lookups/lookup.json)
- [Architecture Documentation](./architecture.md)
- [Governance Framework](./governance.md)

---

## Freeze Statement

**This Azure AI Search Index Design (v1.0.0) is FROZEN as of 2026-01-12.**

No modifications to field definitions, search properties, or semantic configurations are permitted without:

1. Creating a new major version (v2.0.0)
2. Documenting changes in an Architecture Decision Record (ADR)
3. Obtaining formal approval from designated approvers
4. Communicating changes to all consuming teams and stakeholders

Any deviation from this frozen design without following the change management process is a **governance violation** and will be flagged in code review and deployment pipelines.

---

**Document Version**: 1.0.0  
**Last Updated**: 2026-01-12  
**Next Review**: 2026-02-12  
**Approved By**: [Pending formal approval process]  
**Status**: FROZEN (Design-Time Contract)
