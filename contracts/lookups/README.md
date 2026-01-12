# Blob Path Lookup Configuration

## Purpose

This directory contains configuration artifacts that define **design-time mappings** between Azure Blob Storage paths and processing behavior in the AI Metadata Enrichment platform.

**CRITICAL**: These are configuration files, not runtime code. They define the contract between storage layout and platform behavior.

## Files

### lookup.json

**Status**: Design-time configuration  
**Version**: 1.0.0  
**Governance**: Same freeze and approval process as JSON Schemas

The `lookup.json` file maps blob storage path prefixes to:

1. **Source System**: Which system produced the data (synergy, zipline, documentation, etc.)
2. **Validation Schema**: Which JSON Schema to validate against (if applicable)
3. **Search Indexing**: Whether to index content in Azure AI Search for RAG
4. **Enrichment Trigger**: Whether to trigger AI enrichment pipeline
5. **Retention Policy**: How long to retain files before archival

## Blob Path Structure (Design-Time Contract)

The platform expects the following logical folder structure in Azure Blob Storage:

```
container/
├── raw/                    # Ingestion zone for source data
│   ├── synergy/           # Synergy exports (validated against synergy-export.schema.json)
│   ├── zipline/           # Zipline exports (validated against zipline-export.schema.json)
│   └── documentation/     # Unstructured docs (no schema validation)
├── enriched/              # Output zone for AI-enriched metadata
│   ├── synergy/           # Enriched Synergy metadata
│   └── zipline/           # Enriched Zipline metadata
├── archive/               # Long-term cold storage (7-year retention)
└── quarantine/            # Failed validation or processing (manual review)
```

## How lookup.json is Used

### 1. Event Routing (Design)

When a blob is uploaded to Azure Storage, the Event Grid event includes the blob path:
```
/raw/synergy/student-enrollment-2026-01-12.json
```

The platform:
1. Matches the path against `pathPrefix` entries using **longest prefix match**
2. Identifies `sourceSystem: "synergy"`
3. Loads validation schema: `contracts/schemas/synergy-export.schema.json`
4. Determines behavior: `indexInSearch: true`, `triggerEnrichment: true`

### 2. Schema Validation (Design)

If a schema is defined for the path prefix:
- **Raw data** is validated against the schema before processing
- **Invalid data** is moved to `quarantine/` with validation errors logged
- **Valid data** proceeds to enrichment pipeline

### 3. Search Indexing (Design)

If `indexInSearch: true`:
- Content is indexed in Azure AI Search
- Embeddings are generated for semantic search
- Metadata is stored in Cosmos DB for RAG context

### 4. Enrichment Pipeline (Design)

If `triggerEnrichment: true`:
- AI enrichment functions are invoked
- LLM processing adds semantic tags, summaries, relationships
- Enriched output is written to `enriched/{sourceSystem}/`

## Matching Rules

### Longest Prefix Match

Defined in `lookup.json` → `lookupRules.matchingStrategy`:

```json
"matchingStrategy": "longestPrefixMatch"
```

Example:
- Path: `/raw/synergy/enrollments/2026-01-12.json`
- Matches: `raw/synergy/` (not just `raw/`)

### Case Sensitivity

```json
"caseSensitive": false
```

Paths are matched case-insensitively for Azure Blob Storage compatibility:
- `/raw/synergy/` matches `/Raw/Synergy/`
- `/RAW/SYNERGY/` matches `/raw/synergy/`

### Path Normalization

```json
"pathNormalization": "forwardSlashes"
```

All paths normalized to forward slashes before matching:
- `raw\synergy\file.json` → `raw/synergy/file.json`

## Governance

### Ownership

- **Owner**: Platform Architecture Team
- **Approvers**: Architecture Team Lead + Security Team Lead

### Change Process

**CRITICAL**: Changes to `lookup.json` follow the same governance as JSON Schemas:

1. **Breaking Changes** (new major version required):
   - Removing or renaming `pathPrefix` values
   - Changing `sourceSystem` mappings
   - Removing required fields

2. **Non-Breaking Changes** (minor version):
   - Adding new path mappings
   - Adding optional fields
   - Updating descriptions

3. **All Changes Require**:
   - Architecture Decision Record (ADR)
   - Approval from designated approvers
   - Documentation update
   - Communication to consuming teams

### Freeze Protocol

Once `lookup.json` reaches production freeze:
- **No in-place modifications** allowed
- Changes require new version (v2.0.0, etc.)
- Old version maintained during deprecation period
- Migration path documented in ADR

**Current Status**: `pre-production` (not yet frozen)

## Integration with Platform

### Azure Functions

Functions use `lookup.json` to:
- Determine which schema validator to invoke
- Route events to appropriate enrichment handlers
- Apply retention and lifecycle policies
- Configure Search indexing behavior

### Infrastructure (Bicep)

Bicep templates reference path prefixes for:
- Blob lifecycle management policies (move to archive after retention)
- Event Grid subscription filters (trigger on specific prefixes)
- RBAC assignments (different permissions per path)

### Cosmos DB

Blob metadata stored in Cosmos includes:
- `sourceSystem` from lookup
- `schemaVersion` validated against
- `indexedInSearch` flag
- `enrichmentStatus` (pending, complete, failed)

## Example Usage Scenarios

### Scenario 1: Ingest Synergy Export

1. File uploaded: `/raw/synergy/enrollment-data-2026-01-12.json`
2. Lookup matches: `raw/synergy/` → `sourceSystem: "synergy"`
3. Validate against: `contracts/schemas/synergy-export.schema.json`
4. If valid:
   - Index in Azure AI Search (`indexInSearch: true`)
   - Trigger enrichment (`triggerEnrichment: true`)
   - Store metadata in Cosmos DB
5. If invalid:
   - Move to `/quarantine/synergy/enrollment-data-2026-01-12.json`
   - Log validation errors
   - Alert operations team

### Scenario 2: Ingest Documentation

1. File uploaded: `/raw/documentation/data-dictionary.pdf`
2. Lookup matches: `raw/documentation/` → `sourceSystem: "documentation"`
3. No schema validation (`schema: null`)
4. Index in Search (`indexInSearch: true`)
5. Skip enrichment (`triggerEnrichment: false`)

### Scenario 3: Archive Old Data

1. Lifecycle policy triggers after 90 days
2. File moved: `/raw/synergy/old-file.json` → `/archive/synergy/old-file.json`
3. Lookup matches: `archive/` → `indexInSearch: false`, `triggerEnrichment: false`
4. Search index entry marked for deletion
5. Retained in cold storage for 7 years (compliance)

## Future Considerations

### Extensibility

`lookup.json` can be extended with:
- Custom enrichment pipeline configurations
- Source-specific retention policies
- Data classification levels (public, internal, confidential)
- Cost center tags for chargeback

### Multi-Tenant Support

Future versions may include:
- Tenant-specific path prefixes: `/raw/{tenantId}/synergy/`
- Tenant-specific schemas and policies
- Isolation guarantees via path-based RBAC

## Validation

To validate `lookup.json` structure:

```python
import json
from pathlib import Path

# Load lookup configuration
lookup_path = Path("contracts/lookups/lookup.json")
with open(lookup_path, 'r') as f:
    lookup = json.load(f)

# Validate required fields
assert "version" in lookup
assert "blobMappings" in lookup
assert isinstance(lookup["blobMappings"], list)

for mapping in lookup["blobMappings"]:
    assert "pathPrefix" in mapping
    assert "sourceSystem" in mapping
    assert "indexInSearch" in mapping
    assert "triggerEnrichment" in mapping

print("lookup.json structure valid")
```

## References

- [JSON Schemas](../schemas/README.md)
- [Architecture Documentation](../../docs/architecture.md)
- [Governance Framework](../../docs/governance.md)
- [Schema Freeze Protocol](../README.md#schema-freeze-protocol)

---

**Document Version**: 1.0  
**Last Updated**: 2026-01-12  
**Status**: Design-time configuration (pre-production)
