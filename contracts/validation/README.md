# AI Validation Rules (MVP Safe Rule Set)

**Version:** 1.0.0 (FROZEN - MVP Profile)  
**Frozen Date:** 2026-01-14  
**Profile:** Minimal Safe MVP Rule Set  
**Status:** Production-Ready, Change-Controlled

---

## Purpose

This directory contains **frozen, versioned validation rules (MVP profile)** that define deterministic, automated checks for accepting or rejecting AI-generated metadata suggestions.

**MVP Philosophy:** This is a **Minimal Safe** rule set focusing on essential safety guarantees while reducing operational complexity for initial deployment.

Validation rules are **design-time governance artifacts** that:
- Define pass/fail criteria for AI responses
- Detect hallucination and vague source attribution (core indicators)
- Enforce output contract compliance
- Enable automated quality control without human judgment
- Provide audit trail and traceability for AI decisions
- **Balance safety with operational flexibility for MVP**

---

## Current Version (MVP Profile)

### v1-metadata-enrichment.validation.yaml (FROZEN MVP)

**Total Rules:** 16 (reduced from 52+ for MVP)
- **Blocking Rules:** 11 (essential safety, immediate rejection)
- **Advisory Rules:** 5 (quality insights, non-blocking flags)

**MVP Changes:**
- Streamlined from comprehensive rule set to essential safety checks
- Fine-grained patterns reduced to core hallucination indicators
- Array size/length constraints relaxed to advisory
- Complex alignment heuristics simplified
- Focus: RAG-first, HITL, deterministic output, auditability

**Rule Categories:**

#### BLOCKING RULES (11) - Immediate Rejection

**1. Structural Validation (2 rules)**
- **V001:** YAML parseability (critical)
- **V002:** No extraneous text outside YAML (critical)

**2. Required Fields (3 rules)**
- **V010:** `suggested_description` present and non-empty (critical)
- **V011:** `confidence` present and non-empty (critical)
- **V012:** `used_sources` present and non-empty array (critical)

**3. Basic Constraints (2 rules)**
- **V020:** Description length 10-500 characters (high)
- **V021:** Confidence is 'low', 'medium', or 'high' only (critical)

**4. Grounding Enforcement (3 rules)**
- **V030:** No explicit external knowledge references (critical)
  - Detects: "based on (my|general) knowledge", "training data", "as far as I know"
- **V031:** No placeholder responses (high)
  - Detects: "N/A", "Unknown", "TBD", "[placeholder]"
- **V032:** No vague source attribution (critical)
  - Detects: "general knowledge", "training data", "internet", "web search"

**5. Context Handling (1 rule)**
- **V040:** Insufficient context → confidence must be 'low' (high)

#### ADVISORY RULES (5) - Non-Blocking Flags

**Quality Monitoring:**
- **A001:** Low confidence flag (for review prioritization)
- **A002:** Short description flag (<30 chars)
- **A003:** Warnings present flag
- **A004:** Single source flag
- **A005:** Uncertainty language flag ("appears to be", "possibly", etc.)

**Note:** Advisory rules generate flags for monitoring and human review prioritization but do NOT cause rejection.

---

## Validation Workflow

### Execution Order

1. **Critical Rules First** (V001-V012, V021, V030, V032)
   - First failure = immediate rejection
   - No point proceeding if YAML is malformed or hallucination detected

2. **High Severity Rules** (V020, V022, V031, V040, V041)
   - Check constraint violations and context alignment
   - First failure = immediate rejection

3. **Medium/Low Severity Rules** (V023-V025)
   - Check less critical constraints
   - First failure = immediate rejection

4. **Advisory Rules** (V050-V052)
   - Flag for human review but DO NOT reject
   - Used for prioritization and quality insights

5. **Final Result**
   - All mandatory rules pass → **ACCEPTED** (with any flags)
   - Any mandatory rule fails → **REJECTED** (with failure details)

### Validation Response Format

```yaml
status: ACCEPTED | REJECTED
passed_rules:
  - V001
  - V002
  - ...
failed_rules:
  - rule_id: V030
    rule_name: "Forbidden Phrases in Description"
    failure_message: "Suggested description contains forbidden phrases indicating uncertainty or external knowledge."
    severity: critical
flags:
  - rule_id: V050
    rule_name: "Low Confidence Flagging"
    flag_message: "Low confidence response flagged for human review."
summary: "Response rejected due to hallucination indicators." | "Response accepted with 2 advisory flags."
```

---

## MVP Rationale

### Why Rules Were Reduced

**From 52+ rules to 16 (11 blocking, 5 advisory):**

**Problem:** Comprehensive rule sets can cause high false-rejection rates during MVP, blocking valid suggestions and increasing human review burden unnecessarily.

**Solution:** Focus on **essential safety** while relaxing **nice-to-have quality checks** to advisory status.

### What Was Relaxed

**Moved from BLOCKING to ADVISORY or REMOVED:**
1. **Fine-grained phrase patterns:** Extensive "forbidden phrase" lists reduced to core external knowledge indicators
2. **Array size limits:** Max sources (e.g., 10 items) removed from blocking
3. **Item length constraints:** Source/warning character limits made advisory
4. **Entity type contradiction logic:** Removed complex heuristic, kept insufficient context check only
5. **Short description patterns:** Made advisory rather than blocking

### What Remains Strictly Enforced

**BLOCKING (Essential Safety):**
- ✅ YAML parseability and structure
- ✅ Required fields present and non-empty
- ✅ Basic length constraint (10-500 chars prevents empty/verbose)
- ✅ Confidence enum enforcement (deterministic values)
- ✅ **Core hallucination detection** (explicit external knowledge references)
- ✅ **No placeholder responses** (ensures substantive suggestions)
- ✅ **RAG grounding** (no vague source attribution)
- ✅ **Admit uncertainty** (insufficient context → low confidence)

**ADVISORY (Quality Insights):**
- ℹ️ Low confidence flagging (prioritize review)
- ℹ️ Short descriptions (may be valid for simple assets)
- ℹ️ Warnings present (informative, not failure)
- ℹ️ Single source usage (may be appropriate)
- ℹ️ Uncertainty language (helps detect low-certainty responses)

---

## Governance

### Change Control

**These rules are FROZEN.**

Any modification requires:
1. **New version number** (v1.1.0 for minor, v2.0.0 for major)
2. **Architecture Decision Record (ADR)** documenting rationale
3. **Approval from:**
   - Architecture Team
   - Security Team
4. **Impact analysis:**
   - Acceptance rate changes
   - False positive/negative rates
   - Human review workload shifts
5. **Testing with historical data** to assess impact

### Why Governance Matters

Validation rules are **quality gatekeepers**:
- Too strict → legitimate responses rejected, high manual workload
- Too loose → hallucinations accepted, trust erosion
- **MVP Balance:** Essential safety enforced, quality insights advisory
- Changes affect AI success rates and human-in-the-loop workflows
- Public-sector environments require auditable, stable quality criteria
- Changes affect AI success rates and human-in-the-loop workflows
- Public-sector environments require auditable, stable quality criteria

---

## Usage

### For Runtime Implementers

When implementing these validation rules:

1. **Load the rules** from this file (YAML parsing)
2. **Implement each rule** as a function/method:
   - Parse AI response (handle V001)
   - Check structure and fields (V002-V012)
   - Validate constraints (V020-V025)
   - Pattern matching for hallucination (V030-V032)
   - Conditional logic for alignment (V040-V041)
   - Generate flags (V050-V052)

3. **Execute in order:**
   - Stop on first critical/high/medium failure
   - Collect all advisory flags
   - Return validation response

4. **Log everything:**
   - Which rules passed/failed
   - Why a response was rejected
   - Advisory flags for accepted responses
   - For audit, debugging, and improvement

### For Data Scientists / AI Engineers

Use validation results to:
- Identify prompt engineering issues (high V030/V032 failure rate)
- Tune RAG retrieval quality (high V041 failures)
- Adjust confidence thresholds
- Improve source citation in prompts

Do NOT modify rules to "game" acceptance rates. If rules are inappropriate, follow governance process to create a new version.

### For Human Reviewers

Validation runs BEFORE you see a response:
- **ACCEPTED responses** have passed all mandatory rules (may have flags)
- **REJECTED responses** never reach you
- **Flags** highlight responses that need closer attention:
  - Low confidence
  - Short descriptions
  - Warnings from the AI

Flags do not mean the response is wrong; they guide prioritization.

---

## Rule Details

### Critical Rules (Immediate Rejection)

**V001: YAML Parseability**  
*Why Critical:* Unparseable responses cannot be processed.  
*Check:* YAML parser succeeds without exceptions.

**V002: No Extraneous Text**  
*Why Critical:* Commentary breaks machine parsing and structured workflows.  
*Check:* No preambles like "Here is my suggestion:" or markdown code fences.

**V010-V012: Required Fields Present**  
*Why Critical:* Missing required data makes the response incomplete.  
*Check:* All three fields exist, are correct type, and non-empty.

**V021: Confidence Allowed Values**  
*Why Critical:* Invalid enum values break downstream processing.  
*Check:* Value is exactly 'low', 'medium', or 'high' (case-sensitive).

**V030: Forbidden Phrases**  
*Why Critical:* Phrases like "based on my knowledge" indicate hallucination.  
*Check:* No patterns like "I don't know", "in general", "probably", etc.

**V032: Source Attribution Plausibility**  
*Why Critical:* Vague sources like "general knowledge" indicate non-RAG grounding.  
*Check:* No patterns like "training data", "common knowledge", "internet".

### High Severity Rules (Quality Enforcement)

**V020: Description Length**  
*Why High:* Too short = insufficient detail; too long = verbose/off-topic.  
*Check:* 10 ≤ length ≤ 500 characters.

**V022: Used Sources Count**  
*Why High:* At least 1 source required; more than 10 is excessive.  
*Check:* 1 ≤ array size ≤ 10.

**V031: No Placeholder Text**  
*Why High:* Placeholders like "N/A" or "Unknown" indicate non-response.  
*Check:* Not "N/A", "TBD", "[placeholder]", etc.

**V040-V041: Context Alignment**  
*Why High:* Confidence must match warnings (e.g., contradiction → not high).  
*Check:* Conditional logic on warnings and confidence fields.

### Advisory Rules (Flags Only, No Rejection)

**V050-V052: Quality Thresholds**  
*Purpose:* Guide human reviewers to responses needing closer attention.  
*Action:* Flag but do not reject; used for prioritization.

---

## Version History

| Version | Date       | Status | Changes |
|---------|------------|--------|---------|
| 1.0.0   | 2026-01-14 | FROZEN | Initial freeze for production use |

---

## Related Artifacts

- **Prompt Template:** [`../prompts/v1-metadata-enrichment.prompt.yaml`](../prompts/v1-metadata-enrichment.prompt.yaml)
- **Output Contract:** [`../outputs/v1-metadata-enrichment.output.yaml`](../outputs/v1-metadata-enrichment.output.yaml)
- **Architecture Docs:** [`../../docs/architecture.md`](../../docs/architecture.md)

---

**Reminder:** Validation rules are deterministic, automated gatekeepers. They enforce trust without human judgment.
