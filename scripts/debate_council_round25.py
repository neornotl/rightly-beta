"""Run council debate round 25: review + approve realism rules and scoring rubric."""

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath("scripts")))
from scripts.council_models import MEMBERS

PROMPT_FILE = "debate_output/round25_prompt.json"
OUT_FILE = "debate_output/round25.json"

SYSTEM = (
    "Bạn là thành viên hội đồng tư vấn của dự án 'Rightly' - AI tư vấn "
    "thủ tục hành chính/ pháp luật bằng giọng nói tiếng Việt cho người dân. "
    "Bạn phân tích kỹ, đưa ý kiến cụ thể, thực tế, có thể dùng ngay. "
    "Trả lời bằng tiếng Việt."
)


def call_model(member: dict, user_text: str) -> tuple[str, dict]:
    key = os.environ.get(member["key_env"]) if member["key_env"] else None
    if member["key_env"] and not key:
        return "[ERROR] missing API key: %s" % member["key_env"], {}
    body = {
        "model": member["model"],
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.7,
        "max_tokens": int(member.get("max_tokens", 4000)),
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    headers.update(member.get("headers_extra") or {})
    data = json.dumps(body).encode("utf-8")
    last_err = None
    for attempt in range(1, 4):
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(member["url"], data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=300) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            usage = payload.get("usage") or {}
            usage["latency_s"] = round(time.perf_counter() - t0, 2)
            return payload["choices"][0]["message"]["content"].strip(), usage
        except Exception as exc:
            last_err = exc
            if isinstance(exc, urllib.error.HTTPError):
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                print(f"  [{member['display']}] attempt {attempt} HTTP {exc.code}: {detail}")
            else:
                print(f"  [{member['display']}] attempt {attempt} error: {exc}")
    raise RuntimeError(f"{member['display']}: failed after 3 attempts: {last_err}")


def main() -> int:
    with open(PROMPT_FILE, encoding="utf-8") as fh:
        prompt_data = json.load(fh)
    user_text = prompt_data["project_state"]
    opinions = {}
    usages = {}
    for member in MEMBERS:
        print(f"== calling {member['display']} ({member['model']}) ...")
        sys.stdout.flush()
        try:
            text, usage = call_model(member, user_text)
            opinions[member["display"]] = text
            usages[member["display"]] = usage
            print(f"== {member['display']}: OK ({len(text)} chars) usage={usage}")
        except Exception as exc:
            opinions[member["display"]] = f"[ERROR] {exc}"
            usages[member["display"]] = {}
            print(f"== {member['display']}: FAILED - {exc}")
        sys.stdout.flush()
    out = {
        "round": prompt_data["round"],
        "date": prompt_data["date"],
        "project_state": user_text,
        "opinions": opinions,
        "usages": usages,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"Saved -> {OUT_FILE}")
    for name, text in opinions.items():
        status = "OK" if not text.startswith("[ERROR]") else "ERROR"
        print(f"  {status}: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())