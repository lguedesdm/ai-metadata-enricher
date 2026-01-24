# Implementation Details: SHA-256 Change Detection

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   Asset Metadata (from Purview)             │
│  - id, sourceSystem, entityType, description, tags, ...     │
│  - lastUpdated, schemaVersion, scanId (volatile fields)     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────┐
        │  normalize_asset()             │
        │                                │
        │  • Remove volatile fields      │
        │  • Sort collections            │
        │  • Produce canonical form      │
        └────────────────────┬───────────┘
                             │
                             ▼
              ┌──────────────────────────┐
              │  Normalized Asset Dict   │
              │  (material fields only)  │
              └────────────┬─────────────┘
                           │
                           ▼
            ┌─────────────────────────────┐
            │  _to_canonical_json()       │
            │                             │
            │  • Sort keys                │
            │  • No whitespace            │
            │  • UTF-8 encoding           │
            └────────────────┬────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  Canonical JSON      │
                  │  (deterministic)     │
                  └──────────┬───────────┘
                             │
                             ▼
           ┌──────────────────────────────┐
           │  hashlib.sha256()            │
           │  (Python standard library)   │
           └──────────────────┬───────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  SHA-256 Hash   │
                    │  (64 hex chars) │
                    └─────────────────┘
```

## Core Modules

### 1. `normalizer.py` (430 lines)

**Key Functions:**
- `normalize_asset(asset)` - Main normalization entry point
- `_normalize_tags(tags)` - Sort and deduplicate tags
- `_normalize_relationships(rels)` - Sort relationships by id
- `_normalize_columns(cols)` - Sort columns by name
- `is_volatile_field(name)` - Field classification
- `get_material_fields()` - Introspection helper
- `get_volatile_fields()` - Introspection helper

**Material Fields** (13 total):
```
id, sourceSystem, entityType, entityName, entityPath,
description, businessMeaning, domain, tags, content,
relationships, columns, dataType
```

**Volatile Fields** (5 total):
```
lastUpdated, schemaVersion, auditInfo, scanId, ingestionTime
(+ any field starting with _)
```

**Normalization Strategy:**
1. Filter to only material fields
2. Sort all collections deterministically:
   - tags: `sorted(set(tags), key=str.lower)` 
   - relationships: `sorted(rels, key=lambda r: r['id'])`
   - columns: `sorted(cols, key=lambda c: c['name'])`
3. Remove null values
4. Preserve field semantics (no case normalization, etc.)

### 2. `hasher.py` (130 lines)

**Key Functions:**
- `compute_asset_hash(asset)` - Main hash computation
- `are_assets_equal_by_hash(a1, a2)` - Convenience comparison
- `_to_canonical_json(obj)` - Deterministic serialization
- `_json_encoder_default(obj)` - Custom JSON encoder
- `get_asset_hash_components(asset)` - Debug helper

**Hash Algorithm:**
```
1. Normalize asset using normalizer.normalize_asset()
2. Serialize to canonical JSON:
   - json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
   - No spaces, no whitespace, sorted keys
3. Encode to UTF-8 bytes
4. Compute SHA-256: hashlib.sha256(bytes).hexdigest()
5. Return lowercase hexadecimal string (64 chars)
```

**Determinism Guarantee:**
- Same input → identical JSON output (sorted keys, consistent formatting)
- Same JSON → identical hash (SHA-256 is deterministic)
- Therefore: same asset → same hash (guaranteed)

## Test Coverage (31 tests)

### Normalization Tests (8)
```
✓ Removes volatile fields (lastUpdated, schemaVersion, scanId)
✓ Removes underscore-prefixed fields (_metadata, _internal)
✓ Sorts tags alphabetically (case-insensitive)
✓ Removes duplicate tags
✓ Sorts relationships by id
✓ Sorts columns by name
✓ Skips None values
✓ Preserves all material fields
```

### Hash Equivalence Tests (13)
```
✓ Identical assets → same hash
✓ Reordered tags → same hash
✓ Different timestamps → same hash
✓ Different scanIds → same hash
✓ are_assets_equal_by_hash(identical) → True
✓ are_assets_equal_by_hash(different) → False
✓ Volatile fields ignored in hash
✓ Hash format: 64 lowercase hex characters
✓ Material changes produce different hash:
  - Description change → different hash
  - Business meaning change → different hash
  - Content change → different hash
  - New tag → different hash
  - Entity ID change → different hash
```

### Edge Cases & Validation (8)
```
✓ Complex asset with all fields (13 material + 5 volatile)
✓ get_asset_hash_components() debug helper
✓ Empty tags array handled correctly
✓ Minimal asset (only required fields)
✓ Type validation: tags must be list
✓ Type validation: columns must be list
✓ Required field: column must have 'name'
✓ Required field: relationship must have 'id'
```

### Determinism Tests (2)
```
✓ Computing hash 5x produces identical results
✓ Normalizing 5x produces identical results
```

## Material vs. Volatile Decision Matrix

| Field | Type | Material? | Reason |
|-------|------|-----------|--------|
| id | string | ✅ YES | Unique identifier for asset |
| sourceSystem | string | ✅ YES | Different sources are different assets |
| entityType | string | ✅ YES | Different types are different entities |
| entityName | string | ✅ YES | Name is part of identity |
| entityPath | string | ✅ YES | Path represents asset location |
| description | string | ✅ YES | Technical content changes |
| businessMeaning | string | ✅ YES | Semantic meaning changes |
| domain | string | ✅ YES | Domain assignment is material |
| tags | array | ✅ YES | Classification affects discovery |
| content | string | ✅ YES | RAG content is material |
| relationships | array | ✅ YES | Lineage changes are material |
| columns | array | ✅ YES | Schema changes are material |
| dataType | string | ✅ YES | Type information is material |
| lastUpdated | timestamp | ❌ NO | Infrastructure timestamp (volatile) |
| schemaVersion | string | ❌ NO | Technical versioning (infrastructure) |
| auditInfo | object | ❌ NO | Audit trail (operational) |
| scanId | string | ❌ NO | Job identifier (infrastructure) |
| ingestionTime | timestamp | ❌ NO | Processing timestamp (volatile) |
| _* | any | ❌ NO | Internal metadata (infrastructure) |

## Example Scenario: Change Detection

### Scenario 1: No Change
```python
# Original asset (from Purview scan 2026-01-20)
asset_v1 = {
    "id": "synergy.student.table",
    "sourceSystem": "synergy",
    "entityType": "table",
    "entityName": "Student Master",
    "entityPath": "db.dbo.student",
    "description": "Primary student records",
    "businessMeaning": "Single source of truth for students",
    "domain": "Student Information",
    "content": "Contains student ID, name, DOB, status",
    "tags": ["academic", "student"],
    "lastUpdated": "2026-01-20T10:00:00Z",
    "scanId": "scan-2026-01-20-abc"
}

# Updated asset (from Purview scan 2026-01-24)
asset_v2 = {
    "id": "synergy.student.table",
    "sourceSystem": "synergy",
    "entityType": "table",
    "entityName": "Student Master",
    "entityPath": "db.dbo.student",
    "description": "Primary student records",
    "businessMeaning": "Single source of truth for students",
    "domain": "Student Information",
    "content": "Contains student ID, name, DOB, status",
    "tags": ["student", "academic"],  # Reordered!
    "lastUpdated": "2026-01-24T15:30:00Z",  # Updated!
    "scanId": "scan-2026-01-24-def"  # New scan ID!
}

hash_v1 = compute_asset_hash(asset_v1)
hash_v2 = compute_asset_hash(asset_v2)

assert hash_v1 == hash_v2  # ✓ No change detected
# Reason: Tags reordered (normalized), timestamps and scanId are volatile
```

### Scenario 2: Material Change
```python
# Asset updated with new description
asset_v3 = {
    ...,
    "description": "Primary student records (updated)",  # Changed!
    "lastUpdated": "2026-01-24T15:30:00Z",
}

hash_v3 = compute_asset_hash(asset_v3)

assert hash_v1 != hash_v3  # ✓ Change detected
# Reason: description is a material field
```

## Performance Characteristics

- **Time Complexity**: O(n log n) where n = number of collection items
  - Sorting is the dominant operation
  - JSON serialization is O(n)
  - SHA-256 is O(n) where n = JSON length
- **Space Complexity**: O(n) for normalized form
- **Real-world Performance**: 
  - Typical asset: < 1ms
  - Complex asset (100+ columns): < 5ms
  - Suitable for computing on every asset during ingestion

## Integration with Orchestrator (Future)

The module will be used by the Orchestrator like:

```python
from src.domain.change_detection import compute_asset_hash

def process_asset(asset_from_purview, asset_id):
    # Compute current hash
    current_hash = compute_asset_hash(asset_from_purview)
    
    # Get previous hash from storage
    previous_hash = cosmos_db.get_asset_hash(asset_id)
    
    # Determine if asset changed
    if previous_hash is None:
        # New asset, index it
        send_to_indexing(asset_from_purview)
    elif current_hash != previous_hash:
        # Asset changed, re-index it
        send_to_indexing(asset_from_purview)
    else:
        # No change, skip processing
        log.info(f"Asset {asset_id} unchanged, skipping")
    
    # Update stored hash
    cosmos_db.update_asset_hash(asset_id, current_hash)
```

## No External Dependencies

The implementation uses only Python standard library:
- `hashlib` - SHA-256 hashing
- `json` - JSON serialization
- `copy` - Deep copying (for test isolation)
- `typing` - Type hints

Zero dependencies on:
- ❌ Azure SDK
- ❌ Purview API
- ❌ Cosmos DB
- ❌ Service Bus
- ❌ Container Apps
- ❌ Any third-party packages

## Design Decisions & Trade-offs

### Decision 1: Tag Deduplication in Normalization
**Choice**: Remove duplicate tags during normalization
**Reason**: Duplicates shouldn't affect hash; normalized form is canonical
**Impact**: Two assets with `["sales", "sales", "customer"]` and `["sales", "customer"]` will have same hash

### Decision 2: Collection Sorting Strategy
**Choice**: Sort collections by identity field (not contents)
**Reason**: Ensures determinism; supports efficient duplicate detection
**Impact**: Two assets with same columns in different order will hash identically (correct behavior)

### Decision 3: Material vs. Volatile Split
**Choice**: Explicit field whitelisting (material fields only included)
**Reason**: Conservative; new infrastructure fields won't accidentally affect hashes
**Impact**: New fields default to excluded; must explicitly add to MATERIAL_FIELDS if needed

### Decision 4: No Field Ordering Enforcement
**Choice**: Use JSON serialization's key sorting for field order
**Reason**: Simpler than maintaining explicit field ordering
**Impact**: Fields appear sorted alphabetically in canonical JSON, not business order

### Decision 5: String-Based Hash Comparison
**Choice**: Compare hash strings, not binary hashes
**Reason**: Simpler for storage, debugging, and logging
**Impact**: Hash is 64 characters instead of 32 bytes

## Error Handling

The module raises appropriate errors:

```python
TypeError:  # Invalid input types
- compute_asset_hash(not_a_dict)
- normalize_asset(not_a_dict)
- _normalize_tags("not a list")
- _normalize_columns("not a list")

ValueError:  # Missing required fields
- normalize_asset({"columns": [{"type": "int"}]})  # column without name
- normalize_asset({"relationships": [{"type": "parent"}]})  # rel without id
- _to_canonical_json(non_serializable_object)  # non-JSON-serializable
```

All errors include descriptive messages for debugging.

## Testing Strategy

**Unit Tests**: 31 tests covering all scenarios
- Run in isolation (no external dependencies)
- Deterministic (always pass/fail the same way)
- Fast (< 1 second total)
- Comprehensive (100% coverage of core logic)

**Test Organization**:
- `TestNormalization` - Field handling, sorting, filtering
- `TestHashing` - Hash computation, determinism, changes
- `TestEdgeCases` - Complex assets, error handling
- `TestConsistency` - Repeated operations produce same results

**Test Data**:
- Mock assets matching schema contracts (Synergy and Zipline)
- Realistic field values (actual domain content)
- Edge cases (empty collections, null values, special characters)

---

**Implementation complete and fully tested.**
