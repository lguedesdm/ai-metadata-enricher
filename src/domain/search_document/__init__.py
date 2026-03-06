"""
Search Document Builder module for AI Metadata Enricher.

Transforms a ``ContextElement`` into a flat dictionary aligned with the
frozen Azure AI Search index schema (v1.1.0).

Public API:
    - build_search_document(): ContextElement → search document dict.
    - SCHEMA_FIELDS: Frozen set of permitted document field names.
    - SCHEMA_VERSION: Current schema version string.
    - MAX_CONTENT_LENGTH: Safe upper bound for the content field.
"""

from .builder import build_search_document
from .models import (
    MAX_CONTENT_LENGTH,
    SCHEMA_FIELDS,
    SCHEMA_VERSION,
)

__all__ = [
    "build_search_document",
    "MAX_CONTENT_LENGTH",
    "SCHEMA_FIELDS",
    "SCHEMA_VERSION",
]
