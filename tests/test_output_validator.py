"""
Tests for the Runtime Validation Module (src/enrichment/output_validator).

Covers:
- Valid output → PASS, output unchanged
- Invalid output with blocking rule violation → BLOCK
- Output with advisory warnings → PASS with warnings, flow not blocked
- Determinism: same input → same result
- Isolation: no import or call to Orchestrator, LLM client, or Purview client
"""

import ast
import inspect
import sys

import pytest

from src.enrichment.output_validator import (
    AdvisoryFlag,
    RuntimeValidationResult,
    ValidationStatus,
    validate_llm_output,
)


# ======================================================================
# Fixtures — representative YAML payloads
# ======================================================================

VALID_OUTPUT = (
    'suggested_description: "Annual sustainability report for 2024 detailing carbon emissions reductions, renewable energy adoption, and water conservation initiatives across global operations."\n'
    "confidence: high\n"
    "used_sources:\n"
    "  - sustainability-2024.pdf, Page 1\n"
    "  - sustainability-2024.pdf, Page 5\n"
    "warnings: []"
)

VALID_OUTPUT_LOW_CONFIDENCE = (
    'suggested_description: "Financial data compilation with revenue and expense figures, purpose and time period uncertain."\n'
    "confidence: low\n"
    "used_sources:\n"
    "  - data-export.csv, Header row\n"
    "warnings:\n"
    "  - Context does not specify the reporting period or organizational unit"
)

VALID_OUTPUT_SHORT_DESCRIPTION = (
    'suggested_description: "Revenue data extract"\n'
    "confidence: medium\n"
    "used_sources:\n"
    "  - revenue.xlsx, Sheet 1\n"
    "  - revenue.xlsx, Sheet 2\n"
    "warnings: []"
)

VALID_OUTPUT_SINGLE_SOURCE = (
    'suggested_description: "Quarterly enrollment statistics covering student demographics and program participation rates"\n'
    "confidence: medium\n"
    "used_sources:\n"
    "  - enrollment-q3.csv, Row 1\n"
    "warnings: []"
)

VALID_OUTPUT_WITH_UNCERTAINTY_LANGUAGE = (
    'suggested_description: "This record seems to be a weekly attendance summary for district schools"\n'
    "confidence: medium\n"
    "used_sources:\n"
    "  - attendance-weekly.pdf, Page 1\n"
    "  - attendance-weekly.pdf, Page 3\n"
    "warnings: []"
)

INVALID_MISSING_FIELD = (
    "confidence: high\n"
    "used_sources:\n"
    "  - report.pdf, Page 1\n"
    "warnings: []"
)

INVALID_BAD_CONFIDENCE = (
    'suggested_description: "Quarterly report detailing regional sales performance for fiscal year 2025"\n'
    "confidence: very_high\n"
    "used_sources:\n"
    "  - sales-q1.pdf, Page 3\n"
    "warnings: []"
)

INVALID_FORBIDDEN_PHRASE = (
    'suggested_description: "Based on my knowledge, this report covers annual financial data"\n'
    "confidence: high\n"
    "used_sources:\n"
    "  - finance.pdf, Page 1\n"
    "warnings: []"
)

INVALID_GENERIC_DESCRIPTION = (
    'suggested_description: "This asset contains data."\n'
    "confidence: high\n"
    "used_sources:\n"
    "  - generic.txt, Line 1\n"
    "warnings: []"
)

INVALID_NON_YAML = "This is just plain text, not YAML at all."

INVALID_EXTRA_FIELD = (
    'suggested_description: "Detailed inventory report for warehouse operations in Q4 2024"\n'
    "confidence: high\n"
    "used_sources:\n"
    "  - inventory.xlsx, Tab summary\n"
    "warnings: []\n"
    "extra_field: not allowed"
)

INVALID_FORBIDDEN_SOURCE = (
    'suggested_description: "Quarterly expense report with detailed cost breakdowns for operations"\n'
    "confidence: medium\n"
    "used_sources:\n"
    "  - general knowledge about expense reports\n"
    "warnings: []"
)


# ======================================================================
# Test 1: Valid output → PASS, output unchanged
# ======================================================================

class TestValidOutput:
    """Valid LLM output must pass validation with status PASS."""

    def test_valid_output_passes(self):
        result = validate_llm_output(VALID_OUTPUT)

        assert result.status == ValidationStatus.PASS
        assert result.blocking_errors == []
        assert result.raw_output == VALID_OUTPUT

    def test_valid_output_has_no_blocking_errors(self):
        result = validate_llm_output(VALID_OUTPUT)

        assert len(result.blocking_errors) == 0

    def test_valid_output_includes_all_rules_executed(self):
        result = validate_llm_output(VALID_OUTPUT)

        # Must include both blocking and advisory rule IDs
        assert any(r.startswith("V") for r in result.rules_executed)
        assert any(r.startswith("A") for r in result.rules_executed)

    def test_valid_output_preserves_raw_output(self):
        result = validate_llm_output(VALID_OUTPUT)

        assert result.raw_output == VALID_OUTPUT


# ======================================================================
# Test 2: Invalid output (blocking rule) → BLOCK
# ======================================================================

class TestBlockingRules:
    """Invalid LLM output must be rejected with status BLOCK."""

    def test_missing_required_field_blocks(self):
        result = validate_llm_output(INVALID_MISSING_FIELD)

        assert result.status == ValidationStatus.BLOCK
        assert len(result.blocking_errors) > 0
        assert any("suggested_description" in e.lower() or "Missing required field" in e
                    for e in result.blocking_errors)

    def test_invalid_confidence_blocks(self):
        result = validate_llm_output(INVALID_BAD_CONFIDENCE)

        assert result.status == ValidationStatus.BLOCK
        assert len(result.blocking_errors) > 0
        assert any("confidence" in e.lower() for e in result.blocking_errors)

    def test_forbidden_phrase_blocks(self):
        result = validate_llm_output(INVALID_FORBIDDEN_PHRASE)

        assert result.status == ValidationStatus.BLOCK
        assert len(result.blocking_errors) > 0

    def test_generic_description_blocks(self):
        result = validate_llm_output(INVALID_GENERIC_DESCRIPTION)

        assert result.status == ValidationStatus.BLOCK
        assert len(result.blocking_errors) > 0

    def test_non_yaml_blocks(self):
        result = validate_llm_output(INVALID_NON_YAML)

        assert result.status == ValidationStatus.BLOCK
        assert len(result.blocking_errors) > 0

    def test_extra_field_blocks(self):
        result = validate_llm_output(INVALID_EXTRA_FIELD)

        assert result.status == ValidationStatus.BLOCK
        assert any("extra_field" in e for e in result.blocking_errors)

    def test_forbidden_source_blocks(self):
        result = validate_llm_output(INVALID_FORBIDDEN_SOURCE)

        assert result.status == ValidationStatus.BLOCK
        assert len(result.blocking_errors) > 0

    def test_blocked_result_has_no_advisory_flags(self):
        """When output is blocked, advisory rules are NOT evaluated."""
        result = validate_llm_output(INVALID_MISSING_FIELD)

        assert result.status == ValidationStatus.BLOCK
        assert result.advisory_flags == []

    def test_blocking_error_clearly_identifies_rule(self):
        result = validate_llm_output(INVALID_MISSING_FIELD)

        assert result.status == ValidationStatus.BLOCK
        # Blocking errors must be non-empty strings
        for error in result.blocking_errors:
            assert isinstance(error, str)
            assert len(error) > 0


# ======================================================================
# Test 3: Output with advisory warnings → PASS, warnings returned
# ======================================================================

class TestAdvisoryWarnings:
    """Advisory flags must not block execution."""

    def test_low_confidence_triggers_advisory_flag(self):
        result = validate_llm_output(VALID_OUTPUT_LOW_CONFIDENCE)

        assert result.status == ValidationStatus.PASS
        flag_ids = [f.rule_id for f in result.advisory_flags]
        assert "A001" in flag_ids

    def test_short_description_triggers_advisory_flag(self):
        result = validate_llm_output(VALID_OUTPUT_SHORT_DESCRIPTION)

        assert result.status == ValidationStatus.PASS
        flag_ids = [f.rule_id for f in result.advisory_flags]
        assert "A002" in flag_ids

    def test_warnings_present_triggers_advisory_flag(self):
        result = validate_llm_output(VALID_OUTPUT_LOW_CONFIDENCE)

        assert result.status == ValidationStatus.PASS
        flag_ids = [f.rule_id for f in result.advisory_flags]
        assert "A003" in flag_ids

    def test_single_source_triggers_advisory_flag(self):
        result = validate_llm_output(VALID_OUTPUT_SINGLE_SOURCE)

        assert result.status == ValidationStatus.PASS
        flag_ids = [f.rule_id for f in result.advisory_flags]
        assert "A004" in flag_ids

    def test_uncertainty_language_triggers_advisory_flag(self):
        result = validate_llm_output(VALID_OUTPUT_WITH_UNCERTAINTY_LANGUAGE)

        assert result.status == ValidationStatus.PASS
        flag_ids = [f.rule_id for f in result.advisory_flags]
        assert "A005" in flag_ids

    def test_advisory_flags_do_not_block(self):
        """All advisory conditions must result in PASS, never BLOCK."""
        advisory_outputs = [
            VALID_OUTPUT_LOW_CONFIDENCE,
            VALID_OUTPUT_SHORT_DESCRIPTION,
            VALID_OUTPUT_SINGLE_SOURCE,
            VALID_OUTPUT_WITH_UNCERTAINTY_LANGUAGE,
        ]
        for output in advisory_outputs:
            result = validate_llm_output(output)
            assert result.status == ValidationStatus.PASS, (
                f"Advisory output was incorrectly BLOCKED: {result.blocking_errors}"
            )

    def test_advisory_flag_structure(self):
        result = validate_llm_output(VALID_OUTPUT_LOW_CONFIDENCE)

        for flag in result.advisory_flags:
            assert isinstance(flag, AdvisoryFlag)
            assert isinstance(flag.rule_id, str)
            assert isinstance(flag.rule_name, str)
            assert isinstance(flag.message, str)
            assert len(flag.rule_id) > 0
            assert len(flag.rule_name) > 0
            assert len(flag.message) > 0

    def test_valid_output_without_advisory_conditions(self):
        """Clean output with no advisory conditions should have zero flags."""
        result = validate_llm_output(VALID_OUTPUT)

        assert result.status == ValidationStatus.PASS
        assert len(result.advisory_flags) == 0


# ======================================================================
# Test 4: Determinism — same input → same result
# ======================================================================

class TestDeterminism:
    """Same input must always produce the same validation result."""

    def test_deterministic_pass(self):
        results = [validate_llm_output(VALID_OUTPUT) for _ in range(5)]

        for r in results:
            assert r.status == results[0].status
            assert r.blocking_errors == results[0].blocking_errors
            assert r.rules_executed == results[0].rules_executed
            assert len(r.advisory_flags) == len(results[0].advisory_flags)

    def test_deterministic_block(self):
        results = [validate_llm_output(INVALID_MISSING_FIELD) for _ in range(5)]

        for r in results:
            assert r.status == results[0].status
            assert r.blocking_errors == results[0].blocking_errors
            assert r.rules_executed == results[0].rules_executed

    def test_deterministic_advisory_flags(self):
        results = [validate_llm_output(VALID_OUTPUT_LOW_CONFIDENCE) for _ in range(5)]

        for r in results:
            flag_ids = [f.rule_id for f in r.advisory_flags]
            expected_ids = [f.rule_id for f in results[0].advisory_flags]
            assert flag_ids == expected_ids


# ======================================================================
# Test 5: Isolation — no Orchestrator, LLM, or Purview dependency
# ======================================================================

class TestIsolation:
    """Runtime validation must not import or call Orchestrator, LLM, or Purview."""

    def test_no_orchestrator_import(self):
        """The output_validator module must not import from src.orchestrator."""
        source = inspect.getsource(
            sys.modules["src.enrichment.output_validator"]
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                assert "orchestrator" not in module.lower(), (
                    f"Forbidden import from orchestrator: {module}"
                )

    def test_no_llm_client_import(self):
        """The output_validator module must not import from llm_client."""
        source = inspect.getsource(
            sys.modules["src.enrichment.output_validator"]
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                assert "llm_client" not in module.lower(), (
                    f"Forbidden import from llm_client: {module}"
                )

    def test_no_purview_client_import(self):
        """The output_validator module must not import from purview_client."""
        source = inspect.getsource(
            sys.modules["src.enrichment.output_validator"]
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                assert "purview" not in module.lower(), (
                    f"Forbidden import from purview_client: {module}"
                )

    def test_no_rag_import(self):
        """The output_validator module must not import from rag."""
        source = inspect.getsource(
            sys.modules["src.enrichment.output_validator"]
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                assert ".rag" not in module and "rag." not in module, (
                    f"Forbidden import from rag: {module}"
                )


# ======================================================================
# Test 6: correlationId propagation
# ======================================================================

class TestCorrelationId:
    """Validation must accept and propagate correlationId."""

    def test_correlation_id_accepted(self):
        """validate_llm_output must accept correlation_id without error."""
        result = validate_llm_output(VALID_OUTPUT, correlation_id="test-corr-001")

        assert result.status == ValidationStatus.PASS

    def test_correlation_id_none_accepted(self):
        """validate_llm_output must work without correlation_id."""
        result = validate_llm_output(VALID_OUTPUT, correlation_id=None)

        assert result.status == ValidationStatus.PASS

    def test_correlation_id_on_block(self):
        """validate_llm_output must accept correlation_id on block path."""
        result = validate_llm_output(
            INVALID_MISSING_FIELD, correlation_id="test-corr-002"
        )

        assert result.status == ValidationStatus.BLOCK


# ======================================================================
# Test 7: Result type integrity
# ======================================================================

class TestResultTypeIntegrity:
    """RuntimeValidationResult must have consistent, well-typed fields."""

    def test_pass_result_shape(self):
        result = validate_llm_output(VALID_OUTPUT)

        assert isinstance(result, RuntimeValidationResult)
        assert isinstance(result.status, ValidationStatus)
        assert isinstance(result.blocking_errors, list)
        assert isinstance(result.advisory_flags, list)
        assert isinstance(result.rules_executed, list)
        assert isinstance(result.raw_output, str)

    def test_block_result_shape(self):
        result = validate_llm_output(INVALID_MISSING_FIELD)

        assert isinstance(result, RuntimeValidationResult)
        assert isinstance(result.status, ValidationStatus)
        assert isinstance(result.blocking_errors, list)
        assert isinstance(result.advisory_flags, list)
        assert isinstance(result.rules_executed, list)
        assert isinstance(result.raw_output, str)

    def test_status_is_string_compatible(self):
        """ValidationStatus values must be usable as strings."""
        assert str(ValidationStatus.PASS) == "ValidationStatus.PASS"
        assert ValidationStatus.PASS.value == "PASS"
        assert ValidationStatus.BLOCK.value == "BLOCK"
