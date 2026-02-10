"""
Runtime Validation Module — Enrichment Layer Integration.

Provides a deterministic, auditable validation gate for raw LLM output
before it proceeds further in the enrichment pipeline.

This module:
- Accepts raw LLM output as a string
- Executes the existing Validation Engine (structural + semantic)
- Evaluates advisory rules defined in the frozen validation contract
- Returns an explicit result: PASS (with optional warnings) or BLOCK
- Emits structured log entries with correlationId propagation

This module does NOT:
- Invoke Azure OpenAI or any LLM
- Write to Microsoft Purview
- Modify validation rules, frozen contracts, or rule severity
- Interact with the Orchestrator (consumer, message_handler)
- Modify Domain or RAG logic

Usage (explicit invocation only):
    from src.enrichment.output_validator import validate_llm_output

    result = validate_llm_output(
        raw_output="suggested_description: ...",
        correlation_id="abc-123",
    )
    if result.status == "PASS":
        # proceed with validated output
        ...
    elif result.status == "BLOCK":
        # reject and log blocking errors
        ...
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.domain.validation.validator import validate_output
from src.domain.validation.structural_validator import _parse_yaml_subset
from src.domain.validation.result import ValidationResult

logger = logging.getLogger("enrichment.output_validator")

# ---------------------------------------------------------------------------
# Contract version this runtime is built against
# ---------------------------------------------------------------------------
CONTRACT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------

class ValidationStatus(str, Enum):
    """Explicit status for runtime validation outcome."""

    PASS = "PASS"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class AdvisoryFlag:
    """A single advisory (non-blocking) flag raised during validation."""

    rule_id: str
    rule_name: str
    message: str


@dataclass(frozen=True)
class RuntimeValidationResult:
    """Complete result of runtime validation for a single LLM output.

    Attributes:
        status: PASS or BLOCK.
        blocking_errors: List of error strings from blocking rules that
            caused rejection.  Empty when status is PASS.
        advisory_flags: List of AdvisoryFlag objects.  May be non-empty
            even when status is PASS — advisory flags never block.
        rules_executed: List of rule IDs that were evaluated.
        raw_output: The original LLM output string that was validated.
    """

    status: ValidationStatus
    blocking_errors: List[str] = field(default_factory=list)
    advisory_flags: List[AdvisoryFlag] = field(default_factory=list)
    rules_executed: List[str] = field(default_factory=list)
    raw_output: str = ""

    def __post_init__(self) -> None:
        """Enforce internal consistency invariants.

        Prevents construction of structurally impossible states:
        - PASS with non-empty blocking_errors
        - BLOCK with non-empty advisory_flags
        """
        if self.status == ValidationStatus.PASS and len(self.blocking_errors) > 0:
            raise ValueError(
                "Inconsistent state: status is PASS but blocking_errors is non-empty. "
                "A PASS result must have zero blocking errors."
            )
        if self.status == ValidationStatus.BLOCK and len(self.advisory_flags) > 0:
            raise ValueError(
                "Inconsistent state: status is BLOCK but advisory_flags is non-empty. "
                "Advisory rules must not be evaluated when blocking rules fail."
            )


# ---------------------------------------------------------------------------
# Advisory rule IDs (from frozen validation contract v1)
# ---------------------------------------------------------------------------

_ADVISORY_UNCERTAINTY_PATTERNS = [
    re.compile(r"(?i)(appears to be|seems to be|likely|possibly|potentially)"),
]


def _evaluate_advisory_rules(
    parsed: Dict[str, Any],
) -> tuple[list[AdvisoryFlag], list[str]]:
    """Evaluate advisory (non-blocking) rules from the frozen contract.

    Advisory rules generate flags for human-review prioritisation but
    never cause rejection.

    Returns:
        (advisory_flags, rule_ids_executed)
    """
    flags: list[AdvisoryFlag] = []
    executed: list[str] = []

    # A001 — Low Confidence Flag
    executed.append("A001")
    confidence = parsed.get("confidence")
    if confidence == "low":
        flags.append(
            AdvisoryFlag(
                rule_id="A001",
                rule_name="Low Confidence Flag",
                message="Low confidence response - prioritize for human review.",
            )
        )

    # A002 — Short Description Flag
    executed.append("A002")
    desc = parsed.get("suggested_description", "")
    if isinstance(desc, str) and 0 < len(desc) < 30:
        flags.append(
            AdvisoryFlag(
                rule_id="A002",
                rule_name="Short Description Flag",
                message="Short description - may lack detail.",
            )
        )

    # A003 — Warnings Present Flag
    executed.append("A003")
    warnings_val = parsed.get("warnings")
    if isinstance(warnings_val, list) and len(warnings_val) > 0:
        flags.append(
            AdvisoryFlag(
                rule_id="A003",
                rule_name="Warnings Present Flag",
                message="Response contains warnings - review carefully.",
            )
        )

    # A004 — Single Source Flag
    executed.append("A004")
    sources = parsed.get("used_sources")
    if isinstance(sources, list) and len(sources) == 1:
        flags.append(
            AdvisoryFlag(
                rule_id="A004",
                rule_name="Multiple Sources Flag",
                message="Single source used - consider if additional context was available.",
            )
        )

    # A005 — Uncertainty Language Flag
    executed.append("A005")
    if isinstance(desc, str):
        for pattern in _ADVISORY_UNCERTAINTY_PATTERNS:
            if pattern.search(desc):
                flags.append(
                    AdvisoryFlag(
                        rule_id="A005",
                        rule_name="Uncertainty Language Flag",
                        message="Uncertainty language detected - AI expressing low certainty.",
                    )
                )
                break

    return flags, executed


# ---------------------------------------------------------------------------
# Blocking rule IDs evaluated by the existing Validation Engine
# ---------------------------------------------------------------------------

_BLOCKING_RULE_IDS = [
    "V001",  # YAML Parseability
    "V002",  # No Extraneous Text
    "V010",  # Suggested Description Present
    "V011",  # Confidence Present
    "V012",  # Used Sources Present
    "V020",  # Suggested Description Length
    "V021",  # Confidence Allowed Values
    "V030",  # No Explicit External Knowledge
    "V031",  # No Placeholder Responses
    "V032",  # Source Attribution Not Vague
    "V040",  # Insufficient Context Confidence
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_llm_output(
    raw_output: str,
    correlation_id: Optional[str] = None,
) -> RuntimeValidationResult:
    """Validate raw LLM output through the full Validation Engine.

    Executes the frozen validation rules in contract-specified order:
      1. Blocking rules (structural → semantic) via the existing engine.
         First blocking failure causes immediate BLOCK.
      2. Advisory rules — evaluated only when all blocking rules pass.
         Advisory flags are collected but never cause rejection.

    This function is deterministic: the same ``raw_output`` always
    produces the same ``RuntimeValidationResult``.

    Args:
        raw_output: The raw string produced by the LLM (or synthetic).
        correlation_id: Optional correlation ID propagated into every
            log entry for end-to-end traceability.

    Returns:
        RuntimeValidationResult with status PASS or BLOCK, any blocking
        errors, any advisory flags, and the list of rules executed.
    """
    log_extra: Dict[str, Any] = {}
    if correlation_id is not None:
        log_extra["correlationId"] = correlation_id

    logger.info(
        "Starting runtime validation of LLM output",
        extra={
            **log_extra,
            "rawOutputLength": len(raw_output) if raw_output else 0,
        },
    )

    # ------------------------------------------------------------------
    # Phase 1: Blocking validation (existing Validation Engine)
    # ------------------------------------------------------------------
    structural_result, semantic_result = validate_output(raw_output)

    blocking_errors: List[str] = []
    blocking_errors.extend(structural_result.structural_errors)
    blocking_errors.extend(semantic_result.semantic_errors)

    rules_executed = list(_BLOCKING_RULE_IDS)

    if not structural_result.is_valid or not semantic_result.is_valid:
        # Determine failure type for logging
        failure_type = "structural" if not structural_result.is_valid else "semantic"

        logger.warning(
            "Runtime validation BLOCKED — output rejected",
            extra={
                **log_extra,
                "validationStatus": "BLOCK",
                "failureType": failure_type,
                "blockingErrors": blocking_errors,
                "rulesExecuted": rules_executed,
            },
        )

        return RuntimeValidationResult(
            status=ValidationStatus.BLOCK,
            blocking_errors=blocking_errors,
            advisory_flags=[],
            rules_executed=rules_executed,
            raw_output=raw_output,
        )

    # ------------------------------------------------------------------
    # Phase 2: Advisory rules (only if blocking rules all passed)
    # ------------------------------------------------------------------
    parsed, _ = _parse_yaml_subset(raw_output)
    advisory_flags, advisory_rule_ids = _evaluate_advisory_rules(parsed)
    rules_executed.extend(advisory_rule_ids)

    logger.info(
        "Runtime validation PASSED",
        extra={
            **log_extra,
            "validationStatus": "PASS",
            "advisoryFlagCount": len(advisory_flags),
            "advisoryFlags": [
                {"ruleId": f.rule_id, "ruleName": f.rule_name, "message": f.message}
                for f in advisory_flags
            ],
            "rulesExecuted": rules_executed,
        },
    )

    return RuntimeValidationResult(
        status=ValidationStatus.PASS,
        blocking_errors=[],
        advisory_flags=advisory_flags,
        rules_executed=rules_executed,
        raw_output=raw_output,
    )
