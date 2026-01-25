import re
from typing import Dict, Any, List

from .result import ValidationResult


FORBIDDEN_PHRASES = [
    r"\bLLM\b",
    r"\bprompt\b",
    r"\bpipeline\b",
    r"\bsystem\b",
    r"\bmodel\b",
    r"\bAI\b",
    r"\bChatGPT\b",
    r"\bOpenAI\b",
    r"\bAzure\s+OpenAI\b",
    r"\bAnthropic\b",
    r"\bClaude\b",
    r"\bGPT\b",
    r"\borchestrator\b",
]

GENERIC_PATTERNS = [
    r"^\s*This asset contains data\.?\s*$",
    r"^\s*Contains data\.?\s*$",
    r"^\s*A report\.?\s*$",
    r"^\s*Report about something\.?\s*$",
    r"^\s*Dataset\s*(with)?\s*information\.?\s*$",
]

CONFIDENCE_ALLOWED = {"low", "medium", "high"}

# Speculative or disallowed phrasing in suggested_description per grounding rules and output contract
FORBIDDEN_LANGUAGE = [
    r"\bbased\s+on\s+my\s+knowledge\b",
    r"\bin\s+general\b",
    r"\btypically\b",
    r"\blikely\b",
    r"\bprobably\b",
    r"\bappears\s+to\b",
    r"\bmay\b",
    r"\bcould\b",
]


def validate_semantic(parsed_yaml: Dict[str, Any]) -> ValidationResult:
    """Deterministic semantic validation.

    Preconditions: Structural validation passed and provided 'parsed_yaml'.
    Rules:
    - suggested_description: non-empty, length bounds, not trivially generic, no forbidden concepts
    - confidence: allowed closed set
    - used_sources: non-empty, strings, no forbidden source identifiers
    """
    errors: List[str] = []

    desc = parsed_yaml.get("suggested_description", "")
    if not isinstance(desc, str) or desc.strip() == "":
        errors.append("suggested_description must be a non-empty string")
    else:
        if len(desc) < 10:
            errors.append("suggested_description is too short (min 10 chars)")
        if len(desc) > 500:
            errors.append("suggested_description is too long (max 500 chars)")
        # Generic phrases
        for pat in GENERIC_PATTERNS:
            if re.search(pat, desc, flags=re.IGNORECASE):
                errors.append("suggested_description is trivially generic")
                break
        # Forbidden concepts
        for pat in FORBIDDEN_PHRASES:
            if re.search(pat, desc, flags=re.IGNORECASE):
                errors.append("suggested_description references forbidden concepts (LLM/prompt/system)")
                break
        # Speculative or disallowed language
        for pat in FORBIDDEN_LANGUAGE:
            if re.search(pat, desc, flags=re.IGNORECASE):
                errors.append("suggested_description uses speculative or disallowed phrasing (forbidden concepts)")
                break

    conf = parsed_yaml.get("confidence")
    if conf not in CONFIDENCE_ALLOWED:
        errors.append("confidence must be one of: low, medium, high")

    srcs = parsed_yaml.get("used_sources", [])
    if not isinstance(srcs, list) or len(srcs) == 0:
        errors.append("used_sources must be a non-empty array")
    else:
        for idx, s in enumerate(srcs):
            if not isinstance(s, str) or s.strip() == "":
                errors.append(f"used_sources[{idx}] must be a non-empty string")
                continue
            # Disallow generic or non-RAG identifiers
            if re.search(r"general knowledge|training data|internet|wikipedia", s, flags=re.IGNORECASE):
                errors.append(f"used_sources[{idx}] references forbidden source identifiers")

    if errors:
        return ValidationResult.invalid(semantic=errors)
    return ValidationResult.valid()
