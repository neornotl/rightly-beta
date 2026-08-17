"""Command-line interface for Rightly.

Runs the full dialogue state machine. Mock mode requires no API key, no model,
no audio hardware: use ``--transcript`` or a dummy audio file with a sibling
``.txt``.

Usage examples:
    python -m app.cli
    python -m app.cli --transcript "Thủ tục cấp giấy xác nhận hộ khẩu?"
    python -m app.cli --audio data/audio/sample.wav --once
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):  # Windows console encoding workaround
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")

from app.config import ConfigError, load_settings, safe_settings_summary
from app.dialogue.commands import Command, parse_command
from app.dialogue.state_machine import DialogueStateMachine, State
from app.pipeline import Pipeline

DISCLAIMER = (
    "Chào bạn. Tôi là Rightly - trợ lý tra cứu thủ tục hành chính. "
    "Tôi KHÔNG phải cơ quan nhà nước; thông tin chỉ để tham khảo. "
    "Bạn có thể hỏi tôi về thủ tục hành chính, hoặc nói 'trợ giúp' để biết "
    "các lệnh. (BẢN DEMO - dữ liệu mẫu, không phải hướng dẫn chính thức.)"
)

HELP_TEXT = (
    "Tôi hiểu các lệnh: 'nói lại', 'nói chậm hơn', 'bước tiếp theo', "
    "'nguồn ở đâu', 'hỏi người thật', 'nối máy' (kết nối cơ quan), "
    "'kết thúc'. Hoặc đặt câu hỏi thủ tục hành chính, ví dụ: "
    "'Thủ tục cấp giấy xác nhận hộ khẩu?'"
)

RED_TEXT = (
    "Câu hỏi của bạn thuộc tình huống khẩn cấp. Tôi không thể xử lý. "
    "Hãy gọi số khẩn cấp địa phương ngay, hoặc nhờ người thân hỗ trợ. "
    "Tôi không thay thế con người."
)


def _print_result(result, tts: bool = True) -> None:
    d = result.decision
    print(
        f"\n[ROUTING] zone={d.zone.value} action={d.action.value} "
        f"reasons={','.join(d.reason_codes)} requires_human={d.requires_human}"
    )
    if result.chunks:
        print("[RETRIEVED]")
        for c in result.chunks[:3]:
            print(f"  - {c.chunk_id} score={c.score}")
    if result.answer is not None:
        print(f"\n[ANSWER]\n{result.answer.answer_text}")
        if result.answer.spoken_citation:
            print(f"\n[SOURCE]\n{result.answer.spoken_citation}")
        if result.answer.limitations:
            print("\n[LIMITATIONS]")
            for lim in result.answer.limitations:
                print(f"  - {lim}")
        if result.answer.next_step:
            print(f"\n[NEXT STEP]\n{result.answer.next_step}")
        if tts and result.tts_output:
            print(f"\n[SPOKEN TEXT]\n{result.tts_output}")
    else:
        print(f"\n[GUIDANCE]\n{d.user_message}")
    lat = result.latencies_ms
    if lat:
        total = sum(lat.values())
        print(
            "\n[LATENCY] "
            + " ".join(f"{k}={v:.0f}ms" for k, v in lat.items())
            + f" total≈{total:.0f}ms"
        )


def run_cli(args) -> int:
    settings = load_settings()
    print(f"[CONFIG] {safe_settings_summary(settings)}")

    pipeline = Pipeline(settings=settings)
    session_id = pipeline.create_session()
    machine = DialogueStateMachine()
    holder: dict[str, Optional[str]] = {"last_answer": None}
    print(DISCLAIMER)
    machine.transition(State.DISCLAIMER)
    machine.transition(State.LISTENING)

    if args.transcript:
        _handle_query(pipeline, machine, session_id, args.transcript, holder)
        if args.once:
            pipeline.delete_session(session_id)
            return 0
    if args.audio:
        path = Path(args.audio)
        if not path.exists():
            print(f"[ERROR] audio file not found: {path}", file=sys.stderr)
            return 2
        try:
            result = pipeline.process_audio(session_id, path)
        except Exception as exc:
            print(f"[ERROR] audio processing failed: {exc}", file=sys.stderr)
            return 2
        _print_result(result)
        holder["last_answer"] = result.answer.answer_text if result.answer else None
        if args.once:
            pipeline.delete_session(session_id)
            return 0

    print("\nNhập câu hỏi (hoặc lệnh). Gõ 'kết thúc' để thoát.")
    try:
        while not machine.is_terminal():
            try:
                line = input("Bạn: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            cmd = parse_command(line)
            if cmd == Command.END:
                machine.transition(State.DONE)
                break
            if cmd == Command.REPEAT:
                if holder["last_answer"]:
                    print(f"\n[REPEAT]\n{holder['last_answer']}")
                else:
                    print("\n[REPEAT] Chưa có câu trả lời để nói lại.")
                continue
            if cmd == Command.SLOWER:
                print("\n[SLOWER] (chế độ nói chậm hơn - chưa kích hoạt trong bản demo)")
                continue
            if cmd == Command.NEXT_STEP:
                print("\n[NEXT STEP] Hỏi 'nguồn ở đâu?' hoặc đặt câu hỏi mới.")
                continue
            if cmd == Command.SOURCES:
                print(
                    "\n[SOURCES] Các nguồn demo đều có nhãn DEMO/SYNTHETIC, "
                    "không phải hướng dẫn chính thức."
                )
                continue
            if cmd == Command.HUMAN:
                machine.transition(State.ESCALATING)
                print(f"\n[ESCALATE] {RED_TEXT}")
                print("Bạn muốn quay lại hỏi tiếp? (có/không)")
                again = input("Bạn: ").strip().casefold()
                if again in {"co", "có", "yes", "y"}:
                    machine.transition(State.LISTENING)
                else:
                    machine.transition(State.DONE)
                    break
                continue
            if cmd == Command.CONNECT:
                _handle_connect(machine, holder)
                continue
            if cmd == Command.HELP:
                print(f"\n[HELP] {HELP_TEXT}")
                continue
            machine.transition(State.TRANSCRIBING)
            machine.transition(State.RETRIEVING)
            machine.transition(State.SAFETY_CHECK)
            machine.transition(State.HOLDING)
            _handle_query(pipeline, machine, session_id, line, holder)
    finally:
        pipeline.delete_session(session_id)
    return 0


def _handle_connect(machine, holder: dict[str, Optional[str]]) -> None:
    """Kết nối tới đầu mối cơ quan + phiếu chuẩn bị hồ sơ (demo-grade)."""
    from app.contacts import default_contact, find_contact
    from app.forms import build_registration_slip

    machine.transition(State.CONNECTING)
    contact = find_contact("bo-phan-mot-cua-xa-binh-minh") or default_contact()
    if contact is None:
        print("\n[CONNECT] Chưa có đầu mối liên hệ trong danh bạ (P cần xác minh).")
        machine.transition(State.LISTENING)
        return
    # Council R17: 2-step confirmation (false-positive guard on "oke"/"đồng ý").
    print("\n[CONNECT] Tôi kết nối tới cơ quan có thẩm quyền...")
    confirm = input(f"Bạn xác nhận kết nối tới: {contact.label}? (có/không): ").strip().casefold()
    if confirm not in {"co", "có", "yes", "y"}:
        print("  - Đã HỦY kết nối.")
        machine.transition(State.LISTENING)
        return
    print(f"  - {contact.label}")
    if contact.callable:
        print(f"  - Số điện thoại: {contact.phone}")
        print(
            "  - (demo: mở quay số bằng nút Gọi ngay trên giao diện web; cuộc "
            "gọi xuất phát từ thiết bị của bạn — Tiếng Làng không tự gọi.)"
        )
    else:
        print("  - Số điện thoại CHƯA XÁC MINH (placeholder) — không mở quay số.")
    if contact.note:
        print(f"  - Ghi chú: {contact.note}")
    last = holder.get("last_answer")
    if last:
        slip = build_registration_slip(
            query="(câu hỏi trước đó)",
            summary=last,
            contact=contact,
        )
        print(f"\n[SLIP]\n{slip.to_markdown()}")
    machine.transition(State.LISTENING)


def _handle_query(
    pipeline: Pipeline,
    machine,
    session_id: str,
    text: str,
    holder: dict[str, Optional[str]],
) -> None:
    """Run pipeline and drive the state machine to SPEAKING."""
    try:
        result = pipeline.process_text(session_id, text)
    except Exception as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        try:
            machine.transition(State.ERROR)
            machine.transition(State.LISTENING)
        except ValueError:
            machine.reset(State.LISTENING)
        return
    _print_result(result)
    holder["last_answer"] = result.answer.answer_text if result.answer else None
    try:
        machine.transition(State.SPEAKING)
    except ValueError:
        pass
    machine.transition(State.LISTENING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rightly", description=__doc__)
    parser.add_argument(
        "--transcript", type=str, default=None, help="Process one text query (mock path)."
    )
    parser.add_argument(
        "--audio", type=str, default=None, help="Process one audio file (ASR backend per config)."
    )
    parser.add_argument("--once", action="store_true", help="Exit after the first query.")
    return parser


if __name__ == "__main__":
    try:
        sys.exit(run_cli(build_parser().parse_args()))
    except ConfigError as exc:
        print(f"[CONFIG ERROR] {exc}", file=sys.stderr)
        sys.exit(2)
