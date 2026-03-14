# AI Metadata Enricher — Architecture Guardrails

> **Status:** Immutable Engineering Constraints
> **Version:** 1.1 (corrected — canonical flow updated to reflect real implementation, March 2026)
> **Authority:** These guardrails are derived from the LLM Metadata Architecture Document and the Execution Plan.

---

## Agent Compliance Rule

**All automated agents working on this repository must load and follow the architecture documents located in `/architecture` before performing any modification.**

An agent must not propose, implement, or accept changes that violate the constraints in this file, in `architecture.md`, or in `execution_plan.md`. If any task conflicts with these documents, the agent must stop and request human authorization.

---

## 1. Architectural Authority

The following documents define the system architecture and must be treated as authoritative sources of truth:

- **LLM Metadata Architecture** → `architecture/architecture.md`
- **Execution Plan** → `architecture/execution_plan.md`
- **Architecture Guardrails** → this file
- **Architecture Contract** → `architecture/architecture_contract.md`
- **Runtime Architecture** → `architecture/runtime_architecture.md`

Any code implementation must remain compliant with all five documents.

The architecture must be treated as frozen unless explicitly changed by the project owner.

---

## 2. Core Architectural Pattern (Must Not Change)

The platform follows a unified RAG enrichment architecture.

**Canonical flow (authoritative — reflects real implementation):**

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
  filters scan events, attaches correlationId
        │
        ▼
Service Bus Queue: purview-events
        │
        ▼
UpstreamRouterFunction  [Azure Function — C#]
  routes and transforms to enrichment request
        │
        ▼
Service Bus Queue: enrichment-requests
        │
        ▼
Enrichment Orchestrator  [Container App — Python]
  ├── Cosmos DB state check (SHA-256 → SKIP or REPROCESS)
  ├── Azure AI Search (RAG context retrieval)
  ├── Azure OpenAI (description generation)
  ├── Validation Engine (structural + semantic + advisory)
  ├── Purview write-back (AI_Enrichment.suggested_description only)
  └── Cosmos DB audit record
        │
        ▼
Human Review (Purview UI — approve or reject)
```

No component may bypass this flow. The Orchestrator is never called directly by Purview or by Event Grid.

---

## 3. Integration Rules

- The orchestrator must not directly integrate with external metadata systems.
- External systems must export to Blob Storage.

**Allowed integration model:**

```
Synergy → JSON export → Blob Storage (/synergy/)
Zipline → JSON export → Blob Storage (/zipline/)
Docs    → Blob Storage (/documentation/)
Blob Storage → Azure AI Search index (metadata-context-index)
```

The orchestrator retrieves context only through Azure AI Search.

Direct API calls to Synergy or Zipline are **forbidden**.

---

## 4. AI Search Architecture

The solution must use a **single unified index**.

**Index name:** `metadata-context-index`

**Mandatory fields:**

| Field | Purpose |
|---|---|
| `id` | Primary key |
| `source` | Origin of context (synergy, zipline, documentation) |
| `content` | Searchable text |
| `contentVector` | Embedding vector (1536 dimensions, HNSW) |
| `elementName` | Metadata element |
| `elementType` | Asset type |
| `description` | Source description |
| `cedsLink` | CEDS reference |
| `sourceSystem` | System identifier |
| `lastUpdated` | Freshness indicator |

This schema must not be modified without architecture review.

---

## 5. RAG Retrieval Strategy

Context retrieval must follow a **hybrid search model**.

| Retrieval Method | Purpose |
|---|---|
| Vector search (1536d, HNSW) | Semantic similarity |
| Keyword search | Exact field names and terminology |
| Hybrid reranking | Composite score: relevance × source_weight × freshness_factor |

Ranking signals: vector relevance, keyword match, source reliability, freshness (90-day half-life decay).

The orchestrator must retrieve top N context chunks before generation.

---

## 6. Prompt Construction Contract

Prompts must be **deterministic and structured**.

Mandatory prompt components:

| Component | Description |
|---|---|
| Purview metadata | Asset name, schema, fields |
| AI Search context | Retrieved chunks with source attribution |
| Documentation rules | Business definitions |
| CEDS references | When available |
| Output format | Structured YAML (mandatory) |

**Free-form prompt structures are not allowed.**

Prompt template is frozen at `contracts/prompts/v1-metadata-enrichment.prompt.yaml` (v1.0.0).

---

## 7. LLM Generation Rules

Default model configuration:

| Parameter | Value |
|---|---|
| Model | GPT-4.x (latest available) |
| Temperature | 0.1 |
| Max tokens | 1024 |
| Calls per asset | 1 (no batching in current implementation) |

The system must prioritize deterministic outputs.

Responses must use structured YAML format as defined in `contracts/outputs/v1-metadata-enrichment.output.yaml`.

> **Note on batching:** Grouping multiple assets per LLM call is a planned future optimization. It is not implemented and must not be assumed to be active.

---

## 8. Validation Pipeline

All AI outputs must pass validation before writeback.

**Implementation (two-stage):**

| Stage | Component | Type |
|---|---|---|
| 1a | `StructuralValidator` | Blocking — YAML format, required fields, types, length, confidence enum |
| 1b | `SemanticValidator` | Blocking — forbidden phrases, grounding, source attribution, no external knowledge |
| 2 | `OutputValidator` (runtime) | Blocking rules V001–V040 + Advisory flags A001–A005 |

**Invalid outputs (BLOCK status) must not be written to Purview.** Rejection is recorded in Cosmos DB `audit`.

---

## 9. Writeback Strategy

The system must use Purview **Suggested Description** workflow.

| Rule | Description |
|---|---|
| AI output destination | `AI_Enrichment.suggested_description` only |
| HTTP method | POST to `/datamap/api/atlas/v2/entity/guid/{guid}/businessmetadata` |
| Human approval | Mandatory before any AI suggestion becomes official |
| Official description | Updated only after human approval — never by the system |

This guarantees human-governed metadata. The AI system never writes to `entity.description`.

---

## 10. State Store and Change Detection

State tracking must use **Cosmos DB**.

**Containers:**

| Container | Partition Key | TTL | Purpose |
|---|---|---|---|
| `state` | `entityType` | 7 days | Asset hash + lifecycle state |
| `audit` | `entityType` | 180 days | Immutable pipeline audit trail |

Mandatory change detection process:

1. Retrieve asset metadata from Purview
2. Normalize metadata (exclude volatile fields: `lastUpdated`, `schemaVersion`, `scanId`, `ingestionTime`, `_*`)
3. Compute SHA-256 hash of normalized, sorted material fields
4. Compare with stored hash:

| Condition | Action |
|---|---|
| No record in Cosmos | REPROCESS (new asset) |
| Hash matches stored | SKIP (no LLM call) |
| Hash differs | REPROCESS (metadata changed) |

This prevents redundant processing and eliminates unnecessary LLM calls.

> **TTL Note:** The 7-day TTL on the `state` container means assets inactive for more than 7 days will lose their stored state and be treated as new on the next enrichment trigger. This is a known architectural trade-off.

---

## 11. Security Model

- All services must use **Managed Identity** (`DefaultAzureCredential`).
- No hardcoded credentials, connection strings, or API keys in source code.
- RBAC must enforce least privilege across: Service Bus, Cosmos DB, Blob Storage, Azure AI Search, Purview, Azure OpenAI.
- The Azure Functions bridge uses the same Managed Identity model.

---

## 12. Infrastructure Governance

All infrastructure must be deployed using Infrastructure as Code.

| Allowed Tool |
|---|
| Bicep |

**Manual Azure Portal changes are forbidden** except for break-glass recovery scenarios.

The AI Search index schema is version-controlled in `infra/search/schemas/metadata-context-index.json` and deployed via Bicep deployment scripts.

---

## 13. Forbidden Changes

Agents must **never**:

| Forbidden Action |
|---|
| Modify AI Search index schema without architecture review |
| Redesign enrichment pipeline |
| Change RAG retrieval architecture |
| Introduce direct API calls to Synergy or Zipline |
| Bypass validation layer |
| Write directly to Purview official description (`entity.description`) |
| Alter Cosmos state schema |
| Modify frozen contracts in `/contracts/` |
| Remove or weaken security controls |
| Add Azure resources via Portal (IaC only) |
| Change the canonical data flow |
| Introduce new LLM providers without review |
| Skip phases in the Execution Plan |
| Remove or bypass the Azure Functions bridge components |

---

## 14. Allowed Changes

Agents may perform only:

| Allowed Action | Condition |
|---|---|
| Bug fixes | Must not alter architecture or contracts |
| Environment configuration | Must use IaC tooling |
| RBAC corrections | Must follow least-privilege principle |
| Infrastructure provisioning | Must use Bicep |
| Validation improvements | Must not weaken existing validation rules |
| Test additions | Must follow existing test patterns |
| Documentation updates | Must not contradict architecture |
| Prompt tuning | Temperature 0.0–0.2, structured YAML output only |

**Architecture changes require explicit human approval.**

---

## 15. Azure Functions Bridge — Immutable Components

The `HeuristicTriggerBridge` and `UpstreamRouterFunction` are required components of the canonical data flow.

**These functions must not be:**
- Removed or disabled without replacing the trigger ingestion path
- Bypassed so that the Orchestrator directly consumes from Event Hub
- Modified to write directly to `enrichment-requests` without going through `purview-events` first (unless a formal ADR approves collapsing the two-stage bridge)

**The two-queue design (`purview-events` → `enrichment-requests`) is intentional:**
- `purview-events` receives raw Purview telemetry (high volume, mixed event types)
- `enrichment-requests` receives only validated, transformed enrichment requests
- The separation allows independent scaling, filtering logic changes, and routing evolution without touching the Orchestrator
