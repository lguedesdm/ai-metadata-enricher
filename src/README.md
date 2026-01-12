# Source Code

⚠️ **CRITICAL: DEVELOPMENT PHASE PROTECTION**

**DO NOT START** development in this directory until **Phase 1** is 100% complete.

## Phase 1 Prerequisites (Must Complete First)

Before writing any code in `src/`, the following must be frozen and approved:

1. ✅ **JSON Schemas**: All contracts frozen and versioned
2. ✅ **Search Index Schema**: Cosmos DB partition strategy finalized
3. ✅ **System Prompts**: RAG and enrichment prompts finalized
4. ✅ **Cosmos DB Design**: Container, partition keys, indexing policy locked
5. ✅ **ADRs**: All architectural decisions documented and approved

**Why This Matters**: Starting code before schema freeze leads to:
- Massive refactoring when schemas change
- Reindexing entire Cosmos DB collections
- Breaking Search and RAG pipelines
- Invalidating content hashes
- Weeks of rework

---

## Purpose

The `src/` directory is reserved for:
- Application code (Azure Functions, services, utilities)
- Business logic and domain models
- API implementations
- Data access layers
- Shared libraries and modules

## Planned Structure

```
src/
├── functions/              # Azure Functions
│   ├── orchestration/     # Workflow orchestration functions
│   ├── enrichment/        # Metadata enrichment processors
│   └── api/               # HTTP-triggered API functions
├── services/              # Business logic services
├── models/                # Domain models and entities
├── common/                # Shared utilities and helpers
└── config/                # Application configuration
```

## Development Guidelines

### Code Standards
- Follow language-specific best practices (PEP 8 for Python, etc.)
- Write clean, maintainable, and testable code
- Include comprehensive documentation
- Implement proper error handling and logging

### Testing Requirements
- Unit tests for all business logic
- Integration tests for critical paths
- Test coverage minimum: 80%
- All tests must pass before merge

### Security Requirements
- **No hardcoded secrets or credentials** - EVER
- **Managed Identity for all Azure resources** - default authentication method
- **Input validation for all external data** - never trust user input
- **Proper authentication and authorization** - verify identity and permissions
- **Security scanning in CI/CD pipeline** - automated vulnerability detection

#### Authentication Pattern (Production)
```python
# ✅ CORRECT: Using Managed Identity (DefaultAzureCredential)
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

credential = DefaultAzureCredential()
blob_client = BlobServiceClient(
    account_url="https://mystorageaccount.blob.core.windows.net",
    credential=credential  # No connection string!
)

# ❌ WRONG: Connection strings or keys
blob_client = BlobServiceClient.from_connection_string(
    "DefaultEndpointsProtocol=https;AccountName=...;AccountKey=..."  # FORBIDDEN
)
```

#### Secrets in CI/CD Only
The ONLY acceptable use of secrets/credentials:
- GitHub Actions Service Principal for deploying infrastructure
- Bicep deployment authentication
- Never in application runtime

## Technology Stack

(To be determined based on project requirements)

Potential options:
- **Python**: Azure Functions with Python
- **C#**: .NET isolated functions
- **TypeScript/Node.js**: Node.js functions

## Getting Started

1. Review [Architecture Documentation](../docs/architecture.md)
2. Set up local development environment
3. Configure Azure Functions Core Tools
4. Run tests: `npm test` or `pytest`
5. Start local development: `func start`

---

Source code will be added as development progresses.
