"""
Enrichment layer — isolated runtime clients.

This package provides execution-layer adapters for:
- Azure OpenAI (LLM completions)
- Microsoft Purview (Suggested Description writes)

These clients are importable but NOT wired into orchestration.
They do not trigger any enrichment automatically.

Authentication: DefaultAzureCredential (Managed Identity) exclusively.
Configuration: Environment variables only — no secrets in code.
"""
