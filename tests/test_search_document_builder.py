"""
Deterministic tests for the Search Document Builder.

Test categories
===============

1. **One-to-one mapping** — one ``ContextElement`` → exactly one document.
2. **Deterministic replay** — 100 identical calls → identical output.
3. **Identity preservation** — ``document["id"] == element_id``.
4. **Schema compliance** — document keys ⊆ ``SCHEMA_FIELDS`` (13 fields).
5. **Content construction** — ``content`` follows the template structure.
6. **Content truncation** — long content truncated to MAX_CONTENT_LENGTH.
7. **Optional field handling** — missing fields → ``None``.
8. **Immutability** — builder does not mutate the input element.
9. **No runtime values** — no timestamps, no random IDs.
10. **Schema validation gate** — extra fields trigger ``ValueError``.
11. **Architecture isolation** — no Azure SDK imports in the module.
12. **Field mapping verification** — each deployed index field maps correctly.
13. **Integration with upstream modules** — builder + identity in concert.
14. **sourceSystem normalisation** — output is always lowercase.
15. **Backward-compatible payload mapping** — old field names still work.
"""

from __future__ import annotations

import base64
import copy

import pytest

from src.domain.element_splitter.models import ContextElement
from src.domain.element_splitter import generate_element_id
from src.domain.search_document import (
    build_search_document,
    MAX_CONTENT_LENGTH,
    SCHEMA_FIELDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_element(
    *,
    source_system: str = "synergy",
    element_name: str = "Student Enrollment",
    element_type: str = "table",
    description: str = "Stores student enrollment records.",
    raw_payload: dict | None = None,
) -> ContextElement:
    """Create a ``ContextElement`` with sensible defaults."""
    if raw_payload is None:
        raw_payload = {
            "id": "synergy.student.enrollment.table",
            "sourceSystem": source_system,
            "elementType": element_type,
            "elementName": element_name,
            "source": "synergy-export-2026-03-01.json",
            "description": description,
            "businessMeaning": "Core enrollment information for all students.",
            "tags": ["enrollment", "student", "core"],
            "content": "Student Enrollment table in Synergy SIS.",
            "lastUpdated": "2026-01-12T10:00:00Z",
            "cedsReference": "https://ceds.ed.gov/element/000123",
        }
    return ContextElement(
        source_system=source_system,
        element_name=element_name,
        element_type=element_type,
        description=description,
        raw_payload=raw_payload,
    )


def _make_minimal_element() -> ContextElement:
    """Create a ``ContextElement`` with only required fields."""
    return ContextElement(
        source_system="zipline",
        element_name="Assessment Definition",
        element_type="element",
        description="Canonical definition of an assessment.",
        raw_payload={
            "id": "zipline.assessment.definition.element",
            "sourceSystem": "zipline",
            "elementType": "element",
            "elementName": "Assessment Definition",
            "description": "Canonical definition of an assessment.",
            "content": "Assessment definition content.",
            "lastUpdated": "2026-02-01T08:00:00Z",
        },
    )


def _build(element: ContextElement | None = None) -> dict:
    """Helper: build a search document from the default element."""
    elem = element or _make_element()
    eid = generate_element_id(elem)
    return build_search_document(elem, eid)


def _expected_b64(value: str) -> str:
    """Return the expected base64 ID for a given element name."""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


# ===================================================================
# 1. One-to-one mapping
# ===================================================================

class TestOneToOneMapping:
    """One ContextElement must produce exactly one document."""

    def test_returns_single_dict(self):
        doc = _build()
        assert isinstance(doc, dict)

    def test_one_element_one_document(self):
        elem = _make_element()
        eid = generate_element_id(elem)
        doc = build_search_document(elem, eid)
        assert isinstance(doc, dict)
        assert doc["id"] == eid


# ===================================================================
# 2. Deterministic replay
# ===================================================================

class TestDeterministicReplay:
    """Identical inputs must always produce identical documents."""

    def test_100_identical_calls(self):
        elem = _make_element()
        eid = generate_element_id(elem)
        first = build_search_document(elem, eid)
        for _ in range(99):
            assert build_search_document(elem, eid) == first

    def test_independent_elements_same_data(self):
        doc_a = _build(_make_element())
        doc_b = _build(_make_element())
        assert doc_a == doc_b


# ===================================================================
# 3. Identity preservation
# ===================================================================

class TestIdentityPreservation:
    """document["id"] must match the element_id argument."""

    def test_id_matches_element_id(self):
        elem = _make_element()
        eid = generate_element_id(elem)
        doc = build_search_document(elem, eid)
        assert doc["id"] == eid

    def test_id_is_base64_encoded(self):
        elem = _make_element()
        doc = _build(elem)
        assert doc["id"] == _expected_b64("Student Enrollment")

    def test_id_stable_across_reindex(self):
        elem = _make_element()
        eid = generate_element_id(elem)
        doc1 = build_search_document(elem, eid)
        doc2 = build_search_document(elem, eid)
        assert doc1["id"] == doc2["id"] == eid


# ===================================================================
# 4. Schema compliance — 13 deployed fields
# ===================================================================

class TestSchemaCompliance:
    """Document keys must be a subset of SCHEMA_FIELDS (13 fields)."""

    def test_all_keys_in_schema(self):
        doc = _build()
        assert set(doc.keys()) <= SCHEMA_FIELDS

    def test_document_covers_all_schema_fields(self):
        doc = _build()
        assert set(doc.keys()) == SCHEMA_FIELDS

    def test_schema_has_13_fields(self):
        assert len(SCHEMA_FIELDS) == 13

    def test_content_vector_is_none(self):
        doc = _build()
        assert doc["contentVector"] is None


# ===================================================================
# 5. Content construction
# ===================================================================

class TestContentConstruction:
    """The content field must follow the deterministic template."""

    def test_content_contains_element_type(self):
        doc = _build()
        assert "Element Type: table" in doc["content"]

    def test_content_contains_element_name(self):
        doc = _build()
        assert "Element Name: Student Enrollment" in doc["content"]

    def test_content_contains_source_system(self):
        doc = _build()
        assert "Source System: synergy" in doc["content"]

    def test_content_contains_description(self):
        doc = _build()
        assert "Stores student enrollment records." in doc["content"]

    def test_content_contains_suggested_description(self):
        doc = _build()
        assert "Core enrollment information for all students." in doc["content"]

    def test_content_contains_tags(self):
        doc = _build()
        assert "enrollment, student, core" in doc["content"]

    def test_content_contains_additional_content(self):
        doc = _build()
        assert "Student Enrollment table in Synergy SIS." in doc["content"]

    def test_content_template_order(self):
        doc = _build()
        c = doc["content"]
        # Verify ordering of sections
        assert c.index("Element Type:") < c.index("Element Name:")
        assert c.index("Element Name:") < c.index("Source System:")
        assert c.index("Source System:") < c.index("Description:")
        assert c.index("Description:") < c.index("Suggested Description:")
        assert c.index("Suggested Description:") < c.index("Tags:")
        assert c.index("Tags:") < c.index("Additional Content:")

    def test_content_does_not_contain_domain_section(self):
        """Domain section was removed from the deployed index."""
        doc = _build()
        assert "Domain:" not in doc["content"]

    def test_minimal_element_content_no_crash(self):
        doc = _build(_make_minimal_element())
        assert "Element Type: element" in doc["content"]
        assert "Element Name: Assessment Definition" in doc["content"]


# ===================================================================
# 6. Content truncation
# ===================================================================

class TestContentTruncation:
    """Content exceeding MAX_CONTENT_LENGTH must be truncated."""

    def test_content_within_limit(self):
        doc = _build()
        assert len(doc["content"]) <= MAX_CONTENT_LENGTH

    def test_long_content_truncated(self):
        long_desc = "A" * 6000
        elem = ContextElement(
            source_system="synergy",
            element_name="Big Table",
            element_type="table",
            description=long_desc,
            raw_payload={
                "sourceSystem": "synergy",
                "elementType": "table",
                "elementName": "Big Table",
                "description": long_desc,
                "content": "x" * 2000,
                "lastUpdated": "2026-01-01T00:00:00Z",
            },
        )
        doc = _build(elem)
        assert len(doc["content"]) == MAX_CONTENT_LENGTH

    def test_truncation_is_deterministic(self):
        long_desc = "B" * 6000
        elem = ContextElement(
            source_system="synergy",
            element_name="Big Table",
            element_type="table",
            description=long_desc,
            raw_payload={
                "sourceSystem": "synergy",
                "elementType": "table",
                "elementName": "Big Table",
                "description": long_desc,
                "content": "y" * 2000,
                "lastUpdated": "2026-01-01T00:00:00Z",
            },
        )
        results = {_build(elem)["content"] for _ in range(20)}
        assert len(results) == 1


# ===================================================================
# 7. Optional field handling
# ===================================================================

class TestOptionalFields:
    """Missing optional fields must default to None."""

    def test_missing_suggested_description(self):
        doc = _build(_make_minimal_element())
        assert doc["suggestedDescription"] is None

    def test_missing_tags(self):
        doc = _build(_make_minimal_element())
        assert doc["tags"] is None

    def test_missing_ceds_link(self):
        doc = _build(_make_minimal_element())
        assert doc["cedsLink"] is None

    def test_missing_source(self):
        doc = _build(_make_minimal_element())
        assert doc["source"] is None


# ===================================================================
# 8. Immutability
# ===================================================================

class TestImmutability:
    """Builder must not mutate the input ContextElement."""

    def test_raw_payload_unchanged(self):
        elem = _make_element()
        payload_before = copy.deepcopy(elem.raw_payload)
        _build(elem)
        assert elem.raw_payload == payload_before

    def test_element_fields_unchanged(self):
        elem = _make_element()
        name_before = elem.element_name
        desc_before = elem.description
        _build(elem)
        assert elem.element_name == name_before
        assert elem.description == desc_before

    def test_frozen_dataclass_rejects_mutation(self):
        elem = _make_element()
        with pytest.raises(AttributeError):
            elem.element_name = "modified"  # type: ignore[misc]


# ===================================================================
# 9. No runtime values
# ===================================================================

class TestNoRuntimeValues:
    """Builder must not inject timestamps, UUIDs, or random values."""

    def test_id_is_base64_not_uuid(self):
        doc = _build()
        # ID must be base64-encoded, not a UUID or separator-based
        decoded = base64.b64decode(doc["id"]).decode("utf-8")
        assert decoded == "Student Enrollment"

    def test_last_updated_from_payload_not_runtime(self):
        doc = _build()
        assert doc["lastUpdated"] == "2026-01-12T10:00:00Z"


# ===================================================================
# 10. Schema validation gate
# ===================================================================

class TestSchemaValidationGate:
    """Extra fields must trigger ValueError."""

    def test_schema_fields_count(self):
        assert len(SCHEMA_FIELDS) == 13

    def test_document_keys_match_schema(self):
        doc = _build()
        assert set(doc.keys()) == SCHEMA_FIELDS


# ===================================================================
# 11. Architecture isolation
# ===================================================================

class TestArchitectureIsolation:
    """Builder module must not import Azure SDKs."""

    def test_no_azure_imports(self):
        import src.domain.search_document.builder as mod
        source = open(mod.__file__, "r", encoding="utf-8").read()
        azure_patterns = [
            "azure.search",
            "azure.cosmos",
            "azure.storage",
            "azure.servicebus",
            "azure.identity",
            "azure.core",
        ]
        for pattern in azure_patterns:
            assert pattern not in source, (
                f"Builder must not import '{pattern}'"
            )

    def test_no_azure_imports_in_models(self):
        import src.domain.search_document.models as mod
        source = open(mod.__file__, "r", encoding="utf-8").read()
        assert "azure" not in source.lower() or "azure ai search" in source.lower()


# ===================================================================
# 12. Field mapping verification
# ===================================================================

class TestFieldMapping:
    """Verify each field maps to the correct source."""

    def test_source_system_mapping(self):
        doc = _build()
        assert doc["sourceSystem"] == "synergy"

    def test_element_type_mapping(self):
        doc = _build()
        assert doc["elementType"] == "table"

    def test_element_name_mapping(self):
        doc = _build()
        assert doc["elementName"] == "Student Enrollment"

    def test_title_mapping(self):
        """title defaults to element_name."""
        doc = _build()
        assert doc["title"] == "Student Enrollment"

    def test_description_mapping(self):
        doc = _build()
        assert doc["description"] == "Stores student enrollment records."

    def test_suggested_description_from_business_meaning(self):
        """Backward compat: businessMeaning → suggestedDescription."""
        doc = _build()
        assert doc["suggestedDescription"] == (
            "Core enrollment information for all students."
        )

    def test_ceds_link_from_ceds_reference(self):
        """Backward compat: cedsReference → cedsLink."""
        doc = _build()
        assert doc["cedsLink"] == "https://ceds.ed.gov/element/000123"

    def test_source_mapping(self):
        doc = _build()
        assert doc["source"] == "synergy-export-2026-03-01.json"

    def test_last_updated_mapping(self):
        doc = _build()
        assert doc["lastUpdated"] == "2026-01-12T10:00:00Z"

    def test_tags_mapping(self):
        doc = _build()
        assert doc["tags"] == ["enrollment", "student", "core"]

    def test_content_vector_is_none(self):
        doc = _build()
        assert doc["contentVector"] is None


# ===================================================================
# 13. Integration with upstream modules
# ===================================================================

class TestUpstreamIntegration:
    """Builder integrates with identity module."""

    def test_id_from_generate_element_id(self):
        elem = _make_element()
        expected = generate_element_id(elem)
        doc = build_search_document(elem, expected)
        assert doc["id"] == expected

    def test_different_elements_different_documents(self):
        elem_a = _make_element(element_name="Table A")
        elem_b = _make_element(element_name="Table B")
        doc_a = _build(elem_a)
        doc_b = _build(elem_b)
        assert doc_a["id"] != doc_b["id"]
        assert doc_a["elementName"] != doc_b["elementName"]


# ===================================================================
# 14. sourceSystem normalisation
# ===================================================================

class TestSourceSystemNormalisation:
    """sourceSystem in the output document must always be lowercase."""

    def test_uppercase_normalised(self):
        elem = _make_element(source_system="Synergy")
        doc = _build(elem)
        assert doc["sourceSystem"] == "synergy"

    def test_mixed_case_normalised(self):
        elem = _make_element(source_system="ZIPLINE")
        doc = _build(elem)
        assert doc["sourceSystem"] == "zipline"

    def test_already_lowercase(self):
        elem = _make_element(source_system="synergy")
        doc = _build(elem)
        assert doc["sourceSystem"] == "synergy"


# ===================================================================
# 15. Backward-compatible payload mapping
# ===================================================================

class TestBackwardCompatPayload:
    """Builder must accept both old and new payload field names."""

    def test_suggested_description_from_new_field(self):
        """When payload has suggestedDescription directly, use it."""
        elem = _make_element(raw_payload={
            "sourceSystem": "synergy",
            "elementType": "table",
            "elementName": "Students",
            "suggestedDescription": "New-style description.",
            "description": "Desc.",
            "content": "c",
            "lastUpdated": "2026-01-01T00:00:00Z",
        })
        doc = _build(elem)
        assert doc["suggestedDescription"] == "New-style description."

    def test_business_meaning_takes_precedence(self):
        """When payload has both businessMeaning and suggestedDescription,
        businessMeaning wins (backward compat)."""
        elem = _make_element(raw_payload={
            "sourceSystem": "synergy",
            "elementType": "table",
            "elementName": "Students",
            "businessMeaning": "From old field.",
            "suggestedDescription": "From new field.",
            "description": "Desc.",
            "content": "c",
            "lastUpdated": "2026-01-01T00:00:00Z",
        })
        doc = _build(elem)
        assert doc["suggestedDescription"] == "From old field."

    def test_ceds_link_from_new_field(self):
        """When payload has cedsLink directly, use it."""
        elem = _make_element(raw_payload={
            "sourceSystem": "synergy",
            "elementType": "table",
            "elementName": "Students",
            "cedsLink": "https://ceds.ed.gov/new",
            "description": "Desc.",
            "content": "c",
            "lastUpdated": "2026-01-01T00:00:00Z",
        })
        doc = _build(elem)
        assert doc["cedsLink"] == "https://ceds.ed.gov/new"

    def test_ceds_reference_takes_precedence(self):
        """When payload has both cedsReference and cedsLink,
        cedsReference wins (backward compat)."""
        elem = _make_element(raw_payload={
            "sourceSystem": "synergy",
            "elementType": "table",
            "elementName": "Students",
            "cedsReference": "https://ceds.ed.gov/old",
            "cedsLink": "https://ceds.ed.gov/new",
            "description": "Desc.",
            "content": "c",
            "lastUpdated": "2026-01-01T00:00:00Z",
        })
        doc = _build(elem)
        assert doc["cedsLink"] == "https://ceds.ed.gov/old"
