# Asset Metadata Contract for Change Detection

## Overview

This document defines which metadata fields are considered **material** (relevant) for change detection purposes. A material change in any of these fields indicates that the logical state of a Purview asset has changed, and the asset requires re-indexing or reprocessing.

## Material Fields

The following fields are considered material and are included in change detection hashing:

### Core Identity
- **id**: Globally unique, stable identifier for the metadata entity
- **sourceSystem**: Source system identifier (synergy, zipline, etc.)
- **entityType**: Type of metadata entity (table, column, dataset, element)

### Descriptive Content
- **entityName**: Human-readable name of the metadata entity
- **entityPath**: Hierarchical path to the entity within the source system
- **description**: Technical description of the metadata entity
- **businessMeaning**: Business-oriented explanation of what the entity represents
- **domain**: Business domain or subject area

### Classification
- **tags**: Searchable tags for categorization (stored as sorted collection)

### Semantic Content
- **content**: Consolidated textual representation suitable for semantic indexing and RAG embedding

### Lineage & Relationships
- **relationships**: Array of related entities (if present, stored as sorted collection by id)

### Schema/Structure
- **columns**: For table entities, the list of columns (stored as sorted collection by name)
- **dataType**: Data type information for applicable entities

## Non-Material Fields (Excluded from Hashing)

The following fields are considered **volatile** or **non-material** and are explicitly excluded from change detection hashing:

- **lastUpdated**: Timestamp of last update (volatile)
- **schemaVersion**: Schema version identifier (infrastructure concern, not logical content)
- **_metadata**: Any internal system metadata fields (prefixed with _)
- **auditInfo**: Audit or tracking information
- **scanId**: Identifier for a particular scan or import job
- **ingestionTime**: When the metadata was ingested (volatile)

## Normalization Rules

When computing the hash for an asset, the following normalization rules apply:

### 1. Field Filtering
Only material fields are included in the hash computation. Any non-material fields are stripped out.

### 2. Collection Sorting
All arrays and collections must be sorted deterministically:
- **tags**: Sort alphabetically (case-insensitive)
- **relationships**: Sort by the `id` field alphabetically
- **columns**: Sort by the `name` field alphabetically

### 3. Field Ordering
Material fields are ordered deterministically in a canonical JSON representation:
1. id
2. sourceSystem
3. entityType
4. entityName
5. entityPath
6. description
7. businessMeaning
8. domain
9. tags (sorted)
10. content
11. relationships (sorted by id)
12. columns (sorted by name)
13. dataType

### 4. Null and Empty Handling
- Null or missing non-required fields are treated as absent (not included in the canonical representation)
- Empty collections ([], empty tags) are preserved but stored as sorted empty collections
- Empty strings are preserved but may indicate missing required data

### 5. String Normalization
- Whitespace is not trimmed; content is used as-is
- Encoding is UTF-8
- No case normalization is applied to preserve semantic meaning

### 6. Numeric Values
- All numeric values are represented in their standard JSON format
- No rounding or precision normalization is applied

## Example: Change Scenarios

### Scenario 1: Material Change (Hash Changes)
```
Original:  businessMeaning: "Customer purchase records"
Updated:   businessMeaning: "Historical customer transaction records"
Result:    Different hash ✓
```

### Scenario 2: Non-Material Change (Hash Unchanged)
```
Original:  lastUpdated: "2026-01-20T10:30:00Z"
Updated:   lastUpdated: "2026-01-24T14:45:00Z"
Result:    Same hash ✓
```

### Scenario 3: Non-Material Change - Tag Reordering (Hash Unchanged)
```
Original:  tags: ["sales", "analytics", "customer"]
Updated:   tags: ["customer", "sales", "analytics"]
Result:    Same hash (both normalize to ["analytics", "customer", "sales"]) ✓
```

### Scenario 4: Material Change - Content Modification (Hash Changes)
```
Original:  content: "Customer records with sales data"
Updated:   content: "Customer records with sales and inventory data"
Result:    Different hash ✓
```

### Scenario 5: Non-Material Change - Scan ID (Hash Unchanged)
```
Original:  scanId: "scan-2026-01-20-abc123"
Updated:   scanId: "scan-2026-01-24-def456"
Result:    Same hash ✓
```

## Implementation Notes

1. **Determinism**: The normalization and hashing must be completely deterministic. Identical logical assets must always produce identical hashes.

2. **Stability**: The contract should remain stable across schema versions. If the contract must change, document it as a breaking change.

3. **Testing**: All normalization logic must be covered by unit tests demonstrating:
   - Identical logical assets produce the same hash
   - Material changes produce different hashes
   - Non-material changes do not affect the hash

4. **Performance**: Hashing should be fast and suitable for computing on every asset during ingestion.

5. **Encoding**: SHA-256 is computed on UTF-8 JSON, and the result is returned as a lowercase hexadecimal string.
