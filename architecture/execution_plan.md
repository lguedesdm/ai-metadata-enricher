# AI Metadata Enricher — Execution Plan

> **Source:** Execution Plan Document (Authoritative)
> **Status:** Canonical — all task execution must follow this plan
> **Version:** 1.0

---

## Overview

This document defines the phased execution plan for the AI Metadata Enricher platform. Every implementation task must align with the milestones, scope boundaries, and completion criteria defined here.

---

## Phase 1 — Foundation (Completed)

### Infrastructure Provisioning

All Azure resources provisioned via Bicep IaC:
- Azure Container Apps environment
- Azure Service Bus namespace and queues
- Azure Cosmos DB (state + audit containers)
- Azure Blob Storage (synergy, zipline, documentation containers)
- Azure AI Search service and index
- Azure Key Vault
- Application Insights

### Orchestrator Implementation

- Service Bus consumer with peek-lock message processing
- SHA-256 change detection (asset-level hashing)
- Cosmos DB state and audit persistence
- Managed Identity authentication throughout
- Structured JSON logging with Application Insights integration

### Domain Logic

- Asset-level change detection: normalize → canonical JSON → SHA-256
- Decision logic: SKIP (unchanged) / REPROCESS (new or changed)
- Element splitter: blob JSON → ContextElement list
- Element identity: `base64Encode(element_name)`
- Element hashing: element-level SHA-256
- Element state comparison: deterministic SKIP/REPROCESS decisions
- Search document builder: ContextElement → index-aligned document
- Validation engine: structural + semantic validation of LLM output

---

## Phase 2 — Enrichment Clients and RAG Pipeline

### LLM Client (Azure OpenAI)
- **Scope:** Managed Identity wrapper for Azure OpenAI chat completions
- **Constraints:** No retries, no batching, no orchestration awareness
- **Status:** Implemented as inert, importable module
- **Validation:** Manual via `python -m scripts.validate_llm_client`

### Purview Client
- **Scope:** REST API client for Apache Atlas/Purview (GET entity, PATCH metadata)
- **Constraints:** Managed Identity only, no secrets
- **Status:** Implemented as inert, importable module
- **Validation:** Manual via `python -m scripts.validate_purview_client`

### RAG Query Pipeline
- **Start:** Mar 17, 2026 | **End:** Mar 19, 2026 | **Duration:** 3 days
- **Scope:** Hybrid search queries against Azure AI Search, ranking/weighting/freshness logic, context assembly compatible with frozen prompt contracts
- **Exclusions:** No performance tuning, no embedding generation changes, no prompt or validation changes
- **Completion Criteria:**
  - Given an asset, relevant context can be retrieved deterministically
  - Context assembly integrates cleanly with the Orchestrator
  - No schema or index changes required
- **Status:** Implemented — 7 Python files, 61 test cases, all passing

### Validation Engine Runtime Integration
- **Start:** Mar 20, 2026 | **End:** Mar 20, 2026 | **Duration:** 1 day
- **Scope:** Runtime invocation of validation engine, blocking vs advisory rules enforcement
- **Exclusions:** No rule changes, no scoring optimization
- **Completion Criteria:**
  - Invalid LLM output reliably rejected
  - Valid output passes unchanged
  - Validation results auditable and logged
- **Status:** Implemented — 34 tests, all passing

### Purview Integration — Write-back and Lifecycle
- **Start:** Mar 23, 2026 | **End:** Mar 27, 2026 | **Duration:** 5 days
- **Scope:** Write-back to Suggested Description attribute, lifecycle handling (pending/approved/rejected), error handling and traceability
- **Exclusions:** No approval workflow automation, no human UI changes
- **Completion Criteria:**
  - Exactly one asset can be written to Purview safely
  - No overwrite of authoritative metadata
  - Full traceability between Orchestrator, Cosmos, and Purview
- **Status:** Implemented — 74 tests, all passing

---

## Phase 3 — End-to-End Flow Validation

### End-to-End Flow Validation with Controlled Mock Context
- **Start:** Mar 30, 2026 | **End:** Mar 31, 2026 | **Duration:** 2 days
- **Objective:** Validate single real end-to-end execution under controlled Dev conditions

**Required validations:**
- RAG retrieval functions correctly with Synergy + Zipline + Blob documentation
- Context assembly is accurate
- Exactly one LLM invocation occurs
- Semantic validation is enforced
- Suggested Description is written back to Purview
- Audit records persisted in Cosmos DB
- Single correlation ID links all components

**Mock Data Requirements:**
- Azure SQL Database with test tables (Students, ARC01_TBL_A, EnrollmentAudit)
- Synergy mock JSON export → uploaded to Blob Storage synergy container
- Zipline mock JSON export → uploaded to Blob Storage zipline container
- Documentation markdown files → uploaded to Blob Storage documentation container
- All data indexed in Azure AI Search

**Completion Criteria:**

| Validation Area | Required Condition |
|---|---|
| Asset Processing | Exactly one asset processed |
| LLM Invocation | Exactly one invocation |
| Purview Update | Suggested Description updated, official Description unchanged |
| State Store | State container updated |
| Audit Store | Audit record persisted with model, tokens, validation result |
| Correlation | Single correlation ID across logs, Cosmos, and write-back |

If more than one asset is processed or more than one LLM invocation occurs, the task fails.

**Exclusions:** No batch execution, retry simulation, failure injection, load testing, performance tuning, scaling, prompt optimization, or approval workflow.

---

## Phase 4 — Integration Testing

### Integration Testing — Dev
- **Start:** Apr 1, 2026 | **End:** Apr 9, 2026 | **Duration:** 7 days
- **Scope:** Full system behavior under multi-asset scenarios and failure conditions
- **Inclusions:** Full end-to-end flow testing, failure scenarios and DLQ validation, retry and error propagation checks
- **Completion Criteria:**
  - System behaves deterministically under success and failure
  - No data corruption or silent failure
  - Observability supports root-cause analysis

### Dev Closure
- **Start:** Apr 10, 2026 | **End:** Apr 13, 2026 | **Duration:** 2 days
- **Scope:** Formal closure of the Dev phase
- **Inclusions:** Technical documentation, internal handoff, Dev readiness sign-off
- **Completion Criteria:**
  - Architecture, behavior, and contracts documented
  - Team aligned on Test/Prod promotion readiness

---

## Safety and Scope Constraints

All tasks must respect the following constraints:

1. **No orchestration code may be modified** unless the task explicitly targets it
2. **No domain logic may be modified** unless the task explicitly targets it
3. **No prompts or validation rules may be changed** — all contracts are frozen
4. **No enrichment flow may be executed automatically** — clients are inert importable modules
5. **Each task must produce a validation report** confirming scope compliance
6. **Each module must be architecturally isolated** — verified via AST-based import analysis in tests

---

## Module Delivery Status

| Module | Layer | Tests | Status |
|---|---|---|---|
| Orchestrator (consumer, handler, state) | `src/orchestrator/` | 50+ | Delivered |
| Change Detection (hash, decision) | `src/domain/change_detection/` | 31 | Delivered |
| Element Splitter | `src/domain/element_splitter/` | 20+ | Delivered |
| Element Hashing | `src/domain/element_hashing/` | 20+ | Delivered |
| Element State Comparison | `src/domain/element_state/` | 15+ | Delivered |
| Search Document Builder | `src/domain/search_document/` | 15+ | Delivered |
| Validation Engine | `src/domain/validation/` | 20+ | Delivered |
| LLM Client | `src/enrichment/llm_client.py` | — | Delivered (inert) |
| Purview Client | `src/enrichment/purview_client.py` | — | Delivered (inert) |
| RAG Query Pipeline | `src/enrichment/rag/` | 61 | Delivered |
| Output Validator (Runtime) | `src/enrichment/output_validator.py` | 34 | Delivered |
| Purview Write-back + Lifecycle | `src/enrichment/purview_writeback.py` | 74 | Delivered |
| Search Writer | `src/infrastructure/search_writer/` | 15+ | Delivered |
| State Writer | `src/infrastructure/state_store/` | 10+ | Delivered |
| Deterministic Runner | `src/indexing/validation/` | 30+ | Delivered |
