# Validation Module (Design-Time)

This module implements deterministic structural and semantic validation for LLM outputs targeting Purview’s Suggested Description field.

Scope:
- Structural validation: YAML-subset parsing, fixed fields, required presence, types, and strict ordering.
- Semantic validation: Rule-based checks on content, confidence enum, and sources.
- No orchestration, persistence, logging, LLM calls, or corrections.

Artifacts:
- `structural_validator.py`: Deterministic YAML subset validator.
- `semantic_validator.py`: Rule-based semantic validator.
- `result.py`: Validation result contract.

Consumption:
- Future Orchestrator can invoke structural then semantic validation.
- Non-compliant outputs should be rejected early with explicit reasons.
