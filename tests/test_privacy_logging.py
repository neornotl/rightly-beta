"""Privacy/logging tests: scrubbers, JSONL logging, session deletion."""

from __future__ import annotations

from app.logging_utils import JsonlLogger, SessionStore, scrub_text, scrub_value


def test_scrub_removes_email_phone_long_id():
    text = (
        "Liên hệ tôi qua abc.def@gmail.com hoặc 0912 345 678, mã 9f86d081884c7d659a2feaa0c55ad015a"
    )
    scrubbed = scrub_text(text)
    assert "gmail.com" not in scrubbed
    assert "0912" not in scrubbed
    assert "9f86d081884c7d659a2feaa0c55ad015a" not in scrubbed
    assert "[EMAIL_REDACTED]" in scrubbed
    assert "[PHONE_REDACTED]" in scrubbed


def test_scrub_value_recurses():
    record = {
        "transcript": "gọi 0987654321",
        "nested": {"email": "a@b.com", "ok": "thủ tục"},
        "list": ["số 113"],
    }
    scrubbed = scrub_value(record)
    assert scrubbed["transcript"] == "gọi [PHONE_REDACTED]"
    assert scrubbed["nested"]["email"] == "[EMAIL_REDACTED]"
    assert scrubbed["nested"]["ok"] == "thủ tục"


def test_scrubber_limitations_documented():
    # "113" is short and must NOT be falsely redacted by the heuristic.
    assert scrub_text("gọi 113") == "gọi 113"


def test_jsonl_logger_roundtrip(tmp_path):
    logger = JsonlLogger(tmp_path)
    logger.log({"event": "test", "session_id": "s1", "note": "chào bạn, liên hệ a@b.com"})
    records = logger.read_records()
    assert len(records) == 1
    assert records[0]["event"] == "test"
    assert "a@b.com" not in records[0]["note"]


def test_session_store_delete(tmp_path):
    store = SessionStore(tmp_path)
    s1 = store.create()
    store.record(s1, "a", x=1)
    s2 = store.create()
    store.record(s2, "b", x=2)
    removed = store.delete_session(s1)
    assert removed == 2
    remaining = store.logger.read_records()
    assert all(r["session_id"] != s1 for r in remaining)


def test_utf8_vietnamese_in_logs(tmp_path):
    logger = JsonlLogger(tmp_path)
    logger.log({"event": "x", "session_id": "s", "msg": "thủ tục hành chính - Ủy ban nhân dân"})
    text = logger.path.read_text(encoding="utf-8")
    assert "Ủy ban nhân dân" in text


def test_scrub_preserves_session_id_and_timestamp():
    record = {
        "event": "pipeline_result",
        "session_id": "70eadf1234567890",
        "timestamp": "2026-08-07T10:46:27.123+00:00",
        "transcript": "gọi 0912345678 giúp tôi",
    }
    scrubbed = scrub_value(dict(record))
    assert scrubbed["session_id"] == record["session_id"]
    assert scrubbed["timestamp"] == record["timestamp"]
    assert scrubbed["transcript"] == "gọi [PHONE_REDACTED] giúp tôi"


def test_scrub_text_preserves_iso_timestamps_and_hex_ids():
    text = "lúc 2026-08-07T10:46:27 gọi 0912 345 678, id 70eadf12ab34cd56"
    scrubbed = scrub_text(text)
    assert "2026-08-07T10:46:27" in scrubbed
    assert "70eadf12ab34cd56" in scrubbed
    assert "0912 345 678" not in scrubbed


def test_scrub_text_preserves_pure_digit_16_char_ids():
    # A 16-digit run (real phone redaction range is 9-15 digits) must
    # survive; a 10-digit mobile must not.
    scrubbed = scrub_text("mã 1234567890123456, gọi 0987654321")
    assert "1234567890123456" in scrubbed
    assert "0987654321" not in scrubbed


def test_session_store_delete_works_with_hex_session_ids(tmp_path):
    store = SessionStore(tmp_path)
    s1 = store.create()
    store.record(s1, "a", x=1)
    removed = store.delete_session(s1)
    assert removed == 2
    remaining = store.logger.read_records()
    assert all(r["session_id"] != s1 for r in remaining)
