"""
Unit tests for the element_identity module.

Covers:
    - Case normalisation (uppercase, mixed-case → lowercase)
    - Whitespace trimming (leading, trailing)
    - Internal whitespace collapse (multiple spaces, tabs, newlines)
    - Stability / determinism (same input → same ID)
    - Description change does NOT change ID
    - Invalid fields after normalisation → ValueError
    - Error message includes original raw value
    - ID format is "{source}::{type}::{name}"
"""

from __future__ import annotations

import pytest

from src.domain.element_splitter import ContextElement, generate_element_id


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


# ---------------------------------------------------------------------------
# Basic ID construction
# ---------------------------------------------------------------------------

class TestGenerateElementIdBasic:
    """ID must follow the format source::type::name, all lowercase."""

    def test_simple_id(self):
        el = _element()
        assert generate_element_id(el) == "synergy::table::student enrollment"

    def test_zipline_element(self):
        el = _element(
            source_system="zipline",
            element_type="element",
            element_name="Assessment Definition",
        )
        assert generate_element_id(el) == "zipline::element::assessment definition"

    def test_column_type(self):
        el = _element(element_type="column", element_name="Ethnicity")
        assert generate_element_id(el) == "synergy::column::ethnicity"


# ---------------------------------------------------------------------------
# Case normalisation
# ---------------------------------------------------------------------------

class TestGenerateElementIdCaseNormalisation:
    """All segments must be lowercased."""

    def test_uppercase_source_system(self):
        el = _element(source_system="SYNERGY")
        assert generate_element_id(el) == "synergy::table::student enrollment"

    def test_mixed_case_all_fields(self):
        el = _element(
            source_system="Synergy",
            element_type="Table",
            element_name="Student Enrollment",
        )
        assert generate_element_id(el) == "synergy::table::student enrollment"

    def test_all_uppercase(self):
        el = _element(
            source_system="ZIPLINE",
            element_type="DATASET",
            element_name="DAILY ATTENDANCE",
        )
        assert generate_element_id(el) == "zipline::dataset::daily attendance"


# ---------------------------------------------------------------------------
# Whitespace trimming
# ---------------------------------------------------------------------------

class TestGenerateElementIdWhitespaceTrimming:
    """Leading and trailing whitespace must be stripped."""

    def test_leading_trailing_spaces(self):
        el = _element(
            source_system="  synergy  ",
            element_type="  table  ",
            element_name="  Students  ",
        )
        assert generate_element_id(el) == "synergy::table::students"

    def test_tabs_and_newlines_stripped(self):
        el = _element(
            source_system="\tsynergy\n",
            element_type="\ntable\t",
            element_name="\n Students \t",
        )
        assert generate_element_id(el) == "synergy::table::students"


# ---------------------------------------------------------------------------
# Internal whitespace collapse
# ---------------------------------------------------------------------------

class TestGenerateElementIdWhitespaceCollapse:
    """Multiple internal whitespace chars must collapse to single space."""

    def test_double_space(self):
        el = _element(element_name="Student  Enrollment")
        assert generate_element_id(el) == "synergy::table::student enrollment"

    def test_many_spaces(self):
        el = _element(element_name="Student     Enrollment")
        assert generate_element_id(el) == "synergy::table::student enrollment"

    def test_tabs_between_words(self):
        el = _element(element_name="Student\t\tEnrollment")
        assert generate_element_id(el) == "synergy::table::student enrollment"

    def test_mixed_whitespace_between_words(self):
        el = _element(element_name="Student \t \n Enrollment")
        assert generate_element_id(el) == "synergy::table::student enrollment"

    def test_full_example_from_spec(self):
        """Exact example from the task specification."""
        el = _element(
            source_system=" Synergy ",
            element_type=" Table ",
            element_name="   Students   ",
        )
        assert generate_element_id(el) == "synergy::table::students"


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

    def test_equivalent_inputs_same_output(self):
        """Different whitespace / casing, same logical identity."""
        el1 = _element(
            source_system="synergy",
            element_type="table",
            element_name="Students",
        )
        el2 = _element(
            source_system="  SYNERGY  ",
            element_type="TABLE",
            element_name="  students  ",
        )
        assert generate_element_id(el1) == generate_element_id(el2)

    def test_thousand_calls_stable(self):
        el = _element()
        ids = {generate_element_id(el) for _ in range(1_000)}
        assert len(ids) == 1


# ---------------------------------------------------------------------------
# Description change does NOT change ID
# ---------------------------------------------------------------------------

class TestGenerateElementIdDescriptionIndependence:
    """ID must depend only on source_system, element_type, element_name."""

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
# Different identity fields produce different IDs
# ---------------------------------------------------------------------------

class TestGenerateElementIdUniqueness:
    """Different identity fields must produce different IDs."""

    def test_different_source_system(self):
        el1 = _element(source_system="synergy")
        el2 = _element(source_system="zipline")
        assert generate_element_id(el1) != generate_element_id(el2)

    def test_different_element_type(self):
        el1 = _element(element_type="table")
        el2 = _element(element_type="column")
        assert generate_element_id(el1) != generate_element_id(el2)

    def test_different_element_name(self):
        el1 = _element(element_name="Students")
        el2 = _element(element_name="Teachers")
        assert generate_element_id(el1) != generate_element_id(el2)


# ---------------------------------------------------------------------------
# Validation — empty after normalisation → ValueError
# ---------------------------------------------------------------------------

class TestGenerateElementIdValidation:
    """Empty fields after normalisation must raise ValueError."""

    def test_empty_source_system_raises(self):
        el = _element(source_system="")
        with pytest.raises(ValueError, match="source_system"):
            generate_element_id(el)

    def test_whitespace_only_source_system_raises(self):
        el = _element(source_system="   ")
        with pytest.raises(ValueError, match="source_system"):
            generate_element_id(el)

    def test_empty_element_type_raises(self):
        el = _element(element_type="")
        with pytest.raises(ValueError, match="element_type"):
            generate_element_id(el)

    def test_whitespace_only_element_type_raises(self):
        el = _element(element_type="\t\n ")
        with pytest.raises(ValueError, match="element_type"):
            generate_element_id(el)

    def test_empty_element_name_raises(self):
        el = _element(element_name="")
        with pytest.raises(ValueError, match="element_name"):
            generate_element_id(el)

    def test_whitespace_only_element_name_raises(self):
        el = _element(element_name="   \t  ")
        with pytest.raises(ValueError, match="element_name"):
            generate_element_id(el)

    def test_error_includes_original_value(self):
        el = _element(source_system="   ")
        with pytest.raises(ValueError, match=r"original value:.*'   '"):
            generate_element_id(el)


# ---------------------------------------------------------------------------
# Separator injection rejection
# ---------------------------------------------------------------------------

class TestGenerateElementIdSeparatorRejection:
    """Fields containing the reserved separator '::' must be rejected."""

    # --- source_system ---

    def test_source_system_with_separator_raises(self):
        el = _element(source_system="syn::ergy")
        with pytest.raises(ValueError, match=r"source_system.*'::'"): 
            generate_element_id(el)

    # --- element_type ---

    def test_element_type_with_separator_raises(self):
        el = _element(element_type="tab::le")
        with pytest.raises(ValueError, match=r"element_type.*'::'"): 
            generate_element_id(el)

    # --- element_name ---

    def test_element_name_with_separator_in_middle(self):
        el = _element(element_name="student::enrollment")
        with pytest.raises(ValueError, match=r"element_name.*'::'"): 
            generate_element_id(el)

    def test_element_name_with_separator_at_start(self):
        el = _element(element_name="::enrollment")
        with pytest.raises(ValueError, match=r"element_name.*'::'"): 
            generate_element_id(el)

    def test_element_name_with_separator_at_end(self):
        el = _element(element_name="enrollment::")
        with pytest.raises(ValueError, match=r"element_name.*'::'"): 
            generate_element_id(el)

    def test_element_name_with_separator_surrounded_by_whitespace(self):
        """Whitespace around '::' is collapsed first, separator still detected."""
        el = _element(element_name="student  ::  enrollment")
        with pytest.raises(ValueError, match=r"element_name.*'::'"): 
            generate_element_id(el)

    def test_error_includes_original_value_for_separator(self):
        el = _element(element_name="student::enrollment")
        with pytest.raises(ValueError, match=r"original value:.*'student::enrollment'"):
            generate_element_id(el)

    # --- single colon is allowed ---

    def test_single_colon_allowed(self):
        """A single ':' is NOT the separator and must be accepted."""
        el = _element(element_name="student:enrollment")
        result = generate_element_id(el)
        assert result == "synergy::table::student:enrollment"


# ---------------------------------------------------------------------------
# Azure AI Search key length limit (1024 characters)
# ---------------------------------------------------------------------------

class TestGenerateElementIdKeyLength:
    """Final ID must not exceed 1024 characters."""

    def test_id_exactly_1024_allowed(self):
        # "synergy::table::" = 16 chars → name needs 1008 chars
        name = "a" * 1008
        el = _element(element_name=name)
        result = generate_element_id(el)
        assert len(result) == 1024

    def test_id_1025_raises(self):
        # "synergy::table::" = 16 chars → name of 1009 chars = 1025 total
        name = "a" * 1009
        el = _element(element_name=name)
        with pytest.raises(ValueError, match=r"length=1025.*max=1024"):
            generate_element_id(el)

    def test_extremely_long_name_raises(self):
        name = "x" * 5000
        el = _element(element_name=name)
        with pytest.raises(ValueError, match=r"exceeds Azure AI Search limit"):
            generate_element_id(el)

    def test_error_includes_actual_length(self):
        name = "b" * 1100
        el = _element(element_name=name)
        with pytest.raises(ValueError, match=r"length=1116"):
            generate_element_id(el)

    def test_error_includes_max_limit(self):
        name = "c" * 1100
        el = _element(element_name=name)
        with pytest.raises(ValueError, match=r"max=1024"):
            generate_element_id(el)

    def test_error_includes_original_name(self):
        name = "d" * 1100
        el = _element(element_name=name)
        with pytest.raises(ValueError, match=r"name="):
            generate_element_id(el)

    def test_short_id_is_unaffected(self):
        el = _element()
        result = generate_element_id(el)
        assert len(result) < 1024
        assert result == "synergy::table::student enrollment"
