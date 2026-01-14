# ADR 0002 — Schema Contract Freeze v1.0.0

## Status

Accepted

## Date

2026-01-14

## Decision Makers

- Architecture Team
- Data Governance Team
- Integration Team

## Context

The AI Metadata Enricher platform ingests metadata from two external source systems:
- **Synergy**: Student Information System
- **Zipline**: Assessment Management System

These systems export metadata in JSON format, which is validated against JSON Schemas before ingestion, indexing, and AI enrichment. The schemas define the external data contract between source systems and the enrichment platform.

### Why Freeze is Critical

**Stability for External Systems**: Synergy and Zipline teams need stable, predictable contracts. Frequent schema changes create integration fragility and operational risk.

**Deterministic Validation**: Schema validation must be reproducible and deterministic. Once data is validated against v1.0.0, the same data must always validate against v1.0.0.

**Compliance & Auditability**: Public-sector governance requires immutable contracts for data lineage and audit trails. Schema changes must be formally governed and versioned.

**Search Index Alignment**: The Azure AI Search index design is derived from these schemas (see ADR-0003). Schema changes could break the index, requiring reindexing.

**AI Contract Stability**: AI behavior contracts (prompts, outputs, validation rules) reference schema fields. Schema changes could invalidate AI contracts.

### Current State

- Synergy Export Schema v1.0.0: [contracts/schemas/synergy-export.schema.json](../../contracts/schemas/synergy-export.schema.json)
- Zipline Export Schema v1.0.0: [contracts/schemas/zipline-export.schema.json](../../contracts/schemas/zipline-export.schema.json)
- Both schemas use JSON Schema Draft 2020-12
- Both schemas define 8 required fields (MVP-appropriate minimal fields)
- Additional optional fields allow flexibility without breaking changes

### Problem Statement

Without formal freeze governance:
- Developers might modify schemas in-place, breaking external integrations
- Schema versions could drift from documented versions
- No clear process for schema evolution
- Risk of unintentional breaking changes
- Auditability gaps for compliance

## Considered Options

### Option 1: Freeze Schemas v1.0.0 with Formal Governance

**Description**: Declare synergy-export.schema.json and zipline-export.schema.json as frozen at v1.0.0. Prohibit in-place modifications. Require ADR approval for any schema changes. Enforce semantic versioning.

**Pros**:
- Stable, predictable contracts for external systems
- Clear governance process for changes
- Auditability for compliance frameworks
- Prevents accidental breaking changes
- Aligns with external contract best practices
- Protects downstream dependencies (search index, AI contracts)

**Cons**:
- Less flexibility for rapid iteration
- Requires formal process for even minor changes
- May slow down feature development

### Option 2: Allow In-Place Schema Modifications

**Description**: Treat schemas as living documents. Allow modifications without formal versioning or governance.

**Pros**:
- Faster iteration
- No bureaucracy for small changes

**Cons**:
- **Breaking changes without notice** (violates external contract principles)
- No auditability (compliance risk)
- Unpredictable behavior for external systems
- Risk of breaking search index or AI contracts
- Drift between documented and actual schemas
- Operational instability

### Option 3: Version Schemas But No Formal Governance

**Description**: Use semantic versioning but allow changes without ADR approval.

**Pros**:
- Versioning provides some stability
- Faster than full governance

**Cons**:
- No audit trail for why changes were made
- Risk of premature version bumps
- Unclear decision-making authority
- Insufficient for public-sector compliance

## Decision

**Schema Contract Freeze v1.0.0 is formally adopted.**

Both `synergy-export.schema.json` and `zipline-export.schema.json` are **frozen at version 1.0.0** as of 2026-01-14.

### Freeze Rules

1. **No In-Place Modifications**: Existing schema files MUST NOT be modified in place (except for documentation/comment clarifications that do not change validation behavior).

2. **Semantic Versioning Required**:
   - **Patch (1.0.X)**: Documentation only, no validation changes
   - **Minor (1.X.0)**: Backward-compatible additions (new optional fields)
   - **Major (X.0.0)**: Breaking changes (removed fields, changed types, new required fields)

3. **ADR Required for Changes**: Any schema change (minor or major) REQUIRES a new ADR documenting:
   - Reason for change
   - Impact analysis
   - Migration plan
   - Approval from Architecture and Data Governance teams

4. **New Files for New Versions**: Breaking changes create new schema files:
   - `synergy-export.v2.schema.json`
   - `zipline-export.v2.schema.json`

5. **External Communication**: Source system teams (Synergy/Zipline) MUST be notified of any schema changes with at least 30 days advance notice.

### Validation

- JSON Schema Draft 2020-12 compliance enforced via [tests/schemas/test_schemas.py](../../tests/schemas/test_schemas.py)
- Automated tests validate required fields, patterns, enums, and constraints
- Tests MUST pass before any schema version is considered frozen

## Consequences

### Positive Consequences

- **Stable External Contracts**: Synergy and Zipline teams have predictable, reliable integration contracts
- **Deterministic Validation**: Same data always validates the same way against frozen schema
- **Compliance Auditability**: Formal governance and versioning meet public-sector requirements
- **Protected Dependencies**: Search index and AI contracts are protected from breaking schema changes
- **Clear Evolution Path**: Semantic versioning provides clear upgrade path for future needs
- **Reduced Operational Risk**: No surprise breaking changes in production

### Negative Consequences

- **Slower Schema Evolution**: Changes require formal ADR process
- **Process Overhead**: Even small improvements require governance approval
- **Initial Rigidity**: v1 must be "good enough" for initial production use

### Neutral Consequences

- **Training Required**: Developers must understand freeze rules and versioning process
- **Documentation Burden**: ADRs required for all changes

## Implementation

### Immediate Actions

- [x] Create test suite for schema validation ([tests/schemas/test_schemas.py](../../tests/schemas/test_schemas.py))
- [x] Document freeze in schema README ([contracts/schemas/README.md](../../contracts/schemas/README.md))
- [x] Create this ADR documenting freeze governance
- [ ] Notify Synergy integration team of frozen contract
- [ ] Notify Zipline integration team of frozen contract
- [ ] Add schema validation to CI/CD pipeline (future)

### Follow-up Actions

- [ ] Create schema change request template for future ADRs
- [ ] Document migration process for major version upgrades
- [ ] Establish schema review board (Architecture + Data Governance)
- [ ] Set up automated schema validation in pull request checks

## Related Decisions

- [ADR-0003: Search Index Design Freeze v1.0.0](0003-search-index-design-freeze-v1.md) — Index design derived from these schemas
- [Contracts FREEZE v1.0.0](../../contracts/FREEZE-v1.0.0.md) — AI behavior contracts freeze

## References

- [Synergy Export Schema v1.0.0](../../contracts/schemas/synergy-export.schema.json)
- [Zipline Export Schema v1.0.0](../../contracts/schemas/zipline-export.schema.json)
- [Schema Governance Documentation](../../contracts/schemas/README.md)
- [JSON Schema Draft 2020-12 Specification](https://json-schema.org/draft/2020-12/schema)
- [Schema Validation Tests](../../tests/schemas/test_schemas.py)
