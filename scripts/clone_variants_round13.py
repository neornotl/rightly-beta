#!/usr/bin/env python3
"""Clone/paraphrase 100-question pool into new test questions, then smoke-test
FAQMatcher + full pipeline answers on them. Round-13 "M365 clone" step."""
from __future__ import annotations

import concurrent.futures
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PARAPHRASE_SYSTEM = """Bạn là chuyên gia tiếng Việt. Cho một câu hỏi của người dân về thủ tục hành chính, quyền lợi công hoặc pháp luật, hãy viết RA 2 CÁCH HỎI KHÁC — tự nhiên như cách người dân thật trên hotline hỏi (có thể kể chuyện ngắn, đổi thứ tự ý, dùng từ địa phương, mất dấu, sai chính tả nhẹ, hỏi chung chung hơn hoặc cụ thể hơn). GIỮ NGUYÊN Ý và GIỮ CÁC TỪ KHOÁ chính (tên thủ tục, con số, cơ quan). Không thêm yêu cầu mới không có trong câu gốc. Trả về JSON duy nhất: {"v1": "...", "v2": "..."}"""

PARAPHRASE_USER = "Câu hỏi gốc: {q}"


def build_client():
    from groq import Groq
    from app.config import load_settings

    settings = load_settings()
    key = getattr(settings, "groq_api_key", "") or ""
    return Groq(api_key=key, timeout=60.0)


def paraphrase_one(client, q: str) -> list[str]:
    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": PARAPHRASE_SYSTEM},
                {"role": "user", "content": PARAPHRASE_USER.format(q=q)},
            ],
            temperature=0.9,
            max_tokens=220,
        )
        text = (resp.choices[0].message.content or "").strip()
        payload = json.loads(text)
        out = [str(payload[k]).strip() for k in ("v1", "v2") if payload.get(k)]
        return out
    except Exception as exc:  # noqa: BLE001 - retryable clone step
        print(f"  [clone-fail] {q[:40]}... -> {exc}", file=sys.stderr)
        return []


def main() -> int:
    pool = json.loads((ROOT / "data" / "eval_pool_100.json").read_text(encoding="utf-8"))
    questions = pool.get("questions", pool) if isinstance(pool, dict) else pool
    if isinstance(questions, dict):
        questions = list(questions.values())
    questions = [q.get("question") if isinstance(q, dict) else q for q in questions]
    questions = [q for q in questions if q]
    rng = random.Random(20260816)
    rng.shuffle(questions)
    sample = questions[:40]

    print(f"cloning {len(sample)} questions -> 2 variants each")
    client = build_client()
    variants: dict[str, list[str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(paraphrase_one, client, q): q for q in sample}
        for fut in concurrent.futures.as_completed(futures):
            q = futures[fut]
            variants[q] = fut.result()

    rows = []
    for q, vs in variants.items():
        for v in vs:
            rows.append({"original": q, "variant": v})
    out = ROOT / "data" / "eval" / "clone_variants_round13.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"saved {len(rows)} variants -> {out}")

    from app.faq import FAQMatcher

    matcher = FAQMatcher()
    matched = 0
    for r in rows:
        h = matcher.answer(r["variant"])
        if h:
            matched += 1
    print(f"FAQMatcher hits: {matched}/{len(rows)} ({100*matched/max(len(rows),1):.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())