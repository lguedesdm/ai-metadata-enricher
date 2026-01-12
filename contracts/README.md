# Contracts

This directory contains API contracts, schemas, and design-time definitions for the AI Metadata Enricher platform.

## Purpose

Contracts define the interfaces and data structures used across the platform, ensuring:
- **Consistency**: Standardized data formats across services
- **Validation**: Schema-based validation of inputs and outputs
- **Documentation**: Self-documenting API specifications
- **Versioning**: Clear evolution of interfaces over time

## Directory Structure

```
contracts/
├── schemas/           # JSON Schema definitions for data validation
│   └── README.md     
└── docs/             # Contract documentation and specifications
    └── README.md
```

## Schema Standards

All schemas in this repository:
- Follow JSON Schema Draft 2020-12 or later
- Include comprehensive descriptions and examples
- Define clear validation rules
- Are versioned using semantic versioning
- Are validated as part of CI/CD pipeline

## Naming Conventions

- Schema files: `{entity}.schema.json` (e.g., `metadata-enrichment.schema.json`)
- Version-specific: `{entity}.v{major}.schema.json` (e.g., `metadata-enrichment.v1.schema.json`)
- Shared definitions: `common.schema.json`, `types.schema.json`

## Usage

Schemas are used for:
1. **Runtime Validation**: Validating API requests and responses
2. **Code Generation**: Generating type definitions and models
3. **Documentation**: Auto-generating API documentation
4. **Testing**: Validating test data and mocks

## Contract Documentation

See [contracts/docs/](docs/) for detailed contract specifications, including:
- API endpoint definitions
- Message formats for event-driven communication
- Integration patterns and examples
- Version migration guides

## Schema Ownership and Governance

### Schema Owners
- **Primary Owner**: Platform Architecture Team
- **Approvers**: Architecture Team Lead + Security Team Lead
- **Reviewers**: All platform engineers and consuming teams

### Change Control Process

**CRITICAL**: Schemas represent **stable, versioned, immutable contracts** after freeze.

- All schema changes require ADR (Architecture Decision Record)
- Breaking changes require major version increment (new schema file)
- Non-breaking changes (optional fields) require minor version increment
- Backward compatibility maintained within major versions
- Deprecated fields marked clearly with sunset dates (minimum 6 months)
- **No in-place modifications after schema freeze** - always create new version

### Schema Freeze Protocol

Once a schema reaches **production freeze**:
1. **No modifications** to existing version allowed
2. Changes require new major/minor version
3. Migration path documented in ADR
4. Consuming systems (Search, RAG, Cosmos) notified 30 days in advance
5. Old version deprecated with clear sunset timeline

## Best Practices

1. **Be Explicit**: Define all required and optional fields
2. **Use Constraints**: Apply appropriate validation rules (min, max, pattern, etc.)
3. **Provide Examples**: Include example data in schema definitions
4. **Document Purpose**: Explain the intent of each schema field
5. **Version Carefully**: Plan for evolution without breaking existing consumers

---

For questions or contributions, see [CONTRIBUTING.md](../CONTRIBUTING.md)
