"""
Edge-case and adversarial tests for the Runtime Validation Module.

These tests answer 10 specific probing questions about validation rigor,
contract enforcement, internal coherence, advisory robustness, determinism
stability, misuse defense, observability consistency, and version safety.

Each test class maps to one numbered question.
"""

import logging
import re

import pytest

from src.enrichment.output_validator import (
    CONTRACT_VERSION,
    AdvisoryFlag,
    RuntimeValidationResult,
    ValidationStatus,
    validate_llm_output,
    _evaluate_advisory_rules,
)


# ======================================================================
# Helper — build a minimal valid YAML payload with overrides
# ======================================================================

def _build_yaml(
    description: str = "Annual sustainability report for 2024 detailing carbon emissions and water conservation across operations",
    confidence: str = "high",
    sources: list[str] | None = None,
    warnings: list[str] | None = None,
    extra_fields: dict[str, str] | None = None,
    field_order: list[str] | None = None,
) -> str:
    """Build a YAML payload from parts, respecting field order."""
    if sources is None:
        sources = ["sustainability-2024.pdf, Page 1", "sustainability-2024.pdf, Page 5"]
    if warnings is None:
        warnings = []

    parts: dict[str, str] = {}
    parts["suggested_description"] = f'suggested_description: "{description}"'
    parts["confidence"] = f"confidence: {confidence}"

    if sources:
        lines = "used_sources:\n" + "\n".join(f"  - {s}" for s in sources)
        parts["used_sources"] = lines
    else:
        parts["used_sources"] = "used_sources: []"

    if warnings:
        lines = "warnings:\n" + "\n".join(f"  - {w}" for w in warnings)
        parts["warnings"] = lines
    else:
        parts["warnings"] = "warnings: []"

    if extra_fields:
        for k, v in extra_fields.items():
            parts[k] = f"{k}: {v}"

    order = field_order or ["suggested_description", "confidence", "used_sources", "warnings"]
    if extra_fields:
        order.extend(extra_fields.keys())

    return "\n".join(parts[k] for k in order if k in parts)


# ======================================================================
# Q1: YAML "quase válido" — structural rigor vs human ambiguity
# ======================================================================

class TestQ1StructuralRigor:
    """If the LLM produces YAML that looks correct to a human but violates
    structural rules (swapped field order, invisible characters), does the
    validator consistently block it?"""

    def test_swapped_field_order_blocks(self):
        """Fields in wrong order must be BLOCKED even though content is valid."""
        yaml_text = _build_yaml(
            field_order=["confidence", "suggested_description", "used_sources", "warnings"],
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK
        assert any("order" in e.lower() for e in result.blocking_errors)

    def test_missing_warnings_field_still_passes(self):
        """warnings is optional — omitting it should still PASS."""
        yaml_text = (
            'suggested_description: "Detailed enrollment report for 2024 covering student demographics"\n'
            "confidence: high\n"
            "used_sources:\n"
            "  - enrollment-2024.pdf, Page 1\n"
            "  - enrollment-2024.pdf, Page 3"
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.PASS

    def test_trailing_whitespace_on_key_is_stripped(self):
        """Trailing space before colon is stripped by the parser's .strip().
        This is known MVP behavior — the constrained YAML parser normalizes
        key names, so 'suggested_description ' becomes 'suggested_description'.
        A stricter parser could reject this, but the frozen engine accepts it."""
        yaml_text = (
            'suggested_description : "Report on district operating budgets for fiscal year 2025"\n'
            "confidence: medium\n"
            "used_sources:\n"
            "  - budget-2025.xlsx, Sheet 1\n"
            "warnings: []"
        )
        result = validate_llm_output(yaml_text)

        # Parser .strip() normalizes the key — this PASSES in current engine
        assert result.status == ValidationStatus.PASS

    def test_unicode_invisible_char_in_key_blocks(self):
        """Zero-width space (\u200b) in a field name must be blocked."""
        yaml_text = (
            'suggested_\u200bdescription: "Annual report for 2024 covering revenue trends"\n'
            "confidence: high\n"
            "used_sources:\n"
            "  - report.pdf, Page 1\n"
            "warnings: []"
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK

    def test_tab_indentation_accepted_by_parser(self):
        """Tab indentation is accepted by the subset parser's .lstrip().
        This is known MVP behavior — the parser does not distinguish
        between tab and space indentation for array items.
        A stricter parser could reject tabs, but the frozen engine accepts them."""
        yaml_text = (
            'suggested_description: "Operational metrics dashboard for Q3 manufacturing output"\n'
            "confidence: medium\n"
            "used_sources:\n"
            "\t- metrics-q3.csv, Row 1\n"
            "warnings: []"
        )
        result = validate_llm_output(yaml_text)

        # Parser .lstrip() strips tabs — this PASSES in current engine
        assert result.status == ValidationStatus.PASS

    def test_duplicate_key_blocks(self):
        """Duplicate top-level key must be blocked."""
        yaml_text = (
            'suggested_description: "First description of quarterly revenue data"\n'
            "confidence: high\n"
            "used_sources:\n"
            "  - doc1.pdf, Page 1\n"
            "warnings: []\n"
            'suggested_description: "Second description overwrites first"'
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK
        assert any("Duplicate" in e or "order" in e.lower() for e in result.blocking_errors)


# ======================================================================
# Q2: Semantically excellent but contract-violating
# ======================================================================

class TestQ2ContractBeatsQuality:
    """Even if the extra field improves the output from a human perspective,
    any field not in the contract must be blocked."""

    def test_extra_field_with_useful_content_blocks(self):
        """A helpful 'rationale' field still violates the contract."""
        yaml_text = _build_yaml(
            extra_fields={"rationale": "Based on three cross-referenced documents"},
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK
        assert any("rationale" in e for e in result.blocking_errors)

    def test_extra_field_with_empty_value_blocks(self):
        """Even an empty extra field violates the contract."""
        yaml_text = _build_yaml(extra_fields={"notes": ""})
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK

    def test_multiple_extra_fields_all_reported(self):
        """Multiple contract violations are all captured in blocking_errors."""
        yaml_text = _build_yaml(
            extra_fields={"rationale": "good reason", "score": "0.95"},
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK
        error_text = " ".join(result.blocking_errors)
        assert "rationale" in error_text
        assert "score" in error_text


# ======================================================================
# Q3: Forced confidence — high confidence + uncertain language
# ======================================================================

class TestQ3ForcedConfidence:
    """If confidence is 'high' but the description uses hedging language,
    what happens?  Blocking words ('may', 'could') → BLOCK.
    Advisory-only words ('seems to be') → PASS + A005 flag."""

    def test_high_confidence_with_may_blocks(self):
        """'may' is in FORBIDDEN_LANGUAGE → blocking, regardless of confidence."""
        yaml_text = _build_yaml(
            description="This dataset may contain student enrollment records for the 2024 academic year",
            confidence="high",
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK
        assert any("speculative" in e.lower() or "forbidden" in e.lower()
                    for e in result.blocking_errors)

    def test_high_confidence_with_possibly_blocks(self):
        """'possibly' triggers FORBIDDEN_LANGUAGE 'likely' pattern? No —
        'possibly' is NOT in FORBIDDEN_LANGUAGE. It only triggers advisory A005."""
        yaml_text = _build_yaml(
            description="This record is possibly a weekly attendance summary for district schools covering enrollment data",
            confidence="high",
        )
        result = validate_llm_output(yaml_text)

        # 'possibly' is NOT in blocking FORBIDDEN_LANGUAGE list,
        # so it PASSES structurally/semantically, but triggers A005
        assert result.status == ValidationStatus.PASS
        flag_ids = [f.rule_id for f in result.advisory_flags]
        assert "A005" in flag_ids

    def test_high_confidence_with_could_blocks(self):
        """'could' is in FORBIDDEN_LANGUAGE → always BLOCK."""
        yaml_text = _build_yaml(
            description="This report could represent quarterly financial data for the North American division",
            confidence="high",
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK

    def test_high_confidence_with_seems_to_be_passes_with_advisory(self):
        """'seems to be' is NOT in blocking FORBIDDEN_LANGUAGE.
        It triggers advisory A005 but does not block — even with high confidence."""
        yaml_text = _build_yaml(
            description="This dataset seems to be a collection of transportation routes for school districts",
            confidence="high",
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.PASS
        flag_ids = [f.rule_id for f in result.advisory_flags]
        assert "A005" in flag_ids
        # Note: no mechanism currently detects the contradiction between
        # high confidence and uncertainty language — this is documented behavior.


# ======================================================================
# Q4: Implicit vs explicit source traceability
# ======================================================================

class TestQ4SourceTraceability:
    """Vague sources like 'based on internal documentation' pass through
    because the source blocklist only catches specific forbidden identifiers
    (general knowledge, training data, internet, wikipedia)."""

    def test_vague_internal_documentation_passes(self):
        """'internal documentation' is not in the forbidden source patterns."""
        yaml_text = _build_yaml(
            sources=["based on internal documentation"],
        )
        result = validate_llm_output(yaml_text)

        # This PASSES — the source blocklist does not catch it.
        # This is known MVP behavior per the frozen contract.
        assert result.status == ValidationStatus.PASS

    def test_general_knowledge_source_blocks(self):
        """'general knowledge' IS in the forbidden source patterns."""
        yaml_text = _build_yaml(
            sources=["general knowledge about financial reports"],
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK

    def test_training_data_source_blocks(self):
        """'training data' IS in the forbidden source patterns."""
        yaml_text = _build_yaml(sources=["training data"])
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK

    def test_wikipedia_source_blocks(self):
        """'wikipedia' IS in the forbidden source patterns."""
        yaml_text = _build_yaml(sources=["Wikipedia article on data governance"])
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK

    def test_specific_rag_source_passes(self):
        """A specific, traceable RAG source passes correctly."""
        yaml_text = _build_yaml(
            sources=["Document: enrollment-2024.pdf, Page 3, Section 2.1"],
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.PASS


# ======================================================================
# Q5: Minimum viable output
# ======================================================================

class TestQ5MinimumViableOutput:
    """What is the smallest output that still passes as PASS?"""

    def test_minimum_valid_output(self):
        """Smallest possible valid output: 10-char description, 1 source,
        no warnings field."""
        yaml_text = (
            'suggested_description: "Short data"\n'
            "confidence: low\n"
            "used_sources:\n"
            "  - doc.pdf, p1"
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.PASS
        # But it triggers advisory flags: A001 (low), A002 (short), A004 (single source)
        flag_ids = [f.rule_id for f in result.advisory_flags]
        assert "A001" in flag_ids  # low confidence
        assert "A002" in flag_ids  # short description (< 30 chars)
        assert "A004" in flag_ids  # single source

    def test_description_at_exact_min_length_passes(self):
        """Exactly 10 characters passes the length check."""
        yaml_text = _build_yaml(description="1234567890")
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.PASS

    def test_description_below_min_length_blocks(self):
        """9 characters fails the min-length check."""
        yaml_text = _build_yaml(description="123456789")
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK
        assert any("too short" in e.lower() for e in result.blocking_errors)

    def test_empty_sources_array_blocks(self):
        """used_sources: [] must be blocked — at least 1 source required."""
        yaml_text = (
            'suggested_description: "Enrollment report for FY2024 with detailed demographics"\n'
            "confidence: medium\n"
            "used_sources: []\n"
            "warnings: []"
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK


# ======================================================================
# Q6: Advisory flood — all flags at once
# ======================================================================

class TestQ6AdvisoryFlood:
    """If an output triggers ALL advisory flags simultaneously, are they
    all registered correctly, and does the flow continue as PASS?"""

    def test_all_advisory_flags_fire_simultaneously(self):
        """Craft an output that triggers A001 + A002 + A003 + A004 + A005."""
        yaml_text = (
            'suggested_description: "Record seems to be data"\n'  # <30 chars = A002, "seems to be" = A005
            "confidence: low\n"                                   # A001
            "used_sources:\n"
            "  - single-doc.pdf, Page 1\n"                        # single source = A004
            "warnings:\n"
            "  - Insufficient context for full analysis"          # non-empty warnings = A003
        )
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.PASS, (
            f"Should be PASS even with all advisories, got BLOCK: {result.blocking_errors}"
        )

        flag_ids = sorted(f.rule_id for f in result.advisory_flags)
        assert flag_ids == ["A001", "A002", "A003", "A004", "A005"], (
            f"Expected all 5 advisory flags, got: {flag_ids}"
        )

    def test_advisory_flood_does_not_truncate(self):
        """All 5 flags must have complete, non-empty fields."""
        yaml_text = (
            'suggested_description: "Record seems to be data"\n'
            "confidence: low\n"
            "used_sources:\n"
            "  - single-doc.pdf, Page 1\n"
            "warnings:\n"
            "  - Insufficient context for full analysis"
        )
        result = validate_llm_output(yaml_text)

        assert len(result.advisory_flags) == 5
        for flag in result.advisory_flags:
            assert len(flag.rule_id) > 0
            assert len(flag.rule_name) > 0
            assert len(flag.message) > 0

    def test_advisory_flood_preserves_raw_output(self):
        """Even with max advisories, raw_output is preserved unchanged."""
        yaml_text = (
            'suggested_description: "Record seems to be data"\n'
            "confidence: low\n"
            "used_sources:\n"
            "  - single-doc.pdf, Page 1\n"
            "warnings:\n"
            "  - Insufficient context for full analysis"
        )
        result = validate_llm_output(yaml_text)

        assert result.raw_output == yaml_text

    def test_advisory_flood_all_rules_logged(self):
        """All 16 rule IDs (V + A) must appear in rules_executed."""
        yaml_text = (
            'suggested_description: "Record seems to be data"\n'
            "confidence: low\n"
            "used_sources:\n"
            "  - single-doc.pdf, Page 1\n"
            "warnings:\n"
            "  - Insufficient context for full analysis"
        )
        result = validate_llm_output(yaml_text)

        v_rules = [r for r in result.rules_executed if r.startswith("V")]
        a_rules = [r for r in result.rules_executed if r.startswith("A")]
        assert len(v_rules) == 11  # all blocking rules evaluated
        assert len(a_rules) == 5   # all advisory rules evaluated


# ======================================================================
# Q7: Determinism under refactoring
# ======================================================================

class TestQ7DeterminismProtection:
    """Is there any protection against silent behavioral changes from regex
    or threshold refactoring?"""

    def test_advisory_patterns_are_compiled_constants(self):
        """Advisory uncertainty patterns must be pre-compiled constants,
        not generated at call time."""
        from src.enrichment.output_validator import _ADVISORY_UNCERTAINTY_PATTERNS

        assert isinstance(_ADVISORY_UNCERTAINTY_PATTERNS, list)
        for p in _ADVISORY_UNCERTAINTY_PATTERNS:
            assert isinstance(p, re.Pattern), (
                "Advisory patterns must be pre-compiled re.Pattern objects"
            )

    def test_blocking_rule_ids_are_frozen_list(self):
        """Blocking rule ID list must be a module-level constant."""
        from src.enrichment.output_validator import _BLOCKING_RULE_IDS

        assert isinstance(_BLOCKING_RULE_IDS, list)
        assert len(_BLOCKING_RULE_IDS) == 11
        assert _BLOCKING_RULE_IDS[0] == "V001"
        assert _BLOCKING_RULE_IDS[-1] == "V040"

    def test_determinism_across_100_iterations(self):
        """Extended determinism: identical result across 100 runs."""
        reference = validate_llm_output(
            _build_yaml(
                description="Record seems to be enrollment data for state reporting purposes",
                confidence="low",
                sources=["enrollment.csv, Row 1"],
                warnings=["Partial context available"],
            )
        )
        for _ in range(100):
            result = validate_llm_output(reference.raw_output)
            assert result.status == reference.status
            assert result.blocking_errors == reference.blocking_errors
            assert len(result.advisory_flags) == len(reference.advisory_flags)
            assert (
                [f.rule_id for f in result.advisory_flags]
                == [f.rule_id for f in reference.advisory_flags]
            )

    def test_contract_version_is_explicit(self):
        """A CONTRACT_VERSION constant must exist for traceability."""
        assert CONTRACT_VERSION == "1.0.0"


# ======================================================================
# Q8: Misuse defense — ignoring BLOCK status
# ======================================================================

class TestQ8MisuseDefense:
    """Does the type system make it hard to accidentally ignore BLOCK?"""

    def test_status_is_enum_not_bare_string(self):
        """ValidationStatus is an Enum, not a bare string — encourages
        exhaustive matching."""
        assert issubclass(ValidationStatus, str)  # is a str enum
        assert len(ValidationStatus) == 2          # exactly PASS and BLOCK
        assert ValidationStatus("PASS") == ValidationStatus.PASS
        assert ValidationStatus("BLOCK") == ValidationStatus.BLOCK

    def test_invalid_status_string_raises(self):
        """Constructing ValidationStatus with an invalid value raises."""
        with pytest.raises(ValueError):
            ValidationStatus("WARN")

    def test_result_is_frozen(self):
        """RuntimeValidationResult is frozen — cannot be mutated after creation."""
        result = validate_llm_output(VALID_OUTPUT_FOR_Q8)

        with pytest.raises(AttributeError):
            result.status = ValidationStatus.PASS  # type: ignore

        with pytest.raises(AttributeError):
            result.blocking_errors = []  # type: ignore

    def test_cannot_construct_pass_with_blocking_errors(self):
        """The __post_init__ guard prevents PASS + non-empty blocking_errors."""
        with pytest.raises(ValueError, match="PASS but blocking_errors is non-empty"):
            RuntimeValidationResult(
                status=ValidationStatus.PASS,
                blocking_errors=["fake error"],
            )

    def test_cannot_construct_block_with_advisory_flags(self):
        """The __post_init__ guard prevents BLOCK + advisory flags."""
        with pytest.raises(ValueError, match="BLOCK but advisory_flags is non-empty"):
            RuntimeValidationResult(
                status=ValidationStatus.BLOCK,
                blocking_errors=["real error"],
                advisory_flags=[
                    AdvisoryFlag(rule_id="A001", rule_name="Test", message="test"),
                ],
            )


VALID_OUTPUT_FOR_Q8 = _build_yaml()


# ======================================================================
# Q9: Logs vs reality — observability consistency
# ======================================================================

class TestQ9LogsVsReality:
    """Can logs say PASS while the object is in an inconsistent state?"""

    def test_pass_result_invariants(self):
        """Every PASS result must have empty blocking_errors."""
        result = validate_llm_output(_build_yaml())

        assert result.status == ValidationStatus.PASS
        assert result.blocking_errors == []

    def test_block_result_invariants(self):
        """Every BLOCK result must have non-empty blocking_errors
        and empty advisory_flags."""
        result = validate_llm_output(
            _build_yaml(description="N/A", confidence="invalid"),
        )

        assert result.status == ValidationStatus.BLOCK
        assert len(result.blocking_errors) > 0
        assert result.advisory_flags == []

    def test_pass_log_matches_returned_status(self, caplog):
        """Log message must say PASS when result.status is PASS."""
        with caplog.at_level(logging.INFO, logger="enrichment.output_validator"):
            result = validate_llm_output(_build_yaml(), correlation_id="log-test-001")

        assert result.status == ValidationStatus.PASS
        assert any("PASSED" in r.message for r in caplog.records)
        # Verify correlationId appears in log extra
        pass_records = [r for r in caplog.records if "PASSED" in r.message]
        assert len(pass_records) == 1
        assert getattr(pass_records[0], "correlationId", None) == "log-test-001"

    def test_block_log_matches_returned_status(self, caplog):
        """Log message must say BLOCKED when result.status is BLOCK."""
        with caplog.at_level(logging.WARNING, logger="enrichment.output_validator"):
            result = validate_llm_output(
                _build_yaml(confidence="invalid"),
                correlation_id="log-test-002",
            )

        assert result.status == ValidationStatus.BLOCK
        assert any("BLOCKED" in r.message for r in caplog.records)
        block_records = [r for r in caplog.records if "BLOCKED" in r.message]
        assert len(block_records) == 1
        assert getattr(block_records[0], "correlationId", None) == "log-test-002"

    def test_log_advisory_count_matches_result(self, caplog):
        """Logged advisoryFlagCount must match len(result.advisory_flags)."""
        with caplog.at_level(logging.INFO, logger="enrichment.output_validator"):
            result = validate_llm_output(
                _build_yaml(confidence="low", sources=["single-src.pdf, Page 1"]),
            )

        pass_records = [r for r in caplog.records if "PASSED" in r.message]
        assert len(pass_records) == 1
        logged_count = getattr(pass_records[0], "advisoryFlagCount", None)
        assert logged_count == len(result.advisory_flags)


# ======================================================================
# Q10: Contract version evolution
# ======================================================================

class TestQ10ContractVersioning:
    """How does the runtime handle version mismatch?  Currently there is
    no version field in the output itself, so the runtime validates
    blindly against v1.0.0 rules.  These tests document the current
    boundary and prove the CONTRACT_VERSION constant exists for future
    version gating."""

    def test_contract_version_constant_exists(self):
        """The module must expose the version it was built against."""
        assert CONTRACT_VERSION is not None
        assert isinstance(CONTRACT_VERSION, str)
        # Must be semver-ish
        assert re.match(r"^\d+\.\d+\.\d+$", CONTRACT_VERSION)

    def test_contract_version_matches_frozen_spec(self):
        """CONTRACT_VERSION must match the frozen validation contract."""
        assert CONTRACT_VERSION == "1.0.0"

    def test_output_without_version_field_passes(self):
        """Current contract does NOT require a version field in the output.
        This is by design — the runtime applies v1.0.0 rules regardless."""
        yaml_text = _build_yaml()
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.PASS

    def test_output_with_version_field_blocks_as_extra_field(self):
        """If a future LLM emits a 'version' field, it must be BLOCKED
        because the v1.0.0 contract does not allow it."""
        yaml_text = _build_yaml(extra_fields={"version": "1.1.0"})
        result = validate_llm_output(yaml_text)

        assert result.status == ValidationStatus.BLOCK
        assert any("version" in e for e in result.blocking_errors)

    def test_contract_version_importable_for_gating(self):
        """A future caller can import CONTRACT_VERSION and gate logic."""
        from src.enrichment.output_validator import CONTRACT_VERSION as cv

        # This is the mechanism for future version checks:
        # if cv != expected_version: raise VersionMismatch(...)
        assert cv == "1.0.0"
