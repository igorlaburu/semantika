# Refactoring Plan: Unified Context Unit Creation

**Date**: 2025-11-20
**Status**: 🔴 CRITICAL - Production issues
**Priority**: HIGH

---

## Executive Summary

The semantika codebase has **severe architectural fragmentation** in context unit generation:

- **6 different entry points** creating context units inconsistently
- **3 competing LLM methods** with incompatible outputs
- **2 storage patterns** (only 1 correct)
- **~200+ lines of duplicated code** across 5+ files
- **Production impact**: Perplexity units have NO embeddings → semantic search fails

---

## Current Architecture Problems

### 1. Entry Points (6 different flows)

| Source | File | Storage | Embeddings | Dedup | LLM Tracking |
|--------|------|---------|------------|-------|--------------|
| Email | `multi_company_email_monitor.py` | Direct INSERT ❌ | NO ❌ | NO ❌ | Partial ⚠️ |
| Scraping | `scraper_workflow.py` | `context_unit_saver` ✅ | YES ✅ | YES ✅ | YES ✅ |
| Perplexity | `perplexity_news_connector.py` | Direct INSERT ❌ | NO ❌ | NO ❌ | Partial ⚠️ |
| Text API | `core_stateless.py` | No storage | N/A | N/A | YES ✅ |
| URL API | `core_stateless.py` | No storage | N/A | N/A | YES ✅ |
| Universal | `universal_pipeline.py` | Direct INSERT ❌ | NO ❌ | NO ❌ | NO ❌ |

**Result**: Only scraping works correctly. All others missing critical features.

---

### 2. LLM Methods (3 competing approaches)

#### Method A: `analyze_atomic()` (Groq Llama 3.3 70B)
**File**: `utils/llm_client.py:342-415`
**Used by**: Scraping, Perplexity workflow, Text/URL APIs
**Cost**: ~$0.06 per 1M tokens (cheap)
**Speed**: Fast (Groq)

**Output**:
```json
{
  "title": "...",
  "summary": "...",
  "tags": ["tag1", "tag2"],
  "atomic_facts": ["fact 1", "fact 2"],  // ❌ String array (incompatible)
  "category": "política"
}
```

**Problem**: Returns `atomic_facts` as simple strings, needs manual conversion to structured format.

---

#### Method B: `generate_context_unit()` (GPT-4o-mini via OpenRouter)
**File**: `utils/openrouter_client.py:960-1050`
**Used by**: DefaultWorkflow (email processing)
**Cost**: ~$0.15 per 1M input tokens (3x more expensive)
**Speed**: Slower (OpenAI)

**Output**:
```json
{
  "title": "...",
  "summary": "...",
  "tags": ["tag1", "tag2"],
  "atomic_statements": [  // ✅ Structured format
    {
      "order": 1,
      "type": "fact|quote|context",
      "speaker": "Juan Pérez" | null,
      "text": "fact text"
    }
  ]
}
```

**Problem**: More expensive, different output format, not used consistently.

---

#### Method C: `analyze()` (Basic)
**File**: `utils/llm_client.py:316-341`
**Used by**: Legacy code
**Output**: Only title, summary, tags (NO atomic_statements)

**Problem**: Incomplete, should be deprecated.

---

### 3. Atomic Statements Format Chaos

**Database Schema** (`press_context_units.atomic_statements`):
```sql
atomic_statements JSONB  -- Array of objects with: order, type, speaker, text
```

**Problem**: Two incompatible formats in codebase:

```python
# Format A: From analyze_atomic (Groq)
"atomic_facts": ["string 1", "string 2"]

# Format B: From generate_context_unit (GPT-4o-mini)
"atomic_statements": [
    {"order": 1, "type": "fact", "speaker": null, "text": "string 1"}
]
```

**Manual Conversion Code** (repeated in multiple places):
```python
# perplexity_news_connector.py:238-249
if atomic_statements and isinstance(atomic_statements[0], str):
    atomic_statements = [
        {
            "order": i + 1,
            "type": "fact",
            "speaker": None,
            "text": statement
        }
        for i, statement in enumerate(atomic_statements)
    ]
```

**Impact**: Easy to forget, causes bugs, data inconsistency.

---

### 4. Storage Pattern Chaos

#### Pattern A: `context_unit_saver` (CORRECT) ✅

**File**: `utils/context_unit_saver.py`
**Used by**: Only web scraping

**Features**:
- ✅ Generates embeddings via `generate_embedding(title + summary)`
- ✅ Checks duplicates via cosine similarity (threshold 0.98)
- ✅ Consistent field mapping
- ✅ Returns structured result

**Functions**:
```python
save_context_unit_universal(...)  # Core function
save_from_email(...)               # Email-specific wrapper
save_from_perplexity(...)          # Perplexity-specific wrapper
save_from_scraping(...)            # Scraping-specific wrapper
```

---

#### Pattern B: Direct DB Insert (INCORRECT) ❌

**Used by**: Email (3x), Perplexity, Universal pipeline

**Example** (from `perplexity_news_connector.py:263`):
```python
context_unit_data = {
    "id": context_unit.get("id"),
    "company_id": company["id"],
    "source_type": "api",
    "title": context_unit.get("title"),
    "summary": context_unit.get("summary"),
    "atomic_statements": atomic_statements,
    "tags": context_unit.get("tags"),
    "raw_text": context_unit.get("raw_text"),
    "status": "completed"
    # ❌ Missing: category, embedding
}
supabase.client.table("press_context_units").insert(context_unit_data).execute()
```

**Problems**:
- No embedding generation → semantic search fails
- No duplicate detection → repeated content in DB
- No category → filtering broken
- Code duplicated 5+ times
- Easy to forget fields

---

### 5. Code Duplication Statistics

**Direct INSERT code repeated**:
- `multi_company_email_monitor.py` (lines 545-562, 622-639, 758-775) - 3 times
- `perplexity_news_connector.py` (lines 234-263) - 1 time
- `universal_pipeline.py` (lines 206-208) - 1 time

**Total duplicated lines**: ~200+

**SourceContent creation repeated**: 6 times (every connector)

**Workflow invocation repeated**: 5 times

---

## Production Impact

### Current Bugs

1. **Perplexity units unusable for search**
   - Last 5 units created today (02:35 UTC) have NO embeddings
   - Search returns 0 results even with relevant content
   - Category = NULL → filtering broken

2. **Email processing**
   - No duplicate detection → same email creates multiple context units
   - No embeddings → can't find email content in search
   - Inconsistent with scraping

3. **Database state**
   - 179 context units total
   - Only 1 has embedding (test unit)
   - 178 without embeddings (99.4% broken)

---

## Proposed Solution

### Phase 1: Create Unified Abstraction (URGENT)

**New file**: `utils/unified_context_creator.py`

```python
async def create_and_save_context_unit(
    source_content: SourceContent,
    company: Dict[str, Any],
    organization: Dict[str, Any],
    source: Dict[str, Any],
    workflow_code: str = "default",
    generate_embeddings: bool = True,
    check_duplicates: bool = True
) -> Dict[str, Any]:
    """
    Unified pipeline for context unit creation:

    1. Process content through workflow (LLM analysis)
    2. Normalize atomic_statements format
    3. Extract category from workflow result
    4. Generate embeddings (if enabled)
    5. Check duplicates (if enabled)
    6. Save to database
    7. Track LLM usage

    Args:
        source_content: SourceContent with text_content
        company: Company data (for LLM tracking)
        organization: Organization data
        source: Source configuration (for metadata)
        workflow_code: Which workflow to use (default, acme, etc.)
        generate_embeddings: Generate embeddings for semantic search
        check_duplicates: Check for duplicate content before saving

    Returns:
        {
            "success": bool,
            "context_unit_id": str,
            "duplicate_detected": bool,
            "duplicate_id": str | None,
            "similarity_score": float | None,
            "llm_usage": {...}
        }
    """
    # Step 1: Get workflow
    workflow = get_workflow(workflow_code, company.get("settings", {}))

    # Step 2: Process content through workflow
    workflow_result = await workflow.process_content(source_content)

    if not workflow_result.get("success"):
        return {
            "success": False,
            "error": workflow_result.get("error", "Workflow failed")
        }

    context_unit = workflow_result.get("context_unit", {})

    # Step 3: Normalize atomic_statements format
    atomic_statements = normalize_atomic_statements(
        context_unit.get("atomic_statements") or context_unit.get("atomic_facts")
    )

    # Step 4: Save using context_unit_saver (handles embeddings + duplicates)
    save_result = await save_context_unit_universal(
        company_id=company["id"],
        organization_id=organization["id"],
        source_type=source.get("source_type"),
        source_id=source.get("source_id"),
        title=context_unit.get("title"),
        summary=context_unit.get("summary"),
        tags=context_unit.get("tags", []),
        atomic_statements=atomic_statements,
        raw_text=context_unit.get("raw_text", ""),
        category=context_unit.get("category"),  # ✅ Now included
        generate_embedding_flag=generate_embeddings,
        check_duplicates=check_duplicates
    )

    return save_result


def normalize_atomic_statements(
    statements: List[Any]
) -> List[Dict[str, Any]]:
    """
    Normalize atomic_statements to structured format.

    Handles:
    - String array → Object array
    - Object array → Validate and return
    - None/empty → Return empty array

    Args:
        statements: Can be:
            - List[str]: ["fact 1", "fact 2"]
            - List[Dict]: [{"order": 1, "text": "fact 1"}]
            - None

    Returns:
        List[Dict] with structure:
        [
            {
                "order": int,
                "type": "fact|quote|context",
                "speaker": str | None,
                "text": str
            }
        ]
    """
    if not statements:
        return []

    # Already structured format
    if isinstance(statements[0], dict):
        # Validate required fields
        for i, stmt in enumerate(statements):
            if "text" not in stmt:
                raise ValueError(f"Statement {i} missing 'text' field")
            if "order" not in stmt:
                stmt["order"] = i + 1
            if "type" not in stmt:
                stmt["type"] = "fact"
            if "speaker" not in stmt:
                stmt["speaker"] = None
        return statements

    # String array format - convert to structured
    if isinstance(statements[0], str):
        return [
            {
                "order": i + 1,
                "type": "fact",
                "speaker": None,
                "text": statement
            }
            for i, statement in enumerate(statements)
        ]

    raise ValueError(f"Unknown atomic_statements format: {type(statements[0])}")
```

---

### Phase 2: Refactor Connectors (HIGH PRIORITY)

#### 2.1 Perplexity Connector

**File**: `sources/perplexity_news_connector.py`

**Before** (lines 234-270):
```python
# Manual atomic_statements conversion
if atomic_statements and isinstance(atomic_statements[0], str):
    atomic_statements = [...]  # 15 lines of boilerplate

# Direct DB insert - no embeddings, no dedup
context_unit_data = {...}
supabase.client.table("press_context_units").insert(context_unit_data).execute()
```

**After**:
```python
from utils.unified_context_creator import create_and_save_context_unit

# Replace entire save block with:
result = await create_and_save_context_unit(
    source_content=source_content,
    company=company,
    organization=organization,
    source=source,
    workflow_code=source.get("workflow_code", "default")
)

if result.get("duplicate_detected"):
    logger.info("duplicate_news_skipped",
        title=news_item.get("titulo")[:50],
        similarity=result.get("similarity_score")
    )
    continue
```

**Benefits**:
- ✅ Embeddings generated automatically
- ✅ Duplicates detected automatically
- ✅ Category saved automatically
- ✅ Code reduced from 50 lines to 15 lines

---

#### 2.2 Email Monitor

**File**: `sources/multi_company_email_monitor.py`

**Before** (3 separate insert blocks at lines 545-562, 622-639, 758-775):
```python
context_unit_data = {
    "id": context_unit.get("id"),
    "organization_id": organization["id"],
    "company_id": company["id"],
    "source_type": "email",
    # ... 10+ field mappings
}
supabase.client.table("press_context_units").insert(context_unit_data).execute()
```

**After** (use same unified function 3 times):
```python
result = await create_and_save_context_unit(
    source_content=source_content,
    company=company,
    organization=organization,
    source=source
)
```

**Benefits**:
- ✅ Eliminates 150+ lines of duplicated code
- ✅ Email content now searchable via embeddings
- ✅ Duplicate emails detected automatically

---

### Phase 3: Standardize LLM Method (MEDIUM PRIORITY)

**Decision**: Use `analyze_atomic()` (Groq) everywhere

**Rationale**:
- 3x cheaper than GPT-4o-mini
- Faster (Groq infrastructure)
- Already used by scraping (production-tested)
- Only requires format normalization (already implemented)

**Changes needed**:
1. Update `DefaultWorkflow.generate_context_unit()` to use `analyze_atomic()`
2. Remove `generate_context_unit()` OpenRouter method (or keep as fallback)
3. Add `normalize_atomic_statements()` helper to all workflows

---

### Phase 4: Cleanup (LOW PRIORITY)

1. **Audit `universal_pipeline.py`**
   - Check if used in production
   - If not → deprecate and remove
   - If yes → refactor to use unified creator

2. **Remove `analyze()` method**
   - Basic version without atomic_statements
   - Superseded by `analyze_atomic()`

3. **Update documentation**
   - Add architecture diagram
   - Document unified flow
   - Update CLAUDE.md

---

## Implementation Plan

### Week 1: Foundation (3-4 hours)

**Day 1**: Create unified abstraction
- [ ] Create `utils/unified_context_creator.py`
- [ ] Implement `create_and_save_context_unit()`
- [ ] Implement `normalize_atomic_statements()`
- [ ] Add unit tests

**Day 2**: Test thoroughly
- [ ] Test with email data
- [ ] Test with Perplexity data
- [ ] Test with scraping data
- [ ] Verify embeddings generated
- [ ] Verify duplicates detected

---

### Week 2: Refactor Production Connectors (4-6 hours)

**Day 1**: Fix Perplexity (URGENT)
- [ ] Refactor `perplexity_news_connector.py`
- [ ] Test with real Perplexity data
- [ ] Deploy to production
- [ ] Verify search works
- [ ] Monitor for 24h

**Day 2**: Fix Email Monitor
- [ ] Refactor `multi_company_email_monitor.py`
- [ ] Replace 3 insert blocks
- [ ] Test with real emails
- [ ] Deploy to production
- [ ] Monitor for 24h

**Day 3**: Backfill embeddings
- [ ] Run embedding regeneration script for 178 existing units
- [ ] Verify all units now have embeddings
- [ ] Test semantic search with full dataset

---

### Week 3: Standardization (2-3 hours)

**Day 1**: LLM method standardization
- [ ] Update `DefaultWorkflow` to use `analyze_atomic()`
- [ ] Add tests
- [ ] Deploy

**Day 2**: Cleanup
- [ ] Audit `universal_pipeline.py`
- [ ] Remove unused `analyze()` method
- [ ] Update documentation

---

## Testing Checklist

### Integration Tests

- [ ] **Email → Context Unit → Embedding → Search**
  - Send test email
  - Verify context unit created
  - Verify embedding generated
  - Verify findable via semantic search

- [ ] **Perplexity → Context Unit → Embedding → Search**
  - Run Perplexity job
  - Verify 5 units created
  - Verify all have embeddings
  - Verify all have categories
  - Verify findable via search

- [ ] **Scraping → Context Unit → Embedding → Search**
  - Scrape test URL
  - Verify context unit created
  - Verify embedding generated
  - Verify findable via search

- [ ] **Duplicate Detection**
  - Create unit A
  - Try to create identical unit B
  - Verify B rejected as duplicate
  - Verify similarity score logged

### Unit Tests

- [ ] `normalize_atomic_statements()` with string array
- [ ] `normalize_atomic_statements()` with object array
- [ ] `normalize_atomic_statements()` with None
- [ ] `normalize_atomic_statements()` with invalid format
- [ ] `create_and_save_context_unit()` success path
- [ ] `create_and_save_context_unit()` workflow failure
- [ ] `create_and_save_context_unit()` duplicate detected

---

## Rollback Plan

If production issues occur after deployment:

1. **Revert code changes**:
   ```bash
   git revert <commit-hash>
   git push
   ```

2. **Verify old code path works**:
   - Test email processing
   - Test Perplexity job
   - Test scraping

3. **Investigate issue**:
   - Check logs for errors
   - Check database for missing fields
   - Check LLM usage tracking

4. **Fix and redeploy**:
   - Fix issue in dev
   - Test thoroughly
   - Redeploy to production

---

## Success Metrics

### Before Refactoring
- ❌ Perplexity units: 0% have embeddings
- ❌ Email units: 0% have embeddings
- ❌ Scraping units: 100% have embeddings
- ❌ Search success rate: ~0.5% (1/179 units searchable)
- ❌ Code duplication: 200+ lines

### After Refactoring
- ✅ All units: 100% have embeddings
- ✅ Search success rate: 100% (all units searchable)
- ✅ Code duplication: 0 lines
- ✅ Duplicate detection: Active for all sources
- ✅ Category classification: All units categorized
- ✅ LLM usage: Consistently tracked

---

## Risk Assessment

### High Risk
- **Perplexity refactor**: In production, runs daily
  - Mitigation: Test thoroughly before deploy
  - Mitigation: Deploy during low-traffic hours (4 AM UTC)
  - Mitigation: Monitor for 24h after deploy

### Medium Risk
- **Email refactor**: Multiple code paths affected
  - Mitigation: Test all email types (body, attachments, audio)
  - Mitigation: Deploy incrementally (one path at a time)

### Low Risk
- **LLM standardization**: Doesn't affect storage
  - Impact: Only affects quality of analysis
  - Rollback: Easy (just change LLM call)

---

## Timeline

- **Week 1**: Foundation + testing (3-4 hours)
- **Week 2**: Production refactoring (4-6 hours)
- **Week 3**: Cleanup + documentation (2-3 hours)

**Total estimated time**: 9-13 hours

**Critical path**: Perplexity fix (needed immediately for production)

---

## Appendix A: File References

### Files to Modify
- `utils/unified_context_creator.py` (NEW)
- `sources/perplexity_news_connector.py` (refactor)
- `sources/multi_company_email_monitor.py` (refactor)
- `workflows/default/default_workflow.py` (LLM method change)

### Files to Review
- `utils/context_unit_saver.py` (used as-is)
- `utils/llm_client.py` (LLM methods)
- `utils/openrouter_client.py` (LLM methods)
- `core/universal_pipeline.py` (audit for removal)

### Files Not Changed
- `sources/scraper_workflow.py` (already correct)
- `core_stateless.py` (API-only, no storage)
- `workflows/base_workflow.py` (abstract base)

---

## Appendix B: Database Schema

### Current Schema (correct)
```sql
CREATE TABLE press_context_units (
    id UUID PRIMARY KEY,
    company_id UUID NOT NULL,
    organization_id UUID,
    source_type VARCHAR NOT NULL,
    title TEXT,
    summary TEXT,
    tags TEXT[],
    atomic_statements JSONB,  -- Array of objects
    category VARCHAR,          -- ❌ Often NULL due to direct inserts
    embedding vector(768),     -- ❌ Often NULL due to direct inserts
    raw_text TEXT,
    status VARCHAR DEFAULT 'completed',
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Required Atomic Statements Format
```json
[
    {
        "order": 1,
        "type": "fact|quote|context",
        "speaker": "Juan Pérez" | null,
        "text": "The actual statement text"
    }
]
```

---

## Appendix C: LLM Usage Comparison

| Method | Model | Cost (per 1M tokens) | Speed | Output Format |
|--------|-------|----------------------|-------|---------------|
| `analyze_atomic()` | Groq Llama 3.3 70B | $0.06 input | Fast | Simple strings |
| `generate_context_unit()` | GPT-4o-mini | $0.15 input | Slower | Structured objects |

**Recommendation**: Use `analyze_atomic()` + `normalize_atomic_statements()` everywhere for 60% cost savings.

---

**END OF DOCUMENT**
