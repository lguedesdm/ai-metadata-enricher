"""
Indexing validation module for AI Metadata Enricher.

Provides deterministic integration validation for the element-level
ingestion pipeline.

Public API:
    - DeterministicRunner: Executes the full pipeline with in-memory mocks.
    - IntegrationValidator: Validates deterministic pipeline behaviour.
    - PipelineResult: Immutable result of a single pipeline execution.
    - ElementResult: Immutable result of processing a single element.
"""

from .deterministic_runner import DeterministicRunner, PipelineResult, ElementResult
from .integration_validator import IntegrationValidator

__all__ = [
    "DeterministicRunner",
    "IntegrationValidator",
    "PipelineResult",
    "ElementResult",
]
