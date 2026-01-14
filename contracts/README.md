# Contracts

This directory contains API contracts, schemas, and **AI behavior contracts** for the AI Metadata Enricher platform.

## Purpose

Contracts define the interfaces, data structures, and **AI behavior specifications** used across the platform, ensuring:
- **Consistency**: Standardized data formats across services
- **Validation**: Schema-based validation of inputs and outputs
- **Deterministic AI Behavior**: Frozen, versioned contracts governing LLM prompts, outputs, and validation
- **Documentation**: Self-documenting API specifications
- **Versioning**: Clear evolution of interfaces over time
- **Governance**: Auditable, change-controlled AI behavior suitable for production

## Directory Structure

```
contracts/
├── prompts/           # AI prompt templates (v1 FROZEN)
├── outputs/           # AI output format contracts (v1 FROZEN)
├── validation/        # AI validation rules (v1 FROZEN)
├── schemas/           # JSON Schema definitions for data validation
│   └── README.md
├── lookups/           # Reference data and controlled vocabularies
│   └── README.md     
└── docs/              # Contract documentation and specifications
    └── README.md
```

## AI Behavior Contracts (v1.0.0 - FROZEN MVP)

**Status:** FROZEN as of 2026-01-14  
**Profile:** Minimal Safe MVP Rule Set  
**Freeze Notice:** See [FREEZE-v1.0.0.md](FREEZE-v1.0.0.md) for complete details

The platform includes **design-time governance artifacts** that define how AI components behave.  
**MVP deployment uses a streamlined rule set** focusing on essential safety while reducing operational complexity.

### 1. Prompt Templates ([`prompts/`](prompts/))
**File:** [v1-metadata-enrichment.prompt.yaml](prompts/v1-metadata-enrichment.prompt.yaml) | [README](prompts/README.md)

- Defines the AI's role, instructions, and constraints
- System prompt, instruction prompt, and explicit prohibitions
- RAG-first: AI can ONLY use context from Azure AI Search
- Human-in-the-loop: AI writes to "Suggested Description" only
- Model-agnostic and reusable across LLM providers

**MVP Changes:**
- Constraints reduced from 8 to 7 (streamlined, core prohibitions maintained)
- Emphasis on admitting uncertainty (confidence='low' when context is weak)

**Key Constraints:**
- C001-C004: No free-text, no hallucination, RAG-only
- C005-C007: Admit uncertainty, cite sources, reflect context quality

### 2. Output Format ([`outputs/`](outputs/))
**File:** [v1-metadata-enrichment.output.yaml](outputs/v1-metadata-enrichment.output.yaml) | [README](outputs/README.md)

- Strict YAML schema the AI MUST follow
- Required fields: `suggested_description`, `confidence`, `used_sources`
- Optional fields: `warnings`
- Designed for automated validation and human review
- No free-text outside YAML structure

**MVP Changes:**
- Structure UNCHANGED (same 4 fields)
- Validation enforcement streamlined to essential checks

**Key Requirements:**
- Valid YAML, no extra fields, no commentary
- Basic constraints (10-500 char length, enum confidence)
- Required source citations (grounding enforcement)

### 3. Validation Rules ([`validation/`](validation/))
**File:** [v1-metadata-enrichment.validation.yaml](validation/v1-metadata-enrichment.validation.yaml) | [README](validation/README.md)

- Deterministic acceptance/rejection rules
- **MVP: 16 total rules (11 blocking, 5 advisory)**
- Structural validation, required fields, grounding enforcement
- Hallucination detection (core indicators only for MVP)
- LLM-agnostic, automated, auditable

**MVP Changes:**
- **Reduced from 52+ rules to 16** (11 blocking, 5 advisory)
- Fine-grained patterns relaxed to core indicators
- Array size/length constraints moved to advisory
- Focus on essential safety, not comprehensive coverage

**Rule Categories:**
- **BLOCKING (11):** V001-V002 (structural), V010-V012 (required fields), V020-V021 (basic constraints), V030-V032 (grounding), V040 (context handling)
- **ADVISORY (5):** A001-A005 (quality monitoring, non-blocking flags)

---

### MVP Rationale and Guarantees

✅ **STILL ENFORCED (Non-Negotiable):**
- RAG-first architecture (no external knowledge) - V030, V032
- Human-in-the-loop (AI suggests, never overwrites) - C002, design-time guarantee
- Deterministic output (structured YAML only) - V001, V002
- Auditability (source citations required) - V012
- No hallucination (core indicators detected) - V030, V031, V032
- Admit uncertainty (low confidence when context weak) - V040

⚖️ **RELAXED FOR MVP (From Blocking to Advisory or Removed):**
- Fine-grained hallucination phrase lists (kept core patterns only)
- Array size limits beyond minimum (e.g., max 10 sources → advisory)
- Item length constraints (e.g., source excerpt length → advisory)
- Complex context alignment heuristics (simplified to essential V040)
- Short description flagging (advisory only)

🎯 **POST-MVP EVOLUTION:**
- Production data will inform stricter validation rules
- Advisory flags guide which rules to make blocking
- Version 1.1.0+ can add rules without breaking changes
- ADR-driven enhancements based on real-world patterns

---

### Deliverables Summary

✅ **Created (MVP Profile):**
- 3 frozen contract specifications (prompts, outputs, validation)
- 4 comprehensive README files (contracts/, prompts/, outputs/, validation/)
- 1 freeze notice document (FREEZE-v1.0.0.md with MVP details)
- Complete governance and change control documentation

✅ **Enforces:**
- RAG-first architecture (no external knowledge) - **STRICT**
- Human-in-the-loop (AI suggests, humans approve) - **STRICT**
- Deterministic behavior (structured outputs only) - **STRICT**
- Auditability and compliance (versioned, traceable) - **STRICT**

✅ **Balances:**
- Essential safety guarantees (11 blocking rules)
- Operational flexibility (5 advisory rules, reduced false rejections)
- Post-production evolution (data-driven rule enhancements)

✅ **Ready For:**
- Runtime implementation (Python, C#, JavaScript)
- Integration with Azure AI Search (RAG context retrieval)
- Human review workflows (UI/UX development)
- MVP deployment with monitoring and continuous improvement

---

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
- AI contracts: `v{major}-{purpose}.{type}.yaml` (e.g., `v1-metadata-enrichment.prompt.yaml`)

## Usage

Schemas are used for:
1. **Runtime Validation**: Validating API requests and responses
2. **Code Generation**: Generating type definitions and models
3. **Documentation**: Auto-generating API documentation
4. **Testing**: Validating test data and mocks

**AI Contracts** are used for:
1. **Prompt Construction**: Building LLM requests with versioned templates
2. **Output Validation**: Enforcing structured AI responses
3. **Automated Quality Control**: Accepting/rejecting AI suggestions deterministically
4. **Audit and Governance**: Traceable, versioned AI behavior specifications

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

Once a schema or AI contract reaches **production freeze**:
1. **No modifications** to existing version allowed
2. Changes require new major/minor version
3. Migration path documented in ADR
4. Consuming systems (Search, RAG, Cosmos) notified 30 days in advance
5. Old version deprecated with clear sunset timeline

**AI Contracts** follow the same freeze protocol:
- v1.0.0 frozen as of 2026-01-14
- Any change requires v1.1.0+ (minor) or v2.0.0+ (major)
- ADR required documenting rationale and impact
- Architecture + Security approval mandatory

## Best Practices

1. **Be Explicit**: Define all required and optional fields
2. **Use Constraints**: Apply appropriate validation rules (min, max, pattern, etc.)
3. **Provide Examples**: Include example data in schema definitions
4. **Document Purpose**: Explain the intent of each schema field
5. **Version Carefully**: Plan for evolution without breaking existing consumers

---

For questions or contributions, see [CONTRIBUTING.md](../CONTRIBUTING.md)
