from dataclasses import dataclass, field
from typing import List


@dataclass
class ValidationResult:
    """Validation outcome for a single LLM output.

    - is_valid: True only if structural and semantic checks pass.
    - structural_errors: explicit reasons for structural rejection.
    - semantic_errors: explicit reasons for semantic rejection.
    
    This model does not mutate or correct input.
    """

    is_valid: bool
    structural_errors: List[str] = field(default_factory=list)
    semantic_errors: List[str] = field(default_factory=list)

    @classmethod
    def invalid(cls, structural: List[str] = None, semantic: List[str] = None) -> "ValidationResult":
        return cls(
            is_valid=False,
            structural_errors=list(structural or []),
            semantic_errors=list(semantic or []),
        )

    @classmethod
    def valid(cls) -> "ValidationResult":
        return cls(is_valid=True)
