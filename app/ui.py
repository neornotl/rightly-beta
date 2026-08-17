"""Streamlit UI for Rightly - Public Demo Version.

Run with:
    pip install -r requirements-optional.txt
    streamlit run app/ui.py

In mock mode everything works without keys or models. The UI never displays
secrets or raw internal prompts.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit Cloud runs `streamlit run app/ui.py`: only the *script dir*
# (app/) is prepended to sys.path, so `import app...` breaks. Put the repo
# root (parent of app/) on sys.path explicitly.
_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

try:
    import streamlit as st  # type: ignore
except ImportError:  # pragma: no cover - reported to user
    st = None

from app.config import load_settings, safe_settings_summary  # noqa: E402 - needs sys.path fix above
from app.pipeline import Pipeline  # noqa: E402

if st is None:
    raise SystemExit(
        "streamlit is not installed. Run: pip install -r requirements-optional.txt\n"
        "Fallback: use the CLI instead -> python -m app.cli"
    )

st.set_page_config(
    page_title="Rightly | Trợ lý pháp luật",
    page_icon="⚖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Elderly-friendly CSS — bigger fonts, larger click targets, high contrast
st.markdown(
    """
    <style>
      :root { --ink: #17252a; --muted: #617277; --teal: #0f6b68; --line: #dce5e3; }
      html, body, [class*="st-"] { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
      .stApp { background: linear-gradient(135deg, #f7fbfa 0%, #fffdf9 52%, #eef6f4 100%); color: var(--ink); }
      .block-container { max-width: 1180px; padding-top: 2.2rem; padding-bottom: 3rem; }
      .stMarkdown p, .stButton button { font-size: 16px !important; }
      .stButton button { border-radius: 12px; min-height: 48px; font-weight: 700; }
      [data-testid="stTextInput"] input { border-radius: 12px; min-height: 52px; border: 1px solid var(--line); }
      h1, h2, h3 { color: var(--ink); letter-spacing: -0.02em; }
      h1 { font-size: 2.8rem !important; }
      .hero { background: radial-gradient(circle at 85% 15%, #cce8df 0, transparent 33%), #173f43; color: white; padding: 34px 38px; border-radius: 24px; margin: 8px 0 22px; box-shadow: 0 18px 45px #173f4322; }
      .hero h1 { color: white; margin: 0 0 8px; font-size: 2.7rem !important; }
      .hero p { color: #d9eeea; max-width: 700px; font-size: 1.08rem; margin: 0; }
      .eyebrow { color: #a9ddd2; font-size: .78rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
      .stButton button, [data-testid="stLinkButton"] a, .stPopover button {
        min-height: 56px;
        font-weight: 600;
      }
      .stCaption, [data-testid="stCaptionContainer"] {
        color: #333 !important;
        font-size: 16px !important;
      }
      h1 { font-size: 2.2rem !important; }
      h2 { font-size: 1.7rem !important; }
      h3 { font-size: 1.4rem !important; }
      /* High contrast for answer text */
      .answer-box {
        background: #ffffffdd;
        border: 1px solid #d8e8e3;
        border-left: 5px solid var(--teal);
        padding: 20px 22px;
        border-radius: 16px;
        margin: 12px 0;
      }
      .citation-box {
        background: #fff9ed;
        border: 1px solid #f0dfb7;
        border-left: 5px solid #c78b2c;
        padding: 12px;
        border-radius: 8px;
        margin: 8px 0;
        font-style: italic;
      }
      .source-box {
        background: #f1f8f6;
        border: 1px solid #d5e8e2;
        padding: 12px;
        border-radius: 8px;
        margin: 8px 0;
        font-size: 15px !important;
      }
      .warning-box {
        background: #fff6f1;
        border: 1px solid #f3d5c2;
        border-left: 5px solid #c56b35;
        padding: 12px;
        border-radius: 8px;
        margin: 8px 0;
      }
      .disclaimer-box {
        background: #fffdf8;
        border: 1px solid #e9dfce;
        padding: 16px;
        border-radius: 14px;
        margin: 16px 0;
        text-align: center;
      }
      /* Hide Streamlit default footer/menu */
      #MainMenu {visibility: hidden;}
      footer {visibility: hidden;}
      header {background: transparent !important;}
      .stDeployButton {display: none;}
    </style>
    """,
    unsafe_allow_html=True,
)

settings = load_settings()


@st.cache_resource
def get_pipeline() -> Pipeline:
    return Pipeline(settings=load_settings())


pipeline = get_pipeline()

# ============================================================
# HEADER & DISCLAIMER
# ============================================================
st.markdown(
    '<section class="hero"><div class="eyebrow">RIGHTLY · LEGAL ACCESS</div><h1>Hiểu luật, làm đúng bước.</h1><p>Trợ lý pháp luật tiếng Việt giúp bạn tìm quy định hiện hành, hiểu điều khoản và chuẩn bị bước tiếp theo với nguồn trích dẫn rõ ràng.</p></section>',
    unsafe_allow_html=True,
)
st.caption(
    "Dựa trên corpus văn bản pháp luật đã kiểm duyệt · Câu trả lời chỉ mang tính tham khảo, không thay thế tư vấn chính thức"
)

st.markdown(
    """
    <div class="disclaimer-box">
    <strong>⚠️ QUAN TRỌNG - XIN ĐỌC KỸ TRƯỚC KHI DÙNG</strong><br>
    <ul style="text-align: left; margin: 8px 0;">
    <li>Rightly <strong>KHÔNG PHẢI</strong> cơ quan nhà nước, <strong>KHÔNG THAY THẾ</strong> cán bộ hoặc chuyên gia pháp luật</li>
    <li>Câu trả lời chỉ mang tính chất <strong>tham khảo</strong>, dựa trên văn bản pháp luật đã công bố</li>
    <li>Đối với vụ việc quan trọng, hãy <strong>liên hệ trực tiếp cơ quan có thẩm quyền</strong> hoặc chuyên gia luật</li>
    <li>Dữ liệu pháp luật có thể thay đổi - Rightly cập nhật theo chu kỳ, không phải real-time</li>
    </ul>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SESSION & SIDEBAR
# ============================================================
if "session_id" not in st.session_state:
    st.session_state.session_id = pipeline.create_session()
session_id = st.session_state.session_id

with st.sidebar:
    st.header("Cách dùng")
    st.caption("Mỗi câu hỏi được tìm trong nguồn luật, kiểm tra an toàn rồi mới trả lời.")
    with st.expander("Trạng thái hệ thống"):
        st.json(safe_settings_summary(settings))
    
    st.divider()
    st.markdown("### 📋 Hướng dẫn dùng")
    st.markdown("""
    1. **Gõ hoặc dán câu hỏi** vào ô bên dưới
    2. Nhấn **Hỏi** - hệ thống sẽ:
       - Tìm văn bản pháp luật liên quan
       - Kiểm tra an toàn (từ chối nếu rủi ro)
       - Trả lời có trích dẫn nguồn
    3. Xem **Câu trả lời**, **Trích dẫn**, **Nguồn gốc**
    4. Có thể tải **Phiếu chuẩn bị hồ sơ** (nếu có)
    """)
    
    st.divider()
    st.markdown("### 💡 Câu hỏi mẫu")
    sample_queries = [
        "Đăng ký khai sinh cần giấy gì?",
        "Thủ tục cấp giấy xác nhận hộ khẩu?",
        "Thừa kế đất đai cần làm gì?",
        "Người cao tuổi được quyền lợi BHYT gì?",
        "Cấp căn cước công dân cho người >60 tuổi?",
        "Xin xác nhận hộ nghèo ở đâu?",
        "Khám chữa bệnh BHYT tại tuyến xã?",
        "Sang tên xe máy cho con cần gì?",
    ]
    for sq in sample_queries:
        if st.button(sq, key=f"sample_{sq}", use_container_width=True):
            st.session_state.query_input = sq
            st.rerun()
    
    if st.button("🗑️ Xóa phiên (Reset)", type="secondary", use_container_width=True):
        pipeline.delete_session(session_id)
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# ============================================================
# MAIN QUERY INPUT
# ============================================================
st.subheader("Bạn đang cần biết điều gì?")

query = st.text_input(
    "Câu hỏi của bạn:",
    key="query_input",
    placeholder="Ví dụ: Hồ sơ đăng ký khai sinh gồm những giấy tờ gì?",
    label_visibility="collapsed"
)

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    ask_clicked = st.button("🔍 Hỏi", type="primary", use_container_width=True)
with col2:
    st.caption(f"Phiên: {session_id[:8]}...")
with col3:
    st.caption(f"Mode: {settings.app_mode.upper()}")

# ============================================================
# PROCESS QUERY
# ============================================================
if ask_clicked and query.strip():
    with st.spinner("⏳ Đang tìm văn bản pháp luật và tạo câu trả lời..."):
        result = pipeline.process_text(session_id, query)
    
    st.session_state.last_result = result.to_dict()
    st.rerun()

# ============================================================
# DISPLAY RESULT
# ============================================================
if "last_result" in st.session_state:
    data = st.session_state.last_result
    decision = data["decision"]
    answer = data.get("answer")
    
    # Decision zone display
    zone_icons = {"YELLOW": "🟢", "ORANGE": "🟠", "RED": "🔴", "GREEN": "🟢"}
    zone_colors = {"YELLOW": "#2e7d32", "ORANGE": "#ef6c00", "RED": "#c62828", "GREEN": "#2e7d32"}
    zone_icon = zone_icons.get(decision["zone"], "⚪")
    zone_color = zone_colors.get(decision["zone"], "#666")
    
    st.markdown(
        f"""
        <div style="background: {zone_color}15; border-left: 5px solid {zone_color}; 
                    padding: 16px; border-radius: 8px; margin: 16px 0;">
        <strong>Kết quả xử lý:</strong> {zone_icon} <strong>{decision['zone']}</strong>  |  
        <strong>Hành động:</strong> {decision['action']}  |  
        <strong>Cần cán bộ:</strong> {'Có' if decision['requires_human'] else 'Không'}<br>
        <strong>Lý do:</strong> <code>{', '.join(decision['reason_codes'])}</code>
        </div>
        """,
        unsafe_allow_html=True,
    )
    
    if answer:
        # ANSWER
        st.markdown("### ✅ Câu trả lời")
        st.markdown(
            f'<div class="answer-box">{answer["answer_text"]}</div>',
            unsafe_allow_html=True,
        )
        
        # CITATION
        if answer.get("spoken_citation"):
            st.markdown("### 📌 Trích dẫn (đọc kèm câu trả lời)")
            st.markdown(
                f'<div class="citation-box">"{answer["spoken_citation"]}"</div>',
                unsafe_allow_html=True,
            )
        
        # SOURCES
        if answer.get("source_ids"):
            st.markdown("### 📚 Nguồn văn bản pháp luật")
            for src in answer["source_ids"]:
                st.markdown(
                    f'<div class="source-box">📄 <code>{src}</code></div>',
                    unsafe_allow_html=True,
                )
        elif answer.get("limitations") and any("FAQ" in lim for lim in answer["limitations"]):
            st.caption("ℹ️ Câu trả lời từ bộ FAQ nội bộ (đã được team xác minh với corpus pháp luật)")
        
        # LIMITATIONS
        if answer.get("limitations"):
            st.markdown("### ⚠️ Lưu ý quan trọng")
            for lim in answer["limitations"]:
                st.markdown(f'<div class="warning-box">{lim}</div>', unsafe_allow_html=True)
        
        # NEXT STEPS
        if answer.get("next_step"):
            st.markdown("### ➡️ Bước tiếp theo gợi ý")
            st.info(answer["next_step"])
        
        # ACTIONS
        st.divider()
        col_a1, col_a2, col_a3 = st.columns(3)
        
        with col_a1:
            # Audio playback
            audio_path = pipeline.settings.resolved_results_dir() / f"{session_id}.wav"
            if audio_path.exists() and audio_path.stat().st_size > 0:
                st.audio(str(audio_path))
                st.caption("🔊 Nhấn play để nghe câu trả lời")
            else:
                st.caption("🔇 Chế độ demo: TTS chưa kích hoạt trên server này")
        
        with col_a2:
            if st.button("📄 Tải phiếu chuẩn bị hồ sơ", use_container_width=True):
                from app.contacts import default_contact
                from app.forms import build_registration_slip
                contact = default_contact()
                slip = build_registration_slip(
                    query=str(data.get("query", "")),
                    summary=str(answer.get("answer_text", "")),
                    next_step=str(answer.get("next_step", "")),
                    contact=contact,
                )
                st.download_button(
                    "💾 Tải về (.md)",
                    data=slip.to_markdown(),
                    file_name="phieu_chuan_bi_ho_so.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
                st.caption("Phiếu chỉ hỗ trợ khai sẵn quy trình - không thu thập thông tin cá nhân")
        
        with col_a3:
            if st.button("🔁 Hỏi lại / Câu hỏi khác", use_container_width=True):
                if "last_result" in st.session_state:
                    del st.session_state.last_result
                st.rerun()
    
    else:
        # NO ANSWER - SHOW GUIDANCE
        st.markdown("### ℹ️ Hướng dẫn")
        st.warning(decision["user_message"])
        
        if decision["zone"] == "RED":
            st.error("🚨 **Phát hiện rủi ro an toàn** - Rightly không trả lời câu hỏi này.")
            st.markdown(decision.get("user_message", ""))
        
        st.markdown("**Gợi ý:** Hãy thử hỏi lại cụ thể hơn về thủ tục hành chính, ví dụ:")
        st.caption("- 'Thủ tục đăng ký khai sinh cần giấy gì?'")
        st.caption("- 'Quy trình cấp giấy xác nhận hộ khẩu?'")
        st.caption("- 'Thừa kế đất đai cần làm thủ tục gì?'")
    
    # TECHNICAL DETAILS (EXPANDER)
    with st.expander("🔧 Chi tiết kỹ thuật (cho developer)"):
        st.markdown("#### Retrieved chunks (top 5)")
        for i, chunk in enumerate(data["chunks"][:5], 1):
            st.markdown(f"{i}. `{chunk['source_id']}::{chunk['chunk_id']}` — score: {chunk['score']:.4f}")
        
        st.markdown("#### Latency breakdown (ms)")
        st.json(data["latencies_ms"])
        
        st.markdown("#### Raw decision")
        st.json(decision)

# ============================================================
# FOOTER
# ============================================================
st.divider()
st.markdown(
    """
    <div style="text-align: center; color: #666; padding: 16px;">
    <small>
    Rightly - Voice-first public service access agent<br>
    Bản demo - Dữ liệu: 92 văn bản pháp luật (Luật, Nghị định, Thông tư) từ VBPL<br>
    Kiến trúc: ASR → Retrieval (Hybrid BM25+Dense) → Safety Router → LLM → TTS<br>
    <strong>Không gửi audio ra ngoài</strong> | <strong>Không lưu transcript</strong> mặc định | Mã nguồn mở (MIT)
    </small>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# RATE LIMITING (demo-grade)
# ============================================================
from app.ratelimit import RateLimiter

MAX_QUERIES_PER_SESSION = 30
if "query_count" not in st.session_state:
    st.session_state.query_count = 0

_limiter = RateLimiter(
    limit=settings.rate_limit_per_ip,
    window_seconds=settings.rate_limit_window_seconds,
)

def _client_key() -> str:
    ip = ""
    try:
        headers = st.context.headers
        ip = headers.get("X-Forwarded-For", "").split(",")[0].strip()
    except Exception:
        pass
    return f"{hash(ip or 'local') % 10**9}|{session_id}"

# Check limits before processing
if ask_clicked and query.strip():
    if st.session_state.query_count >= MAX_QUERIES_PER_SESSION:
        st.error(f"Đã đạt giới hạn {MAX_QUERIES_PER_SESSION} câu hỏi/phiên. Nhấn 'Xóa phiên' để tiếp tục.")
        st.stop()
    elif len(query) > 1000:
        st.error("Câu hỏi quá dài (tối đa 1000 ký tự).")
        st.stop()
    elif not _limiter.allow(_client_key()):
        st.error(f"Đã đạt giới hạn {settings.rate_limit_per_ip} câu hỏi/{settings.rate_limit_window_seconds//3600}h. Quay lại sau.")
        st.stop()
    else:
        st.session_state.query_count += 1
