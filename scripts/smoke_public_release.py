#!/usr/bin/env python3
"""PII-safe smoke test for the public Rightly web app and installer release.

This tool only sends fixed, non-personal test prompts.  It never downloads the
installer, models, browser assets, or records response bodies in its reports.
Exit status is non-zero when a required public contract fails.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://intel-demo-topaz.vercel.app"
DEFAULT_RELEASE_API = "https://api.github.com/repos/neornotl/rightly/releases/tags/v0.18.0-pilot"
USER_AGENT = "Rightly-Public-Smoke/1.0 (+https://github.com/neornotl/rightly)"
RAW_ENVELOPE_RE = re.compile(r"^\s*\{\s*\"(?:answer_text|answer|reply|response)\"\s*:", re.I)
BAD_REPLY_RE = re.compile(r"(?:trích dẫn|citation)\s*:\s*(?:null|undefined|none|n/?a)\b", re.I)


@dataclass
class Check:
    name: str
    ok: bool
    status: int | None
    elapsed_ms: int | None
    note: str


def _safe_note(value: object) -> str:
    """Keep reports useful without copying provider response data or PII."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"[\w.+-]+@[\w.-]+", "[redacted-email]", text)
    return text[:180]


def _request(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 25.0):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/event-stream, text/html", **({"Content-Type": "application/json"} if body else {})},
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read().decode("utf-8", "replace"), round((time.perf_counter() - started) * 1000)
    except HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), "", round((time.perf_counter() - started) * 1000)
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(_safe_note(type(exc).__name__)) from exc


def _json_body(body: str) -> dict[str, Any]:
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("JSON response is not an object")
    return value


def _valid_reply(value: object) -> bool:
    reply = str(value or "").strip()
    return bool(reply and not RAW_ENVELOPE_RE.search(reply) and not BAD_REPLY_RE.search(reply))


def _check(name: str, callback) -> Check:
    try:
        return callback()
    except Exception as exc:  # Do not expose remote body/error details in output.
        return Check(name=name, ok=False, status=None, elapsed_ms=None, note=_safe_note(type(exc).__name__))


def check_root(base_url: str) -> Check:
    status, content_type, body, elapsed = _request(base_url + "/")
    ok = status == 200 and "text/html" in content_type.lower() and "rightly" in body.lower()
    return Check("root", ok, status, elapsed, "HTML landing page" if ok else "expected Rightly HTML landing page")


def check_health(base_url: str) -> Check:
    status, _content_type, body, elapsed = _request(base_url + "/health")
    data = _json_body(body) if status == 200 else {}
    ok = status == 200 and data.get("status") == "ok" and data.get("runtime") == "public-api"
    return Check("health", ok, status, elapsed, "public API ready" if ok else "expected status=ok and runtime=public-api")


def check_chat(base_url: str, name: str, prompt: str, required_fragment: str) -> Check:
    status, _content_type, body, elapsed = _request(base_url + "/api/chat", method="POST", payload={"text": prompt, "lang": "vi"})
    data = _json_body(body) if status == 200 else {}
    reply = data.get("reply")
    ok = status == 200 and _valid_reply(reply) and required_fragment.casefold() in str(reply).casefold()
    return Check(name, ok, status, elapsed, "structured reply" if ok else "expected a complete structured reply without raw JSON/null")


def _sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        value = json.loads(line[6:])
        if isinstance(value, dict):
            events.append(value)
    return events


def check_stream(base_url: str) -> Check:
    status, content_type, body, elapsed = _request(
        base_url + "/api/chat/stream", method="POST", payload={"text": "quy dinh khi vuot den do", "lang": "vi"}
    )
    events = _sse_events(body) if status == 200 else []
    final = next((event for event in events if event.get("type") == "answer"), {})
    delta = "".join(str(event.get("text", "")) for event in events if event.get("type") == "delta")
    reply = final.get("reply")
    ok = (
        status == 200
        and "text/event-stream" in content_type.lower()
        and _valid_reply(reply)
        and "loại phương tiện" in str(reply).casefold()
        and (not delta or delta == reply)
    )
    return Check("stream", ok, status, elapsed, "SSE final-answer contract" if ok else "expected valid SSE final answer and matching deltas")


def check_release(release_api: str) -> Check:
    status, _content_type, body, elapsed = _request(release_api)
    data = _json_body(body) if status == 200 else {}
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    installer = next((asset for asset in assets if isinstance(asset, dict) and asset.get("name") == "Rightly-Setup.exe"), {})
    url = str(installer.get("browser_download_url", ""))
    ok = (
        status == 200
        and data.get("tag_name") == "v0.18.0-pilot"
        and bool(data.get("prerelease"))
        and int(installer.get("size", 0) or 0) > 0
        and url.startswith("https://github.com/")
    )
    return Check("release_asset", ok, status, elapsed, "installer metadata present (asset not downloaded)" if ok else "expected prerelease metadata and non-empty HTTPS installer asset")


def run(base_url: str, release_api: str) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    checks = [
        _check("root", lambda: check_root(base_url)),
        _check("health", lambda: check_health(base_url)),
        _check("chat_arithmetic", lambda: check_chat(base_url, "chat_arithmetic", "1+4-3+7=?", "9")),
        _check("chat_red_light", lambda: check_chat(base_url, "chat_red_light", "quy định khi vượt đèn đỏ", "loại phương tiện")),
        _check("chat_red_light_unaccented", lambda: check_chat(base_url, "chat_red_light_unaccented", "quy dinh khi vuot den do", "loại phương tiện")),
        _check("chat_red_light_typo", lambda: check_chat(base_url, "chat_red_light_typo", "quy dinh khi vuot den doo", "loại phương tiện")),
        _check("chat_out_of_scope", lambda: check_chat(base_url, "chat_out_of_scope", "thoi tiet hom nay", "pháp luật")),
        _check("stream", lambda: check_stream(base_url)),
        _check("release_asset", lambda: check_release(release_api)),
    ]
    return {
        "schema": 1,
        "target": base_url,
        "release_api": release_api,
        "pii_safe": True,
        "passed": sum(check.ok for check in checks),
        "total": len(checks),
        "ok": all(check.ok for check in checks),
        "checks": [asdict(check) for check in checks],
    }


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Rightly public smoke test",
        "",
        f"Result: {'PASS' if result['ok'] else 'FAIL'} ({result['passed']}/{result['total']})",
        "",
        "| Check | Result | HTTP | Time | Note |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for check in result["checks"]:
        lines.append(
            f"| {check['name']} | {'PASS' if check['ok'] else 'FAIL'} | {check['status'] if check['status'] is not None else '-'} | {check['elapsed_ms'] if check['elapsed_ms'] is not None else '-'} ms | {check['note']} |"
        )
    lines.extend(["", "This report contains no response bodies, user prompts, credentials, or downloaded assets.", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--release-api", default=DEFAULT_RELEASE_API)
    parser.add_argument("--json-out", type=Path, help="Write a machine-readable report to this path")
    parser.add_argument("--markdown-out", type=Path, help="Write a human-readable report to this path")
    args = parser.parse_args(argv)
    result = run(args.base_url, args.release_api)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    markdown = markdown_report(result)
    if args.json_out:
        args.json_out.write_text(encoded, encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(markdown, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
