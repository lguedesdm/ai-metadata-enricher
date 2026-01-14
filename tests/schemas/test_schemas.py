"""
Schema Validation Tests for Synergy and Zipline Export Schemas

This script validates that the JSON schemas are deterministic and enforce MVP constraints.

Requirements:
    pip install jsonschema

Usage:
    python test_schemas.py

Expected Output:
    PASS/FAIL messages for each test case
"""

import json
import os
from pathlib import Path
from jsonschema import validate, ValidationError, Draft202012Validator


# Determine paths relative to this script
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent
SCHEMAS_DIR = REPO_ROOT / "contracts" / "schemas"

SYNERGY_SCHEMA_PATH = SCHEMAS_DIR / "synergy-export.schema.json"
ZIPLINE_SCHEMA_PATH = SCHEMAS_DIR / "zipline-export.schema.json"


def load_schema(path):
    """Load a JSON schema from file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def test_schema_validation(schema_name, schema, valid_example, invalid_examples):
    """
    Test a schema with valid and invalid examples.
    
    Args:
        schema_name: Name of the schema being tested
        schema: JSON schema object
        valid_example: Valid JSON object that should pass validation
        invalid_examples: List of (description, invalid_json) tuples that should fail
    
    Returns:
        Number of failed tests
    """
    print(f"\n{'='*70}")
    print(f"Testing {schema_name}")
    print(f"{'='*70}\n")
    
    failures = 0
    
    # Create validator for Draft 2020-12
    validator = Draft202012Validator(schema)
    
    # Test 1: Valid example should pass
    print(f"Test 1: Valid example should PASS validation")
    try:
        validator.validate(valid_example)
        print("✓ PASS: Valid example accepted")
    except ValidationError as e:
        print(f"✗ FAIL: Valid example rejected: {e.message}")
        failures += 1
    
    # Test 2+: Invalid examples should fail
    for i, (description, invalid_example) in enumerate(invalid_examples, start=2):
        print(f"\nTest {i}: Invalid example ({description}) should FAIL validation")
        try:
            validator.validate(invalid_example)
            print(f"✗ FAIL: Invalid example accepted (should have been rejected)")
            failures += 1
        except ValidationError as e:
            print(f"✓ PASS: Invalid example rejected: {e.message}")
    
    return failures


def run_tests():
    """Run all schema validation tests."""
    print("="*70)
    print("JSON Schema Validation Test Suite")
    print("Testing Synergy and Zipline Export Schemas")
    print(f"JSON Schema Draft: 2020-12")
    print("="*70)
    
    total_failures = 0
    
    # Load schemas
    print("\nLoading schemas...")
    try:
        synergy_schema = load_schema(SYNERGY_SCHEMA_PATH)
        print(f"✓ Loaded: {SYNERGY_SCHEMA_PATH.name}")
    except Exception as e:
        print(f"✗ FAILED to load Synergy schema: {e}")
        return 1
    
    try:
        zipline_schema = load_schema(ZIPLINE_SCHEMA_PATH)
        print(f"✓ Loaded: {ZIPLINE_SCHEMA_PATH.name}")
    except Exception as e:
        print(f"✗ FAILED to load Zipline schema: {e}")
        return 1
    
    # =========================================================================
    # SYNERGY TESTS
    # =========================================================================
    
    # Valid Synergy example (minimal MVP fields)
    synergy_valid = {
        "id": "synergy.test.table",
        "sourceSystem": "synergy",
        "entityType": "table",
        "entityName": "Test Table",
        "entityPath": "synergy.test.table",
        "content": "This is valid content for testing purposes.",
        "lastUpdated": "2026-01-14T10:00:00Z",
        "schemaVersion": "1.0.0"
    }
    
    # Invalid Synergy examples
    synergy_invalid = [
        (
            "missing required field 'id'",
            {
                "sourceSystem": "synergy",
                "entityType": "table",
                "entityName": "Test Table",
                "entityPath": "synergy.test.table",
                "content": "Content here",
                "lastUpdated": "2026-01-14T10:00:00Z",
                "schemaVersion": "1.0.0"
            }
        ),
        (
            "wrong sourceSystem value",
            {
                "id": "synergy.test.table",
                "sourceSystem": "zipline",  # Should be "synergy"
                "entityType": "table",
                "entityName": "Test Table",
                "entityPath": "synergy.test.table",
                "content": "Content here",
                "lastUpdated": "2026-01-14T10:00:00Z",
                "schemaVersion": "1.0.0"
            }
        ),
        (
            "invalid entityType value",
            {
                "id": "synergy.test.table",
                "sourceSystem": "synergy",
                "entityType": "invalid_type",  # Not in enum
                "entityName": "Test Table",
                "entityPath": "synergy.test.table",
                "content": "Content here",
                "lastUpdated": "2026-01-14T10:00:00Z",
                "schemaVersion": "1.0.0"
            }
        ),
        (
            "id with invalid characters",
            {
                "id": "synergy/test@table",  # Should match ^[a-zA-Z0-9._-]+$
                "sourceSystem": "synergy",
                "entityType": "table",
                "entityName": "Test Table",
                "entityPath": "synergy.test.table",
                "content": "Content here",
                "lastUpdated": "2026-01-14T10:00:00Z",
                "schemaVersion": "1.0.0"
            }
        ),
        (
            "invalid schemaVersion format",
            {
                "id": "synergy.test.table",
                "sourceSystem": "synergy",
                "entityType": "table",
                "entityName": "Test Table",
                "entityPath": "synergy.test.table",
                "content": "Content here",
                "lastUpdated": "2026-01-14T10:00:00Z",
                "schemaVersion": "v1.0"  # Should match \d+\.\d+\.\d+
            }
        )
    ]
    
    total_failures += test_schema_validation(
        "Synergy Export Schema",
        synergy_schema,
        synergy_valid,
        synergy_invalid
    )
    
    # =========================================================================
    # ZIPLINE TESTS
    # =========================================================================
    
    # Valid Zipline example (minimal MVP fields)
    zipline_valid = {
        "id": "zipline.assessment.results",
        "sourceSystem": "zipline",
        "entityType": "dataset",
        "entityName": "Assessment Results",
        "entityPath": "zipline.assessment.results",
        "content": "Assessment results dataset containing student performance data.",
        "lastUpdated": "2026-01-14T11:30:00Z",
        "schemaVersion": "1.0.0"
    }
    
    # Invalid Zipline examples
    zipline_invalid = [
        (
            "missing required field 'content'",
            {
                "id": "zipline.test.dataset",
                "sourceSystem": "zipline",
                "entityType": "dataset",
                "entityName": "Test Dataset",
                "entityPath": "zipline.test.dataset",
                "lastUpdated": "2026-01-14T11:30:00Z",
                "schemaVersion": "1.0.0"
            }
        ),
        (
            "wrong sourceSystem value",
            {
                "id": "zipline.test.dataset",
                "sourceSystem": "synergy",  # Should be "zipline"
                "entityType": "dataset",
                "entityName": "Test Dataset",
                "entityPath": "zipline.test.dataset",
                "content": "Content here",
                "lastUpdated": "2026-01-14T11:30:00Z",
                "schemaVersion": "1.0.0"
            }
        ),
        (
            "empty entityName (violates minLength)",
            {
                "id": "zipline.test.dataset",
                "sourceSystem": "zipline",
                "entityType": "dataset",
                "entityName": "",  # minLength is 1
                "entityPath": "zipline.test.dataset",
                "content": "Content here",
                "lastUpdated": "2026-01-14T11:30:00Z",
                "schemaVersion": "1.0.0"
            }
        ),
        (
            "invalid date-time format",
            {
                "id": "zipline.test.dataset",
                "sourceSystem": "zipline",
                "entityType": "dataset",
                "entityName": "Test Dataset",
                "entityPath": "zipline.test.dataset",
                "content": "Content here",
                "lastUpdated": "2026-01-14",  # Should be ISO 8601 date-time
                "schemaVersion": "1.0.0"
            }
        )
    ]
    
    total_failures += test_schema_validation(
        "Zipline Export Schema",
        zipline_schema,
        zipline_valid,
        zipline_invalid
    )
    
    # =========================================================================
    # SUMMARY
    # =========================================================================
    
    print(f"\n{'='*70}")
    print(f"Test Summary")
    print(f"{'='*70}")
    print(f"Total test failures: {total_failures}")
    
    if total_failures == 0:
        print("\n✓ ALL TESTS PASSED")
        print("\nConclusion:")
        print("  - Schemas are deterministic and enforce MVP constraints")
        print("  - Required fields are validated correctly")
        print("  - Pattern matching, enums, and const values work as expected")
        print("  - Invalid data is rejected as expected")
        return 0
    else:
        print(f"\n✗ {total_failures} TESTS FAILED")
        return 1


if __name__ == "__main__":
    exit_code = run_tests()
    exit(exit_code)
