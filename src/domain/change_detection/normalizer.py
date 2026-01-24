"""
Normalization module for asset metadata change detection.

Provides deterministic normalization of asset metadata, removing volatile fields
and sorting collections to ensure identical logical assets produce identical
canonical representations.
"""

from typing import Any, Dict, List, Optional
from copy import deepcopy


# Material fields that are included in change detection
MATERIAL_FIELDS = {
    "id",
    "sourceSystem",
    "entityType",
    "entityName",
    "entityPath",
    "description",
    "businessMeaning",
    "domain",
    "tags",
    "content",
    "relationships",
    "columns",
    "dataType",
}

# Fields to exclude from change detection (volatile or infrastructure-related)
VOLATILE_FIELDS = {
    "lastUpdated",
    "schemaVersion",
    "auditInfo",
    "scanId",
    "ingestionTime",
}


def normalize_asset(asset: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize an asset by removing volatile fields and sorting collections
    deterministically.

    This function produces a canonical representation of an asset that is
    suitable for deterministic hashing. It:
    - Removes all non-material and volatile fields
    - Sorts all collections deterministically
    - Returns a clean dictionary with fields in canonical order

    Args:
        asset: The asset metadata dictionary to normalize

    Returns:
        A normalized dictionary containing only material fields, sorted
        deterministically, suitable for hashing

    Raises:
        TypeError: If asset is not a dictionary
    """
    if not isinstance(asset, dict):
        raise TypeError(f"Expected dict, got {type(asset).__name__}")

    normalized = {}

    # Extract material fields, maintaining their logical meaning
    for field in MATERIAL_FIELDS:
        if field not in asset:
            continue

        value = asset[field]

        # Skip None values or empty strings for non-required fields
        if value is None:
            continue

        # Special handling for collections
        if field == "tags":
            normalized[field] = _normalize_tags(value)
        elif field == "relationships":
            normalized[field] = _normalize_relationships(value)
        elif field == "columns":
            normalized[field] = _normalize_columns(value)
        else:
            # For scalar fields, include as-is
            normalized[field] = value

    return normalized


def _normalize_tags(tags: Any) -> List[str]:
    """
    Normalize tags by sorting them alphabetically.

    Args:
        tags: List of tag strings

    Returns:
        Sorted list of tags (case-insensitive sort)

    Raises:
        TypeError: If tags is not a list or if items are not strings
    """
    if not isinstance(tags, list):
        raise TypeError(f"Expected list for tags, got {type(tags).__name__}")

    # Validate all items are strings
    for i, tag in enumerate(tags):
        if not isinstance(tag, str):
            raise TypeError(f"Tag at index {i} is not a string: {type(tag).__name__}")

    # Sort case-insensitively but preserve original case
    return sorted(set(tags), key=str.lower)


def _normalize_relationships(relationships: Any) -> List[Dict[str, Any]]:
    """
    Normalize relationships by sorting them by id.

    Args:
        relationships: List of relationship dictionaries

    Returns:
        Sorted list of relationships (by id field)

    Raises:
        TypeError: If relationships is not a list
        ValueError: If a relationship lacks an 'id' field
    """
    if not isinstance(relationships, list):
        raise TypeError(
            f"Expected list for relationships, got {type(relationships).__name__}"
        )

    # Validate that each relationship has an id
    for i, rel in enumerate(relationships):
        if not isinstance(rel, dict):
            raise TypeError(f"Relationship at index {i} is not a dict")
        if "id" not in rel:
            raise ValueError(f"Relationship at index {i} lacks required 'id' field")

    # Sort by id, removing duplicates by id
    seen = set()
    unique_rels = []
    for rel in relationships:
        rel_id = rel["id"]
        if rel_id not in seen:
            seen.add(rel_id)
            unique_rels.append(rel)

    return sorted(unique_rels, key=lambda r: r["id"])


def _normalize_columns(columns: Any) -> List[Dict[str, Any]]:
    """
    Normalize columns by sorting them by name.

    Args:
        columns: List of column dictionaries

    Returns:
        Sorted list of columns (by name field)

    Raises:
        TypeError: If columns is not a list
        ValueError: If a column lacks a 'name' field
    """
    if not isinstance(columns, list):
        raise TypeError(f"Expected list for columns, got {type(columns).__name__}")

    # Validate that each column has a name
    for i, col in enumerate(columns):
        if not isinstance(col, dict):
            raise TypeError(f"Column at index {i} is not a dict")
        if "name" not in col:
            raise ValueError(f"Column at index {i} lacks required 'name' field")

    # Sort by name, removing duplicates by name
    seen = set()
    unique_cols = []
    for col in columns:
        col_name = col["name"]
        if col_name not in seen:
            seen.add(col_name)
            unique_cols.append(col)

    return sorted(unique_cols, key=lambda c: c["name"])


def is_volatile_field(field_name: str) -> bool:
    """
    Check if a field is considered volatile and should be excluded from
    change detection.

    Args:
        field_name: Name of the field to check

    Returns:
        True if the field is volatile, False otherwise
    """
    return field_name in VOLATILE_FIELDS or field_name.startswith("_")


def get_material_fields() -> frozenset:
    """
    Get the set of material fields that are included in change detection.

    Returns:
        Frozenset of material field names
    """
    return frozenset(MATERIAL_FIELDS)


def get_volatile_fields() -> frozenset:
    """
    Get the set of volatile fields that are excluded from change detection.

    Returns:
        Frozenset of volatile field names
    """
    return frozenset(VOLATILE_FIELDS)
