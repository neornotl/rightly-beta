"""Static regressions for the browser's explicit cloud-history consent."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cloud_context_is_opt_in_and_can_be_deleted():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert "let cloudSyncEnabled = false;" in html
    assert "if (!cloudSyncEnabled || !supabaseClient || !currentUser || chatHistory.length) return;" in html
    assert "if (!cloudSyncEnabled || !supabaseClient || !currentUser || !chatHistory.length) return;" in html
    assert 'id="cloudSync"' in html
    assert 'id="cloudDelete"' in html
    assert "window.confirm(" in html
    assert ".from('rightly_context').delete().eq('user_id', currentUser.id)" in html
    assert "cloudSyncEnabled = false;" in html


def test_login_does_not_automatically_fetch_or_save_cloud_context():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    init_auth = html[html.index("async function initAuth"):html.index("authOpen.addEventListener")]

    assert "loadCloudContext" not in init_auth
    assert "saveCloudContext" not in init_auth


def test_supabase_schema_keeps_rls_and_has_90_day_retention_job():
    schema = (ROOT / "docs" / "supabase_context.sql").read_text(encoding="utf-8")

    assert "enable row level security" in schema
    assert "interval '90 days'" in schema
    assert "revoke all on function public.prune_rightly_context()" in schema
    assert "rightly-context-retention" in schema
