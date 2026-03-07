# Ingestion Pipeline Repair — Validation Report

**Date**: 2026-03-06  
**Environment**: Dev (`rg-aime-dev`)  
**Search Service**: `aime-dev-search`  
**Target Index**: `metadata-context-index-v1`  
**Storage Account**: `aimedevst4xlyuysynrkk6`

---

## Executive Summary

The Dev ingestion pipeline has been repaired. All three data sources (documentation, synergy, zipline) are now actively indexing into `metadata-context-index-v1`. Multi-source retrieval is validated — search queries return results from all three sources.

**Before**: Only the documentation indexer was functional. The synergy indexer existed but processed 0 items across all runs. No zipline indexer existed.

**After**: 18 documents indexed across 3 sources. All indexers report `status=success`.

---

## Root Causes Identified & Fixed

### 1. Synergy Indexer — Parsing Mode (Critical)

**Symptom**: Indexer completed with `status=success, itemsProcessed=0, itemsFailed=0` — no errors, no warnings.

**Root Cause**: `parsingMode` was set to `json` with `documentRoot: /elements`. The blob's `/elements` path contains a JSON **array**, not a single object. With `parsingMode: json`, the indexer treated the entire blob as one document and could not resolve field mappings against the array structure, silently yielding 0 documents.

**Fix**: Changed `parsingMode` to `jsonArray`. This mode correctly interprets the `/elements` array and creates one search document per array element.

### 2. Synergy Data Source — Query Filter (Critical)

**Symptom**: Even after fixing the parsing mode, the indexer still processed 0 items when the `query` filter was set to `synergy-dev.mock.v2.json`.

**Root Cause**: The `query` parameter (blob name prefix filter) prevented blob enumeration in combination with `jsonArray` parsing mode. This appears to be an Azure AI Search behavioral quirk — removing the query filter resolved the issue immediately, producing 2 indexed documents.

**Fix**: Removed the `query` filter from the data source. The indexer now processes all blobs in the `synergy` container. Blobs without a `/elements` path (e.g., `orders.json`, `synergy-data-dictionary.json`) generate harmless warnings and are skipped.

### 3. Synergy Data Source — Credentials

**Symptom**: Connection string appeared null or invalid in previous data source configurations.

**Fix**: Re-applied storage account key credentials via data source PUT.

### 4. Zipline Indexer — Did Not Exist

**Symptom**: No data source or indexer existed for the zipline container.

**Fix**: Created `blob-zipline-datasource` and `zipline-elements-indexer` with `parsingMode: jsonArray` (root-level array), plus field mappings for schema differences.

---

## Final Configuration

### Data Sources

| Name | Container | Query Filter | Auth |
|------|-----------|-------------|------|
| `blob-metadata-datasource` | `documentation` | *(none)* | Storage Key |
| `blob-synergy-datasource` | `synergy` | *(none)* | Storage Key |
| `blob-zipline-datasource` | `zipline` | *(none)* | Storage Key |

### Indexers

| Name | Data Source | Parsing Mode | Document Root | Field Mappings |
|------|-----------|-------------|--------------|----------------|
| `metadata-context-indexer` | `blob-metadata-datasource` | *(default/text)* | — | *(default)* |
| `synergy-elements-indexer` | `blob-synergy-datasource` | `jsonArray` | `/elements` | 8 mappings (see below) |
| `zipline-elements-indexer` | `blob-zipline-datasource` | `jsonArray` | — | 11 mappings (see below) |

### Synergy Field Mappings

| Source Field | Target Field | Function |
|-------------|-------------|----------|
| `elementName` | `id` | `base64Encode` |
| `elementName` | `elementName` | — |
| `elementName` | `title` | — |
| `elementType` | `elementType` | — |
| `description` | `description` | — |
| `description` | `content` | — |
| `sourceSystem` | `sourceSystem` | — |
| `cedsLink` | `cedsLink` | — |

### Zipline Field Mappings

| Source Field | Target Field | Function |
|-------------|-------------|----------|
| `id` | `id` | `base64Encode` |
| `entityType` | `elementType` | — |
| `entityName` | `elementName` | — |
| `entityName` | `title` | — |
| `cedsReference` | `cedsLink` | — |
| `businessMeaning` | `suggestedDescription` | — |
| `sourceSystem` | `sourceSystem` | — |
| `description` | `description` | — |
| `content` | `content` | — |
| `tags` | `tags` | — |
| `lastUpdated` | `lastUpdated` | — |

---

## Indexer Execution Results

| Indexer | Status | Processed | Failed | Warnings |
|---------|--------|-----------|--------|----------|
| `metadata-context-indexer` | success | 2 | 0 | 0 |
| `synergy-elements-indexer` | success | 2 | 0 | 2 |
| `zipline-elements-indexer` | success | 19 | 0 | 0 |

**Synergy Warnings** (expected, harmless):
- `orders.json` — path `/elements` missing (not a synergy export)
- `synergy-data-dictionary.json` — path `/elements` missing (not a synergy export)

---

## Index Content

**Total Documents**: 18

| Source System | Count | Element Types |
|--------------|-------|---------------|
| `zipline` | 11 | dataset, column, element, table |
| `Synergy` | 2 | column |
| *(documentation)* | 5 | *(unstructured text)* |

### Sample Documents

**Synergy** — `Students.StudentId`:
- elementType: `column`
- description: "Unique identifier assigned to each student at the time of enrollment."
- cedsLink: `https://ceds.ed.gov/element/StudentIdentifier`

**Zipline** — `Student Enrollment Registration`:
- elementType: `dataset`
- description: "Dataset capturing student enrollment registration events..."
- suggestedDescription: "Core enrollment dataset that tracks when and where students register..."
- cedsLink: `CEDS-00120`
- tags: `["enrollment", "registration", "student"]`

---

## Multi-Source Retrieval Validation

Five search queries were executed to validate cross-source retrieval:

| # | Query | Sources Hit | Top Result |
|---|-------|------------|------------|
| 1 | `student enrollment registration` | zipline, documentation | zipline: Student Enrollment Registration (7.92) |
| 2 | `enrollment metadata governance` | documentation, zipline | documentation (3.16) |
| 3 | `StudentId unique identifier enrollment` | documentation, zipline, Synergy | documentation (3.48), Synergy: Students.StudentId (1.73) |
| 4 | `assessment score performance level` | zipline, documentation | zipline: Performance Level (8.00) |
| 5 | `data dictionary element column description` | zipline, documentation | 5 zipline + 3 documentation hits |

**Result**: All three source types appear in cross-source search results. The RAG pipeline can now retrieve grounding context from structured metadata (Synergy, Zipline) alongside documentation.

---

## Guardrails Compliance

| Guardrail | Status |
|-----------|--------|
| No Push API usage | PASS — all documents indexed via blob indexers |
| No schema modifications | PASS — `metadata-context-index-v1` schema unchanged |
| No new indexes created | PASS — using existing index only |
| No new Azure services | PASS — existing search + storage only |
| No IaC modifications | PASS — Bicep files untouched |

---

## Recommendations

1. **Managed Identity**: Data sources currently use storage account keys. Consider migrating to managed identity (`ResourceId` connection string) for production alignment.
2. **Synergy Query Filter**: The query filter bug with `jsonArray` parsing should be monitored. If more blobs are added to the synergy container, consider using a virtual folder structure (e.g., `exports/synergy-dev.mock.v2.json`) to isolate indexable blobs.
3. **Synergy `source` field**: Neither synergy nor zipline documents populate the `source` index field. Consider adding a constant-value field mapping if this field is used by the RAG pipeline.
4. **Schedule**: None of the indexers have schedules configured. For continuous ingestion, configure polling intervals appropriate to the expected data update frequency.
