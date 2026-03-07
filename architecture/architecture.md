# AI Metadata Enricher — Architecture Reference

> **Source:** LLM Metadata Architecture Document (Authoritative)
> **Status:** Canonical — all implementation must comply with this document
> **Version:** 1.0

---

## 1. Solution Objectives

1. Automate generation of business descriptions for Purview assets (tables, columns, datasets).
2. Use existing DOE documentation and vendor data dictionaries as AI context.
3. Integrate Synergy and Zipline definitions through standardized JSON exports.
4. Reduce manual effort in metadata curation while maintaining quality and accuracy.
5. Enable long-term governance through transparent audit trails, review workflows, and repeatable enrichment logic.

---

## 2. Decision Status Summary

| Item | Details | Confidence |
|---|---|---|
| Arch Pattern | JSON export to Blob → AI Search → Orchestrator | 100% |
| Trigger Model | Event-driven (after initial Purview scan) | 100% |
| Synergy Integration | JSON export to Blob Storage (primary context source) | 100% |
| Zipline Integration | JSON export to Blob Storage (no direct API) | 100% |
| Blob Storage | Central repository for all exports and docs | 100% |
| AI Search Role | Unified index for all context sources | 100% |
| CEDS Integration | MVP uses Synergy's CEDS mappings only | 100% |
| Search Type | Hybrid Search selected for MVP | 80% |
| Validation Strategy | Purview's native | 100% |

---

## 3. Architecture Overview

### 3.1 High-Level Data Flow

All external data sources export to Blob Storage, which is then indexed by Azure AI Search. The Enrichment Orchestrator queries only AI Search for unified context, reducing integration complexity.

Instead of the Orchestrator calling multiple APIs directly, external systems export JSON files to Blob Storage. AI Search indexes everything from Blob Storage, providing a unified search interface.

**Data Ingestion Flow (Background/Scheduled):**

1. Synergy Export: Data dictionary exported as JSON to Blob Storage
2. Zipline Export: Metadata definitions exported as JSON to Blob Storage
3. Documentation: Word, Excel, and other docs stored in Blob Storage
4. AI Search Indexing: Automatically indexes all content from Blob Storage

### 3.2 Trigger Mechanism (Event-Driven Architecture)

The enrichment process is initiated through Azure Event Grid integration:

- **Purview Configuration:** Purview emits events upon scan completion to Event Grid.
- **Event Routing:** Event Grid subscription filters events and routes them to Azure Service Bus Topic.
- **Orchestrator Consumption:** The Enrichment Orchestrator (Container App) listens to Service Bus and processes messages in controlled batches.

Benefits:
- Real-time: No polling delays, immediate processing after scan completion
- Scalable: Native Azure event routing handles high volumes
- Reliable: Event Grid provides at-least-once delivery guarantees
- Decoupled: Purview and Orchestrator remain independent

### 3.3 Enrichment Flow (Event-Driven)

1. **Trigger:** Event-driven activation after Purview scan completion
2. **Throttling and Batch Enrichment:** Container App processes messages in controlled batches (e.g., 50 assets/batch). Within each batch, enrichment requests to Azure OpenAI should group 5–20 assets per LLM call whenever possible.
3. **State Check:** Before generating descriptions, check Cosmos DB to verify if the asset has changed. If not, skip to reduce costs.
4. **Query Context:** Retrieve context from Azure AI Search (Hybrid Search).
5. **Generate:** Call Azure OpenAI.
6. **Write:** Write result to "Suggested Description" custom attribute in Purview.

### 3.4 State Store Schema (Cosmos DB)

State tracking uses Cosmos DB. The state document tracks metadata changes, enrichment history, confidence scoring, and audit events.

**Change Detection Logic:**

1. Fetch Current Metadata: Retrieve asset metadata from Purview
2. Calculate Hash: Compute SHA-256 hash of serialized metadata
3. Query State Store: Check Cosmos DB for existing record
4. Compare Hash:
   - No record exists → Proceed with enrichment (new asset)
   - Record exists AND hash matches → Skip enrichment (no change)
   - Record exists AND hash differs → Proceed with enrichment (metadata changed)
5. Update State: After successful enrichment, store new hash and enriched content

### 3.5 Component Inventory

| Component | Azure Service | Purpose | Status |
|---|---|---|---|
| Orchestrator | Container Apps | Central orchestration engine | Confirmed |
| Message Broker | Azure Service Bus | Handle load leveling | Confirmed |
| State Store / Audit | Azure Cosmos DB | Hashing + audit | Confirmed |
| AI Engine | Azure OpenAI | Generate descriptions | Confirmed |
| Unified Search Index | Azure AI Search | Index sources, unified queries | Confirmed |
| Central Repository | Blob Storage | Store JSON exports and docs | Confirmed |
| Data Catalog | Purview | Source/target metadata | Confirmed |
| Secrets | Azure Key Vault | Store API keys, secrets | Confirmed |
| Monitoring | App Insights | Logging, telemetry | Confirmed |

### 3.6 Enrichment Orchestrator

The Enrichment Orchestrator is the central processing engine. It is NOT an API to be consumed by external systems, but an internal service that orchestrates the enrichment workflow.

**What it IS:**
- An internal orchestration engine that coordinates the enrichment pipeline
- A consumer of Purview API (read/write metadata)
- A consumer of AI Search (unified context from all sources)
- A consumer of Azure Service Bus (retrieving scan events)
- A consumer of Azure Cosmos DB (checking asset state and logging audit)
- A consumer of Azure OpenAI (generate descriptions)

**What it is NOT:**
- NOT an API that exposes endpoints
- NOT a direct consumer of Synergy or Zipline APIs (uses AI Search instead)
- NOT responsible for indexing content (AI Search handles this)

**Simplified Workflow:**

1. Message Pickup: Monitor Service Bus queue for new enrichment tasks
2. Query AI Search for all relevant context
3. Build structured prompt with metadata + context
4. Call Azure OpenAI to generate enriched descriptions
5. Validate AI output
6. Write enriched metadata back to Purview

### 3.7 Error Handling, Retry Logic, and Dead-Letter Queues

- **Retry Policy:** Transient errors retried with exponential backoff. Maximum of 3 retries per asset.
- **Dead-Letter Queue (DLQ):** Messages that repeatedly fail moved to DLQ for manual inspection.
- **OpenAI Quota Protection:** Throttle requests based on actual TPM/TPD limits.
- **Fallback Behavior:** When LLM output fails validation, flag but do not submit to Purview.

### 3.8 Orchestrator Lifecycle, Message Locking, and Fault Tolerance

- **Peek-Lock Pattern:** Messages received under Peek-Lock contract. Only completed after Purview write succeeds, state store updated, validation and audit logging complete.
- **Failure Handling:** If container crashes mid-batch, uncompleted messages automatically reappear when lock expires.
- **Processing Model:** Process messages individually or in micro-batches. Long-running processing must renew message lock.

---

## 4. Data Sources and Integration

### 4.1 Microsoft Purview
- **Integration:** REST API (Apache Atlas endpoint)
- **Operations:** GET (retrieve assets), PATCH (update metadata)

### 4.2 Synergy
- JSON export to Blob Storage (primary context source)
- Data dictionary with descriptive information for metadata enrichment
- CEDS Mapping: Data mapped to Common Education Data Standards
- Integration: Export → Blob Storage → AI Search indexes → Orchestrator queries AI Search

### 4.3 CEDS
- CEDS definitions are not crawled or indexed directly
- MVP uses Synergy's CEDS mappings only

### 4.4 Zipline Metadata API
- Zipline exports metadata definitions as JSON files to Blob Storage
- AI Search indexes the JSON files automatically
- Orchestrator queries AI Search (does not call Zipline API directly)

### 4.5 Azure Blob Storage (Central Repository)
- Central repository where all data sources export their content

**Content stored:**
- Synergy JSON Export: Data dictionary with field definitions and CEDS mappings
- Zipline JSON Export: Metadata definitions and element descriptions
- Word Documents: Business rules, legislation references
- Excel Files: Data dictionaries, field mappings
- Other JSON Files: Schema definitions, source system dictionaries

**Container Organization:**
- `/synergy/` — Synergy data dictionary exports
- `/zipline/` — Zipline metadata exports
- `/documentation/` — Word, Excel, and other documentation
- `/schemas/` — JSON schema definitions

---

## 5. RAG Architecture

### 5.1 Azure AI Search

Primary Index: `metadata-context-index`

Single, unified index containing content from all sources:

| Field | Type | Purpose |
|---|---|---|
| `id` | Edm.String | Primary key |
| `source` | Edm.String | Origin of context |
| `content` | Edm.String | Searchable text |
| `contentVector` | Collection(Edm.Single) | Embedding vector (1536 dimensions) |
| `elementName` | Edm.String | Metadata element |
| `elementType` | Edm.String | Asset type |
| `description` | Edm.String | Source description |
| `cedsLink` | Edm.String | CEDS reference |
| `sourceSystem` | Edm.String | System identifier |
| `lastUpdated` | Edm.DateTimeOffset | Freshness indicator |

**Incremental Indexing:**
- Indexer must detect changes based on Blob Storage metadata and re-index only changed documents
- Full index rebuild only when schema changes occur

### 5.2 AI Enrichment Strategy

#### 5.2.1 Context Retrieval (RAG Query Pipeline)
1. **Semantic Vector Search:** Retrieve most relevant chunks based on embedding similarity
2. **Keyword Search:** Ensure exact field names, acronyms, and system-specific terminology are captured
3. **Hybrid Ranking:** Re-ranking layer merges semantic and keyword results, weighting by vector relevance, keyword match score, source reliability, and freshness

#### 5.2.2 Prompt Construction
Structured prompt containing:
- Purview metadata (asset name, schema, data type, existing description)
- Top N context chunks from AI Search
- Business rules from documentation
- Style and tone guidelines
- CEDS references when present
- Output format instructions (structured YAML)

Free-form prompt structures are not allowed.

#### 5.2.3 Generation Model and Parameters
- **Model:** GPT-4.x (or latest available)
- **Temperature:** 0.0–0.2 for deterministic output
- **Max Tokens:** 512–1024, depending on asset type
- **Frequency penalties:** disabled
- **Output format:** Structured YAML (preferred over JSON for token efficiency)

#### 5.2.4 Change Detection Optimization
Enrichment only occurs when:
- The metadata hash changes
- The previous suggestion was rejected and a retry is requested
- The context related to the element changes (optional future enhancement)

#### 5.2.5 Write-Back Strategy
- All AI-generated descriptions written only to Suggested Description attribute
- Human reviewers validate all suggestions before publication
- No automated promotion to official Purview description without human approval

**Staged write approach:**
1. LLM output → written to Suggested Description
2. Official description remains unchanged until approval workflow applied
3. Approved entries copied to primary Purview description field
4. Audit entries recorded in Cosmos DB

### 5.3 Batch Enrichment Optimization
- Group 5–20 assets per LLM request when assets share similar context
- Build single prompt with shared instruction block plus compact YAML per asset
- Parse batched response and map each description back to its Purview asset

### 5.4 AI Output Validation Strategy

#### A. Structural Validation
- Must not exceed predefined token or character limits
- Must follow required internal template
- Must not include hallucinated fields

#### B. Semantic Validation
- Must be consistent with asset's data type
- Must align with Synergy or Zipline definitions
- Must not contradict previously approved descriptions

#### C. Safety Validation
- No sensitive or personal data inferred
- No unsupported compliance claims
- No speculative language

#### D. Confidence Assessment
Synthetic confidenceScore computed from:
- Embedding similarity between metadata and generated text
- Coverage ratio of context chunks used
- Validation rule pass rate

### 5.5 Human-in-the-Loop (Purview)
- LLM output saved as "Suggested Description"
- Reviewer approves or rejects
- Approval triggers update to official Purview description
- Rejection triggers optional re-generation

### 5.6 Audit Logging
All validation steps produce structured audit logs in Cosmos DB:
- Description generated
- Validation rules applied
- Validation results
- Decision (approved/rejected)
- Tokens used
- Model used
- Reviewer identity (if applicable)

---

## 6. Compliance and Sensitive Data Controls

- LLM must not infer or generate sensitive information not explicitly present in Purview metadata
- Validation engine must detect and reject: student-identifiable information, FERPA-protected inferences, sensitive demographic attributes
- Audit logs must track all rejected outputs that violate compliance rules

---

## 7. Non-Functional Requirements

### 7.1 Performance
- Process at least 500 assets per hour during peak Purview scan events

### 7.2 Availability
- Pipeline operational 99.5% of the time (excluding planned maintenance)

### 7.3 Security
- All data in transit must use HTTPS/TLS 1.2+
- All credentials stored in Azure Key Vault
- No PII may be inferred by the LLM beyond what is explicitly present in metadata
- All components must use Managed Identities for authentication
- Key Vault used only when Managed Identity not supported

### 7.4 Disaster Recovery
- RPO ≤ 24 hours (Blob + Cosmos backup)
- RTO ≤ 4 hours (orchestrator redeployment)

### 7.5 Observability
- App Insights must capture: latency, token usage, OpenAI errors, index errors, Purview write failures

---

## 8. Infrastructure as Code (IaC) and CI/CD

### 8.1 IaC Requirements
All Azure resources must be declared using Bicep or Terraform. Manual Azure Portal changes are not permitted except for break-glass scenarios.

### 8.2 Environment Isolation Strategy
- **dev** — Development and schema validation
- **test** — LLMOps evaluation and user acceptance
- **prod** — Final authoritative environment

### 8.3 Version Control Requirements
- AI Search Index Schemas: version-controlled with PR review
- Prompt Templates: versioned under Git with PR reviews mandatory
- Orchestrator Configuration: reviewed, versioned, deployed through CI/CD
- Lookup Files and Schemas: versioned for predictable ingestion

### 8.4 Deployment Governance
- Production deployments require approval from both engineering and DOE leadership
- All deployments tracked in audit logs
- Rollback strategies defined for infrastructure, application, and index changes
