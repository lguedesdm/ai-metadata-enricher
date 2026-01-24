"""
Change detection module for AI Metadata Enricher.

This module provides deterministic SHA-256 hashing of asset metadata to
enable change detection. It normalizes assets by removing volatile fields
and sorting collections, ensuring identical logical assets produce identical
hashes.

Public API:
    - compute_asset_hash(): Compute SHA-256 hash of normalized asset metadata
    - are_assets_equal_by_hash(): Compare two assets by their material content
    - normalize_asset(): Normalize an asset for hashing
    - get_asset_hash_components(): Get normalized form for debugging
"""

from .hasher import (
    compute_asset_hash,
    are_assets_equal_by_hash,
    get_asset_hash_components,
)
from .normalizer import (
    normalize_asset,
    get_material_fields,
    get_volatile_fields,
    is_volatile_field,
)

__all__ = [
    "compute_asset_hash",
    "are_assets_equal_by_hash",
    "get_asset_hash_components",
    "normalize_asset",
    "get_material_fields",
    "get_volatile_fields",
    "is_volatile_field",
]
