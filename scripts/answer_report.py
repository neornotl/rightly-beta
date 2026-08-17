"""Print full natural answers from real-mode (Groq) for review.

Usage: python scripts/answer_report.py [--save]
Saves a markdown report to results/answer_report_<date>.md and prints it.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

QUERIES = [
    "Tôi muốn xin trích lục khai sinh cho con tôi thì cần những giấy tờ gì?",
    "Đăng ký khai sinh quá hạn 60 ngày có bị phạt không?",
    "Tôi cần đăng ký kết hôn, hồ sơ gồm những gì?",
    "Giấy khai sinh bị mất thì xin cấp lại như thế nào?",
    "Tôi nên mua cổ phiếu của công ty nào để sinh lời?",
]


def main() -> int:
    os.environ["APP_MODE"] = "cloud"
    os.environ["LLM_BACKEND"] = "groq"
    os.environ["ASR_BACKEND"] = "mock"
    os.environ["RETRIEVAL_BACKEND"] = "bm25"
    os.environ["TTS_BACKEND"] = "mock"

    from app.config import load_settings
    from app.pipeline import Pipeline

    settings = load_settings()
    if not settings.groq_api_key:
        print("ERROR: GROQ_API_KEY not set.")
        return 2
    pipeline = Pipeline(settings=settings)
    session_id = pipeline.create_session()

    lines: list[str] = []
    for i, query in enumerate(QUERIES, 1):
        result = pipeline.process_text(session_id, query)
        lines.append(f"## {i}. {query}\n")
        lines.append(
            f"- Zone: {result.decision.zone.value} / Action: {result.decision.action.value}"
        )
        lines.append(f"- Reason codes: {', '.join(result.decision.reason_codes)}")
        lines.append(f"- LLM latency: {result.latencies_ms.get('llm_ms', -1):.0f} ms")
        if result.answer:
            lines.append("\n**Trả lời:**\n")
            lines.append(result.answer.answer_text)
            lines.append("\n\n**Spoken citation:** " + (result.answer.spoken_citation or "(trống)"))
            if result.answer.limitations:
                lines.append("\n**Giới hạn:**")
                for lim in result.answer.limitations:
                    lines.append(f"- {lim}")
            if result.answer.next_step:
                lines.append("\n**Next step:** " + result.answer.next_step)
        else:
            lines.append("\n**Không trả lời — hướng dẫn từ router:**\n")
            lines.append(result.decision.user_message)
        lines.append("\n---\n")

    report = "\n".join(lines)
    save = "--save" in sys.argv
    if save:
        out = (
            ROOT
            / "results"
            / f"answer_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.md"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"[saved] {out}\n")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
