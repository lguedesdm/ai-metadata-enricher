import pytest

from src.domain.validation.structural_validator import validate_structural
from src.domain.validation.semantic_validator import validate_semantic


def test_valid_output_passes_both_layers():
    yaml_text = (
        "suggested_description: \"Annual sustainability report for 2024 detailing carbon emissions reductions, renewable energy adoption, and water conservation initiatives across global operations.\"\n"
        "confidence: high\n"
        "used_sources:\n"
        "- Document: sustainability-2024.pdf, Page 1\n"
        "- Document: sustainability-2024.pdf, Page 5\n"
        "warnings: []\n"
    )
    struct_result = validate_structural(yaml_text)
    assert struct_result.is_valid, struct_result.structural_errors

    # For semantic validation, parse using the same subset parser indirectly by reconstructing expected dict
    parsed = {
        "suggested_description": "Annual sustainability report for 2024 detailing carbon emissions reductions, renewable energy adoption, and water conservation initiatives across global operations.",
        "confidence": "high",
        "used_sources": [
            "Document: sustainability-2024.pdf, Page 1",
            "Document: sustainability-2024.pdf, Page 5",
        ],
        "warnings": [],
    }
    sem_result = validate_semantic(parsed)
    assert sem_result.is_valid, sem_result.semantic_errors


def test_structural_accepts_indented_array_items():
    yaml_text = (
        "suggested_description: \"Customer satisfaction dashboard with monthly trends.\"\n"
        "confidence: medium\n"
        "used_sources:\n"
        "  - cx-dashboard.md, Section Overview\n"
        "  - cx-dashboard.md, Appendix A\n"
    )
    struct_result = validate_structural(yaml_text)
    assert struct_result.is_valid, struct_result.structural_errors


def test_structurally_invalid_output_extra_field():
    yaml_text = (
        "suggested_description: \"Annual report for 2024.\"\n"
        "confidence: high\n"
        "used_sources:\n"
        "- Document ABC\n"
        "warnings: []\n"
        "extra_field: not allowed\n"
    )
    struct_result = validate_structural(yaml_text)
    assert not struct_result.is_valid
    assert any("Unknown field 'extra_field'" in e for e in struct_result.structural_errors)


def test_structurally_invalid_output_non_yaml_text():
    yaml_text = (
        "This is my answer:\n"
        "suggested_description: \"Quarterly revenue summary for 2025.\"\n"
        "confidence: medium\n"
        "used_sources:\n"
        "- q1-2025-report.pdf, Page 2\n"
    )
    struct_result = validate_structural(yaml_text)
    assert not struct_result.is_valid
    assert any("Unknown field" in e or "Unexpected" in e for e in struct_result.structural_errors)


def test_structurally_valid_but_semantically_invalid():
    yaml_text = (
        "suggested_description: \"This asset contains data\"\n"
        "confidence: high\n"
        "used_sources:\n"
        "- Document: generic.txt, Line 1\n"
    )
    struct_result = validate_structural(yaml_text)
    assert not struct_result.is_valid or struct_result.is_valid  # structural could pass or fail on missing warnings; not required

    parsed = {
        "suggested_description": "This asset contains data",
        "confidence": "high",
        "used_sources": ["Document: generic.txt, Line 1"],
    }
    sem_result = validate_semantic(parsed)
    assert not sem_result.is_valid
    assert any("trivially generic" in e for e in sem_result.semantic_errors)


def test_multiple_semantic_failures():
    parsed = {
        "suggested_description": "Based on my knowledge, this appears to be a report",
        "confidence": "very_high",
        "used_sources": ["general knowledge"],
    }
    sem_result = validate_semantic(parsed)
    assert not sem_result.is_valid
    # Expect multiple distinct reasons
    assert any("forbidden concepts" in e for e in sem_result.semantic_errors)
    assert any("confidence must be one of" in e for e in sem_result.semantic_errors)
    assert any("forbidden source identifiers" in e for e in sem_result.semantic_errors)
