# AI Metadata Enricher — Architecture Guardrails

> **Status:** Immutable Engineering Constraints
> **Version:** 1.0
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

Any code implementation must remain compliant with all four documents.

The architecture must be treated as frozen unless explicitly changed by the project owner.

---

## 2. Core Architectural Pattern (Must Not Change)

The platform follows a unified RAG enrichment architecture.

**Canonical flow:**

```
Purview Scan Event
        ↓
Event Grid
        ↓
Service Bus
        ↓
Enrichment Orchestrator (Container App)
        ↓
Azure AI Search (RAG context retrieval)
        ↓
Azure OpenAI (description generation)
        ↓
Purview Suggested Description
        ↓
Cosmos DB (state + audit)
```

The orchestrator acts as the central processing engine and must mediate between Purview metadata and AI Search context retrieval.

No component may bypass this flow.

---

## 3. Integration Rules

- The orchestrator must not directly integrate with external metadata systems.
- External systems must export to Blob Storage.

**Allowed integration model:**

```
Synergy → JSON export → Blob Storage
Zipline → JSON export → Blob Storage
Docs → Blob Storage
Blob Storage → Azure AI Search index
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
| `source` | Origin of context |
| `content` | Searchable text |
| `contentVector` | Embedding vector |
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
| Vector search | Semantic similarity |
| Keyword search | Exact field names |
| Hybrid ranking | Merged ranking |

Ranking signals: vector relevance, keyword match, source reliability, freshness.

The orchestrator must retrieve top N context chunks before generation.

---

## 6. Prompt Construction Contract

Prompts must be **deterministic and structured**.

Mandatory prompt components:

| Component | Description |
|---|---|
| Purview metadata | Asset name, schema, fields |
| AI Search context | Retrieved chunks |
| Documentation rules | Business definitions |
| CEDS references | When available |
| Output format | Structured YAML |

**Free-form prompt structures are not allowed.**

---

## 7. LLM Generation Rules

Default model configuration:

| Parameter | Value |
|---|---|
| Model | GPT-4 class model |
| Temperature | 0.0 – 0.2 |
| Max tokens | 512–1024 |

The system must prioritize deterministic outputs.

Responses must use structured YAML format.

---

## 8. Validation Pipeline

All AI outputs must pass validation before writeback.

| Validation Type | Purpose |
|---|---|
| Structural | Format, length |
| Semantic | Consistency with metadata |
| Safety | No sensitive inference |
| Confidence scoring | Quality estimation |

**Invalid outputs must not be written to Purview.**

---

## 9. Writeback Strategy

The system must use Purview **Suggested Description** workflow.

| Rule | Description |
|---|---|
| AI output destination | Suggested Description only |
| Human approval | Mandatory |
| Official description | Updated only after approval |

This guarantees human-governed metadata.

---

## 10. State Store and Change Detection

State tracking must use **Cosmos DB**.

Mandatory change detection process:

1. Retrieve asset metadata from Purview
2. Compute SHA-256 hash
3. Compare with stored hash
4. Decide:

| Condition | Action |
|---|---|
| No record | Enrich |
| Same hash | Skip |
| Different hash | Enrich |

This prevents redundant processing and reduces OpenAI calls.

---

## 11. Security Model

- All services must use **Managed Identity**.
- No hardcoded credentials are allowed.
- RBAC must enforce least privilege across: Service Bus, Cosmos DB, Blob Storage, Azure AI Search, Purview, Azure OpenAI.

---

## 12. Infrastructure Governance

All infrastructure must be deployed using Infrastructure as Code.

| Allowed Tool |
|---|
| Bicep |
| Terraform |

**Manual Azure Portal changes are forbidden** except for break-glass recovery scenarios.

---

## 13. Forbidden Changes

Agents must **never**:

| Forbidden Action |
|---|
| Modify AI Search schema without architecture review |
| Redesign enrichment pipeline |
| Change RAG retrieval architecture |
| Introduce direct API calls to Synergy or Zipline |
| Bypass validation layer |
| Write directly to Purview official description |
| Alter Cosmos state schema |
| Modify frozen contracts |

---

## 14. Allowed Changes

Agents may perform only:

| Allowed Action |
|---|
| Bug fixes |
| Environment configuration |
| RBAC corrections |
| Infrastructure provisioning |
| Validation improvements |

**Architecture changes require explicit human approval.**
