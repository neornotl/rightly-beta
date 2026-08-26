from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORM_URL = (
    "https://docs.google.com/forms/d/11cJjCN9qlkSYzMzSYPoCE0EzQwBddtvS4uRwzwTsTFE/viewform"
)


def test_web_exposes_one_safe_public_pilot_link():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert html.count(FORM_URL) == 1
    anchor = html[html.index(FORM_URL) - 120 : html.index(FORM_URL) + len(FORM_URL) + 180]
    assert 'target="_blank"' in anchor
    assert 'rel="noopener noreferrer"' in anchor
    assert "Góp ý trải nghiệm" in anchor
    assert "/edit" not in anchor


def test_pilot_docs_call_snapshot_non_final_and_do_not_claim_51_current():
    for name in ("README.md", "docs/product-and-pilot.md", "docs/pilot-results-2026-08.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert FORM_URL in text
        assert "56" in text
        assert "26/08/2026" in text
    report = (ROOT / "docs/pilot-results-2026-08.md").read_text(encoding="utf-8")
    assert "không phải tổng cuối cùng" in report
    assert "mốc cũ như 51" in report
