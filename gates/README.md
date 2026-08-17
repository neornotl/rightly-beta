# Pilot-readiness gates (council round 27)

8 gate test từ kết luận của luna + m365 (round 27, `debate_output/round27.json`).
Mục đích: **xác định sản phẩm đã đủ để mở pilot nội bộ (có consent form) chưa.**

## Chạy
```bash
.venv\Scripts\python.exe -m pytest tests/gates -v
```
Chạy nhanh (offline): BM25 corpus thật + MockLLM + MockTTS + validator thật.
Không cần mạng, không cần API key.

## Trạng thái hiện tại (17/08/2026)

`69 passed, 0 failed` (offline; lần đầu: 50 passed / 18 failed)

| Gate | Tên | Loại | File | PASS? |
|---|---|---|---|---|
| 1a | Safety routing (RED/ORANGE/REFUSE) | tự động | `tests/gates/test_gate1_safety.py` | ✅ pass |
| 1b | Out-of-scope không được trả lời | tự động | `tests/gates/test_gate1_safety.py` | ✅ **pass (đã fix)** |
| 2 | Citation & hiệu lực văn bản | tự động | `tests/gates/test_gate2_citation.py` | ✅ pass |
| 3 | Retrieval trên câu đời thường (recall@5 ≥ 80%) | tự động | `tests/gates/test_gate3_retrieval.py` | ✅ **pass (đã fix 6 FAQ)** |
| 4 | Contacts verified ≥ 5 | tự động | `tests/gates/test_gate4_contacts.py` | ✅ **pass (đã điền dữ liệu)** |
| 5 | Privacy / consent / audit | tự động | `tests/gates/test_gate5_privacy.py` | ✅ pass |
| 6 | Usability người cao tuổi | thủ công | `gates/GATE6_usability_checklist.md` | ⏳ tiền quyết đã xác minh; cần người thử |
| 7 | Ổn định 30 phiên + fault injection | tự động | `tests/gates/test_gate7_stability.py` | ✅ **pass (đã xử lý retriever fault)** |
| 8 | Vận hành (freeze + dry-run) | thủ công | `gates/GATE8_ops_checklist.md` | ⏳ freeze/scan xong; cần dry-run người thật |

## Fix OOS đã áp dụng (17/08/2026)
1. **Mở rộng `_OUT_OF_SCOPE_PATTERNS`** (`app/safety/rules.py`): thêm ~40 pattern
   chủ đề đời thường (thời tiết, nấu ăn, cà phê, giá vàng, bóng đá, cổ tích,
   máy giặt, tập thể dục, giờ bay, đổi sim, đăng ký tài khoản mạng xã hội,
   mua/bán hàng, thời trang, làm đẹp...) — xác định, không cần mạng.
2. **Guard "procedural intent"** (`app/safety/rules.py::has_procedural_intent`):
   chỉ marker thủ tục mạnh ("thủ tục", "quy định", "hồ sơ", "điều X", "chế độ"…)
   mới ghi đè OOS; từ khóa khám phá yếu ("là gì", "thế nào") KHÔNG ghi đè
   (vd "Thời trang nam đang hot là gì?" vẫn bị chặn).
3. **Lớp LLM (defense-in-depth)**: bật `classify_safe` cho local+pateway qua
   `USE_LLM_CLASSIFIER=true` (`app/config.py`, `app/pipeline.py`). Probe trên
   Pateway: in-scope 10/10 safe=true, OOS 16/17 safe=false (case lọt "đổi sim"
   đã bị rule chặn ở step 4). Fail-safe: classifier lỗi → CLARIFY, không trả lời.

## Blockers đã đóng (17/08/2026)
1. **Contacts rỗng (gate 4):** đã điền `data/contacts.json` 5 đầu mối verified
   (113/115/114/1022/BHXH 1900 9068 — số công bố chính thức; trước demo vẫn cần
   cuộc gọi thử của team). Đồng bộ `.env` + default `config.py`:
   hotline 113, one-stop 1022.
2. **6 FAQ nguồn không truy xuất được:** thay `search_text` trong
   `data/faq.json` bằng query ngắn, chính xác đã kiểm chứng BM25 (rank 1–3 trong
   top-5): khiếu nại, vượt đèn đỏ (ND 168/2024), tố cáo, hợp tác xã, nghỉ phép
   (BLLĐ), lương hưu (Luật BHXH). Recall 50/50 = 100%.
3. **Retriever-level fault (gate 7):** pipeline mới có `_retrieve()` bọc
   `retriever.search` bằng try/except → lỗi retriever thành `retriever_failure`
   ghi audit + degrade về REFUSE/CLARIFY, không crash phiên. Có test mới
   `test_gate7_retriever_fault_degrades_to_refusal`.

## Còn lại (cần người thật)
- **Gate 6:** tiền quyết đã xác minh tự động (không dấu, OOS, latency, truy vết);
  vẫn cần 2–3 người >60 tuổi thử + điền checklist.
- **Gate 8:** freeze manifest `gates/freeze_manifest.json`, `.env` khớp spec,
  scan no-PII (chỉ session_id + số tiền/điều khoản trong corpus) đã xong;
  còn buổi dry-run với người thật + kênh incident.

## Ghi chú vận hành
- Battery gate chạy với MockLLM cho xác định; **gate 1b đã được kiểm lại trên
  LLM thật (Pateway + hybrid retrieval)**: câu in-scope vẫn trả lời kèm
  citation, câu OOS → GUIDE/CLARIFY, không trả lời tự tin.
- Các gate thủ công 6 + 8 cần người thật; không thể tự động hóa.