"""
SHA-256 hashing module for asset metadata change detection.

Provides deterministic SHA-256 hashing of normalized asset metadata to enable
change detection. Hashes are deterministic: identical logical assets always
produce identical hashes.
"""

import hashlib
import json
from typing import Any, Dict

from .normalizer import normalize_asset


def compute_asset_hash(asset: Dict[str, Any]) -> str:
    """
    Compute a deterministic SHA-256 hash of an asset's metadata.

    This function:
    1. Normalizes the asset (removes volatile fields, sorts collections)
    2. Serializes it deterministically as JSON
    3. Computes SHA-256 hash of the serialized representation
    4. Returns the hash as a lowercase hexadecimal string

    Identical logical assets will always produce identical hashes. Material
    changes to the asset will produce different hashes. Non-material changes
    (timestamps, ordering) will not affect the hash.

    Args:
        asset: The asset metadata dictionary to hash

    Returns:
        SHA-256 hash as a lowercase hexadecimal string (64 characters)

    Raises:
        TypeError: If asset is not a dictionary
        ValueError: If the asset cannot be serialized to JSON
    """
    if not isinstance(asset, dict):
        raise TypeError(f"Expected dict, got {type(asset).__name__}")

    # Normalize the asset
    normalized = normalize_asset(asset)

    # Serialize deterministically to JSON
    canonical_json = _to_canonical_json(normalized)

    # Compute SHA-256 hash
    hash_obj = hashlib.sha256(canonical_json.encode("utf-8"))
    return hash_obj.hexdigest()


def _to_canonical_json(obj: Any) -> str:
    """
    Serialize an object to canonical JSON representation.

    Canonical JSON has the following properties:
    - No whitespace (compact)
    - Keys are sorted alphabetically (for determinism)
    - Uses UTF-8 encoding
    - Separators are fixed (no spaces after comma or colon)

    Args:
        obj: The object to serialize

    Returns:
        Canonical JSON string

    Raises:
        TypeError: If the object contains non-JSON-serializable types
        ValueError: If serialization fails
    """
    try:
        return json.dumps(
            obj,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
            default=_json_encoder_default,
        )
    except (TypeError, ValueError) as e:
        raise ValueError(f"Failed to serialize to canonical JSON: {e}") from e


def _json_encoder_default(obj: Any) -> Any:
    """
    Custom JSON encoder for non-standard types.

    Args:
        obj: The object to encode

    Returns:
        A JSON-serializable representation

    Raises:
        TypeError: If the object type is not supported
    """
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def are_assets_equal_by_hash(asset1: Dict[str, Any], asset2: Dict[str, Any]) -> bool:
    """
    Check if two assets have the same material content by comparing their hashes.

    This is a convenience function for determining if two assets represent
    the same logical state.

    Args:
        asset1: First asset dictionary
        asset2: Second asset dictionary

    Returns:
        True if the hashes are equal (same logical content), False otherwise

    Raises:
        TypeError: If either asset is not a dictionary
    """
    hash1 = compute_asset_hash(asset1)
    hash2 = compute_asset_hash(asset2)
    return hash1 == hash2


def get_asset_hash_components(asset: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get the normalized components that will be hashed for an asset.

    This is useful for debugging and understanding what fields contribute
    to the hash. The returned dictionary is the normalized, canonical form
    that is serialized and hashed.

    Args:
        asset: The asset dictionary to analyze

    Returns:
        Dictionary containing the normalized, canonical form of the asset

    Raises:
        TypeError: If asset is not a dictionary
    """
    return normalize_asset(asset)
