"""
Context assembly for the RAG Query Pipeline.

Assembles ranked ContextChunks into a formatted string compatible with
the frozen prompt contracts:
- ``v1-suggested-description.prompt.md`` expects ``{{retrieved_context}}``
- ``v1-metadata-enrichment.prompt.yaml`` expects RAG Context in the
  instruction prompt

The assembled context format is deterministic: same ranked chunks
always produce the identical formatted string.

No I/O, no side effects, no external dependencies.
"""

from __future__ import annotations

import logging
from typing import Sequence

from .models import ContextChunk, RetrievedContext

logger = logging.getLogger("enrichment.rag.context_assembly")


def assemble_context(
    query: str,
    ranked_chunks: Sequence[ContextChunk],
    max_context_chars: int,
    total_results_found: int,
    search_metadata: dict | None = None,
) -> RetrievedContext:
    """Assemble ranked chunks into a structured RetrievedContext.

    Iterates over ranked chunks in order, formatting each into a text
    block and appending until the character budget is exhausted. The
    output ``formatted_context`` is a deterministic string ready for
    injection into the frozen prompt template placeholder
    ``{{retrieved_context}}``.

    Format per chunk (compatible with the frozen prompt's expected
    "text excerpts retrieved from Azure AI Search"):

        [Source N] <elementName> (<elementType>, <sourceSystem>)
        Source: <source>
        Title: <title>
        Content: <content>
        Description: <description>
        Suggested Description: <suggestedDescription>

    This format provides the LLM with structured, traceable excerpts
    that satisfy the grounding rules (C003, C004, C006) and enable
    the ``used_sources`` field in the output contract.

    Args:
        query: The original query string.
        ranked_chunks: Chunks sorted by composite_score descending.
        max_context_chars: Maximum total characters for the formatted context.
        total_results_found: Total number of search results before filtering.
        search_metadata: Optional metadata about the search operation.

    Returns:
        RetrievedContext with formatted_context ready for prompt injection.
    """
    if search_metadata is None:
        search_metadata = {}

    included_chunks: list[ContextChunk] = []
    formatted_blocks: list[str] = []
    current_length = 0

    for chunk in ranked_chunks:
        block = _format_chunk(chunk, len(included_chunks) + 1)
        block_length = len(block)

        # Check if adding this block would exceed the budget
        if current_length + block_length > max_context_chars:
            # If we haven't included any chunks yet, include at least
            # a truncated version of the first one
            if not included_chunks:
                truncated = block[: max_context_chars]
                formatted_blocks.append(truncated)
                included_chunks.append(chunk)
                current_length += len(truncated)
            break

        formatted_blocks.append(block)
        included_chunks.append(chunk)
        current_length += block_length

    formatted_context = "\n\n".join(formatted_blocks)

    result = RetrievedContext(
        query=query,
        chunks=tuple(included_chunks),
        formatted_context=formatted_context,
        total_results_found=total_results_found,
        results_used=len(included_chunks),
        search_metadata=search_metadata,
    )

    logger.info(
        "Context assembled: %d chunks, %d chars",
        result.results_used,
        len(result.formatted_context),
        extra={
            "query": query,
            "totalFound": total_results_found,
            "resultsUsed": result.results_used,
            "contextLength": len(result.formatted_context),
            "sourceSystems": list(result.source_systems_used),
        },
    )

    return result


def _format_chunk(chunk: ContextChunk, index: int) -> str:
    """Format a single ContextChunk into a text block for prompt injection.

    The format is designed to be:
    1. Human-readable for the LLM to parse
    2. Structured enough for source citation (used_sources field)
    3. Traceable back to the search index document

    Args:
        chunk: The context chunk to format.
        index: 1-based index for source numbering.

    Returns:
        Formatted text block string.
    """
    lines = [
        f"[Source {index}] {chunk.element_name} ({chunk.element_type}, {chunk.source_system})"
    ]

    lines.append(f"Document ID: {chunk.document_id}")

    if chunk.source:
        lines.append(f"Source: {chunk.source}")

    if chunk.title:
        lines.append(f"Title: {chunk.title}")

    if chunk.content:
        lines.append(f"Content: {chunk.content}")

    if chunk.description:
        lines.append(f"Description: {chunk.description}")

    if chunk.suggested_description:
        lines.append(f"Suggested Description: {chunk.suggested_description}")

    if chunk.tags:
        lines.append(f"Tags: {', '.join(chunk.tags)}")

    if chunk.ceds_link:
        lines.append(f"CEDS Link: {chunk.ceds_link}")

    return "\n".join(lines)
