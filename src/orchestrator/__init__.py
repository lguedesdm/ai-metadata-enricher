"""
Orchestrator module for the AI Metadata Enricher.

Minimal structural orchestrator that consumes messages from Azure Service Bus,
executes domain-level decision logic (SKIP/REPROCESS), and logs results.

This module does NOT:
- Call Azure OpenAI or any LLM
- Query Azure AI Search
- Generate embeddings
- Write to Purview or Cosmos DB
- Expose any HTTP endpoints
"""
