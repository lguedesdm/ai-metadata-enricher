"""
Unit tests for the element_identity module.

Covers:
    - Base64 encoding of element_name → document ID
    - ID matches Azure AI Search indexer base64Encode behaviour
    - Stability / determinism (same input → same ID)
    - Description change does NOT change ID
    - sourceSystem and elementType do NOT affect ID
    - Invalid element_name → ValueError
    - Azure AI Search key length limit (1024 characters)
    - sourceSystem normalisation
"""

from __future__ import annotations

import base64

import pytest

from src.domain.element_splitter import ContextElement, generate_element_id
from src.domain.element_splitter.element_identity import normalise_source_system


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _element(**overrides: object) -> ContextElement:
    """Create a ContextElement with sensible defaults and optional overrides."""
    defaults = {
        "source_system": "synergy",
        "element_type": "table",
        "element_name": "Student Enrollment",
        "description": "Some description",
        "raw_payload": {},
    }
    defaults.update(overrides)
    return ContextElement(**defaults)  # type: ignore[arg-type]


def _expected_b64(value: str) -> str:
    """Return the expected base64-encoded ID for a given element_name."""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------
# Basic ID construction — base64 encoding
# ---------------------------------------------------------------------------

class TestGenerateElementIdBasic:
    """ID must be base64Encode(element_name)."""

    def test_simple_id(self):
        el = _element()
        assert generate_element_id(el) == _expected_b64("Student Enrollment")

    def test_zipline_element(self):
        el = _element(
            source_system="zipline",
            element_type="element",
            element_name="Assessment Definition",
        )
        assert generate_element_id(el) == _expected_b64("Assessment Definition")

    def test_column_type(self):
        el = _element(element_type="column", element_name="Ethnicity")
        assert generate_element_id(el) == _expected_b64("Ethnicity")

    def test_dotted_name(self):
        el = _element(element_name="Students.StudentId")
        assert generate_element_id(el) == _expected_b64("Students.StudentId")


# ---------------------------------------------------------------------------
# ID is independent of source_system and element_type
# ---------------------------------------------------------------------------

class TestIdIndependentOfOtherFields:
    """ID depends ONLY on element_name — not source_system or element_type."""

    def test_different_source_system_same_name(self):
        el1 = _element(source_system="synergy", element_name="Students")
        el2 = _element(source_system="zipline", element_name="Students")
        assert generate_element_id(el1) == generate_element_id(el2)

    def test_different_element_type_same_name(self):
        el1 = _element(element_type="table", element_name="Students")
        el2 = _element(element_type="column", element_name="Students")
        assert generate_element_id(el1) == generate_element_id(el2)

    def test_different_element_name_different_id(self):
        el1 = _element(element_name="Students")
        el2 = _element(element_name="Teachers")
        assert generate_element_id(el1) != generate_element_id(el2)


# ---------------------------------------------------------------------------
# Case sensitivity — base64 preserves case
# ---------------------------------------------------------------------------

class TestGenerateElementIdCaseSensitivity:
    """Base64 encoding is case-sensitive on the input."""

    def test_uppercase_different_from_lowercase(self):
        el1 = _element(element_name="students")
        el2 = _element(element_name="Students")
        assert generate_element_id(el1) != generate_element_id(el2)

    def test_exact_case_preserved(self):
        el = _element(element_name="Students.EnrollmentDate")
        assert generate_element_id(el) == _expected_b64("Students.EnrollmentDate")


# ---------------------------------------------------------------------------
# Stability / determinism
# ---------------------------------------------------------------------------

class TestGenerateElementIdStability:
    """Same logical input must always produce the same ID."""

    def test_same_input_same_output(self):
        el = _element()
        id1 = generate_element_id(el)
        id2 = generate_element_id(el)
        assert id1 == id2

    def test_thousand_calls_stable(self):
        el = _element()
        ids = {generate_element_id(el) for _ in range(1_000)}
        assert len(ids) == 1


# ---------------------------------------------------------------------------
# Description change does NOT change ID
# ---------------------------------------------------------------------------

class TestGenerateElementIdDescriptionIndependence:
    """ID must depend only on element_name."""

    def test_different_description_same_id(self):
        el1 = _element(description="Original description")
        el2 = _element(description="Completely different description")
        assert generate_element_id(el1) == generate_element_id(el2)

    def test_empty_description_same_id(self):
        el1 = _element(description="Has description")
        el2 = _element(description="")
        assert generate_element_id(el1) == generate_element_id(el2)

    def test_different_raw_payload_same_id(self):
        el1 = _element(raw_payload={"extra": "data"})
        el2 = _element(raw_payload={})
        assert generate_element_id(el1) == generate_element_id(el2)


# ---------------------------------------------------------------------------
# Validation — empty element_name → ValueError
# ---------------------------------------------------------------------------

class TestGenerateElementIdValidation:
    """Empty element_name after normalisation must raise ValueError."""

    def test_empty_element_name_raises(self):
        el = _element(element_name="")
        with pytest.raises(ValueError, match="element_name"):
            generate_element_id(el)

    def test_whitespace_only_element_name_raises(self):
        el = _element(element_name="   ")
        with pytest.raises(ValueError, match="element_name"):
            generate_element_id(el)

    def test_error_includes_original_value(self):
        el = _element(element_name="   ")
        with pytest.raises(ValueError, match=r"original value"):
            generate_element_id(el)


# ---------------------------------------------------------------------------
# Azure AI Search key length limit (1024 characters)
# ---------------------------------------------------------------------------

class TestGenerateElementIdKeyLength:
    """Final ID must not exceed 1024 characters."""

    def test_short_id_is_fine(self):
        el = _element()
        result = generate_element_id(el)
        assert len(result) < 1024

    def test_extremely_long_name_raises(self):
        name = "x" * 5000
        el = _element(element_name=name)
        with pytest.raises(ValueError, match=r"exceeds Azure AI Search limit"):
            generate_element_id(el)


# ---------------------------------------------------------------------------
# Base64 encoding matches Azure AI Search base64Encode
# ---------------------------------------------------------------------------

class TestBase64Compatibility:
    """Generated IDs must use standard base64 (RFC 4648)."""

    def test_standard_base64_with_padding(self):
        el = _element(element_name="A")
        result = generate_element_id(el)
        assert result == "QQ=="

    def test_no_padding_when_divisible(self):
        el = _element(element_name="ABC")
        result = generate_element_id(el)
        assert result == "QUJD"

    def test_plus_and_slash_characters(self):
        """Standard base64 uses + and / (not URL-safe - and _)."""
        # A name that produces + or / in base64
        el = _element(element_name=">>>")
        result = generate_element_id(el)
        # Just verify it decodes back correctly
        decoded = base64.b64decode(result).decode("utf-8")
        assert decoded == ">>>"

    def test_round_trip_fidelity(self):
        names = [
            "Students.StudentId",
            "Students.EnrollmentDate",
            "Student Enrollment Registration",
            "Assessment Definition",
        ]
        for name in names:
            el = _element(element_name=name)
            result = generate_element_id(el)
            decoded = base64.b64decode(result).decode("utf-8")
            assert decoded == name


# ---------------------------------------------------------------------------
# sourceSystem normalisation
# ---------------------------------------------------------------------------

class TestNormaliseSourceSystem:
    """normalise_source_system must lowercase and validate."""

    def test_lowercase_passthrough(self):
        assert normalise_source_system("synergy") == "synergy"
        assert normalise_source_system("zipline") == "zipline"
        assert normalise_source_system("documentation") == "documentation"

    def test_uppercase_normalised(self):
        assert normalise_source_system("Synergy") == "synergy"
        assert normalise_source_system("ZIPLINE") == "zipline"

    def test_whitespace_stripped(self):
        assert normalise_source_system("  synergy  ") == "synergy"

    def test_unknown_value_raises(self):
        with pytest.raises(ValueError, match="not in the allowed set"):
            normalise_source_system("unknown_system")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="not in the allowed set"):
            normalise_source_system("")
