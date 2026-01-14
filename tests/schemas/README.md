# Schema Validation Tests

This directory contains local-only tests for JSON Schema validation of Synergy and Zipline export contracts.

## Purpose

Validate that:
1. JSON schemas enforce MVP constraints (required fields, data types, patterns)
2. Schemas are deterministic (same input = same validation result)
3. Invalid data is rejected as expected

## Requirements

```bash
pip install jsonschema
```

## Running Tests

```bash
cd tests/schemas
python test_schemas.py
```

## Expected Output

```
======================================================================
JSON Schema Validation Test Suite
Testing Synergy and Zipline Export Schemas
JSON Schema Draft: 2020-12
======================================================================

Loading schemas...
✓ Loaded: synergy-export.schema.json
✓ Loaded: zipline-export.schema.json

======================================================================
Testing Synergy Export Schema
======================================================================

Test 1: Valid example should PASS validation
✓ PASS: Valid example accepted

Test 2: Invalid example (missing required field 'id') should FAIL validation
✓ PASS: Invalid example rejected: 'id' is a required property

...

======================================================================
Test Summary
======================================================================
Total test failures: 0

✓ ALL TESTS PASSED

Conclusion:
  - Schemas are deterministic and enforce MVP constraints
  - Required fields are validated correctly
  - Pattern matching, enums, and const values work as expected
  - Invalid data is rejected as expected
```

## Test Coverage

### Synergy Schema Tests

**Valid Example:**
- Minimal MVP fields (id, sourceSystem, entityType, entityName, entityPath, content, lastUpdated, schemaVersion)

**Invalid Examples:**
- Missing required field (`id`)
- Wrong `sourceSystem` value (should be "synergy")
- Invalid `entityType` (not in enum)
- Invalid `id` pattern (contains disallowed characters)
- Invalid `schemaVersion` format (doesn't match semver pattern)

### Zipline Schema Tests

**Valid Example:**
- Minimal MVP fields (same as Synergy)

**Invalid Examples:**
- Missing required field (`content`)
- Wrong `sourceSystem` value (should be "zipline")
- Empty `entityName` (violates minLength constraint)
- Invalid `lastUpdated` format (not ISO 8601 date-time)

## What This Proves

1. **Determinism**: Same JSON input produces same validation result every time
2. **MVP Enforcement**: Only essential fields are required; optional fields are truly optional
3. **Type Safety**: Invalid types, patterns, and enum values are rejected
4. **Contract Compliance**: Schemas enforce the external data contract correctly

## Limitations

- Local tests only (no CI/CD integration)
- Does not test Azure-specific behavior (blob storage, indexing)
- Does not test runtime data ingestion workflows

## References

- [Synergy Export Schema](../../contracts/schemas/synergy-export.schema.json)
- [Zipline Export Schema](../../contracts/schemas/zipline-export.schema.json)
- [Schema Governance](../../contracts/schemas/README.md)
