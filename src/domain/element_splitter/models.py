"""
Domain model for an individual context element.

``ContextElement`` is a frozen (immutable) dataclass that carries the
minimal set of fields the downstream pipeline requires.  It holds a
*copy* of the original element dict so that later stages can access
the full payload without mutating the source JSON.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class ContextElement:
    """Immutable domain representation of one element from an export JSON.

    Attributes:
        source_system: Origin system identifier (e.g. ``"synergy"``, ``"zipline"``).
        element_name: Human-readable name of the element (``entityName``).
        element_type: Entity classification (``entityType``).
        description: Technical description from the source system.
        raw_payload: Deep copy of the original element dictionary.
    """

    source_system: str
    element_name: str
    element_type: str
    description: str
    raw_payload: Dict[str, Any] = field(repr=False)
