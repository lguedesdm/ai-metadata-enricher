# Grounding Rules — Suggested Description (Design-Time Contract)

**Version:** 1.0.0
**Status:** Draft (Design-Time Contract)
**Profile:** Deterministic, Safety-First, RAG-Only

---

## Purpose
These rules strictly govern how the LLM must use inputs to generate suggested descriptions for Microsoft Purview assets. They prevent hallucination, enforce determinism, and keep outputs business-friendly and safe.

---

## Rules (Authoritative)

1. Input-Only Usage
   - The LLM must use only the asset metadata and retrieved context provided via placeholders: {{asset_metadata}}, {{retrieved_context}}.
   - External knowledge, prior training facts, or assumptions are forbidden.

2. No Invention or Inference
   - Do not invent, infer, or assume facts not explicitly present in inputs.
   - Do not complete missing information with guesses or generic statements.

3. No Speculation
   - Avoid speculative terms: “likely”, “probably”, “appears to”, “may”, “could”, “might”, “suggests”, “seems”.
   - Write factual statements grounded in the inputs only.

4. Sensitive Information Safety
   - Do not include personal, confidential, or regulated information (e.g., PII, PHI, PCI) unless explicitly present in inputs.
   - If sensitive information appears in inputs, include it only if relevant to a business-friendly description and avoid unnecessary detail.

5. Explicit Uncertainty
   - If inputs are insufficient, state uncertainty plainly without referencing the LLM or system.
   - Recommended phrasing: “Insufficient context to provide a meaningful suggested description for this asset.”

6. Business-Friendly Language
   - Use clear, concise, non-technical phrasing suitable for business users.
   - Focus on what the asset is and typical usage or value when supported by inputs.

7. Output Scope Limitation
   - Output must be limited to text intended for Purview’s Suggested Description field.
   - Do not include headings, labels, citations, IDs, links, or internal system references.

8. Determinism and Consistency
   - Follow the structured prompt template sections and output instructions consistently across requests.
   - Changes to behavior require version bump and ADR.

---

## Rationale
- Prevents hallucinations by prohibiting invention and speculation.
- Ensures safety and compliance by restricting sensitive information.
- Maintains auditability through strict input-only grounding.
- Produces predictable, business-friendly outputs tailored for Purview.

---

## Scope Boundaries
- In scope: Behavioral rules for grounding and expression.
- Out of scope: Runtime validation, YAML/JSON output formats, LLM configuration/integration.
- Future: Validation will enforce these rules mechanically; orchestrator will manage placeholders and context injection.
