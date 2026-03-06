# Enrollment Governance — Metadata Ownership and Data Lineage

## Governance Overview

Enrollment metadata is governed under the district's data governance framework. Ownership, stewardship, and quality responsibilities are clearly assigned to ensure that enrollment data meets accuracy, completeness, and timeliness standards required for state and federal reporting.

## Metadata Ownership

| Role | Responsibility |
|------|---------------|
| **Data Owner** | Director of Student Services — accountable for enrollment data accuracy and policy compliance. |
| **Data Steward** | Registrar's Office — responsible for day-to-day data entry, validation, and correction of enrollment records. |
| **Technical Steward** | Data Engineering Team — responsible for ETL pipelines, schema enforcement, and integration across source systems. |
| **Data Consumer** | Analytics and Reporting Teams — consume enrollment data for dashboards, funding calculations, and compliance reports. |

## Audit Logs and Traceability

Every enrollment record modification is tracked through audit logs that capture:

- **Who** made the change (user principal or system identity)
- **What** field was changed (e.g., `EnrollDate`, `WithdrawalCode`, campus assignment)
- **When** the change occurred (UTC timestamp)
- **Why** the change was made (reason code or free-text justification)

Audit logs are retained for a minimum of seven years to support state audit requirements and are immutable once written. The platform stores audit records in Cosmos DB with TTL policies aligned to retention requirements.

## Source Systems and Data Lineage

Enrollment metadata flows through the following lineage path:

1. **Synergy SIS** — Primary source of enrollment events. Exports nightly via structured JSON conforming to `synergy-export.schema.json`.
2. **Zipline Platform** — Secondary source providing assessment-linked enrollment context. Exports on-demand via `zipline-export.schema.json`.
3. **Ingestion Pipeline** — Service Bus queue receives export messages; the orchestrator validates schema compliance and writes to Cosmos DB.
4. **Metadata Enrichment** — The AI enrichment layer generates business descriptions, domain tags, and CEDS references using RAG-grounded LLM calls.
5. **Azure AI Search Index** — Enriched enrollment metadata is indexed for semantic search, enabling discovery across source systems.
6. **Purview Catalog** — Final enriched metadata is written back to Microsoft Purview for enterprise-wide lineage visibility.

## Data Quality Rules

The following quality rules apply to enrollment metadata:

- **Completeness**: `StudentId`, `EnrollDate`, and `Campus` must not be null.
- **Uniqueness**: No two active enrollment records may exist for the same student at the same campus with overlapping date ranges.
- **Timeliness**: Enrollment exports must be processed within 24 hours of generation.
- **Referential Integrity**: Every `StudentId` in enrollment must have a corresponding record in the student identity master.
- **Schema Compliance**: All exports must validate against the frozen contract schema before ingestion.

## Contribution to Data Lineage

Enrollment metadata contributes to the platform's end-to-end data lineage by:

- Providing the **origin node** for student-centric lineage graphs
- Linking enrollment events to downstream attendance, grades, and assessment records
- Enabling impact analysis when enrollment data definitions change
- Supporting audit trails that trace enriched metadata back to the original source record and enrichment pipeline run
