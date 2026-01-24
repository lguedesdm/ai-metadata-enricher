"""
Unit tests for the change detection module.

Tests verify:
- Identical logical assets produce the same hash
- Material metadata changes produce different hashes
- Non-material changes (ordering, timestamps) do not affect the hash
- Normalization handles edge cases correctly
"""

import pytest
from src.domain.change_detection import (
    compute_asset_hash,
    are_assets_equal_by_hash,
    normalize_asset,
    get_asset_hash_components,
)


class TestNormalization:
    """Tests for asset normalization."""

    def test_normalize_removes_volatile_fields(self):
        """Non-material fields like lastUpdated should be removed."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test Table",
            "entityPath": "db.schema.table",
            "description": "A test table",
            "businessMeaning": "Test business meaning",
            "domain": "Testing",
            "content": "Test content",
            "lastUpdated": "2026-01-24T10:00:00Z",  # Volatile
            "schemaVersion": "1.0.0",  # Volatile
            "scanId": "scan-123",  # Volatile
        }

        normalized = normalize_asset(asset)

        assert "lastUpdated" not in normalized
        assert "schemaVersion" not in normalized
        assert "scanId" not in normalized
        assert normalized["id"] == "test.table"
        assert normalized["description"] == "A test table"

    def test_normalize_removes_underscore_fields(self):
        """Fields starting with underscore should be removed."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test Table",
            "entityPath": "db.schema.table",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "_internal_field": "should be removed",
            "_metadata": {"key": "value"},
        }

        normalized = normalize_asset(asset)

        assert "_internal_field" not in normalized
        assert "_metadata" not in normalized

    def test_normalize_sorts_tags_alphabetically(self):
        """Tags should be sorted alphabetically (case-insensitive)."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": ["zebra", "apple", "Banana", "cherry"],
        }

        normalized = normalize_asset(asset)

        # Should be sorted case-insensitively
        assert normalized["tags"] == ["apple", "Banana", "cherry", "zebra"]

    def test_normalize_removes_duplicate_tags(self):
        """Duplicate tags should be removed during normalization."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": ["sales", "analytics", "sales", "customer"],
        }

        normalized = normalize_asset(asset)

        assert normalized["tags"] == ["analytics", "customer", "sales"]

    def test_normalize_sorts_relationships_by_id(self):
        """Relationships should be sorted by id."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "relationships": [
                {"id": "rel.zebra", "type": "child"},
                {"id": "rel.apple", "type": "parent"},
                {"id": "rel.cherry", "type": "sibling"},
            ],
        }

        normalized = normalize_asset(asset)

        ids = [r["id"] for r in normalized["relationships"]]
        assert ids == ["rel.apple", "rel.cherry", "rel.zebra"]

    def test_normalize_sorts_columns_by_name(self):
        """Columns should be sorted by name."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "columns": [
                {"name": "zebra_col", "type": "string"},
                {"name": "apple_col", "type": "int"},
                {"name": "cherry_col", "type": "date"},
            ],
        }

        normalized = normalize_asset(asset)

        names = [c["name"] for c in normalized["columns"]]
        assert names == ["apple_col", "cherry_col", "zebra_col"]

    def test_normalize_skips_none_values(self):
        """None values should be skipped."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": None,
            "relationships": None,
        }

        normalized = normalize_asset(asset)

        assert "tags" not in normalized
        assert "relationships" not in normalized

    def test_normalize_preserves_material_fields(self):
        """All material fields should be preserved in normalized output."""
        asset = {
            "id": "test.table",
            "sourceSystem": "zipline",
            "entityType": "column",
            "entityName": "Test Column",
            "entityPath": "db.schema.table.column",
            "description": "Test description",
            "businessMeaning": "Test business meaning",
            "domain": "Test Domain",
            "content": "Test content for RAG",
            "dataType": "string",
        }

        normalized = normalize_asset(asset)

        assert normalized["id"] == "test.table"
        assert normalized["sourceSystem"] == "zipline"
        assert normalized["entityType"] == "column"
        assert normalized["entityName"] == "Test Column"
        assert normalized["entityPath"] == "db.schema.table.column"
        assert normalized["description"] == "Test description"
        assert normalized["businessMeaning"] == "Test business meaning"
        assert normalized["domain"] == "Test Domain"
        assert normalized["content"] == "Test content for RAG"
        assert normalized["dataType"] == "string"


class TestHashing:
    """Tests for SHA-256 hashing."""

    def test_identical_assets_produce_same_hash(self):
        """Identical assets should always produce the same hash."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Customer Data",
            "entityPath": "db.schema.customer",
            "description": "Contains customer information",
            "businessMeaning": "Primary customer records",
            "domain": "CRM",
            "content": "Customer table with name, email, phone",
            "tags": ["customer", "sales"],
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Customer Data",
            "entityPath": "db.schema.customer",
            "description": "Contains customer information",
            "businessMeaning": "Primary customer records",
            "domain": "CRM",
            "content": "Customer table with name, email, phone",
            "tags": ["customer", "sales"],
        }

        hash1 = compute_asset_hash(asset1)
        hash2 = compute_asset_hash(asset2)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 is 64 hex characters

    def test_reordered_tags_produce_same_hash(self):
        """Different tag ordering should not affect the hash."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": ["analytics", "customer", "sales"],
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": ["sales", "analytics", "customer"],
        }

        hash1 = compute_asset_hash(asset1)
        hash2 = compute_asset_hash(asset2)

        assert hash1 == hash2

    def test_different_timestamp_produces_same_hash(self):
        """Different lastUpdated timestamps should not affect the hash."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "lastUpdated": "2026-01-20T10:00:00Z",
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "lastUpdated": "2026-01-24T14:00:00Z",
        }

        hash1 = compute_asset_hash(asset1)
        hash2 = compute_asset_hash(asset2)

        assert hash1 == hash2

    def test_different_scan_id_produces_same_hash(self):
        """Different scanIds should not affect the hash."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "scanId": "scan-2026-01-20-abc",
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "scanId": "scan-2026-01-24-def",
        }

        hash1 = compute_asset_hash(asset1)
        hash2 = compute_asset_hash(asset2)

        assert hash1 == hash2

    def test_material_content_change_produces_different_hash(self):
        """A change in material content should produce a different hash."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Customer Data",
            "entityPath": "db.schema.customer",
            "description": "Contains customer information",
            "businessMeaning": "Primary customer records",
            "domain": "CRM",
            "content": "Customer table with name, email, phone",
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Customer Data",
            "entityPath": "db.schema.customer",
            "description": "Contains customer information and purchase history",  # Changed
            "businessMeaning": "Primary customer records",
            "domain": "CRM",
            "content": "Customer table with name, email, phone",
        }

        hash1 = compute_asset_hash(asset1)
        hash2 = compute_asset_hash(asset2)

        assert hash1 != hash2

    def test_business_meaning_change_produces_different_hash(self):
        """A change in businessMeaning should produce a different hash."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Sales records only",
            "domain": "Test",
            "content": "Test",
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Sales and inventory records",
            "domain": "Test",
            "content": "Test",
        }

        hash1 = compute_asset_hash(asset1)
        hash2 = compute_asset_hash(asset2)

        assert hash1 != hash2

    def test_content_change_produces_different_hash(self):
        """A change in the content field should produce a different hash."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Original content for semantic indexing",
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Updated content with additional information",
        }

        hash1 = compute_asset_hash(asset1)
        hash2 = compute_asset_hash(asset2)

        assert hash1 != hash2

    def test_new_tag_produces_different_hash(self):
        """Adding a new tag should produce a different hash."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": ["sales", "customer"],
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": ["sales", "customer", "analytics"],
        }

        hash1 = compute_asset_hash(asset1)
        hash2 = compute_asset_hash(asset2)

        assert hash1 != hash2

    def test_entity_id_change_produces_different_hash(self):
        """Changing the entity id should produce a different hash."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
        }

        asset2 = {
            "id": "test.table.v2",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
        }

        hash1 = compute_asset_hash(asset1)
        hash2 = compute_asset_hash(asset2)

        assert hash1 != hash2

    def test_hash_is_lowercase_hex(self):
        """Hash should be lowercase hexadecimal."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
        }

        hash_value = compute_asset_hash(asset)

        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

    def test_are_assets_equal_by_hash_true(self):
        """are_assets_equal_by_hash should return True for identical assets."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
        }

        assert are_assets_equal_by_hash(asset1, asset2)

    def test_are_assets_equal_by_hash_false(self):
        """are_assets_equal_by_hash should return False for different assets."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test Updated",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
        }

        assert not are_assets_equal_by_hash(asset1, asset2)

    def test_are_assets_equal_by_hash_ignores_volatile_fields(self):
        """are_assets_equal_by_hash should ignore volatile fields."""
        asset1 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "lastUpdated": "2026-01-20T10:00:00Z",
        }

        asset2 = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "lastUpdated": "2026-01-24T14:00:00Z",
        }

        assert are_assets_equal_by_hash(asset1, asset2)


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_complex_asset_with_all_fields(self):
        """Should handle complex assets with all material fields."""
        asset = {
            "id": "synergy.student.enrollment.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Student Enrollment",
            "entityPath": "database.schema.enrollment",
            "description": "Records of student course enrollment",
            "businessMeaning": "Primary source of truth for student course registrations",
            "domain": "Student Information",
            "content": "Enrollment records with student ID, course code, term, grade",
            "tags": ["academic", "student", "enrollment"],
            "dataType": "table",
            "columns": [
                {"name": "student_id", "type": "int", "nullable": False},
                {"name": "course_code", "type": "string", "nullable": False},
                {"name": "term", "type": "date", "nullable": False},
                {"name": "grade", "type": "string", "nullable": True},
            ],
            "relationships": [
                {"id": "rel.student", "type": "foreign_key"},
                {"id": "rel.course", "type": "foreign_key"},
            ],
            "lastUpdated": "2026-01-24T10:00:00Z",
            "scanId": "scan-abc123",
        }

        hash_value = compute_asset_hash(asset)

        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

    def test_get_asset_hash_components(self):
        """get_asset_hash_components should return normalized form."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": ["z", "a"],
            "lastUpdated": "2026-01-24T10:00:00Z",
        }

        components = get_asset_hash_components(asset)

        assert "lastUpdated" not in components
        assert components["tags"] == ["a", "z"]
        assert components["id"] == "test.table"

    def test_empty_tags_handled(self):
        """Empty tags array should be handled correctly."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": [],
        }

        normalized = normalize_asset(asset)

        assert normalized["tags"] == []

    def test_single_field_asset(self):
        """Should handle minimal assets with only required fields."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
        }

        hash_value = compute_asset_hash(asset)

        assert len(hash_value) == 64

    def test_normalize_error_on_invalid_tags_type(self):
        """Should raise TypeError if tags is not a list."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": "invalid_string",
        }

        with pytest.raises(TypeError):
            normalize_asset(asset)

    def test_normalize_error_on_invalid_columns_type(self):
        """Should raise TypeError if columns is not a list."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "columns": "invalid_string",
        }

        with pytest.raises(TypeError):
            normalize_asset(asset)

    def test_normalize_error_on_column_without_name(self):
        """Should raise ValueError if column lacks name field."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "columns": [{"type": "string"}],  # Missing name
        }

        with pytest.raises(ValueError):
            normalize_asset(asset)

    def test_normalize_error_on_relationship_without_id(self):
        """Should raise ValueError if relationship lacks id field."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "relationships": [{"type": "parent"}],  # Missing id
        }

        with pytest.raises(ValueError):
            normalize_asset(asset)


class TestConsistency:
    """Tests for consistency and determinism."""

    def test_hash_is_deterministic(self):
        """Hash of same asset computed multiple times should be identical."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
        }

        hashes = [compute_asset_hash(asset) for _ in range(5)]

        assert len(set(hashes)) == 1  # All hashes should be identical

    def test_normalization_is_deterministic(self):
        """Normalization of same asset multiple times should be identical."""
        asset = {
            "id": "test.table",
            "sourceSystem": "synergy",
            "entityType": "table",
            "entityName": "Test",
            "entityPath": "path",
            "description": "Test",
            "businessMeaning": "Test",
            "domain": "Test",
            "content": "Test",
            "tags": ["z", "a", "m"],
        }

        normalized_list = [normalize_asset(asset) for _ in range(5)]

        for norm in normalized_list:
            assert norm["tags"] == ["a", "m", "z"]

        # All normalizations should produce identical results
        for i in range(1, len(normalized_list)):
            assert normalized_list[0] == normalized_list[i]
