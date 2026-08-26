import importlib.util
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke_public_release.py"
_SPEC = importlib.util.spec_from_file_location("public_smoke", _SCRIPT)
smoke = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = smoke
_SPEC.loader.exec_module(smoke)


def test_reply_validator_rejects_raw_json_and_empty_citation_placeholders():
    assert smoke._valid_reply("Câu trả lời bình thường.")
    assert not smoke._valid_reply('{"reply":"raw envelope"}')
    assert not smoke._valid_reply("Nội dung\nTrích dẫn: null")


def test_sse_parser_reads_only_data_events():
    events = smoke._sse_events("event: message\ndata: {\"type\": \"delta\", \"text\": \"Xin chào\"}\n\ndata: {\"type\": \"answer\", \"reply\": \"Xin chào\"}\n")
    assert events == [
        {"type": "delta", "text": "Xin chào"},
        {"type": "answer", "reply": "Xin chào"},
    ]


def test_markdown_report_is_body_free_and_machine_summary_is_pii_safe():
    result = {
        "ok": True,
        "passed": 1,
        "total": 1,
        "checks": [{"name": "root", "ok": True, "status": 200, "elapsed_ms": 1, "note": "HTML landing page"}],
    }
    report = smoke.markdown_report(result)
    assert "PASS (1/1)" in report
    assert "response bodies" in report
    assert "[redacted-email]" in smoke._safe_note("person@example.com")
