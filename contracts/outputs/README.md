# AI Output Format Contracts (MVP)

**Version:** 1.0.0 (FROZEN - MVP Profile)  
**Frozen Date:** 2026-01-14  
**Profile:** Minimal Safe MVP Output Contract  
**Status:** Production-Ready, Change-Controlled

---

## Purpose

This directory contains **frozen, versioned output format contracts (MVP profile)** that define the EXACT structure the AI must follow when generating metadata suggestions.

**MVP Philosophy:** Structure unchanged, validation enforcement streamlined to essential checks.

Output contracts are **design-time governance artifacts** that:
- Define required and optional fields
- Specify data types, constraints, and allowed values
- Enable automated validation and parsing
- Support human review and audit workflows
- Prevent free-text or unstructured AI responses
- **Focus validation on essential safety (MVP: 11 blocking rules)**

---

## Current Version

### v1-metadata-enrichment.output.yaml (FROZEN)

**Contract Structure:**

#### Required Fields
1. **suggested_description** (string, 10-500 chars)
   - AI-suggested description grounded in RAG context
   - Must be concise, accurate, and traceable to sources
   - No placeholder text, no forbidden phrases

2. **confidence** (enum: low | medium | high)
   - AI's confidence based on context quality
   - low: sparse/ambiguous context
   - medium: adequate context
   - high: rich, clear, directly relevant context

3. **used_sources** (array of strings, 1-10 items, max 200 chars each)
   - Specific excerpts or identifiers from RAG context
   - Enables human verification of AI grounding
   - Must reference actual retrieved content, not "general knowledge"

#### Optional Fields
1. **warnings** (array of strings, max 5 items, max 200 chars each)
   - Caveats about the suggestion
   - Used when context is insufficient or contradictory
   - Flags entity type mismatches or interpretation issues

---

## Structural Requirements

The AI response **MUST:**
- Be valid, parseable YAML
- Contain ONLY the defined fields (no extras)
- Have no text outside the YAML structure
- Match all type and constraint definitions

The AI response **MUST NOT:**
- Include preambles, commentary, or explanations
- Use code fences (` ```yaml `)
- Add extra fields not in the contract
- Contain empty required fields or placeholder values

---

## Governance

### Change Control

**This contract is FROZEN.**

Any modification requires:
1. **New version number** (v1.1.0 for minor, v2.0.0 for major)
2. **Architecture Decision Record (ADR)** documenting rationale
3. **Approval from:**
   - Architecture Team
   - Security Team
4. **Impact analysis:**
   - Runtime parsing logic updates
   - Validation rule adjustments
   - UI/UX changes for human review
5. **Migration path** for existing data

### Why Governance Matters

Output contracts are **machine-parseable specifications**:
- Changes break automated validation and processing
- Field additions/removals impact downstream systems
- Constraint changes affect acceptance rates
- Public-sector compliance requires stable, versioned interfaces

---

## Usage

### For Runtime Implementers

When implementing this output contract:

1. **Configure LLM for structured output:**
   - Use JSON mode or structured output features
   - Convert JSON to YAML if needed (keys match contract fields)
   - Instruct the LLM to follow this exact structure (via prompt)

2. **Parse the response:**
   - Use a YAML parser (e.g., PyYAML, js-yaml)
   - Handle parse errors as validation failures
   - Extract fields according to contract

3. **Validate against contract:**
   - Check all required fields are present and non-empty
   - Verify types (string, array, enum)
   - Enforce constraints (length, allowed values, array size)
   - Run validation rules from `contracts/validation/`

4. **Handle validation results:**
   - ACCEPTED: Queue for human review with any flags
   - REJECTED: Log failure reason, do not present to reviewers

### For Human Reviewers

This contract defines what you'll see:
- **suggested_description:** The AI's proposed metadata description
- **confidence:** How confident the AI is (low/medium/high)
- **used_sources:** Excerpts the AI based its suggestion on (verify these!)
- **warnings:** Any caveats or uncertainties the AI flagged

If a field is missing or malformed, the response was rejected before reaching you.

### For Validation Logic

See [`../validation/v1-metadata-enrichment.validation.yaml`](../validation/v1-metadata-enrichment.validation.yaml) for:
- Parsing rules (V001-V003)
- Required field checks (V010-V012)
- Constraint enforcement (V020-V025)
- Hallucination detection (V030-V032)

---

## Examples

### Valid Output (High Confidence)

```yaml
suggested_description: "Annual sustainability report for 2024 detailing carbon emissions reductions, renewable energy adoption, and water conservation initiatives across global operations."
confidence: high
used_sources:
  - "Document: sustainability-2024.pdf, Page 1: 'This report presents our environmental performance for fiscal year 2024.'"
  - "Document: sustainability-2024.pdf, Page 5: 'Carbon emissions decreased by 18% compared to 2023 baseline.'"
  - "Indexed blob: reports/sustainability/2024-annual.docx, Section 3.2: 'Renewable energy now powers 65% of facilities.'"
warnings: []
```

### Valid Output (Low Confidence with Warnings)

```yaml
suggested_description: "Financial data compilation with revenue and expense figures, purpose and time period uncertain based on available context."
confidence: low
used_sources:
  - "Document: data-export.csv, Header row: 'Date, Revenue, Expenses, Net Income'"
warnings:
  - "Context does not specify the reporting period or organizational unit."
  - "No metadata or documentation found describing the dataset's purpose."
  - "Entity type is 'dataset' but format suggests it may be a report extract."
```

### Invalid Outputs (Will Be Rejected)

❌ **Contains commentary:**
```
Here is my suggestion:
suggested_description: "A report about something."
confidence: high
```
*Rejection: Contains text outside YAML structure*

❌ **Empty required field:**
```yaml
suggested_description: ""
confidence: high
used_sources: []
```
*Rejection: Empty suggested_description and used_sources*

❌ **Forbidden phrase:**
```yaml
suggested_description: "Based on my general knowledge, this appears to be a financial report."
confidence: medium
used_sources:
  - "General knowledge about financial reports"
```
*Rejection: Uses forbidden phrase + vague source attribution*

❌ **Invalid confidence value:**
```yaml
suggested_description: "Quarterly report."
confidence: very_high
used_sources:
  - "Document XYZ"
```
*Rejection: 'very_high' is not an allowed value*

---

## Version History

| Version | Date       | Status | Changes |
|---------|------------|--------|---------|
| 1.0.0   | 2026-01-14 | FROZEN | Initial freeze for production use |

---

## Related Artifacts

- **Prompt Template:** [`../prompts/v1-metadata-enrichment.prompt.yaml`](../prompts/v1-metadata-enrichment.prompt.yaml)
- **Validation Rules:** [`../validation/v1-metadata-enrichment.validation.yaml`](../validation/v1-metadata-enrichment.validation.yaml)
- **Architecture Docs:** [`../../docs/architecture.md`](../../docs/architecture.md)

---

**Reminder:** This is a machine-parseable contract. Treat it as a stable API specification.
