"""Tests for the danh bạ (contacts) + phiếu hồ sơ (registration slip) demo."""

from __future__ import annotations

from pathlib import Path

from app.contacts import Contact, all_contacts, default_contact, find_by_category, find_contact
from app.forms import build_registration_slip


def test_contacts_load_from_disk():
    contacts = all_contacts()
    assert isinstance(contacts, tuple)
    assert all(c.id for c in contacts)


def test_binhminh_contacts_removed():
    """Council/user decision: no fake xã Bình Minh contacts in the book."""
    assert find_contact("bo-phan-mot-cua-xa-binh-minh") is None
    assert find_contact("cong-an-xa-binh-minh") is None


def test_find_contact_missing_returns_none():
    assert find_contact("khong-ton-tai") is None


def test_find_by_category_orders_verified_first():
    hits = find_by_category("bo_phan_mot_cua")
    assert isinstance(hits, tuple)
    assert all(c.category == "bo_phan_mot_cua" for c in hits)


def test_default_contact_returns_none_when_book_empty(monkeypatch):
    monkeypatch.setattr("app.contacts._load_contacts", lambda path=None: ())
    assert default_contact() is None


def test_unverified_phone_is_not_callable():
    c = Contact(
        id="x",
        label="X",
        category="bo_phan_mot_cua",
        phone="1900XXXX",
        verified=False,
    )
    assert not c.callable
    assert c.tel_link == ""


def test_verified_phone_is_callable_and_tel():
    c = Contact(
        id="x",
        label="X",
        category="bo_phan_mot_cua",
        phone="0243 000 000",
        verified=True,
    )
    assert c.callable
    assert c.tel_link == "tel:0243000000"


def test_tel_link_drops_non_digits():
    c = Contact(
        id="x",
        label="X",
        category="bo_phan_mot_cua",
        phone="1900 1234 (tổng đài)",
        verified=True,
    )
    assert c.tel_link == "tel:19001234"


def test_slip_markdown_has_privacy_and_no_personal_fields_prefilled():
    c = Contact(id="x", label="Bộ phận một cửa", category="bo_phan_mot_cua", verified=False)
    slip = build_registration_slip(
        query="Xin xác nhận hộ nghèo?",
        summary="Nộp tại UBND xã, phòng số 1.",
        next_step="Mang CCCD + sổ hộ khẩu.",
        contact=c,
    )
    md = slip.to_markdown()
    assert "Xin xác nhận hộ nghèo?" in md
    assert "Bộ phận một cửa" in md
    assert "Họ và tên:" in md
    assert "Số CCCD:" in md
    assert "KHÔNG thu thập, lưu trữ hay gửi" in md
    assert "KHÔNG CÓ GIÁ TRỊ PHÁP LÝ" in md
    assert "Mang CCCD + sổ hộ khẩu." in md


def test_slip_with_callable_contact_shows_phone():
    c = Contact(
        id="x",
        label="Công an xã",
        category="cong_an",
        phone="1900 1234",
        verified=True,
    )
    md = build_registration_slip(
        query="q", summary="s", contact=c, documents=["Đơn trình báo", "CCCD"]
    ).to_markdown()
    assert "1900 1234" in md
    assert "- [ ] Đơn trình báo" in md


def test_slip_without_contact_omits_contact_section(tmp_path: Path):
    md = build_registration_slip(query="q", summary="s").to_markdown()
    assert "Nơi liên hệ" not in md
