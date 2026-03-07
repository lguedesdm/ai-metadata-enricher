# Architectural Correction Report — Enrichment Pipeline Alignment

**Date:** 2025-07-22  
**Scope:** Align enrichment pipeline code with deployed Azure AI Search index  
**Index:** `metadata-context-index-v1` on `aime-dev-search`  
**Status:** ✅ COMPLETE — 703 tests passing

---

## 1. Summary

The enrichment pipeline code was written against the **v1.1.0 frozen design** (19 fields,
`{source}::{type}::{name}` IDs), but the **deployed index** has **13 fields** and
indexers generate IDs via `base64Encode(elementName)`.

This correction aligns all enrichment code to the **deployed index as the source of truth**.

---

## 2. Files Modified

### Production Code

| File | Change |
|------|--------|
| `src/domain/element_splitter/element_identity.py` | Rewrote ID generation: `base64Encode(element_name)` instead of `{source}::{type}::{name}` |
| `src/domain/element_splitter/__init__.py` | Added `normalise_source_system` export |
| `src/domain/search_document/models.py` | `SCHEMA_FIELDS`: 19 → 13 fields. Removed `SCHEMA_VERSION`. Updated `CONTENT_TEMPLATE` |
| `src/domain/search_document/builder.py` | Field mapping aligned to deployed index |
| `src/domain/search_document/__init__.py` | Removed `SCHEMA_VERSION` export |
| `src/indexing/validation/deterministic_runner.py` | Entity type from `element.element_type` instead of `element_id.split("::")` |
| `src/indexing/validation/integration_validator.py` | Schema contract updated to 13 fields. ID format check simplified |
| `src/infrastructure/state_store/state_writer.py` | `_extract_entity_type` deprecated (returns `""` for base64 IDs) |
| `src/domain/validation/structural_validator.py` | Fixed pre-existing bug: array items with `:` misrecognised as top-level keys |

### Test Code

| File | Change |
|------|--------|
| `tests/test_element_identity.py` | Completely rewritten — tests base64 IDs, `normalise_source_system` |
| `tests/test_search_document_builder.py` | Completely rewritten — 13-field schema, backward-compat payload mapping |
| `tests/indexing/test_element_indexing_integration.py` | Updated: ID format, schema count, entity type assertions |
| `tests/test_element_hashing.py` | Removed `::` assertion from ID check |
| `tests/test_element_state_comparison.py` | Updated: same name across source systems → same ID (by design) |
| `tests/test_element_state_update.py` | Updated: entity type extraction, base64 element IDs |

---

## 3. Field Mapping

### Removed Fields (in v1.1.0 design but NOT in deployed index)

| Old Field | Disposition |
|-----------|-------------|
| `entityType` | **Renamed** → `elementType` |
| `entityName` | **Renamed** → `elementName` |
| `businessMeaning` | **Renamed** → `suggestedDescription` |
| `cedsReference` | **Renamed** → `cedsLink` |
| `entityPath` | **Dropped** — not in deployed index |
| `domain` | **Dropped** — not in deployed index |
| `dataType` | **Dropped** — not in deployed index |
| `sourceTable` | **Dropped** — not in deployed index |
| `lineage` | **Dropped** — not in deployed index |
| `schemaVersion` | **Dropped** — not in deployed index |
| `blobPath` | **Dropped** — not in deployed index |
| `originalSourceFile` | **Dropped** — not in deployed index |

### Added Fields (in deployed index but NOT in v1.1.0 code)

| New Field | Source |
|-----------|--------|
| `source` | `payload.get("source")` |
| `title` | `element.element_name` (defaults to element name) |
| `suggestedDescription` | `payload.get("businessMeaning") or payload.get("suggestedDescription")` |

### Deployed Schema (13 fields)

```
id, sourceSystem, source, elementType, elementName, title, description,
suggestedDescription, content, contentVector, tags, cedsLink, lastUpdated
```

---

## 4. ID Generation Strategy

| Component | Strategy | Match? |
|-----------|----------|--------|
| **Enrichment pipeline** (new) | `base64Encode(element_name)` | — |
| **Synergy indexer** | `base64Encode(/document/elementName)` | ✅ MATCH |
| **Zipline indexer** | `base64Encode(/document/id)` where id ≠ elementName | ⚠️ MISMATCH |
| **Documentation indexer** | `base64Encode(blob_URL)` | ⚠️ MISMATCH |

### Collision Safety Check Result

- **Synergy:** Enrichment IDs will match indexed document IDs (same `elementName` → same base64).
- **Zipline:** Enrichment IDs will **NOT** match indexed document IDs. The indexer uses `base64Encode(source_json_id)` where `id` is a dotted path like `zipline.enrollment.registration.dataset`, while enrichment uses `base64Encode(element_name)` where `element_name` is a human-readable name like `Student Enrollment Registration`. **These create different documents.**
- **Documentation:** Enrichment IDs will **NOT** match indexed document IDs. The indexer uses blob URLs, not element names.

### Impact Assessment

The zipline and documentation ID mismatch means:
- Enrichment updates for zipline/documentation elements will create **new** documents in the index rather than updating existing ones.
- This is a **known gap** that requires a follow-up decision:
  - Option A: Align enrichment ID generation per source system (synergy=elementName, zipline=source_id, documentation=blobURL)
  - Option B: Align indexer field mappings to use elementName for all sources
  - Option C: Accept dual documents (indexer-created + enrichment-created)

---

## 5. sourceSystem Normalisation

| Before | After |
|--------|-------|
| Mixed case ("Synergy", "zipline") | Always lowercase (`synergy`, `zipline`, `documentation`) |

`normalise_source_system()` enforces allowed values: `{synergy, zipline, documentation}`.

---

## 6. Backward Compatibility

The builder accepts **both** old and new payload field names:

| Payload Field | Maps To |
|--------------|---------|
| `businessMeaning` | `suggestedDescription` (takes precedence) |
| `suggestedDescription` | `suggestedDescription` (fallback) |
| `cedsReference` | `cedsLink` (takes precedence) |
| `cedsLink` | `cedsLink` (fallback) |

---

## 7. Example Document Output

```json
{
    "id": "U3R1ZGVudCBFbnJvbGxtZW50",
    "sourceSystem": "synergy",
    "source": "synergy-export-2026-03-01.json",
    "elementType": "table",
    "elementName": "Student Enrollment",
    "title": "Student Enrollment",
    "description": "Stores student enrollment records.",
    "suggestedDescription": "Core enrollment information for all students.",
    "content": "Element Type: table\nElement Name: Student Enrollment\n...",
    "contentVector": null,
    "tags": ["enrollment", "student", "core"],
    "cedsLink": "https://ceds.ed.gov/element/000123",
    "lastUpdated": "2026-01-12T10:00:00Z"
}
```

---

## 8. Test Results

```
703 passed in 1.92s
```

- `tests/schemas/test_schemas.py` excluded (pre-existing fixture error, unrelated)

---

## 9. Items NOT Changed (per guardrails)

- ❌ Index schema
- ❌ Indexers or data sources
- ❌ Blob storage layout
- ❌ IaC (Bicep files)
- ❌ Contracts directory
- ❌ RAG pipeline code
