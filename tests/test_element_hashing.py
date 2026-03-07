"""
Deterministic tests for the element hashing module.

Test categories
===============

1. **Stability** — same element → identical hash across invocations.
2. **Order independence** — different field ordering → same hash.
3. **Volatile field exclusion** — elements differing only by volatile
   metadata → same hash.
4. **Logical change detection** — any meaningful content change →
   different hash.
5. **Deterministic serialisation** — canonical JSON is stable.
6. **Collection normalisation** — tag/relationship/column/lineage order
   does not affect the hash.
7. **Edge cases** — missing optional fields, empty collections, etc.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.domain.element_splitter.models import ContextElement
from src.domain.element_hashing import (
    compute_element_hash,
    compute_element_hash_result,
    canonicalize_element,
    extract_canonical_payload,
    ElementHashResult,
    VOLATILE_FIELDS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_element(
    *,
    source_system: str = "synergy",
    element_name: str = "Student Enrollment",
    element_type: str = "table",
    description: str = "Stores student enrollment records.",
    raw_payload: dict | None = None,
) -> ContextElement:
    """Helper to create a ``ContextElement`` with sensible defaults."""
    if raw_payload is None:
        raw_payload = {
            "id": "synergy.student.enrollment.table",
            "sourceSystem": source_system,
            "entityType": element_type,
            "entityName": element_name,
            "entityPath": "synergy.student.enrollment",
            "description": description,
            "businessMeaning": "Core enrollment information for all students.",
            "domain": "Student Information",
            "tags": ["enrollment", "student", "core"],
            "content": "Student Enrollment table in Synergy.",
            "lastUpdated": "2026-01-12T10:00:00Z",
            "schemaVersion": "1.0.0",
        }
    return ContextElement(
        source_system=source_system,
        element_name=element_name,
        element_type=element_type,
        description=description,
        raw_payload=raw_payload,
    )


# ===================================================================
# 1. Stability — same element, same hash
# ===================================================================

class TestStability:
    """Same logical element must always produce the same hash."""

    def test_identical_calls_produce_same_hash(self):
        elem = _make_element()
        assert compute_element_hash(elem) == compute_element_hash(elem)

    def test_independent_identical_elements_produce_same_hash(self):
        elem_a = _make_element()
        elem_b = _make_element()
        assert compute_element_hash(elem_a) == compute_element_hash(elem_b)

    def test_hash_is_64_char_hex_string(self):
        h = compute_element_hash(_make_element())
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_repeated_calls_are_stable(self):
        elem = _make_element()
        hashes = {compute_element_hash(elem) for _ in range(50)}
        assert len(hashes) == 1, "Hash must be identical across runs"


# ===================================================================
# 2. Order independence
# ===================================================================

class TestOrderIndependence:
    """Field ordering must not affect the hash."""

    def test_reversed_field_order_produces_same_hash(self):
        payload_ordered = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "description": "Desc",
            "content": "Content",
        }
        # Reverse the key order
        payload_reversed = dict(reversed(list(payload_ordered.items())))

        h1 = compute_element_hash(_make_element(raw_payload=payload_ordered))
        h2 = compute_element_hash(_make_element(raw_payload=payload_reversed))
        assert h1 == h2

    def test_shuffled_keys_produce_same_hash(self):
        base = {
            "entityName": "Table A",
            "entityType": "table",
            "id": "a.table",
            "sourceSystem": "zipline",
            "domain": "Finance",
            "description": "Financial records",
        }
        # Different insertion order
        alt = {
            "domain": "Finance",
            "id": "a.table",
            "description": "Financial records",
            "sourceSystem": "zipline",
            "entityName": "Table A",
            "entityType": "table",
        }
        h1 = compute_element_hash(_make_element(raw_payload=base))
        h2 = compute_element_hash(_make_element(raw_payload=alt))
        assert h1 == h2


# ===================================================================
# 3. Volatile field exclusion
# ===================================================================

class TestVolatileFieldExclusion:
    """Elements differing only by volatile metadata must hash identically."""

    def test_different_lastUpdated_same_hash(self):
        payload_a = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "description": "Desc",
            "lastUpdated": "2026-01-01T00:00:00Z",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["lastUpdated"] = "2026-06-15T12:00:00Z"

        h1 = compute_element_hash(_make_element(raw_payload=payload_a))
        h2 = compute_element_hash(_make_element(raw_payload=payload_b))
        assert h1 == h2

    def test_different_schemaVersion_same_hash(self):
        payload_a = {
            "id": "v.col",
            "sourceSystem": "zipline",
            "entityType": "column",
            "entityName": "Col",
            "schemaVersion": "1.0.0",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["schemaVersion"] = "2.0.0"

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) == compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_different_scanId_same_hash(self):
        payload_a = {
            "id": "s.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "S",
            "scanId": "scan-001",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["scanId"] = "scan-999"

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) == compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_different_ingestionTime_same_hash(self):
        payload_a = {
            "id": "i.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "I",
            "ingestionTime": "2026-01-01T00:00:00Z",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["ingestionTime"] = "2026-12-31T23:59:59Z"

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) == compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_different_auditInfo_same_hash(self):
        payload_a = {
            "id": "a.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "A",
            "auditInfo": {"user": "alice"},
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["auditInfo"] = {"user": "bob"}

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) == compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_underscore_prefixed_field_excluded(self):
        payload_a = {
            "id": "u.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "U",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["_internal_tracking"] = "some-runtime-value"
        payload_b["_processing_id"] = "proc-42"

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) == compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_presence_or_absence_of_all_volatile_fields_same_hash(self):
        """Adding every known volatile field must not change the hash."""
        base = {
            "id": "all.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "All",
            "description": "Base payload",
        }
        with_volatile = copy.deepcopy(base)
        with_volatile.update(
            {
                "lastUpdated": "2026-03-01T00:00:00Z",
                "schemaVersion": "3.0.0",
                "auditInfo": {"user": "admin", "ts": "now"},
                "scanId": "scan-all",
                "ingestionTime": "2026-03-01T00:00:00Z",
                "_temp": "ephemeral",
            }
        )
        assert compute_element_hash(
            _make_element(raw_payload=base)
        ) == compute_element_hash(
            _make_element(raw_payload=with_volatile)
        )

    def test_volatile_fields_absent_from_canonical_payload(self):
        """Canonical payload dict must not contain any volatile keys."""
        elem = _make_element()
        canonical = extract_canonical_payload(elem)
        for vf in VOLATILE_FIELDS:
            assert vf not in canonical, f"Volatile field {vf!r} was not stripped"
        assert not any(
            k.startswith("_") for k in canonical
        ), "Underscore-prefixed field was not stripped"


# ===================================================================
# 4. Logical change detection
# ===================================================================

class TestLogicalChangeDetection:
    """Any meaningful change in element content must produce a different hash."""

    def test_description_change_produces_different_hash(self):
        payload_a = {
            "id": "d.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "D",
            "description": "Original description",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["description"] = "Updated description with new info"

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) != compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_entityName_change_produces_different_hash(self):
        payload_a = {
            "id": "n.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Original Name",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["entityName"] = "Renamed Entity"

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) != compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_content_change_produces_different_hash(self):
        payload_a = {
            "id": "c.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "C",
            "content": "Original content for RAG embedding.",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["content"] = "Revised content with additional context."

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) != compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_businessMeaning_change_produces_different_hash(self):
        payload_a = {
            "id": "bm.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "BM",
            "businessMeaning": "Records purchases",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["businessMeaning"] = "Historical transaction records"

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) != compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_tag_addition_produces_different_hash(self):
        payload_a = {
            "id": "t.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "T",
            "tags": ["alpha", "beta"],
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["tags"].append("gamma")

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) != compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_domain_change_produces_different_hash(self):
        payload_a = {
            "id": "dom.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Dom",
            "domain": "Finance",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["domain"] = "Human Resources"

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) != compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_id_change_produces_different_hash(self):
        payload_a = {
            "id": "first.id",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "X",
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["id"] = "second.id"

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) != compute_element_hash(
            _make_element(raw_payload=payload_b)
        )


# ===================================================================
# 5. Deterministic serialisation
# ===================================================================

class TestDeterministicSerialisation:
    """Canonical JSON must be stable and reproducible."""

    def test_canonical_json_keys_are_sorted(self):
        elem = _make_element(
            raw_payload={
                "z_field": "last",
                "a_field": "first",
                "m_field": "middle",
            }
        )
        canonical = canonicalize_element(elem)
        parsed = json.loads(canonical)
        assert list(parsed.keys()) == sorted(parsed.keys())

    def test_canonical_json_is_compact(self):
        elem = _make_element(
            raw_payload={
                "id": "compact.table",
                "sourceSystem": "synergy",
                "entityType": "table",
                "entityName": "Compact",
            }
        )
        canonical = canonicalize_element(elem)
        # Compact JSON has no spaces after separators
        assert " : " not in canonical
        assert ", " not in canonical

    def test_canonical_json_stable_across_calls(self):
        elem = _make_element()
        results = {canonicalize_element(elem) for _ in range(50)}
        assert len(results) == 1, "Canonical JSON must be identical across calls"

    def test_canonical_json_does_not_escape_unicode(self):
        elem = _make_element(
            raw_payload={
                "id": "uni.table",
                "entityName": "Ünïcödé Tàble",
                "description": "Contains « special » characters — like em-dashes",
            }
        )
        canonical = canonicalize_element(elem)
        assert "Ünïcödé" in canonical
        assert "«" in canonical


# ===================================================================
# 6. Collection normalisation
# ===================================================================

class TestCollectionNormalisation:
    """Reordered collections must not affect the hash."""

    def test_tag_order_does_not_affect_hash(self):
        payload_a = {
            "id": "tag.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Tag",
            "tags": ["charlie", "alpha", "bravo"],
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["tags"] = ["bravo", "charlie", "alpha"]

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) == compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_duplicate_tags_are_deduplicated(self):
        payload_a = {
            "id": "dup.tag",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "DupTag",
            "tags": ["alpha", "beta"],
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["tags"] = ["alpha", "beta", "alpha", "beta"]

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) == compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_relationship_order_does_not_affect_hash(self):
        rel_a = {"id": "rel-1", "type": "parent"}
        rel_b = {"id": "rel-2", "type": "child"}
        payload_a = {
            "id": "rel.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Rel",
            "relationships": [rel_a, rel_b],
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["relationships"] = [rel_b, rel_a]

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) == compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_column_order_does_not_affect_hash(self):
        col_a = {"name": "col_alpha", "dataType": "VARCHAR"}
        col_b = {"name": "col_beta", "dataType": "INTEGER"}
        payload_a = {
            "id": "col.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Col",
            "columns": [col_a, col_b],
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["columns"] = [col_b, col_a]

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) == compute_element_hash(
            _make_element(raw_payload=payload_b)
        )

    def test_lineage_order_does_not_affect_hash(self):
        payload_a = {
            "id": "lin.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Lin",
            "lineage": ["parent.c", "parent.a", "parent.b"],
        }
        payload_b = copy.deepcopy(payload_a)
        payload_b["lineage"] = ["parent.a", "parent.b", "parent.c"]

        assert compute_element_hash(
            _make_element(raw_payload=payload_a)
        ) == compute_element_hash(
            _make_element(raw_payload=payload_b)
        )


# ===================================================================
# 7. Edge cases
# ===================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_minimal_payload(self):
        """An element with only core fields still produces a valid hash."""
        elem = _make_element(
            raw_payload={
                "id": "min.table",
                "sourceSystem": "synergy",
                "entityType": "table",
                "entityName": "Minimal",
            }
        )
        h = compute_element_hash(elem)
        assert isinstance(h, str) and len(h) == 64

    def test_empty_tags_list_produces_stable_hash(self):
        payload_a = {
            "id": "et.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Empty Tags",
            "tags": [],
        }
        h1 = compute_element_hash(_make_element(raw_payload=payload_a))
        h2 = compute_element_hash(_make_element(raw_payload=copy.deepcopy(payload_a)))
        assert h1 == h2

    def test_empty_string_description_preserved(self):
        """An empty description is different from a missing description."""
        payload_with = {
            "id": "ed.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "ED",
            "description": "",
        }
        payload_without = {
            "id": "ed.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "ED",
        }
        # empty-string is different from absent
        assert compute_element_hash(
            _make_element(raw_payload=payload_with)
        ) != compute_element_hash(
            _make_element(raw_payload=payload_without)
        )

    def test_raw_payload_not_mutated(self):
        """Hashing must not modify the element's raw_payload."""
        payload = {
            "id": "mut.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Mut",
            "lastUpdated": "2026-01-01T00:00:00Z",
            "tags": ["bravo", "alpha"],
        }
        original = copy.deepcopy(payload)
        elem = _make_element(raw_payload=payload)
        compute_element_hash(elem)
        assert elem.raw_payload == original, "raw_payload was mutated by hashing"

    def test_non_dict_raw_payload_raises_type_error(self):
        elem = ContextElement(
            source_system="synergy",
            element_name="Bad",
            element_type="table",
            description="",
            raw_payload="not-a-dict",  # type: ignore[arg-type]
        )
        with pytest.raises(TypeError, match="raw_payload must be a dict"):
            compute_element_hash(elem)


# ===================================================================
# 8. ElementHashResult
# ===================================================================

class TestElementHashResult:
    """Tests for the convenience wrapper."""

    def test_result_contains_id_and_hash(self):
        elem = _make_element()
        result = compute_element_hash_result(elem)
        assert isinstance(result, ElementHashResult)
        assert len(result.element_id) > 0
        assert len(result.content_hash) == 64

    def test_result_hash_matches_standalone_hash(self):
        elem = _make_element()
        result = compute_element_hash_result(elem)
        standalone = compute_element_hash(elem)
        assert result.content_hash == standalone

    def test_result_is_frozen(self):
        result = compute_element_hash_result(_make_element())
        with pytest.raises(AttributeError):
            result.content_hash = "overwrite"  # type: ignore[misc]
