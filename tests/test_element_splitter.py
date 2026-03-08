"""
Unit tests for the element_splitter module.

Covers:
    - Valid JSON with elements (Synergy & Zipline)
    - JSON missing the ``elements`` key
    - JSON with an empty ``elements`` list
    - Order preservation
    - Original JSON immutability
    - Required field validation (missing, empty, whitespace-only)
    - Optional field defaults (description)
    - Non-dict / non-list edge cases
    - Extra / unknown fields preserved in raw_payload
    - Frozen dataclass enforcement
"""

from __future__ import annotations

import copy
import pytest

from src.domain.element_splitter import ContextElement, split_elements


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _valid_element(**overrides: object) -> dict:
    """Return a minimal valid element dict, with optional overrides."""
    base = {
        "sourceSystem": "synergy",
        "entityType": "table",
        "elementName": "Student Enrollment",
        "description": "Stores student enrollment records.",
    }
    base.update(overrides)
    return base


def _synergy_blob() -> dict:
    """Minimal Synergy export blob with two elements."""
    return {
        "sourceSystem": "synergy",
        "schemaVersion": "1.0.0",
        "elements": [
            {
                "id": "synergy.student.enrollment.table",
                "sourceSystem": "synergy",
                "entityType": "table",
                "elementName": "Student Enrollment",
                "entityPath": "synergy.student.enrollment",
                "description": "Stores student enrollment records.",
                "businessMeaning": "Core enrollment information.",
                "domain": "Student Information",
                "tags": ["enrollment", "student"],
                "content": "Enrollment content.",
                "lastUpdated": "2026-02-02T12:00:00Z",
                "schemaVersion": "1.0.0",
            },
            {
                "id": "synergy.student.demographics.ethnicity.column",
                "sourceSystem": "synergy",
                "entityType": "column",
                "elementName": "Ethnicity",
                "entityPath": "synergy.student.demographics.ethnicity",
                "description": "Primary reported ethnicity.",
                "businessMeaning": "Used for equity reporting.",
                "domain": "Student Information",
                "tags": ["demographics"],
                "content": "Ethnicity column.",
                "lastUpdated": "2026-02-02T12:05:00Z",
                "schemaVersion": "1.0.0",
                "dataType": "VARCHAR(50)",
                "sourceTable": "STU_DEMOGRAPHICS",
            },
        ],
    }


def _zipline_blob() -> dict:
    """Minimal Zipline export blob with one element."""
    return {
        "sourceSystem": "zipline",
        "schemaVersion": "1.0.0",
        "elements": [
            {
                "id": "zipline.assessment.definition.element",
                "sourceSystem": "zipline",
                "entityType": "element",
                "elementName": "Assessment Definition",
                "entityPath": "zipline.assessment.definition",
                "description": "Canonical definition of an assessment.",
                "businessMeaning": "Authoritative metadata for assessments.",
                "domain": "Student Assessment",
                "tags": ["assessment", "definition"],
                "content": "Assessment definition content.",
                "lastUpdated": "2026-02-02T12:00:00Z",
                "schemaVersion": "1.0.0",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Valid JSON
# ---------------------------------------------------------------------------

class TestSplitElementsValidJSON:
    """Tests for valid export JSONs."""

    def test_synergy_returns_correct_count(self):
        result = split_elements(_synergy_blob())
        assert len(result) == 2

    def test_zipline_returns_correct_count(self):
        result = split_elements(_zipline_blob())
        assert len(result) == 1

    def test_returns_context_element_instances(self):
        result = split_elements(_synergy_blob())
        for item in result:
            assert isinstance(item, ContextElement)

    def test_source_system_mapped(self):
        result = split_elements(_synergy_blob())
        assert result[0].source_system == "synergy"
        assert result[1].source_system == "synergy"

    def test_element_name_mapped(self):
        result = split_elements(_synergy_blob())
        assert result[0].element_name == "Student Enrollment"
        assert result[1].element_name == "Ethnicity"

    def test_element_type_mapped(self):
        result = split_elements(_synergy_blob())
        assert result[0].element_type == "table"
        assert result[1].element_type == "column"

    def test_description_mapped(self):
        result = split_elements(_synergy_blob())
        assert result[0].description == "Stores student enrollment records."

    def test_raw_payload_is_full_original(self):
        blob = _synergy_blob()
        result = split_elements(blob)
        assert result[0].raw_payload["id"] == "synergy.student.enrollment.table"
        assert result[0].raw_payload["businessMeaning"] == "Core enrollment information."

    def test_zipline_source_system(self):
        result = split_elements(_zipline_blob())
        assert result[0].source_system == "zipline"
        assert result[0].element_type == "element"


# ---------------------------------------------------------------------------
# Order preservation
# ---------------------------------------------------------------------------

class TestSplitElementsOrder:
    """Output list must preserve the original elements[] order."""

    def test_order_matches_input(self):
        result = split_elements(_synergy_blob())
        assert result[0].element_name == "Student Enrollment"
        assert result[1].element_name == "Ethnicity"

    def test_order_with_many_elements(self):
        names = [f"Element_{i}" for i in range(20)]
        blob = {
            "elements": [
                _valid_element(elementName=name)
                for name in names
            ]
        }
        result = split_elements(blob)
        assert [r.element_name for r in result] == names


# ---------------------------------------------------------------------------
# Immutability — original JSON must not be modified
# ---------------------------------------------------------------------------

class TestSplitElementsImmutability:
    """split_elements must never mutate the input JSON."""

    def test_original_json_unchanged(self):
        blob = _synergy_blob()
        original = copy.deepcopy(blob)
        split_elements(blob)
        assert blob == original

    def test_raw_payload_is_independent_copy(self):
        blob = _synergy_blob()
        result = split_elements(blob)
        # Mutate the raw_payload — source blob must remain untouched.
        result[0].raw_payload["description"] = "MUTATED"
        assert blob["elements"][0]["description"] == "Stores student enrollment records."


# ---------------------------------------------------------------------------
# Empty elements
# ---------------------------------------------------------------------------

class TestSplitElementsEmpty:
    """An empty elements list must return an empty list — not an error."""

    def test_empty_elements_returns_empty_list(self):
        result = split_elements({"elements": []})
        assert result == []

    def test_empty_elements_return_type(self):
        result = split_elements({"elements": []})
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Missing elements key
# ---------------------------------------------------------------------------

class TestSplitElementsMissing:
    """Missing ``elements`` key must raise KeyError."""

    def test_missing_elements_raises_key_error(self):
        with pytest.raises(KeyError, match="elements"):
            split_elements({"sourceSystem": "synergy"})

    def test_completely_empty_dict_raises_key_error(self):
        with pytest.raises(KeyError, match="elements"):
            split_elements({})


# ---------------------------------------------------------------------------
# Invalid input types
# ---------------------------------------------------------------------------

class TestSplitElementsInvalidTypes:
    """Non-dict inputs and non-list elements must raise TypeError."""

    def test_none_raises_type_error(self):
        with pytest.raises(TypeError):
            split_elements(None)  # type: ignore[arg-type]

    def test_list_input_raises_type_error(self):
        with pytest.raises(TypeError):
            split_elements([{"elements": []}])  # type: ignore[arg-type]

    def test_string_input_raises_type_error(self):
        with pytest.raises(TypeError):
            split_elements("not a dict")  # type: ignore[arg-type]

    def test_elements_as_string_raises_type_error(self):
        with pytest.raises(TypeError, match="list"):
            split_elements({"elements": "not a list"})

    def test_elements_as_dict_raises_type_error(self):
        with pytest.raises(TypeError, match="list"):
            split_elements({"elements": {}})


# ---------------------------------------------------------------------------
# Required field validation — missing
# ---------------------------------------------------------------------------

class TestSplitElementsRequiredFieldMissing:
    """Missing required fields must raise ValueError with element index."""

    def test_missing_source_system_raises(self):
        el = _valid_element()
        del el["sourceSystem"]
        with pytest.raises(ValueError, match=r"index 0.*source_system"):
            split_elements({"elements": [el]})

    def test_missing_element_name_raises(self):
        el = _valid_element()
        del el["elementName"]
        with pytest.raises(ValueError, match=r"index 0.*element_name"):
            split_elements({"elements": [el]})

    def test_missing_element_type_raises(self):
        el = _valid_element()
        del el["entityType"]
        with pytest.raises(ValueError, match=r"index 0.*element_type"):
            split_elements({"elements": [el]})

    def test_missing_all_required_raises(self):
        """First missing field triggers — order is source_system first."""
        with pytest.raises(ValueError, match=r"index 0.*source_system"):
            split_elements({"elements": [{}]})

    def test_error_includes_correct_index(self):
        """Error must reference index 1, not 0."""
        good = _valid_element()
        bad = _valid_element()
        del bad["elementName"]
        with pytest.raises(ValueError, match=r"index 1.*element_name"):
            split_elements({"elements": [good, bad]})


# ---------------------------------------------------------------------------
# Required field validation — empty string
# ---------------------------------------------------------------------------

class TestSplitElementsRequiredFieldEmpty:
    """Empty-string required fields must raise ValueError."""

    def test_empty_source_system_raises(self):
        with pytest.raises(ValueError, match=r"index 0.*source_system"):
            split_elements({"elements": [_valid_element(sourceSystem="")]})

    def test_empty_element_name_raises(self):
        with pytest.raises(ValueError, match=r"index 0.*element_name"):
            split_elements({"elements": [_valid_element(elementName="")]})

    def test_empty_element_type_raises(self):
        with pytest.raises(ValueError, match=r"index 0.*element_type"):
            split_elements({"elements": [_valid_element(entityType="")]})


# ---------------------------------------------------------------------------
# Required field validation — whitespace-only
# ---------------------------------------------------------------------------

class TestSplitElementsRequiredFieldWhitespace:
    """Whitespace-only required fields must raise ValueError."""

    def test_whitespace_source_system_raises(self):
        with pytest.raises(ValueError, match=r"index 0.*source_system"):
            split_elements({"elements": [_valid_element(sourceSystem="   ")]})

    def test_whitespace_element_name_raises(self):
        with pytest.raises(ValueError, match=r"index 0.*element_name"):
            split_elements({"elements": [_valid_element(elementName="\t\n")]})

    def test_whitespace_element_type_raises(self):
        with pytest.raises(ValueError, match=r"index 0.*element_type"):
            split_elements({"elements": [_valid_element(entityType="  \n  ")]})


# ---------------------------------------------------------------------------
# Required field validation — non-string types
# ---------------------------------------------------------------------------

class TestSplitElementsRequiredFieldNonString:
    """Non-string values in required fields must raise ValueError."""

    def test_integer_source_system_raises(self):
        with pytest.raises(ValueError, match=r"index 0.*source_system"):
            split_elements({"elements": [_valid_element(sourceSystem=123)]})

    def test_none_element_name_raises(self):
        with pytest.raises(ValueError, match=r"index 0.*element_name"):
            split_elements({"elements": [_valid_element(elementName=None)]})

    def test_list_element_type_raises(self):
        with pytest.raises(ValueError, match=r"index 0.*element_type"):
            split_elements({"elements": [_valid_element(entityType=["table"])]})


# ---------------------------------------------------------------------------
# Optional field defaults
# ---------------------------------------------------------------------------

class TestSplitElementsOptionalDefaults:
    """Optional fields must default to empty string — no ValueError."""

    def test_missing_description_defaults_empty(self):
        el = _valid_element()
        del el["description"]
        result = split_elements({"elements": [el]})
        assert result[0].description == ""

    def test_description_preserved_when_present(self):
        el = _valid_element(description="Some description")
        result = split_elements({"elements": [el]})
        assert result[0].description == "Some description"


# ---------------------------------------------------------------------------
# source_system is NOT normalised (case preserved as-is)
# ---------------------------------------------------------------------------

class TestSplitElementsCasePreservation:
    """Splitter must NOT normalise case — that belongs to identity layer."""

    def test_uppercase_source_system_preserved(self):
        el = _valid_element(sourceSystem="SYNERGY")
        result = split_elements({"elements": [el]})
        assert result[0].source_system == "SYNERGY"

    def test_mixed_case_preserved(self):
        el = _valid_element(sourceSystem="Synergy", entityType="Table")
        result = split_elements({"elements": [el]})
        assert result[0].source_system == "Synergy"
        assert result[0].element_type == "Table"


# ---------------------------------------------------------------------------
# Extra / unknown fields preserved in raw_payload
# ---------------------------------------------------------------------------

class TestSplitElementsExtraFields:
    """Unknown fields must be ignored in mapping but preserved in raw_payload."""

    def test_extra_fields_in_raw_payload(self):
        el = _valid_element(customField="hello", nested={"a": 1})
        result = split_elements({"elements": [el]})
        assert result[0].raw_payload["customField"] == "hello"
        assert result[0].raw_payload["nested"] == {"a": 1}

    def test_extra_fields_do_not_affect_attributes(self):
        el = _valid_element(customField="hello")
        result = split_elements({"elements": [el]})
        assert not hasattr(result[0], "customField")


# ---------------------------------------------------------------------------
# Frozen dataclass
# ---------------------------------------------------------------------------

class TestContextElementFrozen:
    """ContextElement must be immutable (frozen dataclass)."""

    def test_cannot_set_attribute(self):
        blob = _synergy_blob()
        result = split_elements(blob)
        with pytest.raises(AttributeError):
            result[0].source_system = "modified"  # type: ignore[misc]
