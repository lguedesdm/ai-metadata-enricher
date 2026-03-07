"""
Enrichment LLM sub-package.

Provides prompt construction utilities for the metadata enrichment pipeline.
The AzureOpenAIClient remains in src/enrichment/llm_client.py (inert module).
"""

from .prompt_builder import build_llm_messages

__all__ = ["build_llm_messages"]
