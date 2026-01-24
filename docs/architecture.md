# AI Metadata Enricher - Architecture Overview

## Executive Summary

The AI Metadata Enricher is an event-driven, cloud-native platform built on Azure that provides intelligent metadata enrichment capabilities for enterprise content. Designed for public-sector and governed environments, it prioritizes security, auditability, and compliance while maintaining developer productivity.

## Architecture Principles

### 1. Event-Driven Architecture
- **Asynchronous Processing**: Decoupled components communicate via events
- **Scalability**: Automatic scaling based on workload
- **Resilience**: Fault isolation and retry mechanisms
- **Flexibility**: Easy to add new enrichment processors

### 2. Infrastructure as Code First
- All Azure resources defined in Bicep
- No manual portal configuration in production
- Version-controlled infrastructure changes
- Repeatable, auditable deployments

### 3. Security by Design
- Zero Trust network architecture
- Managed identities for Azure resource authentication
- Private endpoints for PaaS services
- Azure Key Vault for secrets management
- Encryption at rest and in transit

### 4. Developer-First Experience
- Clear contracts and schemas
- Local development capabilities
- Comprehensive documentation
- Automated testing and validation
- CI/CD pipelines

## High-Level Architecture

```
┌─────────────────┐
│   Data Source   │
│  (Blob Storage) │
└────────┬────────┘
         │ Upload Event
         ▼
┌─────────────────────┐
│   Event Grid        │
│  (Event Router)     │
└─────────┬───────────┘
          │
          ▼
┌──────────────────────┐
│  Azure Functions     │
│  (Orchestration)     │
└──────────┬───────────┘
           │
           ├──────────────┐
           │              │
           ▼              ▼
┌─────────────────┐  ┌──────────────────┐
│  AI Services    │  │  Custom ML       │
│  (Enrichment)   │  │  (Processing)    │
└────────┬────────┘  └────────┬─────────┘
         │                    │
         └──────────┬─────────┘
                    ▼
          ┌──────────────────┐
          │  Metadata Store  │
          │  (Cosmos DB)     │
          └──────────────────┘
```

## Component Architecture

### Ingestion Layer
- **Azure Blob Storage**: Stores source content
- **Event Grid**: Publishes blob creation events
- **Azure Functions**: Receives and validates incoming content

### Processing Layer
- **Orchestrator Functions**: Coordinates enrichment workflow
- **Enrichment Functions**: Parallel processing of metadata extraction
- **Azure Cognitive Services**: AI-powered content analysis
  - Computer Vision (image analysis)
  - Document Intelligence (text extraction)
  - Language Services (NLP, sentiment, entities)

### Storage Layer
- **Azure Cosmos DB**: Metadata and enrichment results
- **Azure Blob Storage**: Original content and artifacts
- **Azure SQL Database** (optional): Structured data storage

### Observability Layer
- **Application Insights**: Application telemetry and traces
- **Log Analytics**: Centralized logging
- **Azure Monitor**: Metrics, alerts, and dashboards

### Security Layer
- **Azure Key Vault**: Secrets, keys, and certificates
- **Managed Identity**: Passwordless authentication
- **Azure Policy**: Governance and compliance enforcement
- **Private Endpoints**: Network isolation

## Data Flow

### 1. Content Upload
```
User → Blob Storage → Event Grid → Validation Function
```

### 2. Metadata Extraction
```
Orchestrator → [Vision API, Document API, Language API] → Results Aggregation
```

### 3. Storage and Indexing
```
Aggregated Metadata → Cosmos DB → Search Index (optional)
```

### 4. Notification
```
Completion Event → Event Grid → Notification Function → User/System
```

## Scalability Considerations

- **Horizontal Scaling**: Azure Functions auto-scale based on queue depth
- **Partitioning**: Cosmos DB partitioned by tenant or content type
- **Throttling**: Implement rate limiting and backpressure
- **Caching**: Redis cache for frequently accessed metadata

## Resilience Patterns

- **Retry Logic**: Exponential backoff for transient failures
- **Circuit Breaker**: Prevent cascading failures
- **Dead Letter Queues**: Handle poison messages
- **Idempotency**: Safe to process messages multiple times

## Network Architecture

```
Internet
    │
    ▼
┌─────────────────┐
│  Azure Front    │
│  Door / APIM    │
└────────┬────────┘
         │
         ▼ (Private Link)
┌─────────────────────┐
│  Virtual Network    │
│  ┌───────────────┐  │
│  │  Function App │  │
│  │  (VNet Integ.)│  │
│  └───────┬───────┘  │
│          │          │
│          ▼          │
│  ┌───────────────┐  │
│  │ Private       │  │
│  │ Endpoints     │  │
│  │ (Storage, AI) │  │
│  └───────────────┘  │
└─────────────────────┘
```

## Deployment Architecture

### Environments
- **Development**: Shared or individual developer environments
- **Test**: Integration testing environment
- **Staging**: Production-like environment for validation
- **Production**: Live production workloads

### Regions
- **Primary**: East US (or region closest to data residency requirements)
- **Secondary**: West US (for disaster recovery)
- **Multi-Region**: For high availability requirements

## Technology Stack

### Compute
- Azure Functions (Python, C#, or Node.js)
- Azure Container Instances (for specialized workloads)

### AI/ML
- Azure Cognitive Services (Vision, Language, Document Intelligence)
- Azure Machine Learning (custom models)

### Data
- Azure Cosmos DB (NoSQL metadata)
- Azure Blob Storage (content storage)
- Azure SQL Database (relational data, if needed)

### Integration
- Azure Event Grid (event routing)
- Azure Service Bus (reliable messaging)
- Azure API Management (API gateway)

### Security
- Azure Key Vault
- Azure Active Directory
- Managed Identity

### Observability
- Application Insights
- Log Analytics
- Azure Monitor

## Design Patterns

**Note**: The following patterns are applied **pragmatically and selectively**, not as full enterprise implementations. Each pattern is used where it provides clear value without unnecessary complexity.

### Event Sourcing (Selective Application)
- State changes captured as events **where audit trail is required**
- Enables replay capabilities for compliance and debugging
- Event store as source of truth **for auditable operations only**
- Not applied globally - only for critical workflows requiring audit

### CQRS (Limited Scope)
- Separate read and write models **for performance-critical paths**
- Optimized queries for different use cases
- Applied to specific bounded contexts, not system-wide
- Read models optimized for Search and RAG scenarios

### Saga Pattern (Distributed Transactions)
- Distributed transaction management for multi-step workflows
- Compensating transactions for rollback scenarios
- Used for orchestration of AI enrichment pipelines
- Simplified implementation focused on idempotency and retry

**Architecture Philosophy**: Pragmatic over dogmatic. Patterns serve the system, not vice versa.

## Compliance and Governance

### Data Governance
- Data classification and labeling
- Data residency requirements enforced
- Retention policies automated
- GDPR, FedRAMP, and other compliance frameworks

### Audit and Logging
- All operations logged with correlation IDs
- Immutable audit logs
- Centralized log retention and analysis

### Access Control
- Role-Based Access Control (RBAC)
- Principle of least privilege
- Conditional Access policies
- Just-In-Time access for privileged operations

## Future Considerations

- **Multi-Tenancy**: Tenant isolation strategies
- **Global Distribution**: Active-active multi-region deployment
- **Real-Time Processing**: Stream processing with Azure Stream Analytics
- **Advanced AI**: Custom ML models for domain-specific enrichment

## Domain Change Detection (SHA-256)

To support deterministic, incremental behavior without coupling to infrastructure, the platform defines a pure domain module for change detection based on SHA-256 hashing:

- Deterministic normalization: removes volatile fields (timestamps, scan IDs, underscore-prefixed metadata) and sorts collections (tags by value, relationships by `id`, columns by `name`).
- Canonical serialization: normalized assets are serialized to compact JSON with sorted keys.
- SHA-256 hashing: the hash is computed from the canonical JSON and returned as lowercase hex.
- Material contract: documented fields included in hashing are defined in [src/domain/change_detection/asset_contract.md](src/domain/change_detection/asset_contract.md) and enforced by [src/domain/change_detection/normalizer.py](src/domain/change_detection/normalizer.py).

Scope boundaries:
- Domain-only: no Azure SDKs, storage, queues, or orchestrators.
- Deterministic: logically identical assets always produce identical hashes; material changes produce different hashes.
- Integration: higher layers (orchestrator/services) may compare current vs. stored hashes to decide re-indexing, without modifying this module.

References:
- Module overview and API: [src/domain/change_detection/README.md](src/domain/change_detection/README.md)
- Unit tests (determinism/materiality): [tests/test_change_detection.py](tests/test_change_detection.py)

## References

- [Azure Well-Architected Framework](https://learn.microsoft.com/en-us/azure/architecture/framework/)
- [Cloud Design Patterns](https://learn.microsoft.com/en-us/azure/architecture/patterns/)
- [Event-Driven Architecture](https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/event-driven)

---

**Document Version**: 1.0  
**Last Updated**: January 2026  
**Status**: Initial Draft
