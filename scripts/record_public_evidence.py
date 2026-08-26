"""Record a privacy-safe public semantic-grounding evidence clip.

This intentionally uses a fresh Playwright context with no storage state and
never opens the pilot form or any authenticated page. The resulting video is
an untracked local artifact; only this script and its metadata are committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


URL = "https://intel-demo-topaz.vercel.app/"
PROMPTS = [
    "quy dinh khi vuot den do",
    "muc phat vuot den do xe may",
    "1+4-3+7=?",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="evidence/2026-08/01-public-semantic-grounding.webm")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    results: list[dict[str, object]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(out.parent),
            record_video_size={"width": 1280, "height": 720},
            service_workers="block",
        )
        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_selector('input[placeholder="Nhập tin nhắn cho Rightly..."]', timeout=20_000)
        page.add_style_tag(content="""
          #codex-evidence-banner { position: fixed; z-index: 2147483647; top: 12px;
            left: 50%; transform: translateX(-50%); background: #16324a; color: #fff;
            padding: 8px 16px; border-radius: 999px; font: 600 15px Arial,sans-serif;
            box-shadow: 0 3px 12px #0005; }
        """)
        page.evaluate("""() => {
          const b = document.createElement('div'); b.id = 'codex-evidence-banner';
          b.textContent = 'POST-SUBMISSION TECHNICAL EVIDENCE · public demo · no login';
          document.body.appendChild(b);
        }""")
        page.wait_for_timeout(1800)
        input_box = page.locator('input[placeholder="Nhập tin nhắn cho Rightly..."]')
        send = page.get_by_role("button", name="Gửi")
        for prompt in PROMPTS:
            before = page.locator(".row.assistant").count()
            input_box.fill(prompt)
            send.click()
            try:
                page.locator(".row.assistant").nth(before).wait_for(timeout=45_000)
            except PlaywrightTimeoutError:
                raise RuntimeError(f"Timed out waiting for visible answer: {prompt}")
            page.wait_for_timeout(2200)
            row = page.locator(".row.assistant").nth(before)
            text = row.inner_text(timeout=5_000)
            results.append({
                "prompt": prompt,
                "visible_answer_chars": len(text),
                "has_source_label": "Nguồn:" in text or "Source:" in text,
                "contains_raw_json": text.lstrip().startswith("{") or '"answer' in text[:80],
            })
            page.wait_for_timeout(1000)
        page.wait_for_timeout(3000)
        video_path = page.video.path()
        context.close()
        browser.close()
    # Playwright writes the video using a generated name; move it to the
    # deterministic artifact path after the context is closed.
    generated = Path(video_path)
    if generated.resolve() != out.resolve():
        generated.replace(out)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    metadata = {
        "artifact": str(out),
        "sha256": digest,
        "started_utc": started.isoformat(),
        "url": URL,
        "context": "fresh, no storage state, service workers blocked",
        "network": "public production (not offline test)",
        "prompts": results,
        "form_responses_opened": False,
        "login_used": False,
        "pii_expected": False,
    }
    out.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
