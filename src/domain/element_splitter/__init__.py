"""
Element splitter module for AI Metadata Enricher.

Transforms a Synergy or Zipline export JSON containing an ``elements[]``
array into a flat list of ``ContextElement`` domain objects.

Public API:
    - ContextElement: Immutable domain object representing one element.
    - split_elements(): Split a blob JSON into a list of ContextElement.
    - generate_element_id(): Deterministic identity for a ContextElement.
"""

from .models import ContextElement
from .splitter import split_elements
from .element_identity import generate_element_id

__all__ = [
    "ContextElement",
    "split_elements",
    "generate_element_id",
]
