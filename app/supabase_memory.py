"""Explicit, opt-in Supabase context sync.

Local mode never calls this module automatically.  A caller must enable
SUPABASE_SYNC and provide a Supabase access token after an explicit user
confirmation.  RLS should restrict the ``rightly_context`` table by
``auth.uid()`` in the deployed Supabase project.
"""

from __future__ import annotations

import json
import os
import time
from urllib.parse import quote
from urllib.request import Request, urlopen


class SupabaseSync:
    def __init__(self, access_token: str):
        self.base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        self.anon_key = (
            os.getenv("SUPABASE_PUBLISHABLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or ""
        ).strip()
        self.table = os.getenv("SUPABASE_CONTEXT_TABLE", "rightly_context").strip()
        self.access_token = str(access_token or "").strip()
        if os.getenv("SUPABASE_SYNC", "false").strip().lower() not in {"1", "true", "yes", "on"}:
            raise RuntimeError("Supabase sync is disabled")
        if not self.base_url or not self.anon_key or not self.access_token:
            raise RuntimeError("Supabase URL, anon key, and signed-in access token are required")

    def _user_id(self) -> str:
        data = self._request("GET", f"{self.base_url}/auth/v1/user")
        user_id = data.get("id") if isinstance(data, dict) else None
        if not user_id:
            raise RuntimeError("Supabase access token is not a signed-in user token")
        return str(user_id)

    def _request(self, method: str, url: str, payload: dict | None = None) -> object:
        headers = {
            "apikey": self.anon_key,
            "Authorization": "Bearer " + self.access_token,
            "Accept": "application/json",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        request = Request(url, data=data, headers=headers, method=method)
        with urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else None

    def push(self, session_id: str, turns: list[dict[str, str]]) -> None:
        payload = {
            "user_id": self._user_id(),
            "session_id": str(session_id)[:100],
            "turns": turns[-100:],
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        url = f"{self.base_url}/rest/v1/{quote(self.table, safe='')}"
        self._request("POST", url, payload)

    def pull(self, session_id: str) -> list[dict[str, str]]:
        url = (
            f"{self.base_url}/rest/v1/{quote(self.table, safe='')}"
            f"?select=turns&user_id=eq.{quote(self._user_id(), safe='')}"
            f"&session_id=eq.{quote(str(session_id)[:100], safe='')}"
        )
        rows = self._request("GET", url)
        if not isinstance(rows, list) or not rows:
            return []
        turns = rows[0].get("turns")
        return turns if isinstance(turns, list) else []
