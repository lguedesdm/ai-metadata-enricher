"""
Deterministic ranking for RAG context chunks.

Implements a composite scoring algorithm that considers:
1. Relevance score (from Azure AI Search)
2. Source weight (configurable per source system)
3. Freshness (recency of the document)

The ranking is fully deterministic: same inputs always produce
the same ordering. Ties are broken by document_id for stability.

No I/O, no side effects, no external dependencies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Sequence

from .models import ContextChunk

logger = logging.getLogger("enrichment.rag.ranking")

# Reference date for freshness calculation.
# Documents newer than this get a positive freshness boost;
# older documents get a reduced boost.
# Using a fixed reference avoids time-dependent ranking changes
# within the same pipeline invocation.
_FRESHNESS_HALFLIFE_DAYS = 90.0


def compute_composite_scores(
    chunks: Sequence[ContextChunk],
    source_weights: dict[str, float],
    freshness_weight: float,
    reference_time: datetime | None = None,
) -> list[ContextChunk]:
    """Compute deterministic composite scores and return re-ranked chunks.

    The composite score formula is:

        composite = relevance * source_weight * (1 + freshness_weight * freshness_factor)

    Where:
        - relevance: normalized search score (0.0–1.0 range, from reranker if available)
        - source_weight: configurable weight per source system (default 1.0)
        - freshness_factor: exponential decay based on document age
          (1.0 for brand-new, approaching 0.0 for very old documents)

    Ties in composite score are broken by document_id (lexicographic ascending)
    to guarantee deterministic ordering.

    Args:
        chunks: Sequence of ContextChunk objects with relevance_score populated.
        source_weights: Mapping of source system name to weight multiplier.
        freshness_weight: Weight factor for freshness (0.0 to 1.0).
        reference_time: Reference datetime for freshness calculation.
            Defaults to current UTC time. Callers can fix this for
            deterministic testing.

    Returns:
        New list of ContextChunk objects with composite_score set,
        sorted in descending order of composite_score, with ties
        broken by document_id ascending.
    """
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)

    scored: list[ContextChunk] = []

    for chunk in chunks:
        relevance = _get_effective_relevance(chunk)
        sw = source_weights.get(chunk.source_system, 1.0)
        ff = _compute_freshness_factor(chunk.last_updated, reference_time)

        composite = relevance * sw * (1.0 + freshness_weight * ff)

        # Create new frozen dataclass instance with composite_score set
        scored_chunk = ContextChunk(
            document_id=chunk.document_id,
            source_system=chunk.source_system,
            entity_type=chunk.entity_type,
            entity_name=chunk.entity_name,
            entity_path=chunk.entity_path,
            content=chunk.content,
            description=chunk.description,
            business_meaning=chunk.business_meaning,
            domain=chunk.domain,
            tags=chunk.tags,
            data_type=chunk.data_type,
            source_table=chunk.source_table,
            ceds_reference=chunk.ceds_reference,
            last_updated=chunk.last_updated,
            relevance_score=chunk.relevance_score,
            reranker_score=chunk.reranker_score,
            composite_score=round(composite, 8),
        )
        scored.append(scored_chunk)

    # Sort: descending composite_score, then ascending document_id for ties
    scored.sort(key=lambda c: (-c.composite_score, c.document_id))

    logger.debug(
        "Ranking computed for %d chunks",
        len(scored),
        extra={
            "chunkCount": len(scored),
            "topScore": scored[0].composite_score if scored else 0.0,
        },
    )

    return scored


def _get_effective_relevance(chunk: ContextChunk) -> float:
    """Get the effective relevance score for a chunk.

    Prefers the semantic reranker score if available, as it provides
    more accurate relevance assessment. Falls back to the base
    relevance score from keyword/vector search.

    Returns a value in [0.0, 1.0] range.
    """
    if chunk.reranker_score is not None and chunk.reranker_score > 0.0:
        # Semantic reranker scores are typically 0–4 range;
        # normalize to 0–1 by dividing by 4.
        return min(chunk.reranker_score / 4.0, 1.0)
    # Base search scores are already in a usable range.
    # Clamp to [0.0, 1.0] for safety.
    return max(0.0, min(chunk.relevance_score, 1.0))


def _compute_freshness_factor(
    last_updated: datetime | None,
    reference_time: datetime,
) -> float:
    """Compute an exponential decay freshness factor.

    Returns a value in [0.0, 1.0]:
    - 1.0 for documents updated at or after reference_time
    - Decaying towards 0.0 for older documents
    - Half-life is _FRESHNESS_HALFLIFE_DAYS (90 days by default)

    Documents without a timestamp receive a neutral factor of 0.5.
    """
    if last_updated is None:
        return 0.5

    # Ensure timezone-aware comparison
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    age_seconds = (reference_time - last_updated).total_seconds()

    if age_seconds <= 0:
        return 1.0

    age_days = age_seconds / 86400.0
    # Exponential decay: factor = 2^(-age_days / halflife)
    import math
    factor = math.pow(2.0, -age_days / _FRESHNESS_HALFLIFE_DAYS)

    return max(0.0, min(factor, 1.0))
