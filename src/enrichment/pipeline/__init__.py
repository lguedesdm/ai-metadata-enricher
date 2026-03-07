"""
Enrichment Pipeline sub-package.

Provides the deterministic, single-asset enrichment execution pipeline
that integrates RAG retrieval, LLM invocation, validation, Purview
writeback, and state persistence.
"""

from .enrichment_pipeline import (
    EnrichmentPipelineResult,
    run_enrichment_pipeline,
)

__all__ = [
    "EnrichmentPipelineResult",
    "run_enrichment_pipeline",
]
