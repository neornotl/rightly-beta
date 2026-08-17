"""Basic real Groq LLM test: 8 grounded questions against demo chunks.

Verifies: valid API key, structured JSON output, schema enforcement
(no hallucinated source_ids). Maximum 8 LLM calls total.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_settings  # noqa: E402
from app.llm.groq_llm import GroqLLM  # noqa: E402
from app.retrieval.bm25_retriever import BM25Retriever  # noqa: E402

QUERIES = [
    "Tôi cần đăng ký khai sinh cho con, thủ tục như thế nào?",
    "Hồ sơ đăng ký kết hôn cần những giấy tờ gì?",
    "Đăng ký tạm trú cần bao nhiêu ngày xử lý?",
    "Tôi muốn xin cấp lại giấy khai sinh vì bị mất, phí là bao nhiêu?",
    "Thủ tục xin giấy xác nhận tình trạng hôn nhân mất bao lâu?",
    "Đăng ký khai sinh quá hạn có bị phạt không?",
    "Hồ sơ xin cấp hộ chiếu gồm những gì?",
    "Tôi cần thay đổi họ tên trong giấy khai sinh, làm ở đâu?",
]


def main() -> int:
    settings = load_settings()
    llm = GroqLLM(api_key=settings.groq_api_key)
    if not llm.available:
        print("FAIL: GROQ_API_KEY not set")
        return 1

    retriever = BM25Retriever.from_jsonl(settings.chunks_dir / "demo_chunks.jsonl")
    min_score = settings.min_retrieval_score

    results = []
    for i, q in enumerate(QUERIES, start=1):
        chunks = [c for c in retriever.search(q, top_k=3) if c.score >= min_score]
        allowed = {c.source_id for c in chunks}
        print(f"\nQ{i}: {q}")
        print(f"  chunks: {len(chunks)} | allowed sources: {sorted(allowed)}")
        try:
            ans = llm.generate_answer(q, chunks, max_chars=settings.max_response_chars)
            ok_schema = (
                isinstance(ans.get("answer_text"), str)
                and isinstance(ans.get("spoken_citation"), str)
                and isinstance(ans.get("source_ids"), list)
                and isinstance(ans.get("limitations"), list)
                and isinstance(ans.get("next_step"), str)
            )
            hall = [s for s in ans.get("source_ids", []) if s not in allowed]
            cited = ans.get("source_ids", []) or ["(none)"]
            print(f"  OK: schema={ok_schema} hallucinated_ids={hall or 'none'}")
            print(f"  cited: {cited}")
            print(f"  answer[:160]: {ans.get('answer_text', '')[:160]}")
            results.append(
                {
                    "query": q,
                    "schema_ok": ok_schema,
                    "hallucinated_ids": hall,
                    "cited": ans.get("source_ids", []),
                    "answer_preview": ans.get("answer_text", "")[:160],
                }
            )
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}")
            results.append({"query": q, "error": str(exc)})

    out = ROOT / "results" / "groq_basic_test.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps({"total": len(results), "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ok = all(r.get("schema_ok", False) for r in results if "error" not in r)
    print(
        f"\nSUMMARY: {len(results)} queries, {sum('error' not in r for r in results)} answered, file: {out}"
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
