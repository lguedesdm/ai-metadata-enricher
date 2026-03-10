# 0005 Cosmos DB Partition Key: entityType

## Status

Accepted

## Date

2026-03-09

## Decision Makers

- Engineering (INF-014)

## Context

The Cosmos DB `state` container requires a partition key. Two values appeared in the codebase:

- `asset_type` — in `runtime_architecture_contract.yaml` (both repos)
- `entityType` — in all runtime code and IaC (50+ consistent references)

The contract value `asset_type` was never implemented anywhere. The runtime (`cosmos_state_store.py`, `lifecycle.py`, `message_handler.py`, and others) universally uses `entityType` as both the Cosmos document field name and the partition key value passed to every read/write operation. The IaC (`infra/cosmos/containers.bicep`, `infra/main.bicep`) already provisions the containers with partition key `/entityType`.

## Considered Options

### Option 1: `entityType`

Keep the value used by all existing runtime code and IaC.

**Pros**:
- Already implemented — no code changes required
- Consistent with Purview's entity classification vocabulary
- Cosmos documents already contain the `entityType` field at root level

**Cons**:
- None — this is the current deployed state

### Option 2: `asset_type`

Rename to match the contract's original (incorrect) value.

**Pros**:
- None — would require changes across 50+ runtime callsites and rewriting deployed containers

**Cons**:
- Massive runtime refactor with no functional benefit
- Breaking change on any deployed container (partition key is immutable after creation)

## Decision

**`entityType`** is the canonical partition key for the `state` container (Cosmos DB path: `/entityType`).

The `asset_type` value in `runtime_architecture_contract.yaml` was a documentation error that was never propagated to code or IaC. The contract is corrected to match the deployed and implemented reality.

No runtime code, IaC, or container schema changes are required — they are already correct.

## Consequences

### Positive Consequences

- Contract, runtime, and IaC are now fully aligned
- Architecture drift detector (`infra_contract_validator.py`) will pass without false positives

### Negative Consequences

- None

## Follow-up Actions

- [x] Update `runtime_architecture_contract.yaml` in `ai-metadata-enricher` (line 141)
- [x] Update `runtime_architecture_contract.yaml` in `ai-metadata-enricher-infra` (line 141)

## Related Decisions

- ADR-0002: Schema contract freeze v1
- INF-001: Cosmos DB database name correction (`metadata` → `metadata_enricher`)

---

**Last Updated**: 2026-03-09
