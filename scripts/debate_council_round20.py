"""Run council debate round 20."""

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath("scripts")))
from scripts.council_models import MEMBERS

PROMPT_FILE = "debate_output/round20_prompt.json"
OUT_FILE = "debate_output/round20.json"

SYSTEM = (
    "Bạn là thành viên hội đồng tư vấn của dự án 'Rightly' - AI tư vấn "
    "thủ tục hành chính/ pháp luật bằng giọng nói tiếng Việt cho người dân. "
    "Bạn phân tích kỹ, đưa ý kiến cụ thể, thực tế, có thể dùng ngay. "
    "Trả lời bằng tiếng Việt."
)


def call_model(member: dict, user_text: str) -> str:
    key = os.environ.get(member["key_env"]) if member["key_env"] else None
    body = {
        "model": member["model"],
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.7,
        "max_tokens": 4000,
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    headers.update(member.get("headers_extra") or {})
    data = json.dumps(body).encode("utf-8")
    last_err = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(member["url"], data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload["choices"][0]["message"]["content"].strip()
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
    for member in MEMBERS:
        print(f"== calling {member['display']} ({member['model']}) ...")
        sys.stdout.flush()
        try:
            opinions[member["display"]] = call_model(member, user_text)
            print(f"== {member['display']}: OK ({len(opinions[member['display']])} chars)")
        except Exception as exc:
            opinions[member["display"]] = f"[ERROR] {exc}"
            print(f"== {member['display']}: FAILED - {exc}")
        sys.stdout.flush()
    out = {
        "round": prompt_data["round"],
        "date": prompt_data["date"],
        "project_state": user_text,
        "opinions": opinions,
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
