from typing import Dict, Any, List, Tuple

from .result import ValidationResult


EXPECTED_ORDER = [
    "suggested_description",
    "confidence",
    "used_sources",
    "warnings",
]

REQUIRED_FIELDS = [
    "suggested_description",
    "confidence",
    "used_sources",
]

OPTIONAL_FIELDS = ["warnings"]


def _parse_yaml_subset(yaml_text: str) -> Tuple[Dict[str, Any], List[str]]:
    """Parse a constrained YAML subset deterministically.

    Supports:
    - Top-level string fields: key: value (quoted or unquoted)
    - Top-level arrays: key: followed by indented '- item' lines OR 'key: []'

    Disallows:
    - Comments ('# ...')
    - Markdown or arbitrary preface text
    - Nested objects

    Returns: (parsed_dict, errors)
    """
    errors: List[str] = []
    if yaml_text is None:
        return {}, ["Input is None"]

    lines = [ln.rstrip("\r\n") for ln in yaml_text.splitlines()]
    # Remove empty lines
    lines = [ln for ln in lines if ln.strip() != ""]

    if any(ln.strip().startswith("#") for ln in lines):
        errors.append("Comments are not allowed in YAML output")

    # Track order and content
    parsed: Dict[str, Any] = {}
    seen_keys: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        # Top-level key must start at column 0 and contain ':'
        if ln.startswith(" ") or ":" not in ln:
            errors.append(f"Unexpected line format: '{ln}'")
            i += 1
            continue

        key, sep, rest = ln.partition(":")
        key = key.strip()
        value = rest.strip()

        if key in parsed:
            errors.append(f"Duplicate key '{key}'")

        seen_keys.append(key)

        # Array empty form: key: []
        if value == "[]":
            parsed[key] = []
            i += 1
            continue

        # Array block form: key: \n  - item\n  - item
        if value == "":
            # Collect indented array items
            items: List[str] = []
            j = i + 1
            while j < n:
                nxt = lines[j]
                stripped = nxt.lstrip()
                if stripped.startswith("-") and not stripped.startswith("- "):
                    # Disallow '-item' without space after '-'
                    errors.append(f"Invalid array item format: '{nxt}'")
                    j += 1
                    continue
                if stripped.startswith("- "):
                    items.append(stripped[2:].strip())
                    j += 1
                    continue
                # Not an array item; stop array collection
                break
            parsed[key] = items if items else None
            i = j
            continue

        # String scalar value (quoted or unquoted)
        scalar = value
        # Strip surrounding quotes if present
        if (scalar.startswith("\"") and scalar.endswith("\"")) or (
            scalar.startswith("'") and scalar.endswith("'")
        ):
            scalar = scalar[1:-1]
        parsed[key] = scalar
        i += 1

    return parsed, errors


def validate_structural(yaml_text: str) -> ValidationResult:
    """Deterministic structural validation per output contract.

    Checks:
    - Valid constrained YAML (subset) and parseable
    - Only defined fields present
    - All mandatory fields present
    - Field types (string/array)
    - Field ordering matches spec
    """
    parsed, parse_errors = _parse_yaml_subset(yaml_text)
    errors: List[str] = []

    if parse_errors:
        errors.extend(parse_errors)

    # Unknown fields
    for k in parsed.keys():
        if k not in REQUIRED_FIELDS and k not in OPTIONAL_FIELDS:
            errors.append(f"Unknown field '{k}' not permitted by contract")

    # Required presence
    for k in REQUIRED_FIELDS:
        if k not in parsed:
            errors.append(f"Missing required field '{k}'")

    # Types
    if "suggested_description" in parsed and not isinstance(parsed["suggested_description"], str):
        errors.append("Field 'suggested_description' must be a string")
    if "confidence" in parsed and not isinstance(parsed["confidence"], str):
        errors.append("Field 'confidence' must be a string")
    if "used_sources" in parsed:
        val = parsed["used_sources"]
        if not isinstance(val, list) or val is None:
            errors.append("Field 'used_sources' must be a non-empty array")
        else:
            if len(val) == 0:
                errors.append("Field 'used_sources' must contain at least one item")
            for idx, item in enumerate(val):
                if not isinstance(item, str) or item.strip() == "":
                    errors.append(f"used_sources[{idx}] must be a non-empty string")
    if "warnings" in parsed:
        val = parsed["warnings"]
        if not isinstance(val, list):
            errors.append("Field 'warnings' must be an array when present")
        else:
            for idx, item in enumerate(val):
                if not isinstance(item, str):
                    errors.append(f"warnings[{idx}] must be a string")

    # Ordering: reconstruct order from original text lines
    # Re-parse to get seen order without skipping unknown lines
    lines = [ln.rstrip("\r\n") for ln in yaml_text.splitlines() if ln.strip() != ""]
    seen_order: List[str] = []
    for ln in lines:
        if ln.startswith(" ") or ":" not in ln:
            # Only consider top-level keys
            if ln.lstrip().startswith("- "):
                continue
            # Any non-key line is a violation of determinism
            if not ln.lstrip().startswith("- ") and not ln.strip().startswith("#"):
                # Non-YAML text before/after
                errors.append(f"Unexpected non-key line: '{ln}'")
            continue
        key = ln.split(":", 1)[0].strip()
        seen_order.append(key)

    # Compare to expected order for keys present
    expected_seq = [k for k in EXPECTED_ORDER if k in parsed]
    if seen_order != expected_seq:
        errors.append(
            "Field order must be: suggested_description, confidence, used_sources, warnings"
        )

    if errors:
        return ValidationResult.invalid(structural=errors)
    return ValidationResult.valid()
