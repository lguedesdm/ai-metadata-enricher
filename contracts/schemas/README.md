# JSON Schemas

This directory contains JSON Schema definitions for validating data structures and API contracts used throughout the AI Metadata Enricher platform.

## Overview

JSON Schemas provide:
- **Type Safety**: Strongly-typed data structures
- **Validation**: Automatic validation of data conformance
- **Documentation**: Self-documenting data models
- **Code Generation**: Source for auto-generated types and classes
- **Immutable Contracts**: Stable, versioned contracts independent of implementation details

### Contract Stability Principles

**CRITICAL**: These schemas are **external contracts**, not internal implementation details.

✅ **DO**:
- Treat schemas as API contracts with external consumers
- Version schemas using semantic versioning
- Create new versions for breaking changes
- Maintain backward compatibility within major versions
- Design schemas independent of internal platform details (Synergy, Zipline, etc.)

❌ **DO NOT**:
- Modify schemas in-place after freeze
- Expose internal implementation details in schemas
- Make breaking changes without new major version
- Assume consuming systems can adapt to schema changes instantly

## Schema Organization

Schemas are organized by:
- **Domain**: Grouped by business domain or service boundary
- **Version**: Major versions maintained for backward compatibility
- **Type**: Request, response, event, or shared types

## Schema Naming Convention

```
{domain}.{entity}.{version}.schema.json
```

Examples:
- `enrichment.metadata-request.v1.schema.json`
- `enrichment.metadata-response.v1.schema.json`
- `events.document-processed.v1.schema.json`
- `common.types.schema.json`

## Creating New Schemas

When creating a new schema:

1. **Use JSON Schema Draft 2020-12**:
   ```json
   {
     "$schema": "https://json-schema.org/draft/2020-12/schema",
     "$id": "https://your-org.com/schemas/entity.v1.schema.json",
     "title": "Entity Name",
     "type": "object"
   }
   ```

2. **Include Metadata**:
   - `$id`: Unique identifier for the schema
   - `title`: Human-readable name
   - `description`: Purpose and usage
   - `version`: Semantic version

3. **Define Validation Rules**:
   - Required vs. optional fields
   - Data types and formats
   - Constraints (min, max, pattern, enum)
   - Default values where appropriate

4. **Provide Examples**:
   ```json
   "examples": [
     {
       "field1": "value1",
       "field2": "value2"
     }
   ]
   ```

## Schema Validation

All schemas in this directory must:
- [ ] Be valid JSON Schema (validated in CI/CD)
- [ ] Include comprehensive descriptions
- [ ] Define all required fields
- [ ] Include at least one example
- [ ] Follow naming conventions
- [ ] Be reviewed and approved

## Versioning Strategy

- **Patch** (x.y.Z): Documentation, clarifications, non-breaking additions
- **Minor** (x.Y.0): Backward-compatible additions (new optional fields)
- **Major** (X.0.0): Breaking changes (removed/renamed fields, changed types)

## Post-Freeze Change Process

**After a schema reaches production freeze**, any change follows this mandatory process:

### For Breaking Changes (Major Version)
1. **Create ADR**: Document why change is needed, impact analysis
2. **Create New Schema File**: `{entity}.v{N+1}.schema.json`
3. **Maintain Old Version**: Keep previous version active during deprecation
4. **Update Consumers**: Notify all consuming systems (Search, RAG, Cosmos, etc.)
5. **Migration Period**: Minimum 6 months dual-version support
6. **Sunset Old Version**: After migration period + governance approval

### For Non-Breaking Changes (Minor Version)
1. **Create ADR**: Document rationale
2. **Add Optional Fields Only**: Never modify existing fields
3. **Update Documentation**: Include examples of new fields
4. **Notify Consumers**: Optional adoption timeline

### Absolutely Forbidden Post-Freeze
- ❌ In-place field modifications
- ❌ Changing field types
- ❌ Removing or renaming fields
- ❌ Making optional fields required
- ❌ Changing validation rules that reject previously valid data

**Rationale**: These changes break incremental indexing, content hashing, and downstream systems.

## Integration

These schemas are used by:
- API gateways for request/response validation
- Event processors for message validation
- Client libraries for type generation
- Documentation generators
- Testing frameworks

## Tools and References

- [JSON Schema Specification](https://json-schema.org/)
- [JSON Schema Validator](https://www.jsonschemavalidator.net/)
- [Understanding JSON Schema](https://json-schema.org/understanding-json-schema/)

---

**Example Schema Structure**:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://organization.com/schemas/example.v1.schema.json",
  "title": "Example Schema",
  "description": "Description of the schema purpose",
  "type": "object",
  "required": ["requiredField"],
  "properties": {
    "requiredField": {
      "type": "string",
      "description": "Description of this field",
      "minLength": 1,
      "maxLength": 255
    },
    "optionalField": {
      "type": "integer",
      "description": "An optional numeric field",
      "minimum": 0
    }
  },
  "additionalProperties": false,
  "examples": [
    {
      "requiredField": "example value",
      "optionalField": 42
    }
  ]
}
```
