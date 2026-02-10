"""
Orchestrator module for the AI Metadata Enricher.

Consumes messages from Azure Service Bus, executes domain-level decision
logic (SKIP/REPROCESS), persists state and audit records to Cosmos DB,
and logs results.

All Azure resource access uses Managed Identity (DefaultAzureCredential):
- Azure Service Bus: message consumption
- Azure Cosmos DB: state and audit persistence

This module does NOT:
- Call Azure OpenAI or any LLM
- Query Azure AI Search
- Generate embeddings
- Write to Purview
- Expose any HTTP endpoints
- Use connection strings, keys, or secrets
"""
