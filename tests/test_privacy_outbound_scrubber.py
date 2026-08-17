"""Outbound privacy scrubber tests (app/privacy/scrubber.py)."""

from __future__ import annotations

from app.privacy.scrubber import scrub_outbound


def test_scrub_outbound_redacts_email_and_phone():
    text = "Liên hệ abc.def@gmail.com hoặc 0912 345 678 để gặp tôi"
    scrubbed = scrub_outbound(text)
    assert "gmail.com" not in scrubbed
    assert "0912" not in scrubbed
    assert "[EMAIL]" in scrubbed
    assert "[SĐT]" in scrubbed


def test_scrub_outbound_redacts_cccd_9_digit():
    scrubbed = scrub_outbound("CMND của tôi là 023456789")
    assert "023456789" not in scrubbed
    assert "[CCCD]" in scrubbed


def test_scrub_outbound_redacts_cccd_12_digit():
    scrubbed = scrub_outbound("CCCD 079203001234 hết hạn")
    assert "079203001234" not in scrubbed
    assert "[CCCD]" in scrubbed


def test_scrub_outbound_redacts_passport():
    scrubbed = scrub_outbound("hộ chiếu C1234567 của tôi")
    assert "C1234567" not in scrubbed
    assert "[HỘ CHIẾU]" in scrubbed


def test_scrub_outbound_redacts_address_with_marker():
    scrubbed = scrub_outbound("tôi ở số 12 đường Nguyễn Huệ, xã Bình Minh")
    assert "số 12 đường" not in scrubbed
    assert "[ĐỊA CHỈ]" in scrubbed


def test_scrub_outbound_keeps_law_document_numbers():
    # "số 123/2021/QĐ-UBND" has no street marker: must survive (law text).
    text = "quyết định số 123/2021/QĐ-UBND còn hiệu lực không"
    scrubbed = scrub_outbound(text)
    assert "123/2021/QĐ-UBND" in scrubbed
    assert "[ĐỊA CHỈ]" not in scrubbed


def test_scrub_outbound_keeps_plain_query_text():
    text = "tôi muốn xin trích lục khai sinh cho con tôi cần giấy gì"
    assert scrub_outbound(text) == text


def test_scrub_outbound_keeps_short_numbers_like_113():
    assert "113" in scrub_outbound("gọi 113 ngay")


def test_scrub_outbound_redacts_long_ids():
    scrubbed = scrub_outbound("mã số 9f86d081884c7d659a2feaa0c55ad015a đã hết")
    assert "9f86d081884c7d659a2feaa0c55ad015a" not in scrubbed
    assert "[ID]" in scrubbed


def test_scrub_outbound_keeps_quasi_identifiers_in_query():
    # Age + commune stay in the QUERY: needed for a personalized, correct
    # answer; risk is mitigated by scripted pilot data (documented in
    # app/privacy/scrubber.py docstring).
    text = "tôi 60 tuổi ở xã Bình Minh hỏi chế độ hưu trí"
    assert scrub_outbound(text) == text
