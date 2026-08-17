# Baseline Documentation — Demo Branch

**Branch:** `demo` (from `master` commit `541591727d441d7033a4077d98fbfb373feea787`)
**Date:** 2026-08-17
**Purpose:** Frozen baseline before any modifications

---

## Corpus & Data

| Metric | Value |
|--------|-------|
| FAQ entries | 50 |
| Chunks (real_chunks.jsonl) | 33,171 |
| Sources (metadata.csv) | 1 (demo only - real sources need ingest) |
| FAQ last updated | 2026-08-16 |

> Note: Real corpus requires running ingest pipeline. Current `metadata.csv` shows only demo source.

---

## Model & Retrieval Configuration

| Setting | Value |
|---------|-------|
| `llm_backend` | pateway |
| `retrieval_backend` | hybrid |
| `top_k` | 5 |
| `min_retrieval_score` | 0.01 |
| `retriever_rerank` | False |
| `retriever_gate` | bm25_dense |
| `bm25_gate` | 12.2 |
| `dense_gate` | 0.84 |
| `max_context_chars` | 12,000 |
| `max_response_chars` | 2,000 |

---

## Prompt Version

| Attribute | Value |
|-----------|-------|
| SYSTEM_PROMPT SHA256 (first 16) | `7192dfa091ca8e9a` |
| Prompt length | 8,176 chars |

---

## Test Results (Baseline)

### All Tests (272 tests)
```
tests/test_citation_validator.py ........           8 passed
tests/test_config.py ..............                12 passed
tests/test_demo_connect.py ...........             9 passed
tests/test_eval_and_machine.py .................   15 passed
tests/test_f4_f5_cloud.py .................        15 passed
tests/test_llm_cloud.py ..................         18 passed
tests/test_llm_local.py .......                    7 passed
tests/test_naturalness.py ......................... 25 passed
tests/test_pipeline_mock.py .................      15 passed
tests/test_privacy_logging.py ..........           10 passed
tests/test_privacy_outbound_scrubber.py .......... 10 passed
tests/test_retrieval.py ......                     6 passed
tests/test_safety_router.py ................................ 34 passed
tests/test_schemas.py ....                         4 passed
tests/test_tts_fallback.py .......                 7 passed
```
**Total: 272 passed, 0 failed**

### Gate Tests (69 tests)
| Gate | Test File | Passed |
|------|-----------|--------|
| 1a | Safety routing (RED/ORANGE/REFUSE) | 43 |
| 1b | Out-of-scope blocking | 4 |
| 2 | Citation & law validity | 9 |
| 3 | Retrieval recall@5 ≥ 80% | 4 |
| 4 | Contacts verified ≥ 5 | 3 |
| 5 | Privacy / consent / audit | 5 |
| 7 | Stability + fault injection | 5 |
| **Total** | | **69 passed** |

---

## Known Issues at Baseline

1. **Retrieval gate**: Only checks max score, not evidence coverage
2. **Adjacent expansion**: Adds chunks from same source without structural check
3. **Context budget**: `max_context_chars` configured but not enforced in context building
4. **FAQ bypass**: FAQ can override RED/ORANGE router decisions
5. **FAQ matcher**: Single keyword substring match, no intent/subject verification
6. **Citation validator**: `ok = any(valid)` allows unknown/outdated citations if one valid exists
7. **Prompt conflicts**: Multiple competing length/structure instructions
8. **No claim-level validation**: Only source_id checked, not claim support
9. **Follow-up rescue**: No continuity check before reusing memory evidence
10. **Chunking**: Character-based, may split điều/khoản

---

## Next Steps

Per `IMPLEMENTATION_PLAN.md`:
1. Phase 0: Create probe test set (`eval/probe_questions.json`)
2. Phase 1: Retrieval fixes (score logging, evidence classification, restricted expansion, context budget, answerability gate)
3. Phase 2: FAQ safety & grounding
4. Phase 3: Citation validation hardening
5. Phase 4: Prompt redesign
6. Phase 5: Follow-up control
7. Phase 6: Evaluation infrastructure
8. Phase 7: Iteration until stop criteria met

---

## Environment

- Python: 3.14.5
- pytest: 9.1.1
- OS: Windows 10/11
- Working dir: `C:\Users\laptopppp\intel-demo`