from typing import Tuple, Dict, Any

from .result import ValidationResult
from .structural_validator import validate_structural, _parse_yaml_subset
from .semantic_validator import validate_semantic


def validate_output(yaml_text: str) -> Tuple[ValidationResult, ValidationResult]:
    """Run two-layer validation on the given YAML text.

    Returns a tuple: (structural_result, semantic_result).
    Semantic validation runs only if structural validation passes; otherwise,
    semantic_result will be a valid() placeholder with no errors.
    """
    structural = validate_structural(yaml_text)
    if not structural.is_valid:
        return structural, ValidationResult.valid()

    parsed, parse_errors = _parse_yaml_subset(yaml_text)
    # Structural should have caught parse errors; be defensive
    if parse_errors:
        return ValidationResult.invalid(structural=parse_errors), ValidationResult.valid()

    semantic = validate_semantic(parsed)
    return structural, semantic
