# AI Metadata Enricher — Architecture Contract

> **Status:** Immutable
> **Version:** 1.0
> **Authority:** This contract synthesizes binding rules from the LLM Metadata Architecture, Execution Plan, and Architecture Guardrails.

---

## Purpose

This document defines the **non-negotiable architecture rules**, **prohibited changes**, **decision hierarchy**, and **agent compliance requirements** for the AI Metadata Enricher repository.

All contributors — human or automated — must comply with this contract before proposing or implementing any change.

---

## 1. Decision Hierarchy

Architecture decisions follow a strict precedence order:

| Priority | Authority | Scope |
|---|---|---|
| 1 | LLM Metadata Architecture (`architecture/architecture.md`) | System design, data flow, component inventory |
| 2 | Architecture Guardrails (`architecture/architecture_guardrails.md`) | Immutable engineering constraints |
| 3 | Execution Plan (`architecture/execution_plan.md`) | Phased delivery milestones and completion criteria |
| 4 | Schema Contracts (`contracts/`) | Frozen interface definitions |
| 5 | ADRs (`docs/adr/`) | Individual design decisions |

In case of conflict, higher-priority documents take precedence.

---

## 2. Immutable Architecture Rules

The following rules cannot be overridden by any contributor or agent:

### 2.1 Data Flow Integrity

- The canonical flow (Purview → Event Grid → Service Bus → Orchestrator → AI Search → OpenAI → Purview → Cosmos DB) must not be altered.
- No component may bypass the orchestrator.
- External systems (Synergy, Zipline) must integrate only via Blob Storage exports.

### 2.2 Single Index Rule

- All context retrieval must use the unified `metadata-context-index` in Azure AI Search.
- No secondary or shadow indexes are permitted without architecture review.

### 2.3 RAG-Only Context

- The orchestrator must retrieve context exclusively through Azure AI Search (hybrid search: vector + keyword + hybrid ranking).
- Direct database queries or API calls for context retrieval are prohibited.

### 2.4 LLM Output Governance

- All AI-generated output must pass the 4-layer validation pipeline (structural, semantic, safety, confidence scoring) before any writeback.
- AI output must target Purview **Suggested Description** only — never the official description.
- Human approval is mandatory before any AI suggestion becomes an official description.

### 2.5 State Management

- Cosmos DB is the single source of truth for asset processing state.
- Change detection uses SHA-256 hashing to determine SKIP or ENRICH decisions.
- No alternative state management mechanism is permitted.

### 2.6 Security

- All service-to-service authentication must use Managed Identity.
- Hardcoded credentials, connection strings, or API keys in source code are prohibited.
- RBAC with least-privilege principle applies to all Azure resources.

### 2.7 Infrastructure

- All infrastructure must be defined as code (Bicep or Terraform).
- Manual Azure Portal changes are forbidden except for break-glass emergency recovery.

---

## 3. Prohibited Changes

The following changes are **explicitly forbidden** without written approval from the project owner:

| # | Prohibited Action | Rationale |
|---|---|---|
| 1 | Modify AI Search index schema | Schema is frozen under contract |
| 2 | Redesign the enrichment pipeline | Architecture is locked |
| 3 | Change RAG retrieval architecture | Hybrid search model is mandatory |
| 4 | Introduce direct API calls to Synergy/Zipline | Integration must go through Blob Storage |
| 5 | Bypass the validation layer | All outputs must be validated |
| 6 | Write directly to Purview official description | Only Suggested Description is allowed |
| 7 | Alter Cosmos DB state schema | State contract is frozen |
| 8 | Modify frozen contracts in `/contracts/` | Contracts are versioned and immutable |
| 9 | Remove or weaken security controls | Managed Identity and RBAC are mandatory |
| 10 | Add new Azure resources via portal | IaC governance is mandatory |
| 11 | Change the canonical data flow | Flow is architecturally locked |
| 12 | Introduce new LLM providers without review | Model configuration is constrained |
| 13 | Skip phases in the Execution Plan | Phased delivery is mandatory |

---

## 4. Permitted Changes

The following changes are allowed within the existing architecture:

| # | Permitted Action | Condition |
|---|---|---|
| 1 | Bug fixes | Must not alter architecture or contracts |
| 2 | Environment configuration | Must use IaC tooling |
| 3 | RBAC corrections | Must follow least-privilege principle |
| 4 | Infrastructure provisioning | Must use Bicep/Terraform |
| 5 | Validation improvements | Must not weaken existing validation rules |
| 6 | Test additions | Must follow existing test patterns |
| 7 | Documentation updates | Must not contradict architecture documents |
| 8 | Prompt tuning | Must stay within LLM generation rules (temp 0.0–0.2, structured YAML output) |

---

## 5. Contract Freeze Policy

### 5.1 Frozen Artifacts

The following artifacts are frozen and must not be modified:

- Schema contracts in `/contracts/schemas/`
- Output contracts in `/contracts/outputs/`
- Validation contracts in `/contracts/validation/`
- Prompt contracts in `/contracts/prompts/`
- This architecture contract

### 5.2 Change Process

To modify any frozen artifact or architecture rule:

1. The change must be proposed in writing with rationale
2. An ADR must be created in `docs/adr/`
3. The project owner must provide explicit written approval
4. The change must be reflected in all affected architecture documents
5. Affected tests must be updated to validate the new behavior

---

## 6. Agent Compliance Requirements

### 6.1 Pre-Execution Check

Before performing any modification, an automated agent must:

1. Load all files in `/architecture/`
2. Verify the proposed change does not violate any rule in this contract
3. Verify the proposed change does not violate the guardrails
4. Verify the proposed change is consistent with the current execution plan phase

### 6.2 During Execution

While performing modifications, an automated agent must:

1. Track all changes made
2. Validate that each change remains within permitted boundaries
3. Stop immediately if a guardrail violation is detected
4. Report any architectural ambiguity to the human operator

### 6.3 Post-Execution

After completing modifications, an automated agent must:

1. Verify no frozen contracts were modified
2. Confirm the canonical data flow is intact
3. Ensure all new code follows existing patterns
4. Report a summary of changes made

---

## 7. Compliance Verification

Any contributor can verify compliance by checking:

- [ ] Does the change respect the canonical data flow?
- [ ] Does the change use only permitted integration patterns?
- [ ] Does the change comply with the single-index rule?
- [ ] Does the change pass through the validation pipeline?
- [ ] Does the change target only Suggested Description (not official)?
- [ ] Does the change use Managed Identity for authentication?
- [ ] Is the infrastructure defined as code?
- [ ] Does the change align with the current execution plan phase?
- [ ] Are all frozen contracts intact?

---

## References

- [Architecture](architecture.md)
- [Execution Plan](execution_plan.md)
- [Architecture Guardrails](architecture_guardrails.md)
- [Schema Contracts](../contracts/)
- [ADRs](../docs/adr/)
