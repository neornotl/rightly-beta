"""Rule-based checks (pure keyword/regex heuristics, no LLM).

Order of application matters: RED first, then ORANGE, then scope checks.

IMPORTANT: these rules are conservative heuristics for Vietnamese text. They
are NOT a replacement for trained classifiers and must be reviewed with a
Vietnamese-speaking safety expert before pilot (docs/responsible_ai.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_EMERGENCY_PATTERNS = [
    r"cấp cứu",
    r"đau tim",
    r"đột quỵ",
    r"ngộ độc",
    r"tự tử",
    r"tự sát",
    r"muốn chết",
    r"sốc phản vệ",
    r"cháy (nhà|rừng|xe|quần áo|đang cháy|không bị bắt|bắt lửa)",
    r"đang cháy",
    r"hỏa hoạn",
    r"nguy hiểm đến tính mạng",
    r"đang bị tấn công",
    r"bị đánh gấp",
    r"khủng hoảng",
    r"đốt nhà",
    r"hack tài khoản",
    r"tấn công mạng",
    r"xâm nhập trái phép",
]

_VIOLENCE_THREAT_PATTERNS = [
    r"đe dọa",
    r"bạo lực",
    r"hành hung",
    r"bắt cóc",
    r"cướp (giật|xe|tài sản|ngân hàng|tiệm vàng|nhà dân)",
    r"xâm hại",
    r"hiếp dâm",
    # Active victim statements: "bị chồng đánh", "tôi bị đánh"... (the
    # person-named form excludes compounds like "đánh giá"/"đánh thuế").
    r"bị (?:chồng|vợ|bố|mẹ|cha|chú|dì|hàng xóm|bạn trai|người yêu)\s+đánh(?!\s+giá)",
    r"(?:tôi|con tôi|em tôi|bố tôi|mẹ tôi|chồng tôi|vợ tôi|người thân(?: của)? tôi)\s+(?:đang\s+|vừa\s+|mới\s+)?bị\s+đánh(?!\s+giá)",
]

_LEGAL_PATTERNS = [
    r"tòa án",
    r"tòa ",
    r"tranh chấp",
    r"kiện (tụng|ra tòa|tòa)",
    r"khởi kiện",
    r"phán quyết",
    r"án tòa",
    r"chia tài sản (ly hôn|thừa kế)",
    r"quyết định của tòa",
    r"luật sư",
    r"đòi nợ",
    r"đất (đai )?tranh chấp",
]

_CRIMINAL_PATTERNS = [
    r"hình sự",
    r"khởi tố",
    r"tạm giam",
    r"tội phạm",
    r"bắt giữ",
    r"tố giác tội phạm",
]

# Fake / rumored / future law signals — route to ORANGE/REFUSE because the
# system must never "confirm" a law that does not exist in its verified
# registry (data/law_status.json). This is hallucination prevention at the
# router level (council T4).
_FAKE_LAW_PATTERNS = [
    # 4-digit numbers are never real NĐ/Thông tư numbers (max 3 digits)
    r"(nghị định|nđ|thông tư|tt|quyết định)\s*(số|so)?\s*\d{4,}/",
    # any decree cited with a future year (2031+) cannot be verified
    r"(nghị định|nđ|thông tư|tt|quyết định)\s*(số|so)?\s*\d+/(203[1-9]|204\d)",
    r"năm\s+20(3[1-9]|4\d)\s+(quy\s+định|có\s+hiệu\s+lực)",
    r"luật\s+năm\s+20(3\d|4\d)",
    r"luật\s+bãi\s+bỏ",
    r"bộ\s+luật\s+\d{4}",
    r"(facebook|zalo|mạng\s+xã\s+hội)\s+nói",
    r"nghe\s+nói",
    r"bạn\s+tôi\s+bảo",
    r"sắp\s+bị\s+hủy",
    r"chỉ\s+cần.*(nộp\s+ảnh|chụp\s+ảnh)",
]

# Citation pattern to verify against the law registry:
# "Nghị định/NĐ/Thông tư/TT số? XXXX/YYYY" -> (number, year)
_CITED_DECREE_RE = re.compile(
    r"(?:nghị\s+định|nđ|thông\s+tư|tt|quyết\s+định|luật)\s*(?:số|so)?\s*(\d{1,4})/(20\d\d)",
    re.IGNORECASE,
)

_OUT_OF_SCOPE_PATTERNS = [
    r"dự đoán (giá|xổ số|kết quả)",
    r"xổ số",
    r"chơi (chứng khoán|bạc)",
    r"cá cược",
    r"thầy bói",
    r"bói toán",
    r"tử vi",
    r"tin tức nóng",
    r"bình luận chính trị",
    r"hướng dẫn (làm|nấu|cày) (game|game)",
    r"phim ",
    r"bài tập về nhà",
    # --- Everyday / entertainment / shopping / lifestyle topics (gate 1b).
    # False positives are contained by the router: an OOS rule only guides a
    # query out when it has NO legal-info intent marker ("thủ tục", "quy định",
    # "hồ sơ", "chế độ"...). A legit legal question mentioning one of these
    # words still carries a marker and keeps flowing to grounded answering.
    r"thời tiết",
    r"nấu (?:phở|cháo|cơm|bánh|món|ăn)",
    r"công thức nấu",
    r"món ăn",
    r"đồ ăn",
    r"pha cà phê",
    r"cà phê sữa đá",
    r"giá vàng",
    r"giá (?:xăng|dầu|gạo)",
    r"mua (?:điện thoại|máy tính|quần áo|giày|nhà cửa|đồ dùng|hàng hóa)",
    r"bán (?:giày|quần áo|hàng)",
    r"thời trang",
    r"khuyến mãi",
    r"giảm giá",
    r"bóng đá",
    r"đá banh",
    r"cổ tích",
    r"ca nhạc",
    r"bài hát",
    r"lịch chiếu",
    r"xếp hạng",
    r"máy giặt",
    r"máy lạnh",
    r"sửa (?:máy giặt|máy lạnh|máy tính|điện thoại|tivi)",
    r"bài tập thể dục",
    r"tập (?:yoga|gym|chạy bộ|bơi)",
    r"ăn kiêng",
    r"giảm cân",
    r"chế độ ăn",
    r"giờ bay",
    r"chuyến bay",
    r"vé máy bay",
    r"du lịch",
    r"khách sạn",
    r"đổi sim",
    r"đăng ký tài khoản (?:game|facebook|zalo|instagram|youtube|google|telegram)",
    r"kết bạn",
    r"chơi game",
    r"tải game",
    r"chăm sóc da",
    r"trang điểm",
    r"làm đẹp",
    r"cắt tóc",
    r"nhuộm tóc",
]

_DOUBT_WORDS = [
    r"hay là",
    r"hay\?",
    r"không biết",
    r"không rõ",
    r"có phải",
    r"là gì nhỉ",
    r"thế nào nhỉ",
    r"\bhả\b",
]

# ---------------------------------------------------------------------------
# Intent disambiguation (item: distinguish law-information questions from
# dangerous situations).
#
# Our keyword patterns are conservative: "bạo lực", "xâm hại", "cấp cứu",
# "hỏa hoạn" etc. are also textbook LAW TOPICS (Luật phòng chống bạo lực
# gia đình, thủ tục cấp cứu, ...). Questioning ABOUT these topics is a
# legitimate legal-information request, NOT an active emergency.
#
# Strategy: a RED hit is downgraded (allowed to fall through to ordinary
# legal/safe routing) ONLY when ALL of the following hold:
#   1. every emergency/violence hit is a "soft/topic" keyword (see
#      _TOPIC_EMERGENCY_KW) -- hard signals (tự tử, đốt nhà, hack tài khoản,
#      đang bị tấn công, ...) NEVER downgrade;
#   2. the query carries a strong legal-information intent marker
#      (_LEGAL_INFO_MARKERS) -- it is asking about a rule/procedure/citation;
#   3. the query has NO victim/danger context marker (_DANGER_CONTEXT_MARKERS)
#      -- e.g. "Tôi bị chồng bạo lực, luật quy định thế nào?" must stay RED.
# ---------------------------------------------------------------------------

# Soft/topic keywords whose presence ALONE does not prove an active danger.
# EXACT raw pattern strings (as they appear in _EMERGENCY_PATTERNS /
# _VIOLENCE_THREAT_PATTERNS) that merely name a law topic (Luật phòng chống
# bạo lực gia đình, thủ tục cấp cứu, ...) and may appear inside legitimate
# legal-information questions.
_TOPIC_EMERGENCY_PATTERNS = {
    r"bạo lực",
    r"xâm hại",
    r"cấp cứu",
    r"hỏa hoạn",
    r"hành hung",
    r"tấn công mạng",
    r"cháy (nhà|rừng|xe|quần áo|đang cháy|không bị bắt|bắt lửa)",
}

# Markers of a legal-information / procedural request (NOT a judgment plea).
_LEGAL_INFO_MARKERS = [
    r"thủ tục",
    r"quy trình",
    r"hồ sơ",
    r"quy định",
    r"trường hợp",
    r"theo\s+(?:luat|n?đ|nghị định|quyết định|thông tư|bộ luật)",
    r"luat\d+_\d+",
    r"boluat\d+_\d+",
    r"nd\d+_\d+",
    r"nđ\s*\d+",
    r"là gì",
    r"ra sao",
    r"như thế nào",
    r"thế nào ạ",
    r"khác gì",
    r"khác không",
    r"liên quan thế nào",
    r"liên quan gì đến",
    r"nói lại",
    r"nghe lại",
    r"hướng dẫn",
    r"cho tôi hỏi về",
    r"cho hỏi",
    r"có những",
    r"điều\s+\d+",
    r"khoản\s+\d+",
    r"có khác không",
    r"quyền lợi",
    r"chế độ",
    r"theo quy định",
    r"có được phép",
    r"được phép",
    r"phép làm",
    r"đúng không",
    r"có đúng không",
    r"nghe facebook",
    r"nghe nói",
    r"bạn tôi bảo",
    r"facebook nói",
    r"zalo nói",
    r"có bị hủy",
    r"sắp bị hủy",
]

# Markers that the user (or someone close) is an ACTIVE victim / in danger.
# Any of these overrides the legal-info downgrade -> stay RED.
_DANGER_CONTEXT_MARKERS = [
    r"tôi (?:đang )?bị",
    r"bị đánh",
    r"bị xâm hại",
    r"bị hiếp",
    r"bị cướp",
    r"bị bắt cóc",
    r"bị đe dọa",
    r"bị bạo lực",
    r"con tôi",
    r"em tôi",
    r"chồng tôi",
    r"vợ tôi",
    r"bố tôi",
    r"mẹ tôi",
    r"người thân (?:của )?tôi",
    r"bị hành hung",
    r"tôi bị đánh",
    r"đang đe dọa tôi",
    r"đe dọa đánh tôi",
    r"đánh tôi",
    r"tấn công tôi",
    r"cứu tôi",
    r"đang đe dọa",
    r"bị chồng",
    r"bị vợ",
    r"đang bị (?:đánh|xâm|hiếp|cướp|bắt cóc|đe dọa|bạo lực|tấn công|hành hung|sát|khống chế)",
    r"muốn (?:tự tử|tự sát|chết)",
    r"đang cháy",
    r"bị thương",
    r"bị ngộ độc",
    r"đau tim",
    r"đột quỵ",
    r"bị sốc",
]

# Markers of an ACTIVE legal/procedural request. Narrower than
# _LEGAL_INFO_MARKERS: only strong procedural/regulatory framing. Used to
# decide whether an out-of-scope topic rule should be overridden — a bare
# question-word ("là gì", "thế nào") must NOT turn an everyday query
# ("Thời trang nam đang hot là gì?") into an answerable legal question.
_PROCEDURAL_MARKERS = [
    r"thủ tục",
    r"quy trình",
    r"hồ sơ",
    r"quy định",
    r"trường hợp",
    r"theo\s+(?:luat|n?đ|nghị định|quyết định|thông tư|bộ luật)",
    r"luat\d+_\d+",
    r"boluat\d+_\d+",
    r"nd\d+_\d+",
    r"nđ\s*\d+",
    r"cho tôi hỏi về",
    r"cho hỏi",
    r"hướng dẫn",
    r"quyền lợi",
    r"chế độ",
    r"theo quy định",
    r"có được phép",
    r"được phép",
    r"phép làm",
    r"đúng không",
    r"có đúng không",
    r"nghe facebook",
    r"nghe nói",
    r"bạn tôi bảo",
    r"facebook nói",
    r"zalo nói",
    r"có bị hủy",
    r"sắp bị hủy",
    r"điều\s+\d+",
    r"khoản\s+\d+",
]

# Compact compiled forms used by the intent helper functions below.
_COMPILED_LEGAL_INFO = [re.compile(p, re.IGNORECASE) for p in _LEGAL_INFO_MARKERS]
_COMPILED_DANGER = [re.compile(p, re.IGNORECASE) for p in _DANGER_CONTEXT_MARKERS]
_COMPILED_PROCEDURAL = [re.compile(p, re.IGNORECASE) for p in _PROCEDURAL_MARKERS]

_COMPILED = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in _EMERGENCY_PATTERNS
    + _VIOLENCE_THREAT_PATTERNS
    + _CRIMINAL_PATTERNS
    + _FAKE_LAW_PATTERNS
    + _LEGAL_PATTERNS
    + _OUT_OF_SCOPE_PATTERNS
    + _DOUBT_WORDS
]
_N_EMERGENCY = len(_EMERGENCY_PATTERNS)
_N_VIOLENCE = len(_VIOLENCE_THREAT_PATTERNS)
_N_CRIMINAL = len(_CRIMINAL_PATTERNS)
_N_LEGAL = len(_LEGAL_PATTERNS)
_N_OOS = len(_OUT_OF_SCOPE_PATTERNS)


@dataclass(frozen=True)
class RuleHits:
    emergency: list[str] = field(default_factory=list)
    violence: list[str] = field(default_factory=list)
    criminal: list[str] = field(default_factory=list)
    legal: list[str] = field(default_factory=list)
    fake_law: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)


def _match(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def check_rules(normalized_text: str) -> RuleHits:
    """Run all rule groups on normalized (lowercased) Vietnamese text."""
    hits = RuleHits()
    text = normalized_text.casefold()
    for i, pat in enumerate(_EMERGENCY_PATTERNS):
        if _match(pat, text):
            hits.emergency.append(pat)
    for i, pat in enumerate(_VIOLENCE_THREAT_PATTERNS):
        if _match(pat, text):
            hits.violence.append(pat)
    for i, pat in enumerate(_CRIMINAL_PATTERNS):
        if _match(pat, text):
            hits.criminal.append(pat)
    for i, pat in enumerate(_FAKE_LAW_PATTERNS):
        if _match(pat, text):
            hits.fake_law.append(pat)
    for i, pat in enumerate(_LEGAL_PATTERNS):
        if _match(pat, text):
            hits.legal.append(pat)
    for i, pat in enumerate(_OUT_OF_SCOPE_PATTERNS):
        if _match(pat, text):
            hits.out_of_scope.append(pat)
    for i, pat in enumerate(_DOUBT_WORDS):
        if _match(pat, text):
            hits.ambiguous.append(pat)
    return hits


def normalize_query(text: str) -> str:
    """Lowercase + collapse whitespace (diacritics preserved)."""
    return " ".join(text.casefold().split())


def is_soft_topic_emergency(hits: RuleHits) -> bool:
    """True when EVERY emergency/violence hit is a soft law-topic keyword.

    Hard, unambiguous danger signals (tự tử, đốt nhà, hack tài khoản, đe dọa,
    bắt cóc, hiếp dâm, cướp, đang bị tấn công, xâm nhập trái phép, ...) are
    NOT in this set, so a query carrying one can never be downgraded.
    """
    ev = hits.emergency + hits.violence
    if not ev:
        return False
    return all(_is_topic_pattern(p) for p in ev)


def _is_topic_pattern(pattern: str) -> bool:
    return pattern in _TOPIC_EMERGENCY_PATTERNS


def has_legal_info_intent(normalized_text: str) -> bool:
    """True when the query reads as a legal-information/procedural request."""
    text = normalized_text.casefold()
    return any(pat.search(text) for pat in _COMPILED_LEGAL_INFO)


def has_procedural_intent(normalized_text: str) -> bool:
    """True when the query carries STRONG procedural/regulatory framing.

    Narrower than :func:`has_legal_info_intent` — used to decide whether an
    out-of-scope topic rule applies. Bare question-words ("là gì", "ra sao",
    "thế nào") are deliberately excluded so an everyday query about an
    off-scope topic is not promoted to an answerable legal question.
    """
    text = normalized_text.casefold()
    return any(pat.search(text) for pat in _COMPILED_PROCEDURAL)


def has_danger_context(normalized_text: str) -> bool:
    """True when the user (or a relative) is an active victim / in danger.

    Overrides the legal-info downgrade so genuine emergencies stay RED.
    """
    text = normalized_text.casefold()
    return any(pat.search(text) for pat in _COMPILED_DANGER)
