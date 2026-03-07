"""
Search Document Builder module for AI Metadata Enricher.

Transforms a ``ContextElement`` into a flat dictionary aligned with the
deployed Azure AI Search index schema (metadata-context-index-v1).

Public API:
    - build_search_document(): ContextElement → search document dict.
    - SCHEMA_FIELDS: Frozen set of permitted document field names.
    - MAX_CONTENT_LENGTH: Safe upper bound for the content field.
"""

from .builder import build_search_document
from .models import (
    MAX_CONTENT_LENGTH,
    SCHEMA_FIELDS,
)

__all__ = [
    "build_search_document",
    "MAX_CONTENT_LENGTH",
    "SCHEMA_FIELDS",
]
