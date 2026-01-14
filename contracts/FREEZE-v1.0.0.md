# AI Behavior Contracts - Freeze Notice (MVP Safe Rule Set)

**Version:** 1.0.0 (MVP Profile)  
**Status:** FROZEN  
**Freeze Date:** 2026-01-14  
**Effective Date:** 2026-01-14  
**Profile:** Minimal Safe MVP Rule Set  
**Approval Authority:** Architecture Team + Security Team

---

## Freeze Summary

The following AI behavior contracts are hereby **FROZEN** for MVP production deployment with a **Minimal Safe Rule Set**:

### 1. Prompt Templates (MVP)
- **File:** [`contracts/prompts/v1-metadata-enrichment.prompt.yaml`](prompts/v1-metadata-enrichment.prompt.yaml)
- **Version:** 1.0.0
- **Profile:** Minimal Safe MVP Prompt
- **Purpose:** Defines AI role, instructions, and constraints for metadata enrichment
- **Status:** FROZEN
- **Changes:** Streamlined from 8 to 7 constraints, focus on essential prohibitions

### 2. YAML Output Format (MVP)
- **File:** [`contracts/outputs/v1-metadata-enrichment.output.yaml`](outputs/v1-metadata-enrichment.output.yaml)
- **Version:** 1.0.0
- **Profile:** Minimal Safe MVP Output Contract
- **Purpose:** Defines strict YAML structure for AI responses
- **Status:** FROZEN
- **Changes:** Structure unchanged; validation enforcement streamlined

### 3. Validation Rules (MVP)
- **File:** [`contracts/validation/v1-metadata-enrichment.validation.yaml`](validation/v1-metadata-enrichment.validation.yaml)
- **Version:** 1.0.0
- **Profile:** Minimal Safe MVP Rule Set
- **Purpose:** Defines deterministic acceptance/rejection criteria
- **Status:** FROZEN
- **Changes:** Reduced from 52+ rules to 16 (11 blocking, 5 advisory)

---

## MVP Profile Rationale

This freeze represents a **Minimal Safe MVP deployment** that:

### ✅ **PRESERVES Core Architectural Guarantees**
- RAG-first: AI can ONLY use Azure AI Search context
- Human-in-the-loop: AI suggests, humans approve
- Deterministic output: Structured YAML only
- Auditability: Source citations required
- No external knowledge: Explicit detection and rejection

### ⚖️ **BALANCES Safety with Operational Flexibility**
- **Blocking rules (11):** Essential safety, grounding, structure
- **Advisory rules (5):** Quality insights without false rejections
- Reduced phrase pattern lists (core indicators only)
- Relaxed array size/length constraints (advisory monitoring)

### 🎯 **ENABLES Post-Production Evolution**
- Production data will inform stricter rules
- Advisory flags guide rule enhancement
- Version 1.1.0+ can add blocking rules without breaking changes
- ADR-driven evolution based on real-world patterns

## What "Frozen (MVP Profile)" Means

These contracts are **immutable design-time specifications with MVP safety profile**:

✅ **ALLOWED:**
- Reference these contracts in runtime implementations
- Use them as-is without modification
- Cite them in ADRs and documentation
- Test against them
- Create runtime parsers and validators based on them
- Monitor advisory flags to inform post-MVP enhancements

❌ **FORBIDDEN:**
- Modify any blocking rule, constraint, or field in-place
- Add or remove sections without versioning
- Override rules for individual requests
- Use experimental or unapproved variations
- Weaken RAG-first or HITL guarantees

⚠️ **MVP CONTEXT:**
- This is a **Minimal Safe** rule set, not comprehensive
- Stricter rules may be introduced post-production via v1.1.0+
- Advisory rules flag quality issues without blocking
- Human review remains mandatory for all suggestions

---

## MVP Safety Profile Details

### What Was Streamlined for MVP

**Validation Rules:**
- **Removed from blocking:** Fine-grained hallucination phrase patterns, array size limits (beyond minimum), item length constraints, complex context alignment heuristics
- **Moved to advisory:** Quality flags (low confidence, short descriptions, single source usage, uncertainty language detection)
- **Reduced total rules:** From 52+ to 16 (11 blocking, 5 advisory)

**Prompts:**
- **Simplified constraints:** From 8 to 7 (merged structural requirements into C001)
- **Maintained focus:** Core prohibitions (external knowledge, hallucination, free-text responses)
- **Clarified guidance:** Explicit instruction to use confidence='low' when uncertain

**Output Contract:**
- **Structure:** Unchanged (4 fields: suggested_description, confidence, used_sources, warnings)
- **Validation enforcement:** Streamlined to essential checks only

### What Remains Strictly Enforced (BLOCKING)

1. **Structural Integrity** (V001-V002)
   - YAML parseability
   - No text outside YAML structure

2. **Required Fields** (V010-V012)
   - suggested_description present and non-empty
   - confidence present and valid enum
   - used_sources present and non-empty array

3. **Basic Constraints** (V020-V021)
   - Description length: 10-500 characters
   - Confidence: must be 'low', 'medium', or 'high'

4. **Grounding Enforcement** (V030-V032)
   - No explicit external knowledge references
   - No placeholder responses
   - No vague source attribution

5. **Context Handling** (V040)
   - Insufficient context → confidence must be 'low'

### Advisory Rules (NON-BLOCKING)

These generate flags for monitoring and review prioritization:
- A001: Low confidence flag
- A002: Short description flag
- A003: Warnings present flag
- A004: Single source flag
- A005: Uncertainty language flag

### Post-MVP Evolution Path

**Version 1.1.0+ May Introduce (Additive, Non-Breaking):**
- Additional hallucination detection patterns based on production data
- Entity-specific validation rules (e.g., dataset vs. report)
- Enhanced source citation quality checks
- Context quality scoring mechanisms
- More sophisticated confidence calibration

**Version 2.0.0+ May Introduce (Breaking Changes):**
- New required output fields
- Stricter length or array size constraints
- Changed confidence enum values
- Removal of optional fields
- Major prompt restructuring

---

## Change Control Process

To modify a frozen contract:

### Step 1: Determine Change Type

**Minor Change (v1.1.0):**
- Add optional field to output contract
- Add new advisory validation rule (info severity)
- Clarify prompt wording without changing behavior
- Add examples or documentation

**Major Change (v2.0.0):**
- Remove or rename fields in output contract
- Change required field constraints
- Add/remove critical validation rules
- Change prompt constraints or prohibitions
- Any breaking change to existing behavior

### Step 2: Document Rationale

Create an **Architecture Decision Record (ADR)** using [`docs/adr/template.md`](../docs/adr/template.md):
- Why is the change needed?
- What problem does it solve?
- What are the alternatives?
- What is the impact on existing workflows?
- What is the migration path?

### Step 3: Obtain Approval

**Required Approvals:**
- Architecture Team Lead
- Security Team Lead

**Optional Reviewers:**
- Platform Engineers
- Data Science Team
- Compliance Officer (for public-sector deployments)

### Step 4: Impact Analysis

Assess impact on:
- **Runtime Systems:** Parsing logic, validation enforcement
- **Human Review Workflows:** UI changes, training updates
- **Acceptance Rates:** Will more/fewer responses be accepted?
- **Audit and Compliance:** Traceability, governance documentation

### Step 5: Create New Version

1. **Copy frozen contract** to new versioned file:
   - `v1-metadata-enrichment.prompt.yaml` → `v2-metadata-enrichment.prompt.yaml`
2. **Make changes** in the new file only
3. **Update version metadata** (version number, freeze date, change log)
4. **Test thoroughly** with representative data
5. **Deprecate old version** with sunset timeline (minimum 6 months)

### Step 6: Communicate and Deploy

- Notify consuming teams 30 days in advance
- Update runtime implementations to use new version
- Monitor acceptance rates and validation outcomes
- Maintain old version in parallel during transition period

---

## Architectural Principles

These contracts enforce **non-negotiable architectural constraints**:

1. **Event-Driven Architecture**
   - No polling, no manual triggers (enforced at runtime)

2. **RAG-First**
   - AI can ONLY use context from Azure AI Search (enforced in prompts: C003, C004)
   - No external knowledge or training data (enforced in validation: V032)

3. **No Direct Access**
   - AI cannot call Synergy, Zipline, or documents directly (enforced at runtime)

4. **Human-in-the-Loop**
   - AI writes ONLY to "Suggested Description" field (enforced in prompts: C002)
   - Humans approve changes (enforced at runtime)

5. **No Automatic Overwrite**
   - Official metadata never modified by AI (enforced at runtime)

6. **Deterministic Behavior**
   - No free-form outputs (enforced in output contract, validation: V001-V003)
   - All responses parseable and structured (enforced in validation)

7. **Managed Identity**
   - No secrets in configuration (enforced at runtime, not in contracts)

---

## Compliance and Audit

### Traceability

Every AI decision is traceable to:
- **Prompt Version:** Which instructions the AI followed
- **Output Contract Version:** Which structure it produced
- **Validation Rules Version:** Which quality gates it passed
- **RAG Context:** Which documents informed the suggestion
- **Human Reviewer:** Who approved or rejected the suggestion

### Auditability

For compliance audits, provide:
- Frozen contract files (this repository)
- ADRs documenting changes (docs/adr/)
- Validation logs (runtime system)
- Human review logs (runtime system)
- Version history (this document)

### Public Sector Governance

These contracts are designed for public-sector and regulated environments:
- **Transparency:** AI behavior is explicitly documented
- **Accountability:** Changes require approval and rationale
- **Fairness:** Deterministic rules applied consistently
- **Explainability:** Source citations enable verification
- **Privacy:** No PII in training data (RAG-only, no fine-tuning)

---

## Version History

| Version | Freeze Date | Artifacts                          | Status | ADR Reference |
|---------|-------------|------------------------------------|--------|---------------|
| 1.0.0   | 2026-01-14  | Prompts, Outputs, Validation (v1) | FROZEN | Initial freeze (no ADR required) |

---

## Contact

For questions about frozen contracts:
- **Architecture Team:** See [governance.md](../docs/governance.md)
- **Change Requests:** Submit ADR using [template](../docs/adr/template.md)
- **Runtime Issues:** Report to platform engineering team
- **Compliance Questions:** Contact governance lead

---

## Appendix: Freeze Checklist

Before freezing a contract version, ensure:

- [ ] All required sections are complete and documented
- [ ] Examples are provided for valid and invalid cases
- [ ] Constraints are testable and deterministic
- [ ] Governance requirements are clearly stated
- [ ] Version number follows semantic versioning
- [ ] Freeze date is recorded in metadata
- [ ] Change control process is documented
- [ ] Related artifacts are cross-referenced
- [ ] README files explain purpose and usage
- [ ] Architecture and Security teams have reviewed
- [ ] Impact on existing systems is assessed
- [ ] Migration path (if applicable) is documented

**Freeze Status:** ✅ COMPLETE (2026-01-14)

---

**This document is part of the governed AI Metadata Enrichment platform.**  
**Unauthorized modifications are prohibited.**
