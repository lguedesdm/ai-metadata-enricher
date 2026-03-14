# AI Metadata Enricher — Architecture Reference

> **Source:** LLM Metadata Architecture Document (Authoritative)
> **Status:** Canonical — all implementation must comply with this document
> **Version:** 1.1 (corrected — aligns with audited implementation, March 2026)
> **Previous version:** 1.0 (contained incorrect trigger model and messaging topology)

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
| Trigger Model | Event-driven via Azure Monitor → Event Hub → Functions Bridge | 100% |
| Synergy Integration | JSON export to Blob Storage (primary context source) | 100% |
| Zipline Integration | JSON export to Blob Storage (no direct API) | 100% |
| Blob Storage | Central repository for all exports and docs | 100% |
| AI Search Role | Unified index for all context sources | 100% |
| CEDS Integration | MVP uses Synergy's CEDS mappings only | 100% |
| Search Type | Hybrid Search (vector + keyword + semantic reranking) | 100% |
| Messaging Topology | Service Bus Queues (not topics) with peek-lock | 100% |
| Validation Strategy | Structural + Semantic validators + advisory rules | 100% |

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

> ⚠️ **Correction from v1.0:** The previous version described Event Grid routing directly to Service Bus. The actual implementation uses Azure Monitor Diagnostic Settings, an Event Hub, and two intermediate Azure Functions. See section 3.3 for the component details.

The enrichment process is initiated through the following chain:

1. **Purview Scan Completion:** Microsoft Purview emits diagnostic telemetry upon scan completion via Azure Monitor Diagnostic Settings.
2. **Event Hub Ingestion:** Diagnostic events are streamed to an Azure Event Hub namespace (`purview-diagnostics` hub).
3. **HeuristicTriggerBridge (Azure Function):** An Event Hub-triggered C# Azure Function consumes raw Purview diagnostic events, filters relevant scan-completion events, attaches a correlation ID, and publishes them to the Service Bus queue `purview-events`.
4. **UpstreamRouterFunction (Azure Function):** A Service Bus-triggered C# Azure Function consumes messages from `purview-events`, applies routing logic, transforms the event payload into an enrichment request, and publishes it to the Service Bus queue `enrichment-requests`.
5. **Orchestrator Consumption:** The Enrichment Orchestrator (Python Container App) listens to `enrichment-requests` using peek-lock and processes messages individually.

**Full trigger chain:**

```
Purview Scan Completion
        │
        ▼
Azure Monitor Diagnostic Settings
        │
        ▼
Azure Event Hub  (purview-diagnostics)
        │
        ▼
HeuristicTriggerBridge  [Azure Function — C#]
  - filters relevant scan events
  - attaches correlationId
  - publishes to Service Bus
        │
        ▼
Service Bus Queue: purview-events
        │
        ▼
UpstreamRouterFunction  [Azure Function — C#]
  - routes and transforms payload
  - publishes enrichment request
        │
        ▼
Service Bus Queue: enrichment-requests
        │
        ▼
Enrichment Orchestrator  [Container App — Python]
```

Benefits of this design:
- **Decoupled ingestion:** Purview never calls the Orchestrator directly; diagnostic telemetry is the integration surface
- **Filtered routing:** HeuristicTriggerBridge discards irrelevant Purview events before they enter the enrichment queue
- **Evolvable pipeline:** The two-stage Function bridge allows independent routing logic changes without touching the Orchestrator
- **Reliable delivery:** Event Hub provides durable event retention; Service Bus provides at-least-once delivery with DLQ

### 3.3 Azure Functions Bridge Components

The Azure Functions bridge (`purview-bridge`) is a C# .NET 8 Function App deployed under Flex Consumption (FC1). It contains two functions:

#### HeuristicTriggerBridge

| Attribute | Value |
|---|---|
| Trigger | Event Hub (`purview-diagnostics`) |
| Output | Service Bus queue: `purview-events` |
| Language | C# (.NET 8) |

**Responsibilities:**
- Consume batched events from the Event Hub
- Filter for scan-completion and relevant Purview event types
- Attach a `correlationId` for end-to-end traceability
- Forward filtered events to `purview-events` queue

#### UpstreamRouterFunction

| Attribute | Value |
|---|---|
| Trigger | Service Bus queue: `purview-events` |
| Output | Service Bus queue: `enrichment-requests` |
| Language | C# (.NET 8) |

**Responsibilities:**
- Consume Purview events from `purview-events`
- Apply routing logic to determine if enrichment is warranted
- Transform the event into a canonical enrichment request payload
- Publish to `enrichment-requests` for Orchestrator consumption

### 3.4 Service Bus Messaging Topology

> ⚠️ **Correction from v1.0:** The previous version described a Service Bus Topic + Subscription model. The actual implementation uses two independent queues.

The system uses two Service Bus queues (not topics):

| Queue | Producer | Consumer | Purpose |
|---|---|---|---|
| `purview-events` | HeuristicTriggerBridge | UpstreamRouterFunction | Raw Purview event routing |
| `enrichment-requests` | UpstreamRouterFunction | Orchestrator | Canonical enrichment job queue |

**Queue configuration (both queues):**

| Parameter | Value |
|---|---|
| Mode | Peek-Lock |
| Max Delivery Count | 10 |
| Message TTL | P7D (7 days) |
| Lock Duration | PT5M (5 minutes) |
| Dead-Letter Queue | Enabled (`deadLetteringOnMessageExpiration: true`) |

**Peek-Lock semantics in the Orchestrator:**
- Message is locked on receive — not removed from queue yet
- Lock is renewed by a background thread every 15 seconds during long processing
- `complete()` is called only after successful end-to-end processing (state saved, Purview written)
- `abandon()` is called on recoverable failures — message returns to queue for retry
- After 10 failed deliveries, message is automatically moved to the Dead-Letter Queue

**Retry behavior:**
- No explicit retry policy is configured outside Service Bus
- Retry is handled natively: `abandon()` + `maxDeliveryCount: 10`
- DLQ messages trigger an alert in Application Insights for manual inspection

### 3.5 Enrichment Flow (Event-Driven)

1. **Trigger:** Message received from `enrichment-requests` Service Bus queue
2. **State Check:** Before any LLM call, check Cosmos DB to determine SKIP or REPROCESS (SHA-256 hash comparison)
3. **Query Context:** If REPROCESS, retrieve context from Azure AI Search (Hybrid Search)
4. **Generate:** Call Azure OpenAI — one LLM call per asset
5. **Validate:** Run output through Structural + Semantic validators and advisory rules
6. **Write:** If validation passes, write to Purview `AI_Enrichment.suggested_description` only
7. **Audit:** Persist state, lifecycle, and audit record to Cosmos DB
8. **Complete:** Call `complete()` on the Service Bus message

### 3.6 State Store Schema (Cosmos DB)

State tracking uses Cosmos DB. The state document tracks metadata changes, enrichment history, confidence scoring, and audit events.

**Change Detection Logic:**

1. Fetch Current Metadata: Retrieve asset metadata from Purview
2. Calculate Hash: Compute SHA-256 hash of normalized, serialized metadata (material fields only)
3. Query State Store: Check Cosmos DB `state` container for existing record
4. Compare Hash:
   - No record exists → Proceed with enrichment (new asset)
   - Record exists AND hash matches → Skip enrichment (no change — no LLM call made)
   - Record exists AND hash differs → Proceed with enrichment (metadata changed)
5. Update State: After successful enrichment, store new hash and lifecycle state

**Cosmos DB containers:**

| Container | Purpose | Partition Key | TTL |
|---|---|---|---|
| `state` | Asset processing state + SHA-256 hash | `entityType` | 7 days |
| `audit` | Immutable pipeline execution audit trail | `entityType` | 180 days |

> ⚠️ **Architectural Note — TTL Impact:** The `state` container TTL of 7 days means that assets not processed within that window will lose their stored hash. On the next enrichment trigger, those assets will be treated as new (REPROCESS decision), regardless of whether their metadata actually changed. Teams should be aware of this behavior during periods of inactivity.

### 3.7 Component Inventory

| Component | Azure Service | Purpose | Status |
|---|---|---|---|
| Orchestrator | Container Apps | Central orchestration engine | Confirmed |
| Event Ingestion | Azure Event Hub | Purview diagnostic event ingestion | Confirmed |
| Functions Bridge | Azure Functions (FC1) | HeuristicTriggerBridge + UpstreamRouterFunction | Confirmed |
| Message Broker | Azure Service Bus | Load leveling — queues: `purview-events`, `enrichment-requests` | Confirmed |
| State Store / Audit | Azure Cosmos DB | SHA-256 hashing + audit (containers: `state`, `audit`) | Confirmed |
| AI Engine | Azure OpenAI | Generate descriptions (GPT-4.x, temp 0.1) | Confirmed |
| Unified Search Index | Azure AI Search | Index sources, unified queries (`metadata-context-index`) | Confirmed |
| Central Repository | Blob Storage | Store JSON exports and docs | Confirmed |
| Data Catalog | Purview | Source/target metadata | Confirmed |
| Secrets | Azure Key Vault | Store API keys, secrets (Managed Identity preferred) | Confirmed |
| Monitoring | App Insights | Logging, telemetry, correlationId propagation | Confirmed |

### 3.8 Enrichment Orchestrator

The Enrichment Orchestrator is the central processing engine. It is NOT an API to be consumed by external systems, but an internal service that orchestrates the enrichment workflow.

**What it IS:**
- An internal orchestration engine that coordinates the enrichment pipeline
- A consumer of Purview API (read metadata, write suggested description)
- A consumer of AI Search (unified context from all sources)
- A consumer of Azure Service Bus queue `enrichment-requests`
- A consumer of Azure Cosmos DB (state checks and audit writes)
- A consumer of Azure OpenAI (generate descriptions)

**What it is NOT:**
- NOT an API that exposes endpoints
- NOT a direct consumer of Synergy or Zipline APIs (uses AI Search instead)
- NOT responsible for indexing content (AI Search handles this)
- NOT the first consumer of Purview events (the Functions bridge precedes it)

**Processing model:**
- Batch size: default 1 message per receive cycle (deterministic for Phase 3 E2E validation)
- Processing is sequential within each message: one element → full 7-step pipeline → complete
- Lock renewal runs as a background thread to prevent lock expiry on long enrichments

### 3.9 Error Handling and Fault Tolerance

- **Retry Policy:** Handled by Service Bus `maxDeliveryCount: 10`. On recoverable errors, Orchestrator calls `abandon()` and the message re-enters the queue.
- **Dead-Letter Queue (DLQ):** Messages exceeding 10 delivery attempts are automatically moved to DLQ. Application Insights alerts are triggered on DLQ activity.
- **OpenAI Quota Protection:** Single LLM call per asset; no parallel calls.
- **Fallback Behavior:** When LLM output fails validation, the output is discarded, a rejection audit record is written to Cosmos DB, and the Service Bus message is completed (not retried — validation failure is a permanent decision, not a transient error).
- **Partial Write Detection:** If Purview write succeeds but Cosmos write fails, the system detects and logs a `PARTIAL_WRITE` error. Manual reconciliation is required for this scenario.

---

## 4. Data Sources and Integration

### 4.1 Microsoft Purview

- **Integration:** REST API (Apache Atlas endpoint)
- **Read operation:** `GET /datamap/api/atlas/v2/entity/guid/{guid}`
- **Write operation:** `POST /datamap/api/atlas/v2/entity/guid/{guid}/businessmetadata`
  - Writes only to `AI_Enrichment.suggested_description`
  - Returns HTTP 204 on success
  - Never writes to `entity.description` (official description)

### 4.2 Synergy

- JSON export to Blob Storage (primary context source)
- Data dictionary with descriptive information for metadata enrichment
- CEDS Mapping: Data mapped to Common Education Data Standards
- Integration: Export → Blob Storage `/synergy/` → AI Search indexes → Orchestrator queries AI Search

### 4.3 CEDS

- CEDS definitions are not crawled or indexed directly
- MVP uses Synergy's CEDS mappings only

### 4.4 Zipline Metadata API

- Zipline exports metadata definitions as JSON files to Blob Storage
- AI Search indexes the JSON files automatically
- Orchestrator queries AI Search (does not call Zipline API directly)

### 4.5 Azure Blob Storage (Central Repository)

Central repository where all data sources export their content.

**Container organization:**
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
| `source` | Edm.String | Origin of context (synergy, zipline, documentation) |
| `content` | Edm.String | Searchable text |
| `contentVector` | Collection(Edm.Single) | Embedding vector (1536 dimensions, HNSW algorithm) |
| `elementName` | Edm.String | Metadata element name |
| `elementType` | Edm.String | Asset type (table, column, dataset, etc.) |
| `description` | Edm.String | Source description |
| `cedsLink` | Edm.String | CEDS reference |
| `sourceSystem` | Edm.String | System identifier |
| `lastUpdated` | Edm.DateTimeOffset | Freshness indicator |

**RAG module files (actual implementation):**

| Responsibility | File |
|---|---|
| Search client (hybrid query execution) | `src/enrichment/rag/search_client.py` |
| Result ranking and composite scoring | `src/enrichment/rag/ranking.py` |
| Context assembly for prompt injection | `src/enrichment/rag/context_assembly.py` |
| Pipeline orchestration (entry point) | `src/enrichment/rag/pipeline.py` |

**Incremental Indexing:**
- Indexer must detect changes based on Blob Storage metadata and re-index only changed documents
- Full index rebuild only when schema changes occur

### 5.2 AI Enrichment Strategy

#### 5.2.1 Context Retrieval (RAG Query Pipeline)

1. **Semantic Vector Search:** Retrieve most relevant chunks based on embedding similarity (1536-dimension vectors, HNSW)
2. **Keyword Search:** Ensure exact field names, acronyms, and system-specific terminology are captured
3. **Hybrid Reranking:** Re-ranking layer merges semantic and keyword results using a composite score: `relevance × source_weight × (1 + freshness_weight × freshness_factor)`
   - Source reliability weights are configurable per source system
   - Freshness uses exponential decay with 90-day half-life
   - Tie-breaking is deterministic (by document ID ascending)

#### 5.2.2 Prompt Construction

Structured prompt containing:
- Purview metadata (asset name, schema, data type, existing description)
- Top N context chunks from AI Search (formatted with source attribution per chunk)
- Business rules from documentation
- CEDS references when present
- Output format instructions (structured YAML)

Free-form prompt structures are not allowed. Prompt template is frozen at `contracts/prompts/v1-metadata-enrichment.prompt.yaml`.

#### 5.2.3 Generation Model and Parameters

| Parameter | Value | Source |
|---|---|---|
| Model | GPT-4.x (latest available on Azure OpenAI endpoint) | `runtime_architecture_contract.yaml` |
| Temperature | 0.1 | `runtime_architecture_contract.yaml` |
| Max Tokens | 1024 | `runtime_architecture_contract.yaml` |
| Output format | Structured YAML (mandatory) | Frozen contract `v1-metadata-enrichment.output.yaml` |
| Calls per asset | 1 (single call per enrichment) | Architecture invariant |

#### 5.2.4 Change Detection Optimization

Enrichment only occurs when:
- The metadata hash changes (SHA-256 mismatch vs. Cosmos DB state)
- The previous suggestion was rejected and a retry is requested
- No previous state record exists (new asset)

**LLM is never called for assets whose hash matches the stored state.**

#### 5.2.5 Write-Back Strategy

- All AI-generated descriptions written only to `AI_Enrichment.suggested_description` (Purview Business Metadata attribute)
- Human reviewers validate all suggestions before publication
- No automated promotion to official Purview description without human approval

**Staged write approach:**
1. LLM output passes validation → written to `AI_Enrichment.suggested_description` (status: PENDING)
2. Official `entity.description` remains unchanged
3. Human reviewer approves in Purview UI → lifecycle transitions to APPROVED
4. On approval, suggested description is manually copied to official description by the reviewer
5. Audit entries recorded in Cosmos DB `audit` container

### 5.3 Batch Enrichment — Future Optimization (Not Yet Implemented)

> **Current behavior (MVP):** The enrichment pipeline processes **one asset per LLM call**. There is no grouping or batching of multiple assets into a single prompt.

**Planned future optimization:** Group 5–20 assets per LLM request when assets share similar context, building a single prompt with a shared instruction block plus compact YAML per asset and mapping responses back to individual assets.

This optimization is documented as a future phase. It must not be assumed to be active in any current environment.

### 5.4 AI Output Validation Strategy

The validation pipeline runs in two stages before any write to Purview.

**Stage 1 — Domain Validation (blocking):**
- `StructuralValidator`: validates YAML parseability, required fields (`suggested_description`, `confidence`, `used_sources`), field types, length constraints (10–500 chars for description), and confidence enum (`low`, `medium`, `high`)
- `SemanticValidator`: detects forbidden phrases (LLM, model, AI, external knowledge references), generic boilerplate patterns, placeholder text, and unsupported source attributions

**Stage 2 — Runtime Validation (advisory + blocking):**
- `OutputValidator` wraps the domain validators and adds advisory flags
- Blocking rules V001–V040: any failure results in status `BLOCK` — write-back is rejected
- Advisory flags A001–A005: non-blocking flags for human review prioritization (low confidence, short description, single source, uncertainty language)

**Invalid outputs (BLOCK) must not and are not written to Purview.** Rejection is recorded in the Cosmos DB `audit` container.

### 5.5 Human-in-the-Loop (Purview)

- LLM output saved as `AI_Enrichment.suggested_description` with `review_status: PENDING`
- Reviewer approves or rejects via Purview UI
- Approval: lifecycle transitions to APPROVED, reviewer identity and timestamp recorded in Cosmos DB
- Rejection: lifecycle transitions to REJECTED; optional re-generation can be requested

### 5.6 Audit Logging

All enrichment operations produce structured audit records in Cosmos DB `audit` container:
- Description generated
- Validation rules applied and results
- Decision (ACCEPTED / REJECTED / SKIP)
- Tokens used (input + output)
- Model used
- Reviewer identity (on approval/rejection)
- Correlation ID (end-to-end traceability)
- Timestamp

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
- All credentials managed via Managed Identity (DefaultAzureCredential)
- Key Vault used only when Managed Identity is not directly supported
- No PII may be inferred by the LLM beyond what is explicitly present in metadata
- All components must use Managed Identities for authentication

### 7.4 Disaster Recovery

- RPO ≤ 24 hours (Blob + Cosmos backup)
- RTO ≤ 4 hours (orchestrator redeployment)

### 7.5 Observability

- App Insights must capture: latency, token usage, OpenAI errors, index errors, Purview write failures
- Correlation ID propagated end-to-end: Event Hub → Functions → Service Bus → Orchestrator → Cosmos DB

---

## 8. Infrastructure as Code (IaC) and CI/CD

### 8.1 IaC Requirements

All Azure resources must be declared using Bicep. Manual Azure Portal changes are not permitted except for break-glass scenarios.

**Bicep module structure:**

| Module | Path | Resource |
|---|---|---|
| Event Hub | `infra/eventhub/main.bicep` | Event Hub namespace + hub |
| Functions | `infra/functions/main.bicep` | Function App (Flex Consumption FC1) |
| Service Bus | `infra/messaging/main.bicep` | Namespace + queues (`purview-events`, `enrichment-requests`) |
| Cosmos DB | `infra/cosmos/account-db.bicep` | Account + database + containers |
| AI Search | `infra/search/main.bicep` | Search service + index deployment script |
| Blob Storage | `infra/storage/main.bicep` | Storage account + containers |
| Container Apps | `infra/compute/main.bicep` | Container Apps Environment + Orchestrator |

### 8.2 Environment Isolation Strategy

- **dev** — Development and schema validation
- **test** — LLMOps evaluation and user acceptance
- **prod** — Final authoritative environment

### 8.3 Version Control Requirements

- AI Search Index Schemas: version-controlled in `infra/search/schemas/` with PR review
- Prompt Templates: versioned under `/contracts/prompts/` — frozen at v1.0.0
- Orchestrator Configuration: reviewed, versioned, deployed through CI/CD
- Lookup Files and Schemas: versioned for predictable ingestion

### 8.4 Deployment Governance

- Production deployments require approval from both engineering and DOE leadership
- All deployments tracked in audit logs
- Rollback strategies defined for infrastructure, application, and index changes
