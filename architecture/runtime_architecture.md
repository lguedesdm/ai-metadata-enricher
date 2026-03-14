# AI Metadata Enricher — Runtime Architecture

> **Status:** Canonical — reflects the verified production implementation
> **Version:** 1.0 (created March 2026 — derived from audit of IaC, source code, and Azure Functions)
> **Authority:** This document supersedes any informal descriptions of runtime topology

---

## 1. Purpose

This document describes the **runtime architecture** of the AI Metadata Enricher: every component that is alive at runtime, how they connect, what each one does, and the exact sequence of operations from a Purview scan event to an enriched metadata suggestion.

This is not a conceptual overview. It is grounded in the actual source code, Bicep IaC, and Azure Functions verified during the March 2026 architecture audit.

---

## 2. Full Runtime Component Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     MICROSOFT PURVIEW                                   │
│  Emits diagnostic telemetry on scan completion                          │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ Azure Monitor Diagnostic Settings
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       AZURE EVENT HUB                                   │
│  Hub: purview-diagnostics                                               │
│  Receives raw Purview diagnostic events (mixed types, high volume)      │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ Event Hub Trigger
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              HeuristicTriggerBridge  [Azure Function — C#]              │
│                                                                         │
│  - Consumes batched Event Hub messages                                  │
│  - Filters relevant scan-completion events                              │
│  - Attaches correlationId for end-to-end traceability                  │
│  - Publishes filtered events to Service Bus queue: purview-events       │
│                                                                         │
│  Runtime: Azure Functions Flex Consumption (FC1), .NET 8               │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ Service Bus Send
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              SERVICE BUS QUEUE: purview-events                          │
│  maxDeliveryCount: 10  │  TTL: P7D  │  DLQ: enabled                   │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ Service Bus Trigger
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              UpstreamRouterFunction  [Azure Function — C#]              │
│                                                                         │
│  - Consumes messages from purview-events                                │
│  - Applies routing logic                                                │
│  - Transforms payload into canonical enrichment request                 │
│  - Publishes to Service Bus queue: enrichment-requests                  │
│                                                                         │
│  Runtime: Azure Functions Flex Consumption (FC1), .NET 8               │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ Service Bus Send
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              SERVICE BUS QUEUE: enrichment-requests                     │
│  maxDeliveryCount: 10  │  TTL: P7D  │  lockDuration: PT5M  │  DLQ: enabled │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ Peek-Lock receive
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              ENRICHMENT ORCHESTRATOR  [Container App — Python]          │
│                                                                         │
│  consumer.py — ServiceBusReceiveMode.PEEK_LOCK                         │
│  message_handler.py — 7-step pipeline per element                      │
│                                                                         │
│  Step 1: Parse message, extract elements (element_splitter)            │
│  Step 2: Compute SHA-256 hash per element (change_detection)           │
│  Step 3: Query Cosmos DB state container → SKIP or REPROCESS          │
│  Step 4: [if REPROCESS] RAG retrieval (search_client + ranking)        │
│  Step 5: [if REPROCESS] LLM generation (llm_client → Azure OpenAI)    │
│  Step 6: [if REPROCESS] Validation (StructuralValidator + Semantic)    │
│  Step 7: [if PASS] Write-back (purview_writeback → Purview)            │
│  Step 8: Persist state + audit to Cosmos DB                            │
│  Step 9: complete() on Service Bus message                             │
│                                                                         │
│  Lock renewal: background thread, every 15 seconds                     │
│  Batch size: default 1 (deterministic MVP behavior)                    │
└────────┬──────────────┬───────────────┬──────────────┬─────────────────┘
         │              │               │              │
         ▼              ▼               ▼              ▼
  ┌──────────┐  ┌──────────────┐ ┌──────────┐ ┌──────────────┐
  │ COSMOS DB│  │ AZURE AI     │ │  AZURE   │ │  MICROSOFT   │
  │ (state)  │  │ SEARCH       │ │  OPENAI  │ │  PURVIEW     │
  │ SHA hash │  │ metadata-    │ │  GPT-4.x │ │  POST        │
  │ SKIP/    │  │ context-index│ │  temp=0.1│ │  /business   │
  │ REPROCESS│  │ hybrid search│ │  YAML out│ │  metadata    │
  └──────────┘  └──────────────┘ └──────────┘ └──────────────┘
         │
         ▼
  ┌──────────┐
  │ COSMOS DB│
  │ (audit)  │
  │ full     │
  │ trail    │
  └──────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    HUMAN REVIEWER  (Purview UI)                         │
│  Reviews AI_Enrichment.suggested_description                            │
│  Decision: APPROVE (lifecycle → APPROVED) or REJECT (lifecycle → REJECTED) │
│  On approval: reviewer manually promotes to entity.description          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Reference

### 3.1 Azure Monitor Diagnostic Settings

| Attribute | Value |
|---|---|
| Source | Microsoft Purview |
| Event type | `Microsoft.Purview.ScanCompleted` (and related telemetry) |
| Destination | Azure Event Hub namespace |
| Configuration | IaC — `infra/eventhub/main.bicep` |

The diagnostic settings export Purview scan telemetry as raw JSON events. These are not structured enrichment requests — raw filtering is applied downstream in `HeuristicTriggerBridge`.

### 3.2 Azure Event Hub

| Attribute | Value |
|---|---|
| Hub name | `purview-diagnostics` |
| Consumer | `HeuristicTriggerBridge` (Azure Function) |
| IaC | `infra/eventhub/main.bicep` |

Provides durable event retention. If the Function is temporarily unavailable, events remain in the hub and are re-processed on recovery (within the hub's retention window).

### 3.3 HeuristicTriggerBridge (Azure Function)

| Attribute | Value |
|---|---|
| File | `functions/purview-bridge/HeuristicTriggerBridge.cs` |
| Trigger | Event Hub |
| Output | Service Bus queue: `purview-events` |
| Runtime | .NET 8, Flex Consumption (FC1) |
| Auth | Managed Identity |

**Key behaviors:**
- Processes batches of Event Hub messages
- Filters irrelevant Purview event types (only scan-completion relevant events pass)
- Generates and attaches a `correlationId` to every outgoing message
- Forwards to `purview-events` Service Bus queue

### 3.4 Service Bus Queue: `purview-events`

| Attribute | Value |
|---|---|
| Purpose | Raw Purview event routing stage |
| Producer | `HeuristicTriggerBridge` |
| Consumer | `UpstreamRouterFunction` |
| Max Delivery Count | 10 |
| TTL | P7D |
| DLQ | Enabled |

This queue acts as a buffer between raw event ingestion and enrichment routing. It allows the routing logic (`UpstreamRouterFunction`) to be independently scaled, deployed, or updated without affecting the ingestion side.

### 3.5 UpstreamRouterFunction (Azure Function)

| Attribute | Value |
|---|---|
| File | `functions/purview-bridge/UpstreamRouterFunction.cs` |
| Trigger | Service Bus queue: `purview-events` |
| Output | Service Bus queue: `enrichment-requests` |
| Runtime | .NET 8, Flex Consumption (FC1) |
| Auth | Managed Identity |

**Key behaviors:**
- Consumes messages from `purview-events`
- Applies routing decisions (determines if enrichment is warranted for this event)
- Transforms the raw Purview event payload into a canonical enrichment request
- Publishes the enrichment request to `enrichment-requests`
- Preserves `correlationId` for downstream traceability

### 3.6 Service Bus Queue: `enrichment-requests`

| Attribute | Value |
|---|---|
| Purpose | Canonical enrichment job queue — primary Orchestrator input |
| Producer | `UpstreamRouterFunction` |
| Consumer | Enrichment Orchestrator |
| Max Delivery Count | 10 |
| TTL | P7D |
| Lock Duration | PT5M |
| DLQ | Enabled |
| Receive Mode | PEEK_LOCK |

This queue contains only well-formed, validated enrichment requests. The Orchestrator treats every message in this queue as an actionable enrichment job.

### 3.7 Enrichment Orchestrator (Python Container App)

| Attribute | Value |
|---|---|
| Language | Python |
| Platform | Azure Container Apps |
| Entry point | `python -m src.orchestrator` |
| Source | `src/orchestrator/` |
| Scaling | Single replica (Phase 3); scales to zero when idle |
| Auth | System-assigned Managed Identity |

**Source file map:**

| File | Responsibility |
|---|---|
| `__main__.py` | Entry point, signal handling, heartbeat thread |
| `consumer.py` | Service Bus peek-lock consumer, lock renewal |
| `message_handler.py` | 7-step pipeline orchestration per element |
| `cosmos_state_store.py` | Cosmos DB state and audit container access |
| `config.py` | Environment variable configuration |

**Processing sequence per message:**

```
1. Receive message (peek-lock)
2. Parse JSON payload → split into ContextElements
3. Per element:
   a. Compute SHA-256 hash (normalize → hash)
   b. Query Cosmos DB state container
   c. Decision: SKIP or REPROCESS
   d. [REPROCESS] Query AI Search (hybrid RAG)
   e. [REPROCESS] Assemble prompt with RAG context
   f. [REPROCESS] Call Azure OpenAI (1 call, temp 0.1)
   g. [REPROCESS] Validate output (StructuralValidator + SemanticValidator + OutputValidator)
   h. [PASS] Write to Purview AI_Enrichment.suggested_description
   i. Persist lifecycle state to Cosmos DB state container
   j. Write audit record to Cosmos DB audit container
4. complete() on Service Bus message
```

### 3.8 Azure AI Search — RAG Index

| Attribute | Value |
|---|---|
| Index name | `metadata-context-index` |
| Search type | Hybrid (semantic vector + keyword + reranking) |
| Vector dimensions | 1536 (HNSW algorithm) |
| IaC schema | `infra/search/schemas/metadata-context-index.json` |

**RAG module source files:**

| File | Responsibility |
|---|---|
| `src/enrichment/rag/search_client.py` | Hybrid query execution against AI Search |
| `src/enrichment/rag/ranking.py` | Composite score: relevance × source_weight × freshness |
| `src/enrichment/rag/context_assembly.py` | Format ranked chunks into prompt-ready context |
| `src/enrichment/rag/pipeline.py` | Entry point — orchestrates search → rank → assemble |

### 3.9 Azure OpenAI

| Attribute | Value |
|---|---|
| Model | GPT-4.x (latest available on endpoint) |
| Temperature | 0.1 |
| Max tokens | 1024 |
| Output format | Structured YAML (enforced by prompt contract) |
| Calls per asset | 1 (no batching — future optimization) |
| Auth | Managed Identity (RBAC: Cognitive Services OpenAI User) |
| Source | `src/enrichment/llm_client.py` |

### 3.10 Validation Engine

| Attribute | Value |
|---|---|
| Source | `src/domain/validation/`, `src/enrichment/output_validator.py` |
| Blocking rules | V001–V040 (11 rules) |
| Advisory flags | A001–A005 (5 flags) |
| On BLOCK | Write-back skipped; rejection written to Cosmos DB audit |
| On PASS | Write-back proceeds; advisory flags attached to audit record |

**Validators:**

| Component | Type | File |
|---|---|---|
| `StructuralValidator` | Blocking | `src/domain/validation/structural_validator.py` |
| `SemanticValidator` | Blocking | `src/domain/validation/semantic_validator.py` |
| `OutputValidator` | Blocking + Advisory | `src/enrichment/output_validator.py` |

### 3.11 Purview Write-Back

| Attribute | Value |
|---|---|
| Target field | `AI_Enrichment.suggested_description` |
| Initial status | `review_status: PENDING` |
| HTTP method | POST |
| Endpoint | `/datamap/api/atlas/v2/entity/guid/{guid}/businessmetadata` |
| Success response | HTTP 204 No Content |
| Official description | **Never written by the system** |
| Auth | Managed Identity (RBAC: Purview Data Curator) |
| Source | `src/enrichment/purview_client.py`, `src/enrichment/purview_writeback.py` |

**Error categories:**

| Category | Meaning |
|---|---|
| `AUTHENTICATION` | Token acquisition failure |
| `AUTHORIZATION` | RBAC insufficient |
| `ENTITY_NOT_FOUND` | Asset GUID not found in Purview |
| `NETWORK` | Transient HTTP error |
| `LIFECYCLE_VIOLATION` | Invalid lifecycle transition |
| `AUTHORITATIVE_METADATA_CONFLICT` | Write would alter protected field |
| `COSMOS_FAILURE` | State persistence failed after Purview write (PARTIAL_WRITE) |
| `PARTIAL_WRITE` | Purview written, Cosmos failed — requires manual reconciliation |

### 3.12 Cosmos DB State Store

| Attribute | Value |
|---|---|
| Database | `metadata_enricher` |
| Auth | Managed Identity (RBAC: Cosmos DB Built-in Data Contributor) |
| Source | `src/orchestrator/cosmos_state_store.py`, `src/enrichment/lifecycle.py` |

**Containers:**

| Container | Partition Key | TTL | Contents |
|---|---|---|---|
| `state` | `entityType` | 7 days | Asset hash, lifecycle status, last processed timestamp |
| `audit` | `entityType` | 180 days | Full pipeline audit: model, tokens, validation result, decision, reviewer, correlationId |

> **TTL Warning:** The 7-day TTL on `state` means assets not re-enriched within 7 days will lose their stored hash. On next trigger, they are treated as new (REPROCESS), even if their metadata is unchanged.

---

## 4. Lifecycle State Machine

```
[new asset]
     │
     ▼
  PENDING  ←── initial write by Orchestrator
     │
  ┌──┴──┐
  ▼     ▼
APPROVED  REJECTED
(terminal) (terminal)
```

Lifecycle transitions are enforced by `src/enrichment/lifecycle.py`. Invalid transitions (e.g., APPROVED → PENDING) raise a `LIFECYCLE_VIOLATION` error and are blocked.

---

## 5. Correlation ID Propagation

A `correlationId` is attached at `HeuristicTriggerBridge` and propagated through every downstream component:

```
Event Hub event
  → HeuristicTriggerBridge (generates correlationId)
  → Service Bus message: purview-events (correlationId in properties)
  → UpstreamRouterFunction (preserves correlationId)
  → Service Bus message: enrichment-requests (correlationId in properties)
  → Orchestrator (reads correlationId, propagates to all log events)
  → Cosmos DB state record (correlationId field)
  → Cosmos DB audit record (correlationId field)
  → Application Insights (correlationId as custom dimension)
```

This allows complete end-to-end tracing of a single Purview scan event through every component.

---

## 6. Security Surface

All runtime components authenticate exclusively via **Managed Identity** (`DefaultAzureCredential`). There are no connection strings, API keys, or secrets in source code.

| Connection | Auth Method | RBAC Role |
|---|---|---|
| Orchestrator → Service Bus | Managed Identity | Azure Service Bus Data Receiver |
| Orchestrator → Cosmos DB | Managed Identity | Cosmos DB Built-in Data Contributor |
| Orchestrator → AI Search | Managed Identity | Search Index Data Reader |
| Orchestrator → Azure OpenAI | Managed Identity | Cognitive Services OpenAI User |
| Orchestrator → Purview | Managed Identity | Purview Data Curator |
| Functions → Service Bus | Managed Identity | Azure Service Bus Data Sender / Receiver |
| Functions → Event Hub | Managed Identity | Azure Event Hubs Data Receiver |

---

## 7. Observability

| Signal | Platform | Details |
|---|---|---|
| Structured logs | Application Insights | JSON logs with correlationId, batchId, decision, tokensUsed |
| Heartbeat | Application Insights | `host_alive` event emitted every 60 minutes |
| DLQ alerts | Application Insights | Alert on any message entering DLQ |
| LLM token usage | Application Insights | input_tokens, output_tokens, total_tokens per enrichment |
| Validation failures | Application Insights | Failed rule IDs logged per rejection |
| Purview write errors | Application Insights | Error category and HTTP status logged |

---

## 8. Infrastructure Module Reference

| Component | Bicep Module |
|---|---|
| Event Hub | `infra/eventhub/main.bicep` |
| Azure Functions | `infra/functions/main.bicep` |
| Service Bus (queues) | `infra/messaging/main.bicep` |
| Cosmos DB | `infra/cosmos/account-db.bicep` |
| Azure AI Search | `infra/search/main.bicep` |
| AI Search index schema | `infra/search/schemas/metadata-context-index.json` |
| Blob Storage | `infra/storage/main.bicep` |
| Container Apps | `infra/compute/main.bicep` |
| Key Vault | `infra/main.bicep` (inline) |
| Application Insights | `infra/main.bicep` (inline) |
