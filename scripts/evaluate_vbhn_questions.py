"""Run a small, manually reviewable VBHN question set through the pipeline."""

import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings
from app.pipeline import Pipeline


QUESTIONS = [
    "Theo Bộ luật Lao động hiện hành, thời giờ làm việc bình thường tối đa bao nhiêu giờ mỗi ngày và mỗi tuần?",
    "Theo Luật Bảo hiểm xã hội hiện hành, hồ sơ giải quyết hưởng lương hưu gồm những giấy tờ gì?",
    "Theo Luật Cư trú hiện hành, đăng ký tạm trú cần nộp hồ sơ ở đâu và gồm giấy tờ gì?",
    "Theo Luật Nhà ở hiện hành, điều kiện để được mua nhà ở xã hội là gì?",
    "Những ai thuộc diện được trợ giúp pháp lý miễn phí theo quy định hiện hành?",
    "Theo Luật Trẻ em, trẻ em có quyền được bảo vệ khỏi những hành vi nào?",
    "Tôi muốn xin hộ chiếu gấp trong ngày, cần làm thủ tục ở đâu?",
    "Luật hiện hành quy định thế nào?",
]


def main() -> None:
    settings = load_settings()
    settings = replace(settings, retrieval_backend="hybrid", tts_backend="mock")
    pipeline = Pipeline(settings=settings)
    session = pipeline.create_session()
    results = []
    for question in QUESTIONS:
        result = pipeline.process_text(session, question)
        results.append(
            {
                "question": question,
                "decision": result.decision.zone.value,
                "answer": result.answer.answer_text if result.answer else None,
                "sources": list(result.answer.source_ids) if result.answer else [],
                "retrieved": [c.source_id for c in result.chunks[:8]],
                "limitations": result.answer.limitations if result.answer else [],
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    Path("data/vbhn_question_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
