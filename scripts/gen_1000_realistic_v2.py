# -*- coding: utf-8 -*-
"""Generate 1000 REALISTIC Vietnamese questions grounded in the actual corpus.

Unlike data/eval/gen_1k_clean.jsonl (heavy noise layers that produced many
ungrammatical questions), this generator keeps every question grammatical:

  1. Mine concrete facts from real chunks: ages, fines, deadlines,
     percentages, dossiers -> each question has expected_source_ids.
  2. Intent templates (muc-phat / tuoi / thoi-han / ho-so / dieu-kien /
     quyen-loi / thu-tuc) x law topic keywords.
  3. Speaker wrappers + light, grammatical variation only:
     ~85% clean, ~10% folk/elderly phrasing, ~5% no-diacritics (ASR-like).
  4. ~10% adversarial out-of-corpus topics (expected: refuse/ORANGE).
  5. Domain floor >= 2%; seeded & reproducible; manifest with distributions.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "eval" / "gen_1000_realistic_v2.jsonl"
MANIFEST = ROOT / "data" / "eval" / "1000_realistic_v2_manifest.json"
SEED = 20260823
N_TOTAL = 1000
ADVERSARIAL_RATIO = 0.10
DOMAIN_FLOOR = 20  # per-domain minimum among grounded questions

random.seed(SEED)

# ---------------- corpus mining ----------------

recs = [json.loads(l) for l in (ROOT / "data/chunks/real_chunks.jsonl").open(encoding="utf-8") if l.strip()]
status_db = json.loads((ROOT / "data/law_status.json").read_text(encoding="utf-8"))["sources"]

by_source: dict[str, list[str]] = {}
for r in recs:
    by_source.setdefault(r["source_id"], []).append(r["text"])

DOMAIN_RULES = [
    (("bảo hiểm xã hội", "hưu", "trợ cấp thất nghiệp", "bhxh"), "BHXH"),
    (("bảo hiểm y tế", "bhyt", "khám chữa bệnh"), "BHYT"),
    (("cư trú", "cư dân", "hộ khẩu", "thường trú", "tạm trú"), "Cư trú"),
    (("hộ tịch", "khai sinh", "kết hôn", "ly hôn", "chết"), "Hộ tịch"),
    (("đất đai", "sổ đỏ", "sổ đỏ", "thừa kế quyền sử dụng đất", "lâm nghiệp"), "Đất đai"),
    (("xây dựng", "phép xây dựng", "urban"), "Xây dựng"),
    (("giao thông", "xe máy", "giấy phép lái xe", "đường bộ"), "Giao thông"),
    (("lao động", "hợp đồng lao động", "tiền lương tối thiểu", "an toàn lao động"), "Lao động"),
    (("hình sự", "phạt tù", "tội"), "Hình sự"),
    (("xử phạt vi phạm hành chính", "vi phạm hành chính"), "XVPHC"),
    (("doanh nghiệp", "đăng ký kinh doanh", "thuế"), "KD-Thuế"),
    (("di chúc", "thừa kế", "di sản"), "Dân sự/Thừa kế"),
    (("trợ giúp pháp lý",), "Trợ giúp PL"),
    (("quốc tịch",), "Quốc tịch"),
    (("người cao tuổi", "người khuyết tật", "trẻ em", "bạo lực gia đình"), "An sinh XH"),
]


def domain_of(source_id: str) -> str:
    info = status_db.get(source_id) or {}
    hay = f"{info.get('trich_yeu', '')} {info.get('ky_hieu', '')}".casefold()
    for keys, dom in DOMAIN_RULES:
        if any(k in hay for k in keys):
            return dom
    return "Khác"


def pick_source_text(sid: str) -> str:
    texts = by_source.get(sid) or []
    return random.choice(texts) if texts else ""


AGE_RE = re.compile(r"(\d{2})\s*tuổi")
MONEY_RE = re.compile(r"(?:từ\s+)?(\d[\d.,]*)\s*(?:triệu|đồng)")
DEADLINE_RE = re.compile(r"(\d+)\s*(?:ngày|ngày làm việc|tháng)\s*(?:kể từ|liền kề|không quá|,)")
PCT_RE = re.compile(r"(\d{2,3})\s*%")


def mine_fact(text: str) -> tuple[str | None, dict]:
    """Return (fact_kind, template_slots) mined from chunk text."""
    m = AGE_RE.search(text)
    if m and ("tuổi nghỉ hưu" in text or "đủ tuổi" in text or "độ tuổi" in text):
        return "tuoi", {}
    m = MONEY_RE.search(text)
    if m and ("phạt tiền" in text or "mức phạt" in text):
        return "muc_phat", {}
    m = DEADLINE_RE.search(text)
    if m and ("thời hạn" in text or "trong vòng" in text):
        return "thoi_han", {}
    if PCT_RE.search(text) and ("mức hưởng" in text or "trợ cấp" in text or "chi trả" in text or "hưởng" in text):
        return "phan_tram", {}
    if re.search(r"hồ sơ(?!:)", text) and ("gồm" in text or "bao gồm" in text):
        return "ho_so", {}
    if "điều kiện" in text and ("được hưởng" in text or "đề nghị" in text):
        return "dieu_kien", {}
    return None, {}


TOPIC_HINTS = {
    "BHXH": ("bảo hiểm xã hội", "lương hưu", "trợ cấp thất nghiệp", "bảo hiểm thất nghiệp"),
    "BHYT": ("bảo hiểm y tế", "thẻ bảo hiểm y tế", "khám bệnh chữa bệnh"),
    "Cư trú": ("cư trú", "đăng ký thường trú", "tạm trú", "tách hộ"),
    "Hộ tịch": ("khai sinh", "kết hôn", "ly hôn", "hộ tịch"),
    "Đất đai": ("đất đai", "sổ đỏ", "quyền sử dụng đất", "đất nông nghiệp"),
    "Xây dựng": ("xây dựng", "giấy phép xây dựng"),
    "Giao thông": ("giao thông đường bộ", "giấy phép lái xe", "xe máy"),
    "Lao động": ("lao động", "hợp đồng lao động", "tiền lương"),
    "Hình sự": ("bộ luật hình sự",),
    "XVPHC": ("vi phạm hành chính", "xử phạt"),
    "KD-Thuế": ("doanh nghiệp", "đăng ký kinh doanh"),
    "Dân sự/Thừa kế": ("thừa kế", "di chúc", "di sản"),
    "Trợ giúp PL": ("trợ giúp pháp lý",),
    "Quốc tịch": ("quốc tịch",),
    "An sinh XH": ("người cao tuổi", "người khuyết tật", "bạo lực gia đình"),
}

INTENT_TEMPLATES = {
    "muc_phat": [
        "Mức phạt tiền khi vi phạm quy định về {topic} là bao nhiêu?",
        "{topic_cap} mà vi phạm thì bị xử phạt bao nhiêu ạ?",
        "Cho hỏi mức xử phạt đối với hành vi vi phạm {topic} là bao nhiêu?",
    ],
    "tuoi": [
        "Năm nay tôi {age_hint} tuổi, cho hỏi độ tuổi áp dụng cho {topic} là bao nhiêu?",
        "Điều kiện về độ tuổi liên quan đến {topic} được quy định thế nào ạ?",
    ],
    "thoi_han": [
        "Thời hạn giải quyết công việc liên quan đến {topic} là bao lâu ạ?",
        "Pháp luật quy định thời hạn như thế nào đối với {topic}?",
    ],
    "phan_tram": [
        "Mức hưởng theo phần trăm liên quan đến {topic} được quy định ra sao ạ?",
        "Tôi muốn biết tỷ lệ chi trả, mức hưởng về {topic}.",
    ],
    "ho_so": [
        "Làm thủ tục liên quan đến {topic} thì hồ sơ gồm những giấy tờ gì ạ?",
        "Hồ sơ, giấy tờ về {topic} được quy định gồm những gì thưa bác?",
    ],
    "dieu_kien": [
        "Điều kiện áp dụng quy định về {topic} gồm những gì ạ?",
        "Nhà tôi có việc liên quan đến {topic}, phải đáp ứng điều kiện gì không?",
    ],
    "general": [
        "Cho tôi hỏi pháp luật hiện hành quy định về {topic} như thế nào?",
        "{topic_cap} được quy định trong văn bản pháp luật nào ạ?",
        "Tôi muốn tra cứu nội dung pháp luật về {topic}.",
    ],
}

SPEAKERS = [
    "{q}",
    "Bác ơi cho con hỏi, {lower}",
    "Dạ thưa anh/chị, {lower}",
    "Cho con hỏi {lower}",
    "Tôi xin hỏi {lower}",
    "Ông bà nhà tôi bảo {lower} nhưng tôi chưa rõ.",
]

ADVERSARIAL_TOPICS = [
    "làm hộ chiếu đi nước ngoài",
    "xin visa du lịch Nhật Bản",
    "đăng ký khai thác mỏ vàng",
    "mua nhà ở nước ngoài",
    "đổi bằng lái xe quốc tế",
    "nhập cư Mỹ cần điều kiện gì",
    "đăng ký mã số thuế cá nhân cho người nước ngoài",
    "xin học bổng du học Úc",
    "thủ tục ly hôn tại Thái Lan",
    "mở công ty chứng khoán",
]


def strip_diacritics(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


_DOC_PREFIX = re.compile(
    r"^(?:bộ luật|luật|nghị định|thông tư liên tịch|thông tư|quyết định|nghị quyết)\s*"
    r"(?:số\s*)?\d*[\d/]*\s*(?:/NĐ-CP|/QH\d*|/TT-[\w]+)?\s*",
    re.IGNORECASE,
)
_NOISE_WORDS = re.compile(r"^(?:về|quy định|chi tiết|hướng dẫn|sửa đổi|bổ sung|của|theo|nay|hiện hành|năm \d{4})\b[\s,]*", re.IGNORECASE)
_VBHN_TOKEN = re.compile(r"\b\d{1,3}\s*[-–]\s*VBHN[\w-]*\b|\bVBHN[-\w]*\b", re.IGNORECASE)


def clean_topic(trich_yeu: str) -> str:
    """Derive a natural noun phrase from a registry title."""
    t = (trich_yeu or "").strip()
    t = _VBHN_TOKEN.sub(" ", t)
    # drop leading doc-number remnants like "156-", "113/", "(sửa đổi ...)"
    t = re.sub(r"^[\d\s.,/–-]+", "", t).strip()
    t = _DOC_PREFIX.sub("", t, count=1) or t
    t = re.sub(r"\b(19|20)\d{2}\b", " ", t)
    prev = None
    while prev != t:
        prev = t
        t = _NOISE_WORDS.sub("", t).strip(" ,.-")
        t = re.sub(r"\s+", " ", t)
    words = [w for w in t.split() if not re.fullmatch(r"[\d.,/-]+", w)]
    return " ".join(words[:8]) if len(words) > 8 else " ".join(words)


def usable_topic(topic: str) -> bool:
    t = topic.strip()
    if len(t) < 5:
        return False
    if not re.search(r"[a-zA-ZÀ-ỹ]", t):
        return False
    if re.fullmatch(r"[\d\s.,/-]+", t):
        return False
    return True


def short_topic(topic: str) -> str:
    return topic.strip()


def cap_first(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def make_question(topic: str, intent: str, sid: str, law_hint: str = "") -> str:
    # avoid redundant phrasing when the topic itself is the penalty concept
    if intent == "muc_phat" and "vi phạm hành chính" in topic.casefold():
        intent = "general"
    tpl = random.choice(INTENT_TEMPLATES[intent])
    suffix = f" Theo {law_hint} ạ?" if law_hint and random.random() < 0.8 else "?"
    q = tpl.format(
        topic=short_topic(topic),
        topic_short=short_topic(topic),
        topic_cap=cap_first(short_topic(topic)),
        age_hint=random.choice(["58", "60", "62"]),
    )
    q = re.sub(r"\?\s*$", suffix, q)
    starts_with_ask = re.match(r"^(cho (hỏi|tôi)|tôi |xin hỏi|điều kiện|mức |thời hạn|hồ sơ|năm nay)", q, re.IGNORECASE)
    speaker = "{q}" if starts_with_ask else random.choice(SPEAKERS)
    if speaker == "{q}":
        final = q
    else:
        body = q[0].lower() + q[1:] if not speaker.endswith("chưa rõ.") else q
        final = speaker.format(lower=body)
    # light grammatical-only variations
    roll = random.random()
    if roll < 0.05:
        final = strip_diacritics(final)  # ASR-like but still readable
    return final


#: folk terms users actually say -> canonical topic tokens for retrieval
ALIAS_TOKENS = {
    "sổ đỏ": "đất đai quyền sử dụng đất",
    "sổ hồng": "nhà ở quyền sử dụng đất",
    "hộ khẩu": "cư trú hộ gia đình",
    "bhxh": "bảo hiểm xã hội",
    "bhyt": "bảo hiểm y tế",
    "bảo hiểm thất nghiệp": "trợ cấp thất nghiệp bảo hiểm",
}


def title_family_key(title: str) -> str:
    """Coarse key so different editions of the SAME law share one family."""
    value = (title or "").casefold().replace("_", " ").replace("-", " ")
    value = re.sub(r"\d+", " ", value)
    value = re.sub(r"\b(vbhn|vpqh|luat|luật|bo|bộ|qh|nd|tt|sửa đổi)\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


_GUIDES_RE = re.compile(
    r"(?:hướng dẫn|thi hành|quy định chi tiết|quy định trình tự)[^,.;]{0,40}?"
    r"(?:của\s+)?(bộ\s+luật|luật)\s+([^,.;()]{4,60})",
    re.IGNORECASE,
)


def _link_guides_to_parents(status_db: dict, fam_members: dict[str, list[str]]) -> dict[str, set[str]]:
    """Union guiding decrees/circulars with the law they implement.

    A question about "trợ cấp thất nghiệp" answered from Nghị định 374/2025
    (hướng dẫn Luật Việc làm) is CORRECT; the grader must accept either.
    Returns sid -> merged sid-group (law + its guiding docs + siblings).
    """
    parent = {}
    n_fam_items = sorted(fam_members.items(), key=lambda kv: -len(kv[0]))
    for sid, info in status_db.items():
        ty = info.get("trich_yeu", "") or ""
        m = _GUIDES_RE.search(ty)
        if not m:
            continue
        # The referenced act is named right after "(bộ) luật": keep that core
        # phrase only, so "Luật Việc làm về bảo hiểm thất nghiệp" pins the
        # 'việc làm' family instead of a narrower keyword family.
        core_words = (m.group(2) or "").split()
        name_core = re.sub(r"\s+", " ", f"{m.group(1)} {' '.join(core_words[:4])}").strip().casefold()
        best = None
        for fk, _members in n_fam_items:
            if fk and fk in name_core:
                if best is None or len(fk) > len(best):
                    best = fk
        if best:
            parent[sid] = best
    # union-find
    parent_of: dict[str, str] = {}

    def find(x: str) -> str:
        while parent_of.get(x, x) != x:
            x = parent_of[x] = parent_of.get(parent_of[x], parent_of[x])
        return x

    def union(a: set[str], b: set[str]) -> None:
        ra, rb = find(next(iter(a))), find(next(iter(b)))
        if ra != rb:
            parent_of[rb] = ra

    groups: dict[str, set[str]] = {}
    for fk, members in fam_members.items():
        groups[fk] = set(members)
    for sid, fk in parent.items():
        groups.setdefault(fk, set()).add(sid)
    # merge guide-groups into their parent family groups
    merged: dict[str, set[str]] = {fk: set(v) for fk, v in fam_members.items()}
    for sid, fk in parent.items():
        root = None
        # attach to any family that shares a member with fk's group? keep simple:
        merged.setdefault(fk, set()).add(sid)
    # transitive merge when a doc guides a law whose family contains another guide
    changed = True
    while changed:
        changed = False
        keys = list(merged.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                if merged[keys[i]] & merged[keys[j]]:
                    merged[keys[i]] |= merged[keys[j]]
                    del merged[keys[j]]
                    changed = True
                    break
            if changed:
                break
    out: dict[str, set[str]] = {}
    for members in merged.values():
        for sid in members:
            out.setdefault(sid, set()).update(members)
    return out


def law_short_name(info: dict) -> str:
    """Human phrasing users cite: 'Luật Đất đai', 'Nghị định 151/2025'."""
    loai = (info.get("loai") or "").strip()
    ty = clean_topic(info.get("trich_yeu", ""))
    if not usable_topic(ty):
        return ""
    words = ty.split()[:4]
    base = " ".join(words)
    num = re.search(r"(\d+/\d{4})", info.get("ky_hieu", "") or "")
    tail = f" số {num.group(1)}" if num else ""
    if loai and loai.casefold() not in base.casefold():
        return f"{loai} {base}{tail}"
    return f"{base}{tail}"


def main() -> None:
    active_sources = [
        sid for sid in by_source
        if (status_db.get(sid) or {}).get("status") == "active_verified"
    ]
    # Pre-compute title families over the registry so every grounded question
    # carries ALL acceptable editions of its target law (grader scores the
    # family primarily; the single drawn source stays as strict reference).
    fam_members: dict[str, list[str]] = {}
    for sid, info in status_db.items():
        fam = title_family_key(info.get("trich_yeu", ""))
        if len(fam) >= 2:
            fam_members.setdefault(fam, []).append(sid)
    print(f"active sources with chunks: {len(active_sources)}")
    # Merge guiding decrees/circulars into their parent-law families so the
    # grader accepts an answer sourced from the implementing document.
    sid_groups = _link_guides_to_parents(status_db, fam_members)

    # ---- grounded questions ----
    grounded: list[dict] = []
    seen_q: set[str] = set()
    domain_counts: Counter[str] = Counter()
    attempts = 0
    while len(grounded) < int(N_TOTAL * (1 - ADVERSARIAL_RATIO)) and attempts < 200_000:
        attempts += 1
        sid = random.choice(active_sources)
        dom = domain_of(sid)
        info = status_db[sid]
        if dom != "Khác":
            topics = TOPIC_HINTS.get(dom) or ("quy định pháp luật",)
            topic = random.choice(topics)
        else:
            topic = clean_topic(info.get("trich_yeu", ""))
            if not usable_topic(topic):
                continue
        chunk = pick_source_text(sid)
        kind, _ = mine_fact(chunk)
        if kind is None:
            intent = random.choices(
                ["ho_so", "dieu_kien", "thoi_han", "general"],
                weights=[25, 25, 15, 35],
            )[0]
        elif kind == "muc_phat":
            intent = "muc_phat"
        elif kind == "tuoi":
            intent = "tuoi"
        elif kind == "phan_tram":
            intent = "phan_tram"
        else:
            intent = "thoi_han"
        if intent not in INTENT_TEMPLATES:
            intent = "general"
        q = make_question(topic, intent, sid, law_hint=law_short_name(status_db[sid]))
        key = " ".join(strip_diacritics(q).casefold().split())
        if key in seen_q:
            continue
        seen_q.add(key)
        if domain_counts[dom] >= max(DOMAIN_FLOOR, 0) and dom != "Khác" and sum(domain_counts.values()) > 300:
            # after warm-up keep balance soft (no hard rejection; weight below)
            pass
        domain_counts[dom] += 1
        fam_set = sid_groups.get(sid) or set(
            fam_members.get(title_family_key(status_db[sid].get("trich_yeu", "")), [])
        ) | {sid}
        grounded.append({
            "question_id": "",
            "question_text": q,
            "category": "REALISTIC_GROUNDED",
            "intent": intent,
            "domain": dom,
            "difficulty": "easy" if intent == "general" else "medium",
            "expected_source_ids": [sid],
            "expected_family_sources": sorted(fam_set),
            "expected_zone": "YELLOW",
            "asr_simulated": False,
        })

    # enforce domain floor by topping-up rare domains
    for dom in TOPIC_HINTS:
        have = sum(1 for g in grounded if g["domain"] == dom)
        need = DOMAIN_FLOOR - have
        tries = 0
        cands = [sid for sid in active_sources if domain_of(sid) == dom]
        while need > 0 and tries < 500 and cands:
            tries += 1
            sid = random.choice(cands)
            topic = random.choice(TOPIC_HINTS[dom])
            q = make_question(topic, "general", sid)
            key = " ".join(strip_diacritics(q).casefold().split())
            if key in seen_q:
                continue
            seen_q.add(key)
            fam_set = sid_groups.get(sid) or set(
                fam_members.get(title_family_key(status_db[sid].get("trich_yeu", "")), [])
            ) | {sid}
            grounded.append({
                "question_id": "", "question_text": q,
                "category": "REALISTIC_GROUNDED", "intent": "general",
                "domain": dom, "difficulty": "easy",
                "expected_source_ids": [sid],
                "expected_family_sources": sorted(fam_set),
                "expected_zone": "YELLOW",
                "asr_simulated": False,
            })
            need -= 1

    # ---- adversarial ----
    n_adv = N_TOTAL - len(grounded)
    adv: list[dict] = []
    seen_adv: set[str] = set()
    i = 0
    while len(adv) < n_adv:
        topic = ADVERSARIAL_TOPICS[i % len(ADVERSARIAL_TOPICS)]
        i += 1
        variants = [
            f"Làm sao để {topic}? Cần giấy tờ gì?",
            f"Tôi muốn {topic}, thủ tục thế nào ạ?",
            f"Cho hỏi điều kiện {topic} là gì?",
        ]
        q = random.choice([s for s in SPEAKERS if s != "{q}"]).format(lower=random.choice(variants)) if random.random() < 0.4 else random.choice(variants)
        q = cap_first(q)
        key = " ".join(strip_diacritics(q).casefold().split())
        if key in seen_adv:
            continue
        seen_adv.add(key)
        adv.append({
            "question_id": "", "question_text": q,
            "category": "ADVERSarial_OUT_OF_SCOPE".upper(),
            "intent": "out_of_scope",
            "domain": " Ngoài phạm vi".strip(),
            "difficulty": "hard",
            "expected_source_ids": [],
            "expected_zone": "ORANGE",
            "asr_simulated": False,
        })

    all_q = grounded + adv
    random.shuffle(all_q)
    for idx, item in enumerate(all_q, 1):
        item["question_id"] = f"RV2_{idx:04d}"
    OUT.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in all_q) + "\n", encoding="utf-8"
    )

    manifest = {
        "seed": SEED,
        "total": len(all_q),
        "grounded": len(grounded),
        "adversarial": len(adv),
        "category_dist": dict(Counter(x["category"] for x in all_q)),
        "intent_dist": dict(Counter(x["intent"] for x in all_q if x["intent"] != "out_of_scope")),
        "domain_dist": dict(Counter(x["domain"] for x in all_q)),
        "unique_normalized": len(seen_q | seen_adv),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("\nSamples:")
    for s in all_q[:6]:
        print(" -", s["question_text"][:95], "|", s["expected_source_ids"], "|", s["category"])


if __name__ == "__main__":
    main()
