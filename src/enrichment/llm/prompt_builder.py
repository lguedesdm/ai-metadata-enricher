"""
Prompt Builder — Constructs LLM message list from frozen prompt contracts.

Reads the frozen prompt contract (v1-metadata-enrichment.prompt.yaml) to
assemble the system and user messages passed to AzureOpenAIClient.complete().

Frozen contracts referenced:
  contracts/prompts/v1-metadata-enrichment.prompt.yaml  — system + instruction
  contracts/outputs/v1-metadata-enrichment.output.yaml  — YAML output structure

This module does NOT:
- Invoke any LLM or AI service
- Write to Purview or Cosmos DB
- Modify frozen contract files
- Perform validation

Output format instruction is inline per contract guidance:
  "Combine system_prompt, instruction_prompt, and constraints into a single
   prompt payload. Append the specific asset metadata and RAG context as
   variables. Enforce the output format contract through response parsing."
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("enrichment.llm.prompt_builder")

# ---------------------------------------------------------------------------
# Contract paths (relative to repository root)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[4]
_PROMPT_CONTRACT_PATH = (
    _REPO_ROOT / "contracts" / "prompts" / "v1-metadata-enrichment.prompt.yaml"
)

# ---------------------------------------------------------------------------
# Lazy contract loader (reads once, cached at module level)
# ---------------------------------------------------------------------------

_CONTRACT_CACHE: Dict[str, str] | None = None


def _load_prompt_contract() -> Dict[str, str]:
    """Load the frozen prompt contract YAML and cache it.

    Returns a dict with keys: system_prompt, instruction_prompt.

    Falls back to embedded minimal prompts if the contract file cannot be
    read — this preserves pipeline function under test isolation without
    the full repository structure.
    """
    global _CONTRACT_CACHE
    if _CONTRACT_CACHE is not None:
        return _CONTRACT_CACHE

    try:
        import yaml  # type: ignore[import-untyped]

        with open(_PROMPT_CONTRACT_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)

        _CONTRACT_CACHE = {
            "system_prompt": raw.get("system_prompt", "").strip(),
            "instruction_prompt": raw.get("instruction_prompt", "").strip(),
        }
        logger.debug(
            "Loaded prompt contract",
            extra={"contractPath": str(_PROMPT_CONTRACT_PATH)},
        )
    except Exception as exc:
        logger.warning(
            "Could not load prompt contract from disk (%s); using fallback.",
            exc,
        )
        _CONTRACT_CACHE = {
            "system_prompt": (
                "You are a Metadata Enrichment Assistant operating within a "
                "governed, enterprise-grade AI platform. "
                "Ground ALL suggestions strictly in the context provided to you. "
                "Output ONLY valid YAML conforming to the required structure."
            ),
            "instruction_prompt": (
                "Suggest a metadata description for the given asset using ONLY "
                "the provided asset metadata and retrieved context. "
                "If inputs are insufficient, set confidence to 'low' and add warnings."
            ),
        }

    return _CONTRACT_CACHE


# ---------------------------------------------------------------------------
# Output format instruction (derived from frozen output contract v1.0.0)
# ---------------------------------------------------------------------------

_OUTPUT_FORMAT_INSTRUCTION = """\
REQUIRED OUTPUT FORMAT — output ONLY the following YAML, no other text:

suggested_description: "<concise, plain-language description of the asset>"
confidence: <low|medium|high>
used_sources:
  - "<excerpt or identifier from the retrieved context>"
warnings: []
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_llm_messages(
    asset: Dict[str, Any],
    entity_type: str,
    formatted_context: str,
) -> List[Dict[str, str]]:
    """Build the message list for AzureOpenAIClient.complete().

    Assembles:
      1. System message  — from frozen prompt contract (system_prompt +
                           instruction_prompt) as a single system role.
      2. User message    — asset metadata (JSON) + retrieved context +
                           output format specification.

    This function is deterministic: the same inputs always produce the
    same messages list.

    Args:
        asset:             Full asset metadata dictionary.
        entity_type:       Asset entity type (e.g. "table", "column").
        formatted_context: Assembled context string from RAGQueryPipeline.
                           Corresponds to the {{retrieved_context}} placeholder.

    Returns:
        List of message dicts compatible with openai.AzureOpenAI chat format.
    """
    contract = _load_prompt_contract()

    # System role: combines system_prompt and instruction_prompt per contract
    system_content = (
        contract["system_prompt"]
        + "\n\n"
        + contract["instruction_prompt"]
    )

    # Serialize asset metadata — strip internal volatile fields for the prompt
    asset_for_prompt = {
        k: v
        for k, v in asset.items()
        if k not in {"schemaVersion", "lastUpdated"}
    }
    asset_metadata_str = json.dumps(asset_for_prompt, indent=2, default=str)

    # User message: asset context + retrieved context + output format
    user_content = (
        f"Entity Type: {entity_type}\n\n"
        f"Asset Metadata:\n{asset_metadata_str}\n\n"
        f"Retrieved Context:\n{formatted_context}\n\n"
        f"{_OUTPUT_FORMAT_INSTRUCTION}"
    )

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

    logger.debug(
        "Built LLM messages",
        extra={
            "entityType": entity_type,
            "contextLength": len(formatted_context),
            "systemLength": len(system_content),
            "userLength": len(user_content),
        },
    )

    return messages
