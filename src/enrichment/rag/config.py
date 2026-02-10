"""
Configuration for the RAG Query Pipeline.

All configuration is sourced from environment variables.
No secrets are stored in code — authentication uses Managed Identity.

This configuration is independent of OrchestratorConfig and EnrichmentConfig.
It is consumed only by the RAG Query Pipeline.
"""

import os


class RAGConfig:
    """Immutable configuration for the RAG Query Pipeline, sourced from environment variables."""

    def __init__(self) -> None:
        # -----------------------------------------------------------------
        # Azure AI Search
        # -----------------------------------------------------------------
        # Fully qualified endpoint, e.g. "https://search-ai-metadata-dev.search.windows.net"
        self.search_endpoint: str = os.environ.get(
            "AZURE_SEARCH_ENDPOINT", ""
        )

        # Name of the Azure AI Search index (frozen v1 design)
        self.search_index_name: str = os.environ.get(
            "AZURE_SEARCH_INDEX_NAME", ""
        )

        # Semantic configuration name defined in the index
        self.semantic_configuration_name: str = os.environ.get(
            "AZURE_SEARCH_SEMANTIC_CONFIG", "default"
        )

        # -----------------------------------------------------------------
        # Search Behavior
        # -----------------------------------------------------------------
        # Maximum number of results to retrieve from search
        self.max_results: int = int(
            os.environ.get("RAG_MAX_RESULTS", "10")
        )

        # Minimum relevance score threshold (0.0 to 1.0).
        # Results below this score are discarded.
        self.min_relevance_score: float = float(
            os.environ.get("RAG_MIN_RELEVANCE_SCORE", "0.0")
        )

        # -----------------------------------------------------------------
        # Source Weight Configuration
        # -----------------------------------------------------------------
        # Weights for deterministic ranking by source system.
        # Higher weight = higher priority when relevance scores are equal.
        # Format: comma-separated "source:weight" pairs.
        # Default weights: synergy=1.0, zipline=1.0, documentation=0.8
        self._source_weights_raw: str = os.environ.get(
            "RAG_SOURCE_WEIGHTS",
            "synergy:1.0,zipline:1.0,documentation:0.8"
        )

        # -----------------------------------------------------------------
        # Freshness Configuration
        # -----------------------------------------------------------------
        # Weight factor for freshness (recency) in ranking.
        # 0.0 = freshness has no effect; 1.0 = maximum freshness boost.
        self.freshness_weight: float = float(
            os.environ.get("RAG_FRESHNESS_WEIGHT", "0.1")
        )

        # -----------------------------------------------------------------
        # Context Assembly
        # -----------------------------------------------------------------
        # Maximum total character length for assembled context.
        # This is a CHARACTER limit, not a TOKEN limit.  The consumer
        # (enrichment flow / LLM caller) must set this value based on
        # the target model's context window after accounting for the
        # system prompt, instruction prompt, and asset_metadata.
        # Rule of thumb: 1 token ≈ 4 characters for English text.
        # Default 8 000 chars ≈ ~2 000 tokens.
        self.max_context_chars: int = int(
            os.environ.get("RAG_MAX_CONTEXT_CHARS", "8000")
        )

        # -----------------------------------------------------------------
        # Runtime
        # -----------------------------------------------------------------
        self.environment: str = os.environ.get("ENVIRONMENT", "dev")

    @property
    def source_weights(self) -> dict[str, float]:
        """Parse source weights from environment variable string.

        Format: "source1:weight1,source2:weight2"
        Returns a dict mapping source system names to their weight values.
        """
        weights: dict[str, float] = {}
        if not self._source_weights_raw.strip():
            return weights
        for pair in self._source_weights_raw.split(","):
            pair = pair.strip()
            if ":" not in pair:
                continue
            source, weight_str = pair.split(":", 1)
            source = source.strip()
            weight_str = weight_str.strip()
            if source and weight_str:
                try:
                    weights[source] = float(weight_str)
                except ValueError:
                    continue
        return weights

    def validate(self) -> None:
        """Raise ValueError if required configuration is incomplete."""
        if not self.search_endpoint:
            raise ValueError(
                "AZURE_SEARCH_ENDPOINT environment variable is required "
                "for RAG Query Pipeline initialization."
            )
        if not self.search_index_name:
            raise ValueError(
                "AZURE_SEARCH_INDEX_NAME environment variable is required "
                "for RAG Query Pipeline initialization."
            )
        if self.max_results < 1:
            raise ValueError(
                "RAG_MAX_RESULTS must be at least 1."
            )
        if not (0.0 <= self.min_relevance_score <= 1.0):
            raise ValueError(
                "RAG_MIN_RELEVANCE_SCORE must be between 0.0 and 1.0."
            )
        if not (0.0 <= self.freshness_weight <= 1.0):
            raise ValueError(
                "RAG_FRESHNESS_WEIGHT must be between 0.0 and 1.0."
            )
        if self.max_context_chars < 100:
            raise ValueError(
                "RAG_MAX_CONTEXT_CHARS must be at least 100."
            )
