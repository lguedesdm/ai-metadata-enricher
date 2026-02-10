"""
RAG Query Pipeline — Context Retrieval from Azure AI Search.

This package provides an isolated, deterministic context retrieval pipeline
for the AI Metadata Enrichment platform. It queries Azure AI Search using
hybrid search (keyword + semantic ranking) and assembles structured context
compatible with the frozen prompt contracts.

This module does NOT:
- Invoke any LLM or generate completions
- Write to Purview or modify any metadata
- Alter orchestration, domain logic, or validation
- Create or modify Azure AI Search indexes
- Generate embeddings
- Execute enrichment end-to-end

Authentication: DefaultAzureCredential (Managed Identity) exclusively.
Configuration: Environment variables only — no secrets in code.

Public API:
    - RAGQueryPipeline: Main pipeline class for context retrieval
    - RAGConfig: Configuration for the RAG pipeline
    - RetrievedContext: Structured context result
    - ContextChunk: Individual context chunk from search results
"""

from .config import RAGConfig
from .errors import RAGErrorCategory, RAGSearchError
from .models import ContextChunk, RetrievedContext
from .pipeline import RAGQueryPipeline

__all__ = [
    "RAGConfig",
    "RAGErrorCategory",
    "RAGQueryPipeline",
    "RAGSearchError",
    "RetrievedContext",
    "ContextChunk",
]
