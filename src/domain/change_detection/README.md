# Change Detection Module

Deterministic SHA-256 hashing for asset metadata change detection.

## Overview

This module provides pure domain logic for detecting whether Purview asset metadata has materially changed. It implements a deterministic hashing mechanism that:

- **Normalizes** asset metadata by removing volatile fields (timestamps, scan IDs) and sorting collections
- **Canonicalizes** the representation into a deterministic JSON format
- **Hashes** the canonical form using SHA-256
- **Guarantees** that identical logical assets always produce identical hashes
- **Ensures** that material changes produce different hashes
- **Ignores** non-material changes (ordering, timestamps, infrastructure metadata)

## Purpose

The hashing mechanism enables the system to later determine whether an asset requires re-indexing or reprocessing by comparing its current hash to a previously stored hash. This is the foundation for incremental indexing and change detection in the AI Metadata Enrichment platform.

## Module Structure

```
src/domain/change_detection/
├── __init__.py              # Public API exports
├── asset_contract.md        # Documentation of material vs. volatile fields
├── normalizer.py            # Normalization logic (field filtering, sorting)
└── hasher.py                # SHA-256 hash computation
```

## Public API

### `compute_asset_hash(asset: Dict[str, Any]) -> str`

Compute the SHA-256 hash of an asset's normalized metadata.

```python
from src.domain.change_detection import compute_asset_hash

asset = {
    "id": "synergy.student.enrollment.table",
    "sourceSystem": "synergy",
    "entityType": "table",
    "entityName": "Student Enrollment",
    "entityPath": "database.schema.enrollment",
    "description": "Records of student course enrollment",
    "businessMeaning": "Primary source of truth for registrations",
    "domain": "Student Information",
    "content": "Enrollment records with student ID, course code, term",
    "tags": ["academic", "student"],
    "lastUpdated": "2026-01-24T10:00:00Z",  # Ignored in hash
}

hash_value = compute_asset_hash(asset)
# Returns: '3f7c8e...' (64-character lowercase hex)
```

**Returns:** SHA-256 hash as a lowercase hexadecimal string (64 characters)

### `are_assets_equal_by_hash(asset1, asset2) -> bool`

Check if two assets have the same material content by comparing their hashes.

```python
from src.domain.change_detection import are_assets_equal_by_hash

if are_assets_equal_by_hash(current_asset, previous_asset):
    print("Asset has not materially changed")
else:
    print("Asset has changed and requires re-indexing")
```

### `normalize_asset(asset: Dict[str, Any]) -> Dict[str, Any]`

Normalize an asset by removing volatile fields and sorting collections.

```python
from src.domain.change_detection import normalize_asset

normalized = normalize_asset(asset)
# Returns a clean dictionary suitable for hashing
```

**Returns:** Dictionary containing only material fields, sorted deterministically

### `get_asset_hash_components(asset) -> Dict[str, Any]`

Get the normalized components that contribute to the asset's hash (useful for debugging).

```python
from src.domain.change_detection import get_asset_hash_components

components = get_asset_hash_components(asset)
# Returns the normalized form of the asset
```

### `get_material_fields() -> frozenset`

Get the set of field names considered material for change detection.

```python
from src.domain.change_detection import get_material_fields

material = get_material_fields()
# frozenset({'id', 'sourceSystem', 'entityType', ...})
```

### `get_volatile_fields() -> frozenset`

Get the set of field names considered volatile and excluded from hashing.

```python
from src.domain.change_detection import get_volatile_fields

volatile = get_volatile_fields()
# frozenset({'lastUpdated', 'schemaVersion', 'scanId', ...})
```

## Material vs. Volatile Fields

### Material Fields (Included in Hash)

These fields represent the logical state of an asset and are included in change detection:

- **id**: Unique identifier
- **sourceSystem**: Source system (synergy, zipline, etc.)
- **entityType**: Type (table, column, dataset, element)
- **entityName**: Display name
- **entityPath**: Hierarchical path
- **description**: Technical description
- **businessMeaning**: Business context
- **domain**: Subject area
- **tags**: Classification tags
- **content**: Semantic content for RAG
- **relationships**: Related entities
- **columns**: Table structure
- **dataType**: Data type information

### Volatile Fields (Excluded from Hash)

These fields are infrastructure or operational concerns and do not affect the hash:

- **lastUpdated**: Timestamp (volatile)
- **schemaVersion**: Schema version
- **auditInfo**: Audit metadata
- **scanId**: Scan/import job identifier
- **ingestionTime**: When metadata was ingested
- **_*** : Any field prefixed with underscore

See [asset_contract.md](./asset_contract.md) for detailed field definitions and examples.

## Normalization Rules

When computing a hash, the module applies these deterministic normalization rules:

### 1. Field Filtering
Only material fields are included. Volatile fields and fields starting with `_` are stripped.

### 2. Collection Sorting

- **tags**: Sorted alphabetically (case-insensitive), duplicates removed
- **relationships**: Sorted by `id` field, duplicates by id removed
- **columns**: Sorted by `name` field, duplicates by name removed

### 3. Null Handling
Missing or `None` values are omitted from the normalized form.

### 4. Determinism Guarantees
- No whitespace trimming (content used as-is)
- No case normalization (semantic meaning preserved)
- JSON serialization with sorted keys
- UTF-8 encoding
- No field ordering imposed (canonical JSON handles ordering)

## Use Cases

### Change Detection
```python
previous_hash = "3f7c8e..."  # Stored from previous ingestion
current_asset = {...}
current_hash = compute_asset_hash(current_asset)

if previous_hash != current_hash:
    print("Asset has changed, re-index it")
    # Trigger re-indexing
```

### Duplicate Detection
```python
asset_a = {...}
asset_b = {...}

if are_assets_equal_by_hash(asset_a, asset_b):
    print("Assets are logically equivalent")
    # Skip processing duplicates
```

### Migration Validation
```python
# Ensure assets survive migrations unchanged
for asset in migrated_assets:
    new_hash = compute_asset_hash(asset)
    if new_hash != asset['originalHash']:
        print(f"Asset {asset['id']} was inadvertently modified")
```

## Testing

The module includes 31 comprehensive unit tests covering:

- **Normalization**: Field filtering, sorting, null handling
- **Material Changes**: Verified to produce different hashes
- **Non-Material Changes**: Verified to produce same hashes
- **Determinism**: Multiple computations produce identical results
- **Edge Cases**: Complex assets, error handling, empty collections

Run tests with:
```bash
python -m pytest tests/test_change_detection.py -v
```

## Examples

### Example 1: Identical Assets Produce Same Hash

```python
asset1 = {
    "id": "test.table",
    "sourceSystem": "synergy",
    "entityType": "table",
    "entityName": "Customer Data",
    "entityPath": "db.schema.customer",
    "description": "Customer records",
    "businessMeaning": "Primary customers",
    "domain": "CRM",
    "content": "Customer table",
    "tags": ["sales", "customer"],
}

asset2 = {
    "id": "test.table",
    "sourceSystem": "synergy",
    "entityType": "table",
    "entityName": "Customer Data",
    "entityPath": "db.schema.customer",
    "description": "Customer records",
    "businessMeaning": "Primary customers",
    "domain": "CRM",
    "content": "Customer table",
    "tags": ["customer", "sales"],  # Different order
}

hash1 = compute_asset_hash(asset1)
hash2 = compute_asset_hash(asset2)
assert hash1 == hash2  # ✓ Tags were normalized
```

### Example 2: Material Changes Produce Different Hash

```python
asset1 = {
    ...,
    "businessMeaning": "Primary customer records"
}

asset2 = {
    ...,
    "businessMeaning": "Historical customer records"
}

hash1 = compute_asset_hash(asset1)
hash2 = compute_asset_hash(asset2)
assert hash1 != hash2  # ✓ Business meaning changed
```

### Example 3: Non-Material Changes Ignored

```python
asset1 = {
    ...,
    "lastUpdated": "2026-01-20T10:00:00Z",
    "scanId": "scan-123",
}

asset2 = {
    ...,
    "lastUpdated": "2026-01-24T14:00:00Z",
    "scanId": "scan-456",
}

hash1 = compute_asset_hash(asset1)
hash2 = compute_asset_hash(asset2)
assert hash1 == hash2  # ✓ Timestamps and scan IDs are volatile
```

## Design Principles

1. **Pure Logic**: No I/O, no external dependencies, no side effects
2. **Deterministic**: Identical inputs always produce identical outputs
3. **Testable**: Fully unit tested with no external dependencies
4. **Simple**: Clear, straightforward implementation
5. **Contract-Based**: Material vs. volatile fields clearly documented
6. **Stable**: Suitable for persistence and long-term comparison

## No Out-of-Scope Features

This module intentionally does NOT include:

- ❌ State persistence (no database, no file I/O)
- ❌ Hash comparison with storage (just computes hashes)
- ❌ Skip/reprocess logic (hashing only)
- ❌ Purview, Azure, or external API integration
- ❌ Orchestration or worker processes
- ❌ Queue or messaging logic

These will be implemented in higher layers (Orchestrator, Services) that import and use this module.

## Future Integration

The Orchestrator will use this module like:

```python
from src.domain.change_detection import compute_asset_hash

current_hash = compute_asset_hash(asset_from_purview)
previous_hash = cosmos_db.get_hash(asset_id)

if current_hash != previous_hash:
    # Enqueue for re-indexing
    service_bus.send(asset)
    cosmos_db.update_hash(asset_id, current_hash)
```

The module remains completely independent and testable locally.
