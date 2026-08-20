# Rightly

Source-grounded, voice-first public-service access agent — hỗ trợ người dân
(nhất là người cao tuổi, người khiếm thị, người khó đọc, người hạn chế kỹ
năng số, và người bận rộn không có thời gian tự tra cứu) tra cứu thủ tục hành
chính, quyền lợi công và quy định pháp luật (dân sự) bằng **tiếng Việt**, với
câu trả lời **bám nguồn chính thống** và rào chắn an toàn rõ ràng.

> **Trạng thái: PREPARATION / MVP (mock-first).** Mọi kết quả hiện tại là
> SYNTHETIC DEMO, không phải kết quả pilot.

## Problem

Thông tin hành chính thường dạng văn bản dài, chữ nhỏ, ít kênh bằng giọng nói.
Người cao tuổi / khiếm thị / khó đọc gặp rào cản lớn. Rightly cung cấp kênh
hỏi-đáp bằng giọng nói, mỗi câu trả lời kèm nguồn, và **từ chối trả lời** khi
không đủ nguồn tin cậy.

## Target users

- Người cao tuổi nông thôn / thành thị.
- Người khiếm thị, người khó đọc.
- Người ít kỹ năng số.
- Người bận rộn, không có thời gian đọc/tra cứu văn bản — gọi điện hỏi nhanh
  về thủ tục, dân sự, quy định pháp luật như gọi hotline.

## Scope and non-goals

**Trong phạm vi (phase này):**
- Voice-first pipeline chạy local: ASR → chuẩn hóa → retrieval (RAG) →
  LLM có nguồn → safety routing (VÀNG/CAM/ĐỎ) → TTS.
- Mock mode chạy đầu-cuối không cần API key / model nặng.
- Bộ đánh giá R1 (WER), R2 (Retrieval), R3 (Routing), R4 (Latency) với
  fixture SYNTHETIC.
- Giao diện CLI (state machine) + Streamlit UI tùy chọn.

**Ngoài phạm vi (phase này):**
- FreeSWITCH / SIP / callback tự động, đa ngôn ngữ, OpenVINO.
- Tích hợp điện thoại/SIM (adapter tùy chọn sau).
- Không dùng dữ liệu thật; không nhận PII ngoài câu hỏi cần thiết.

## Architecture

```
Người dùng nói
  → ASR (MockASR | PhoWhisper, local)
  → normalize + phát hiện rủi ro (rule-based, trước LLM)
  → retrieval (BM25 trên kho nguồn đã ingest)
  → SafetyRouter (RED→ORANGE→scope→đủ nguồn→LLM classification tùy chọn)
  → LLM tạo câu trả lời bám nguồn (MockLLM | Gemini | Groq)
  → TTS (MockTTS | Edge-TTS)
  → human-in-the-loop / chuyển kênh chính thức khi cần
```

Chi tiết: `docs/architecture.md`.

## Quick start (mock mode — không cần key, không tải model)

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/ingest_documents.py
.\.venv\Scripts\python.exe scripts/run_mock_demo.py
```

Unix (make): `make setup && make mock-demo`.

Demo dữ liệu là **DEMO/SYNTHETIC** (xã Bình Minh hư cấu) — không phải hướng
dẫn hành chính thật.

## Local / cloud mode

- `ASR_BACKEND=phowhisper`: cần `pip install faster-whisper` + chủ động tải
  model (xem `docs/hardware_benchmark_plan.md`).
- `LLM_BACKEND=gemini|groq|pateway`: cần API key trong `.env` (`GEMINI_API_KEY`,
  `GROQ_API_KEY`, `PATEWAY_API_KEY`). Chỉ transcript + chunks được gửi; không gửi audio.
- `LLM_BACKEND=local`: Ollama (hoặc server OpenAI-compatible bất kỳ), với model
  được `scripts/detect_hardware.py` chọn theo RAM/GPU. Sau khi pull model một
  lần, phần LLM chạy offline. Nếu Ollama chưa sẵn sàng, web vẫn khởi động bằng
  `MockLLM` an toàn thay vì crash.
- `TTS_BACKEND=edge`: cần `edge-tts`, cần mạng lúc chạy.
- `APP_MODE=cloud`: bật thêm LLM classification trong router (vẫn bị rule
  RED/ORANGE ghi đè).

Setup chi tiết: `docs/setup.md`.

### One-click local pilot (Windows)

After the one-time `scripts\offline_setup.bat`, double-click
`scripts\run_local_pilot.bat`. It starts Ollama if needed, verifies the local
model, launches Streamlit with local-only settings, and automatically records
the runtime manifest, one-time local benchmark, session traces and latency
under `logs/` and `results/`. It never falls back to cloud. Export consenting
pilot metrics separately with `python scripts/log_pilot_metrics.py --export`.

### One-click deploy to another machine (Windows)

Copy the whole folder to the target PC, then
double-click **`start.bat`**. It:

1. Creates a local `.venv` and installs `requirements-deploy.txt`.
2. Creates `.env` from `.env.example` (defaults: LLM `local`/Ollama, ASR
   `whisper`/faster-whisper, retrieval `bm25` — fully offline).
3. Detects RAM/CPU/GPU/disk and chooses a fitting local LLM and ASR model.
4. If `LLM_BACKEND=local`, verifies Ollama is installed and pulls the selected
   model. If it is unavailable, the API stays online with safe fallbacks.
5. Starts the FastAPI web server on `http://localhost:8010` and opens the browser.

Optional feature flags in `.env`:
- `ASR_BACKEND=whisper` + `WHISPER_MODEL=small` — local Vietnamese speech input.
  The web UI has Chat and simulated Call modes. TTS tries the Vietnamese neural
  endpoint first, then gTTS, then the browser's local voice as a no-network
  fallback.
- `LEGAL_INTAKE=true` — before answering a personalized legal question, the
  assistant asks (one at a time) for the missing facts the answer depends on.
- `ANSWER_REVIEW=true` — before sending the answer, the model reviews the
  question against the answer by itself. If it finds the answer unfit it is
  allowed to rewrite it and redo the answer process (self-correction loop,
  bounded by `ANSWER_REVIEW_MAX_REVISIONS`, default 2), still grounded in the
  retrieved evidence. The summary + fit result is shown in the web UI.
- `RETRIEVAL_BACKEND=hybrid` — better answers but needs a one-time download of
  the `multilingual-e5-small` embedding model (internet on first run).

### Web deployment

The production container runs `webhook_server.py` with FastAPI, not Streamlit,
so missing Ollama, embedding models, or native ML libraries cannot prevent the
health endpoint and UI from starting. It uses BM25 + safe fallback modes by
default. `Dockerfile` and `render.yaml` are included for a Render Docker web
service; set the service health check to `/health`.

To stop the server: close the window that runs `webhook_server.py`, or kill the
python process listening on port 8010.

## Data structure

```
data/
├── sources/            # markdown nguồn (DEMO/SYNTHETIC)
├── chunks/             # chunks JSONL (sinh bởi ingest)
├── metadata.csv
├── eval/               # fixture dev/test cho R2, R3
└── schemas/            # JSON schema cho source & eval cases
```

Xem `docs/data_card.md` và `docs/evaluation_dataset_card.md`.

## Evaluation (R1-R4)

```powershell
python -m eval.run_all            # chạy tất cả, ghi results/
python -m eval.wer --input data/eval/wer_dev.jsonl
python -m eval.retrieval --input data/eval/retrieval_test.jsonl
python -m eval.routing --input data/eval/routing_test.jsonl
python -m eval.latency --input data/eval/latency_dev.jsonl
```

Output tại `results/`: `*_results.csv`, `*_summary.json`,
`evaluation_report.md` — tất cả ghi chú **SYNTHETIC DEMO - NOT PILOT RESULTS**.

## Privacy and safety

- Không gửi audio lên cloud ở thiết kế mặc định.
- Log ẩn danh (session ID ngẫu nhiên), transcript không lưu trừ khi
  `SAVE_TRANSCRIPTS=true`; xóa raw audio sau phiên.
- `scripts/scrub_logs.py` — scrub heuristic (email/điện thoại/ID dài); không
  phải thay thế xóa dữ liệu pháp lý.
- Không hard-code số điện thoại khẩn cấp chưa xác minh; dùng placeholder
  trong config.
- Xem `docs/responsible_ai.md`, `docs/privacy_deletion_policy.md`,
  `docs/threat_model.md`.

## Quality gates

```powershell
python -m pytest                # test
python -m ruff check .          # lint
python -m ruff format --check . # format
python scripts/validate_data.py # dữ liệu
python scripts/preflight.py     # toàn bộ (test+lint+demo+eval+secret scan)
```

## Limitations

- Rule an toàn là heuristic, cần review bởi chuyên gia tiếng Việt.
- BM25 không hiểu ngữ nghĩa; chưa có embedding/rerank.
- Không dùng confidence score (chưa có calibration).
- Xem đầy đủ: `docs/limitations.md`.

## Project status

| Hạng mục | Trạng thái |
|---|---|
| Mock vertical slice | DONE |
| Adapter PhoWhisper / Gemini / Groq / Edge-TTS | DONE (lazy, chưa pilot) |
| Streamlit UI | DONE (tùy chọn) |
| Eval R1-R4 (synthetic) | DONE |
| Pilot (8-10 người) | TODO — `docs/pilot_protocol.md` |
| Deployment | TODO — `docs/deployment_strategy.md` |

## License

MIT — xem `LICENSE`.
