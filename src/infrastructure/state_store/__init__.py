"""
Element State Store module for AI Metadata Enricher.

Provides controlled, single-element state persistence after successful
search indexing operations.

Public API:
    - update_element_state(): Persist the processing state of one element.
    - STATE_RECORD_FIELDS: Frozen set of permitted state record fields.
"""

from .state_writer import update_element_state
from .models import STATE_RECORD_FIELDS

__all__ = [
    "update_element_state",
    "STATE_RECORD_FIELDS",
]
