# Deliverables — Vai trò T (Technical — chủ: T, công tác viên: OpenCode)

> Nộp các quest T1-T5 tại đây. Quy ước tên file + template: `deliverables/README.md`.

| Quest | File dự kiến | Trạng thái hiện tại |
|---|---|---|
| T1 | `T1_public_link_checklist.md` (deploy Streamlit + secrets, deadline 12/08) | **DONE 08/08** — chờ T nối repo trên dashboard Streamlit (xem checklist) |
| T2 | `T2_openvino_benchmark.md` (nếu có AI PC, deadline 20/08) | PENDING — chờ xác định máy |
| T3 | `T3_cloud_llm_hardening.md` (timeout/retry/classify, deadline 15/08) | **DONE 08/08** — xem dưới |
| T4 | `T4_red_false_positive_tests.md` (deadline 15/08) | PENDING |
| T5 | `T5_release_note.md` (release + tag, deadline 24/08) | PENDING |

## Trạng thái T1 (DONE 08/08)

- Secrets merge từ Streamlit dashboard (`_merge_streamlit_secrets`), secrets
  template + gitignore, retention log 30 ngày, guard abuse UI (20 câu/phiên,
  1000 ký tự), `.streamlit/config.toml`, `requirements-streamlit.txt`.
- **Real-mode smoke test Groq: 12/12 passed** — 9 trả lời có nguồn, 3 từ
  chối/CLARIFY đúng; 2/12 chậm ~56s (retry — nghi rate limit free tier).
  Report: `results/smoke_cloud_20260808_1123.json`.
- Bước cuối của T: xoay key + nối repo trong Streamlit dashboard (xem
  `T1_public_link_checklist.md`).

## Trạng thái T3 (DONE 08/08)

- `app/llm/base.py`: `retry_transient()` với exponential backoff + policy
  retry chỉ cho transient (network/429/5xx — KHÔNG retry JSON lỗi).
- `app/llm/groq_llm.py` + `app/llm/gemini_llm.py`: timeout client,
  retry 3 lần, và **`classify_safe()`** — classifier an toàn LLM cho router
  (trước đây path này là code chết vì adapter không có method này).
- Cấu hình: `LLM_TIMEOUT_SECONDS` (60), `LLM_MAX_RETRIES` (3),
  `LLM_RETRY_BACKOFF_SECONDS` (1.0).
- 11 test mới (`tests/test_llm_cloud.py`), tổng 94 tests xanh, ruff sạch.
- Bằng chứng sửa lỗi test quan trọng: fake SDK phải là method có `self`
  (bound) giống SDK thật — lỗi fake trước đó khiến retry-path không được
  test đúng.

## Ghi chú

- T4 (RED false positive) + T1 (deploy) đang chờ: T1 cần API key (Groq/Gemini)
  + tài khoản Streamlit. T2 cần xác nhận máy AI PC.
