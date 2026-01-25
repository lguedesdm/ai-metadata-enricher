# AI Prompt Templates (MVP)

**Version:** 1.0.0 (FROZEN - MVP Profile)  
**Frozen Date:** 2026-01-14  
**Profile:** Minimal Safe MVP Prompt  
**Status:** Production-Ready, Change-Controlled

---

## Purpose

This directory contains **frozen, versioned prompt templates (MVP profile)** that define how the AI system reasons and operates in the metadata enrichment platform.

**MVP Philosophy:** Streamlined for initial deployment while maintaining core architectural guarantees.

Prompt templates are **design-time governance artifacts** that:
- Define the AI's role and identity
- Specify task instructions and grounding requirements
- Enforce architectural constraints (RAG-first, human-in-the-loop, no hallucination)
- Ensure consistent, deterministic AI behavior across LLM providers
- **Balance comprehensiveness with operational simplicity for MVP**

---

## Current Version

### v1-metadata-enrichment.prompt.yaml (FROZEN)

**Components:**
1. **System Prompt:** Defines the AI as a governed metadata enrichment assistant
2. **Instruction Prompt:** Explains the task with strict RAG grounding requirements
3. **Constraints:** Explicit prohibitions and behavioral boundaries

**Key Principles:**
- RAG-first: AI can ONLY use context from Azure AI Search
- Human-in-the-loop: AI writes ONLY to "Suggested Description" field
- Transparent: AI must cite sources and admit uncertainty
- No hallucination: AI cannot invent information or use external knowledge
- Model-agnostic: Works with any LLM provider (OpenAI, Azure OpenAI, Anthropic, etc.)

**Constraints Enforced:**
- C001: No free-text outside YAML format (V001, V002)
- C002: No modifying official metadata directly (architectural guarantee)
- C003: No using external knowledge or training data (V030, V032)
- C004: No inventing information not in RAG context (V030, V031, V032)
- C005: When context insufficient, set confidence='low' and add warnings (V040)
- C006: All claims must be cited with source excerpts (V012)
- C007: Confidence must reflect context quality (V021, V040)

**MVP Changes:**
- Reduced from 8 to 7 constraints (merged C006 into C001)
- Simplified enforcement mapping to align with streamlined validation (11 blocking rules)
- Maintained all core prohibitions (external knowledge, hallucination, free-text)

---

## Governance

### Change Control

**This template is FROZEN.**

Any modification requires:
1. **New version number** (v1.1.0 for minor, v2.0.0 for major)
2. **Architecture Decision Record (ADR)** documenting rationale
3. **Approval from:**
   - Architecture Team
   - Security Team
4. **Impact analysis** on existing workflows
5. **Testing** with representative RAG contexts

### Why Governance Matters

Prompt templates are the **foundation of AI trust**:
- They define what the AI is allowed and forbidden to do
- Changes can introduce hallucination, bias, or unsafe behavior
- Public-sector environments require auditable, traceable AI decisions
- Version control enables rollback and compliance verification

---

## Usage

### For Runtime Implementers

When implementing this prompt template:

1. **Load the template** from this file (YAML parsing)
2. **Combine sections** according to your LLM provider's format:
   - OpenAI: `[{"role": "system", "content": system_prompt + constraints}, {"role": "user", "content": instruction_prompt + context}]`
   - Azure OpenAI: Same as OpenAI
   - Anthropic: Use system parameter for system_prompt, user messages for instructions
3. **Append dynamic context:**
   - Asset metadata (entity type, current fields)
   - RAG context (retrieved documents/excerpts from Azure AI Search)
4. **Configure response format:**
   - Request structured YAML output
   - Use JSON mode if LLM supports it (then convert to YAML)
   - Enforce output contract from `contracts/outputs/`

### For AI Reviewers

This template ensures the AI:
- Cannot modify official metadata (only suggests changes)
- Cannot use external knowledge (only RAG-retrieved context)
- Must cite sources for every claim
- Must admit when it doesn't know

If you see AI output that violates these rules, it should have been rejected by validation. Report such cases for investigation.

---

## Version History

| Version | Date       | Status | Changes |
|---------|------------|--------|---------|
| 1.0.0   | 2026-01-14 | FROZEN | Initial freeze for production use |

---

## Related Artifacts

- **Output Contract:** [`../outputs/v1-metadata-enrichment.output.yaml`](../outputs/v1-metadata-enrichment.output.yaml)
- **Validation Rules:** [`../validation/v1-metadata-enrichment.validation.yaml`](../validation/v1-metadata-enrichment.validation.yaml)
- **Architecture Docs:** [`../../docs/architecture.md`](../../docs/architecture.md)
- **ADR Template:** [`../../docs/adr/template.md`](../../docs/adr/template.md)

---

**Reminder:** This is a production-oriented, governed platform. Prompts are not experimental. They are auditable contracts.

---

## Structured Prompt & Grounding Rules (Design-Time Contracts)

The following artifacts define deterministic, auditable behavior for generating Purview Suggested Descriptions using RAG-only inputs. They are design-time contracts and must not be embedded in application code.

### v1-suggested-description.prompt.md (Design-Time)
- Purpose: Provides a structured prompt with explicit sections and placeholders.
- Sections: System Role, Task Objective, Asset Metadata ({{asset_metadata}}), Retrieved Context ({{retrieved_context}}), Grounding Rules, Output Instructions.
- Output: Business-friendly text only, 1–3 sentences, no references to the LLM, prompt, or internal systems; intended for Purview’s Suggested Description field.

### v1-grounding-rules.md (Design-Time)
- Purpose: Defines strict rules to prevent hallucinations and enforce input-only grounding.
- Key rules: Use only inputs; never invent/infer; avoid speculative language; handle sensitive info conservatively; state uncertainty explicitly when context is insufficient; keep output business-friendly and free of internal references.

### Intent and Scope
- Intent: Establish a clear, governance-ready foundation for later runtime execution.
- Prevents hallucinations: Rules prohibit invention/speculation and restrict sensitive information.
- Scope boundaries: No LLM calls, no runtime orchestration, no YAML/JSON enforcement here. Later tasks will add formatting contracts and validation.

### Locations
- Prompt Template: [`./v1-suggested-description.prompt.md`](./v1-suggested-description.prompt.md)
- Grounding Rules: [`./v1-grounding-rules.md`](./v1-grounding-rules.md)

