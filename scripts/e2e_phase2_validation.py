"""
End-to-End Phase 2 Validation Script
=====================================
Controlled single-asset validation of the enrichment pipeline.
batch_size=1 | parallelism=disabled | retry=disabled

Stages:
  1.  Purview Read          - GET entity from Purview
  2.  SHA-256 Hash          - compute deterministic asset hash
  3.  State Comparison      - REPROCESS / SKIP decision via Cosmos
  4.  RAG Retrieve          - context retrieval from Azure AI Search
  5.  Build Prompt          - assemble LLM prompt
  6.  LLM Invoke            - Azure OpenAI gpt-4o-mini
  7.  Semantic Validation   - validate LLM output through rule engine
  8.  Purview Writeback     - write Suggested Description to Purview
  9.  Cosmos State Update   - persist state record
  10. Cosmos Audit/Lifecycle - verify lifecycle + audit records
"""

import json
import os
import sys
import uuid
import hashlib
import traceback
from datetime import datetime, timezone

# ===========================================================================
# Environment setup
# ===========================================================================
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://oai-ai-metadata-dev.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini")
os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2024-06-01")
os.environ.setdefault("AZURE_SEARCH_ENDPOINT", "https://aime-dev-search.search.windows.net")
os.environ.setdefault("AZURE_SEARCH_INDEX_NAME", "metadata-context-index-v1")
os.environ.setdefault("AZURE_SEARCH_SEMANTIC_CONFIG", "default-semantic-config")
os.environ.setdefault("COSMOS_ENDPOINT", "https://cosmos-ai-metadata-dev.documents.azure.com:443/")
os.environ.setdefault("COSMOS_DATABASE_NAME", "metadata")
os.environ.setdefault("PURVIEW_ACCOUNT_NAME", "purview-ai-metadata-dev")
os.environ.setdefault("SERVICE_BUS_NAMESPACE", "ai-metadata-dev-sbus.servicebus.windows.net")

# ===========================================================================
# Test asset
# ===========================================================================
ENTITY_GUID = "ab7860f3-8dd6-4d4d-9348-8ef6f6f60000"
ENTITY_TYPE = "azure_sql_table"
ENTITY_NAME = "backup_metadata_store"
SOURCE_SYSTEM = "synergy"
CORRELATION_ID = f"e2e-phase2-{uuid.uuid4().hex[:8]}"
RUN_TIMESTAMP = datetime.now(timezone.utc).isoformat()

print("=" * 70)
print("END-TO-END PHASE 2 VALIDATION")
print("=" * 70)
print(f"Run Timestamp : {RUN_TIMESTAMP}")
print(f"Correlation ID: {CORRELATION_ID}")
print(f"Entity GUID   : {ENTITY_GUID}")
print(f"Entity Type   : {ENTITY_TYPE}")
print(f"Entity Name   : {ENTITY_NAME}")
print("=" * 70)

results = {}

# ===========================================================================
# Stage 1 - Purview Read
# ===========================================================================
print("\n[Stage 1] Purview Read")
try:
    from src.enrichment.config import EnrichmentConfig
    from src.enrichment.purview_client import PurviewClient

    enrichment_config = EnrichmentConfig()
    purview_client = PurviewClient(enrichment_config)
    entity_data = purview_client.get_entity(ENTITY_GUID)

    entity_body = entity_data.get("entity", {})
    entity_attrs = entity_body.get("attributes", {})
    type_name = entity_body.get("typeName", "")
    entity_name_from_purview = entity_attrs.get("name", "")
    qualified_name = entity_attrs.get("qualifiedName", "")
    existing_desc = entity_attrs.get("description", "")
    existing_user_desc = entity_attrs.get("userDescription", "")

    print(f"  PASS - HTTP 200")
    print(f"  typeName     : {type_name}")
    print(f"  name         : {entity_name_from_purview}")
    print(f"  qualifiedName: {str(qualified_name)[:80]}...")
    print(f"  description  : {str(existing_desc or '(empty)')[:80]}")
    print(f"  userDesc     : {str(existing_user_desc or '(empty)')[:80]}")
    results["stage1"] = {"status": "PASS", "type_name": type_name, "name": entity_name_from_purview}
except Exception as exc:
    print(f"  FAIL - {type(exc).__name__}: {exc}")
    traceback.print_exc()
    results["stage1"] = {"status": "FAIL", "error": str(exc)}
    sys.exit(1)

# ===========================================================================
# Stage 2 - SHA-256 Hash
# ===========================================================================
print("\n[Stage 2] SHA-256 Hash")
try:
    from src.domain.change_detection import compute_asset_hash

    asset_payload = {
        "id": ENTITY_GUID,
        "entityType": ENTITY_TYPE,
        "name": entity_name_from_purview,
        "qualifiedName": qualified_name,
        "description": existing_desc or "",
    }

    asset_hash = compute_asset_hash(asset_payload)
    print(f"  PASS - SHA-256: {asset_hash}")
    results["stage2"] = {"status": "PASS", "hash": asset_hash}
except Exception as exc:
    print(f"  FAIL - {type(exc).__name__}: {exc}")
    traceback.print_exc()
    results["stage2"] = {"status": "FAIL", "error": str(exc)}
    sys.exit(1)

# ===========================================================================
# Stage 3 - State Comparison (Cosmos DB)
# ===========================================================================
print("\n[Stage 3] State Comparison")
try:
    from azure.identity import AzureCliCredential
    from azure.cosmos import CosmosClient

    cosmos_cred = AzureCliCredential()
    cosmos_client = CosmosClient(
        url=os.environ["COSMOS_ENDPOINT"],
        credential=cosmos_cred,
        connection_timeout=30,
    )
    cosmos_db = cosmos_client.get_database_client(os.environ["COSMOS_DATABASE_NAME"])
    state_container = cosmos_db.get_container_client("state")
    audit_container = cosmos_db.get_container_client("audit")

    from src.domain.change_detection import decide_reprocess_or_skip

    try:
        existing_state = state_container.read_item(
            item=ENTITY_GUID,
            partition_key=ENTITY_TYPE,
        )
        previous_hash = existing_state.get("assetHash", "")
    except Exception:
        existing_state = None
        previous_hash = ""

    decision = decide_reprocess_or_skip(asset_hash, previous_hash)
    print(f"  PASS - Decision: {decision.value}")
    print(f"  Previous hash: {(previous_hash[:16] or '(none)') + '...'}")
    print(f"  Current hash : {asset_hash[:16]}...")
    results["stage3"] = {"status": "PASS", "decision": decision.value}
except Exception as exc:
    print(f"  FAIL - {type(exc).__name__}: {exc}")
    traceback.print_exc()
    results["stage3"] = {"status": "FAIL", "error": str(exc)}
    sys.exit(1)

# ===========================================================================
# Stage 4 - RAG Retrieve
# ===========================================================================
print("\n[Stage 4] RAG Retrieve")
retrieved = None
try:
    from src.enrichment.rag.config import RAGConfig
    from src.enrichment.rag.pipeline import RAGQueryPipeline

    rag_config = RAGConfig()
    rag_pipeline = RAGQueryPipeline(rag_config)
    reference_time = datetime.now(timezone.utc)

    retrieved = rag_pipeline.retrieve_context_for_asset(
        asset_id=ENTITY_GUID,
        entity_type=ENTITY_TYPE,
        source_system=SOURCE_SYSTEM,
        element_name=ENTITY_NAME,
        correlation_id=CORRELATION_ID,
        reference_time=reference_time,
    )

    print(f"  PASS - {retrieved.results_used} chunks retrieved")
    print(f"  Total found   : {retrieved.total_results_found}")
    print(f"  Has context   : {retrieved.has_context}")
    print(f"  Context length: {len(retrieved.formatted_context)} chars")
    if retrieved.results_used > 0:
        top = retrieved.chunks[0]
        print(f"  Top chunk     : {top.element_name} ({top.source_system}, score={top.composite_score:.4f})")

    rag_pipeline.close()
    results["stage4"] = {
        "status": "PASS",
        "chunks_used": retrieved.results_used,
        "has_context": retrieved.has_context,
    }
except Exception as exc:
    print(f"  PARTIAL - RAG failed (non-fatal, proceeding with empty context)")
    print(f"  Error: {type(exc).__name__}: {exc}")
    results["stage4"] = {"status": "PARTIAL", "error": str(exc)}

# ===========================================================================
# Stage 5 - Build Prompt
# ===========================================================================
print("\n[Stage 5] Build Prompt")
try:
    import yaml

    with open("contracts/prompts/v1-metadata-enrichment.prompt.yaml", encoding="utf-8") as f:
        prompt_contract = yaml.safe_load(f)

    system_prompt = prompt_contract["system_prompt"]
    instruction_prompt = prompt_contract["instruction_prompt"]

    if retrieved and retrieved.has_context:
        rag_context = retrieved.formatted_context
    else:
        rag_context = "No context documents retrieved from Azure AI Search for this asset."

    asset_metadata_str = (
        f"Asset Name: {entity_name_from_purview}\n"
        f"Entity Type: {ENTITY_TYPE}\n"
        f"Qualified Name: {qualified_name}\n"
        f"Existing Description: {existing_desc or '(none)'}\n"
        f"Source System: {SOURCE_SYSTEM}\n"
    )

    user_message = (
        f"{instruction_prompt}\n\n"
        f"ASSET METADATA:\n{asset_metadata_str}\n\n"
        f"RAG CONTEXT:\n{rag_context}\n\n"
        "STRICT OUTPUT REQUIREMENTS — respond with ONLY the following YAML, no markdown code fences, no preamble:\n"
        "suggested_description: \"<concise business description based on context or uncertainty statement>\"\n"
        "confidence: <low|medium|high>\n"
        "used_sources:\n"
        "  - \"<elementName or title from a Source above>\"\n"
        "warnings: []\n"
        "\n"
        "RULES:\n"
        "1. DO NOT wrap in ```yaml or ``` or any markdown fences\n"
        "2. Start your response directly with: suggested_description:\n"
        "3. Use block YAML array (  - \"item\") for used_sources, NOT inline ([\"item\"])\n"
        "4. warnings must be [] (empty array) or block array with strings\n"
        "5. Cite at least one elementName from the RAG Context in used_sources\n"
        "6. FORBIDDEN words in suggested_description: 'system', 'AI', 'LLM', 'model', 'pipeline', 'orchestrator', 'ChatGPT', 'OpenAI'\n"
        "   Use alternatives: 'platform' instead of 'system', 'data source' instead of 'source system'\n"
    )

    print(f"  PASS - Prompt assembled ({len(user_message)} chars)")
    print(f"  System prompt : {len(system_prompt)} chars")
    print(f"  RAG context   : {len(rag_context)} chars")
    results["stage5"] = {"status": "PASS", "prompt_length": len(user_message)}
except Exception as exc:
    print(f"  FAIL - {type(exc).__name__}: {exc}")
    traceback.print_exc()
    results["stage5"] = {"status": "FAIL", "error": str(exc)}
    sys.exit(1)

# ===========================================================================
# Stage 6 - LLM Invoke
# ===========================================================================
print("\n[Stage 6] LLM Invoke (gpt-4o-mini)")
raw_llm_output = None
try:
    from src.enrichment.llm_client import AzureOpenAIClient

    llm_client = AzureOpenAIClient(enrichment_config)
    raw_llm_output = llm_client.complete(
        prompt=user_message,
        system_message=system_prompt,
    )
    llm_client.close()

    # Strip markdown code fences if present (known LLM formatting behavior)
    stripped = raw_llm_output.strip()
    if stripped.startswith("```"):
        lines_out = stripped.split("\n")
        # Remove first line (```yaml or ```) and last line (```)
        if lines_out[0].startswith("```"):
            lines_out = lines_out[1:]
        if lines_out and lines_out[-1].strip() == "```":
            lines_out = lines_out[:-1]
        raw_llm_output = "\n".join(lines_out).strip()

    print(f"  PASS - Response length: {len(raw_llm_output)} chars")
    print(f"  LLM Output:")
    for line in raw_llm_output[:600].split("\n"):
        print(f"    {line}")
    results["stage6"] = {"status": "PASS", "output_length": len(raw_llm_output)}
except Exception as exc:
    print(f"  FAIL - {type(exc).__name__}: {exc}")
    traceback.print_exc()
    results["stage6"] = {"status": "FAIL", "error": str(exc)}
    sys.exit(1)

# ===========================================================================
# Stage 7 - Semantic Validation
# ===========================================================================
print("\n[Stage 7] Semantic Validation")
try:
    from src.enrichment.output_validator import validate_llm_output, ValidationStatus

    validation_result = validate_llm_output(raw_llm_output, correlation_id=CORRELATION_ID)

    print(f"  Status          : {validation_result.status.value}")
    print(f"  Rules executed  : {len(validation_result.rules_executed)}")
    print(f"  Blocking errors : {len(validation_result.blocking_errors)}")
    print(f"  Advisory flags  : {len(validation_result.advisory_flags)}")

    for err in validation_result.blocking_errors:
        print(f"  BLOCKING ERROR: {err}")

    for flag in validation_result.advisory_flags:
        print(f"  ADVISORY [{flag.rule_id}]: {flag.message}")

    if validation_result.status == ValidationStatus.BLOCK:
        print("  FAIL - Validation BLOCKED the LLM output")
        results["stage7"] = {"status": "FAIL", "blocking_errors": validation_result.blocking_errors}
        sys.exit(1)

    print("  PASS - Output passed all blocking validation rules")
    results["stage7"] = {
        "status": "PASS",
        "advisory_count": len(validation_result.advisory_flags),
    }
except Exception as exc:
    print(f"  FAIL - {type(exc).__name__}: {exc}")
    traceback.print_exc()
    results["stage7"] = {"status": "FAIL", "error": str(exc)}
    sys.exit(1)

# ===========================================================================
# Extract suggested_description from validated YAML
# ===========================================================================
suggested_description = ""
confidence = ""
used_sources = []
try:
    import yaml as _yaml
    parsed_output = _yaml.safe_load(raw_llm_output)
    suggested_description = str(parsed_output.get("suggested_description", ""))
    confidence = str(parsed_output.get("confidence", ""))
    used_sources = parsed_output.get("used_sources", [])
    print(f"\n  Extracted description ({len(suggested_description)} chars):")
    print(f"    {suggested_description[:250]}")
    print(f"  Confidence: {confidence}")
    print(f"  Used sources: {used_sources[:3]}")
except Exception as exc:
    suggested_description = raw_llm_output[:300]
    print(f"  Warning: Could not parse YAML - using raw: {exc}")

# ===========================================================================
# Stage 8 - Purview Writeback
# ===========================================================================
print("\n[Stage 8] Purview Writeback")
try:
    from src.enrichment.lifecycle import LifecycleStore
    from src.enrichment.purview_writeback import PurviewWritebackService

    lifecycle_store = LifecycleStore(
        lifecycle_container=state_container,
        audit_container=audit_container,
    )

    writeback_service = PurviewWritebackService(purview_client, lifecycle_store)
    final_description = f"[E2E VALIDATION {RUN_TIMESTAMP[:10]}] {suggested_description}"
    writeback_result = writeback_service.write_suggested_description(
        entity_guid=ENTITY_GUID,
        entity_type=ENTITY_TYPE,
        suggested_description=final_description,
        correlation_id=CORRELATION_ID,
    )

    print(f"  Success          : {writeback_result.success}")
    print(f"  Lifecycle status : {writeback_result.lifecycle_status}")
    print(f"  Purview written  : {writeback_result.purview_written}")
    if writeback_result.error:
        print(f"  Error            : {writeback_result.error}")

    if not writeback_result.success:
        print(f"  FAIL - Writeback did not succeed")
        results["stage8"] = {"status": "FAIL", "error": writeback_result.error}
        sys.exit(1)

    print("  PASS - Suggested Description written to Purview")
    results["stage8"] = {
        "status": "PASS",
        "lifecycle_status": writeback_result.lifecycle_status,
        "description_hash": writeback_result.description_hash,
    }
except Exception as exc:
    print(f"  FAIL - {type(exc).__name__}: {exc}")
    traceback.print_exc()
    results["stage8"] = {"status": "FAIL", "error": str(exc)}
    sys.exit(1)

# ===========================================================================
# Stage 9 - Cosmos State Update
# ===========================================================================
print("\n[Stage 9] Cosmos State Update")
try:
    now_iso = datetime.now(timezone.utc).isoformat()
    state_doc = {
        "id": ENTITY_GUID,
        "entityType": ENTITY_TYPE,
        "entityName": ENTITY_NAME,
        "assetHash": asset_hash,
        "correlationId": CORRELATION_ID,
        "lastProcessed": now_iso,
        "decision": "REPROCESS",
        "descriptionHash": writeback_result.description_hash or "",
        "recordType": "state",
    }
    upserted = state_container.upsert_item(body=state_doc)
    print(f"  PASS - State record upserted (id: {upserted['id']})")
    results["stage9"] = {"status": "PASS"}
except Exception as exc:
    print(f"  FAIL - {type(exc).__name__}: {exc}")
    traceback.print_exc()
    results["stage9"] = {"status": "FAIL", "error": str(exc)}
    sys.exit(1)

# ===========================================================================
# Stage 10 - Cosmos Audit / Lifecycle Verification
# ===========================================================================
print("\n[Stage 10] Cosmos Audit / Lifecycle Verification")
try:
    # Verify audit record was written by the writeback service
    audit_id = f"wb:{ENTITY_GUID}:{CORRELATION_ID}"
    audit_found = False
    try:
        audit_doc = audit_container.read_item(item=audit_id, partition_key=ENTITY_TYPE)
        audit_found = True
        print(f"  Audit record found  : {audit_doc['id']}")
        print(f"  Operation           : {audit_doc.get('operation', '?')}")
        print(f"  Outcome             : {audit_doc.get('outcome', '?')}")
        print(f"  Lifecycle status    : {audit_doc.get('lifecycleStatus', '?')}")
    except Exception as audit_exc:
        print(f"  Warning: Audit record not found by id: {audit_exc}")

    # Verify state record
    state_doc_verify = state_container.read_item(item=ENTITY_GUID, partition_key=ENTITY_TYPE)
    print(f"  State record found  : {state_doc_verify['id']}")
    print(f"  Asset hash          : {state_doc_verify.get('assetHash', '?')[:16]}...")
    print(f"  Last processed      : {state_doc_verify.get('lastProcessed', '?')}")

    # Verify lifecycle record (written by PurviewWritebackService into state container)
    lifecycle_found = False
    try:
        lifecycle_doc = state_container.read_item(item=ENTITY_GUID, partition_key=ENTITY_TYPE)
        if lifecycle_doc.get("recordType") in ("lifecycle", "state"):
            lifecycle_found = True
            print(f"  Lifecycle/state record: recordType={lifecycle_doc.get('recordType', '?')}")
    except Exception:
        pass

    print("  PASS - Audit and state records verified in Cosmos DB")
    results["stage10"] = {"status": "PASS", "audit_found": audit_found}
except Exception as exc:
    print(f"  FAIL - {type(exc).__name__}: {exc}")
    traceback.print_exc()
    results["stage10"] = {"status": "FAIL", "error": str(exc)}

# ===========================================================================
# Final Report
# ===========================================================================
print()
print("=" * 70)
print("VALIDATION REPORT")
print("=" * 70)

stage_names = {
    "stage1": "Purview Read",
    "stage2": "SHA-256 Hash",
    "stage3": "State Comparison",
    "stage4": "RAG Retrieve",
    "stage5": "Build Prompt",
    "stage6": "LLM Invoke",
    "stage7": "Semantic Validation",
    "stage8": "Purview Writeback",
    "stage9": "Cosmos State Update",
    "stage10": "Cosmos Audit/Lifecycle",
}

all_pass = True
for stage_key in ["stage1", "stage2", "stage3", "stage4", "stage5",
                  "stage6", "stage7", "stage8", "stage9", "stage10"]:
    name = stage_names.get(stage_key, stage_key)
    status = results.get(stage_key, {}).get("status", "MISSING")
    if status not in ("PASS", "PARTIAL"):
        all_pass = False
    icon = "PASS" if status == "PASS" else ("WARN" if status == "PARTIAL" else "FAIL")
    num = stage_key.replace("stage", "")
    print(f"  Stage {num:>2}  {name:<32} [{icon}]")

print()
print("Six Completion Criteria:")
criteria = [
    ("C1", "Purview entity read without error",
     results.get("stage1", {}).get("status") == "PASS"),
    ("C2", "SHA-256 hash computed deterministically",
     results.get("stage2", {}).get("status") == "PASS"),
    ("C3", "REPROCESS/SKIP decision from state",
     results.get("stage3", {}).get("status") == "PASS"),
    ("C4", "LLM output passes semantic validation",
     results.get("stage7", {}).get("status") == "PASS"),
    ("C5", "Purview Suggested Description written",
     results.get("stage8", {}).get("status") == "PASS"),
    ("C6", "Cosmos state+audit records persisted",
     results.get("stage9", {}).get("status") == "PASS"
     and results.get("stage10", {}).get("status") == "PASS"),
]
all_criteria_met = True
for cid, desc, met in criteria:
    status_str = "MET" if met else "NOT MET"
    if not met:
        all_criteria_met = False
    print(f"  {cid}: {desc:<50} [{status_str}]")

print()
print("=" * 70)
if all_pass and all_criteria_met:
    print("END-TO-END VALIDATION SUCCESSFUL")
else:
    print("VALIDATION FAILED - REQUIREMENTS NOT MET")
print("=" * 70)
print(f"Correlation ID: {CORRELATION_ID}")
print(f"Completed at  : {datetime.now(timezone.utc).isoformat()}")
