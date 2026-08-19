"""Streamlit UI for Rightly - Continuous chat (ChatGPT-style).

Run with:
    pip install -r requirements-optional.txt
    streamlit run app/ui.py

The UI keeps the whole conversation in one thread (multi-turn memory lives in
the pipeline session) and hides all internal machinery from the user.
"""

from __future__ import annotations

import sys
from html import escape
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

from app.config import load_settings  # noqa: E402 - needs sys.path fix above
from app.pipeline import Pipeline  # noqa: E402

if st is None:
    raise SystemExit(
        "streamlit is not installed. Run: pip install -r requirements-optional.txt\n"
        "Fallback: use the CLI instead -> python -m app.cli"
    )

st.set_page_config(
    page_title="Rightly | Trợ lý pháp luật",
    page_icon="⚖",
    layout="centered",
    initial_sidebar_state="expanded",
)

# Clean, chat-first CSS (no technical panels, no hero)
st.markdown(
    """
    <style>
      :root { --ink: #1f2328; --muted: #6b7280; --teal: #0f6b68; --line: #e5e7eb; }
      html, body, [class*="st-"] { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
      .stApp { background: #ffffff; color: var(--ink); }
      .block-container { max-width: 860px; padding-top: 1.4rem; padding-bottom: 6rem; }
      .stMarkdown p, .stChatMessage { font-size: 15.5px; line-height: 1.7; }
      .stChatMessage [data-testid="stMarkdownContainer"] p { font-size: 15.5px; line-height: 1.7; }
      .stChatInput input, [data-testid="stChatInput"] textarea { border-radius: 22px !important; font-size: 15.5px !important; }
      h1, h2, h3 { color: var(--ink); letter-spacing: -0.02em; }
      h1 { font-size: 1.9rem !important; }
      #MainMenu {visibility: hidden;}
      footer {visibility: hidden;}
      .stDeployButton {display: none;}
      header[data-testid="stHeader"] { background: transparent !important; height: 0px !important; }
      .topbar { display: flex; align-items: center; justify-content: space-between; padding: 4px 0 16px; border-bottom: 1px solid var(--line); }
      .topbar h1 { margin: 0; font-size: 1.35rem !important; display: flex; align-items: center; gap: 8px; }
      .topbar .pill { font-size: .72rem; color: var(--muted); background: #f3f4f6; border: 1px solid var(--line); border-radius: 999px; padding: 3px 10px; }
      .src-line { font-size: 13px; color: var(--muted); margin-top: 6px; }
      .src-line code { background: #f3f4f6; padding: 1px 6px; border-radius: 6px; font-size: 12px; color: #374151; }
      .notice { font-size: 13px; color: var(--muted); margin-top: 8px; }
      .cite { color: var(--muted); font-size: 13.5px; font-style: italic; margin-top: 8px; }
      .warn { background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px; padding: 8px 12px; font-size: 13.5px; margin-top: 8px; color: #92400e; }
      .disclaimer { text-align: center; font-size: 12.5px; color: #9ca3af; margin-top: 4px; }
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
# SESSION STATE (conversation thread + pipeline session)
# ============================================================
if "session_id" not in st.session_state:
    st.session_state.session_id = pipeline.create_session()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "query_count" not in st.session_state:
    st.session_state.query_count = 0

session_id = st.session_state.session_id

# ============================================================
# SIDEBAR (simple, no technical details)
# ============================================================
with st.sidebar:
    st.markdown("### 💡 Thử hỏi")
    sample_queries = [
        "Đăng ký khai sinh cần giấy tờ gì?",
        "Khi nào tôi được nghỉ hưu?",
        "Vượt đèn đỏ bị phạt bao nhiêu?",
        "Ly hôn thuận tình cần hồ sơ gì?",
        "Trẻ em dưới 6 tuổi có phải đóng BHYT không?",
        "Dạy thêm ngoài nhà trường có được không?",
    ]
    for sq in sample_queries:
        if st.button(sq, key=f"sample_{sq}", use_container_width=True):
            st.session_state.pending_query = sq
            st.rerun()

    st.divider()
    if st.button("🗑️ Xóa hội thoại", type="secondary", use_container_width=True):
        pipeline.delete_session(session_id)
        st.session_state.session_id = pipeline.create_session()
        st.session_state.messages = []
        st.session_state.query_count = 0
        st.rerun()

    st.divider()
    st.markdown("##### ⚖️ Rightly")
    st.caption(
        "Trợ lý pháp luật tiếng Việt. Câu trả lời chỉ mang tính tham khảo, "
        "dựa trên văn bản pháp luật đã công bố, không thay thế tư vấn chính thức."
    )

# ============================================================
# TOP BAR
# ============================================================
st.markdown(
    """
    <div class="topbar">
      <h1>⚖️ Rightly</h1>
      <span class="pill">Trợ lý pháp luật</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
def _render_assistant(st, msg: dict) -> None:
    """Render assistant message: answer text + citation + sources + limitations + next step."""
    st.markdown(msg["text"])
    if msg.get("citation"):
        st.markdown(
            f'<div class="cite">📌 {escape(msg["citation"])}</div>',
            unsafe_allow_html=True,
        )
    if msg.get("next_step"):
        st.markdown(
            f'<div class="notice">➡️ {escape(msg["next_step"])}</div>',
            unsafe_allow_html=True,
        )
    if msg.get("limitations"):
        for lim in msg["limitations"]:
            st.markdown(
                f'<div class="warn">⚠️ {escape(lim)}</div>',
                unsafe_allow_html=True,
            )
    if msg.get("sources"):
        srcs = " · ".join(
            f"<code>{escape(s)}</code>" for s in msg["sources"]
        )
        st.markdown(
            f'<div class="src-line">📚 Nguồn: {srcs}</div>',
            unsafe_allow_html=True,
        )


# RENDER CONVERSATION THREAD
# ============================================================
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.markdown(msg["text"])
        else:
            _render_assistant(st, msg)

# ============================================================
# PROCESS A QUERY (chat input or sidebar sample)
# ============================================================
def handle_query(text: str) -> None:
    text = text.strip()
    if not text:
        return
    if st.session_state.query_count >= 30:
        st.error("Đã đạt giới hạn 30 câu hỏi/phiên. Bấm 'Xóa hội thoại' để tiếp tục.")
        return
    if len(text) > 1000:
        st.error("Câu hỏi quá dài (tối đa 1000 ký tự).")
        return

    st.session_state.query_count += 1
    st.session_state.messages.append({"role": "user", "text": text})

    with st.spinner(""):
        try:
            result = pipeline.process_text(session_id, text)
        except Exception as exc:  # pragma: no cover
            st.error(f"Đã có lỗi xử lý: {exc}")
            return
        msg = _assistant_payload(result)
        st.session_state.messages.append(msg)
    st.rerun()


def _assistant_payload(result) -> dict:
    """Build a chat-ready payload from a PipelineResult (no internal fields)."""
    decision = result.decision
    answer = result.answer
    if answer and answer.answer_text.strip():
        text = answer.answer_text
        citations = answer.spoken_citation or ""
        sources = list(answer.source_ids)
        limitations = list(answer.limitations)
        next_step = answer.next_step or ""
        is_answer = True
    else:
        text = decision.user_message or (
            "Tôi chưa thể trả lời câu hỏi này. Bạn có thể hỏi lại cụ thể hơn "
            "về một thủ tục hành chính hoặc quy định pháp luật nhé."
        )
        citations = ""
        sources = []
        limitations = []
        next_step = ""
        is_answer = False
    return {
        "role": "assistant",
        "text": text,
        "is_answer": is_answer,
        "citation": citations,
        "sources": sources,
        "limitations": limitations,
        "next_step": next_step,
    }


def _render_assistant(st, msg: dict) -> None:
    st.markdown(msg["text"])
    if msg.get("citation"):
        st.markdown(f'<div class="cite">📌 {escape(msg["citation"])}</div>', unsafe_allow_html=True)
    if msg.get("next_step"):
        st.markdown(f'<div class="notice">➡️ {escape(msg["next_step"])}</div>', unsafe_allow_html=True)
    if msg.get("limitations"):
        for lim in msg["limitations"]:
            st.markdown(f'<div class="warn">⚠️ {escape(lim)}</div>', unsafe_allow_html=True)
    if msg.get("sources"):
        srcs = " · ".join(f"<code>{escape(s)}</code>" for s in msg["sources"])
        st.markdown(f'<div class="src-line">📚 Nguồn: {srcs}</div>', unsafe_allow_html=True)


# Sample question clicked in sidebar -> run it
pending = st.session_state.pop("pending_query", None)
if pending:
    handle_query(pending)

# ============================================================
# CHAT INPUT (continuous thread)
# ============================================================
# Chat input (continuous thread)
prompt = st.chat_input(
    "Hỏi về quy định, thủ tục hành chính hoặc pháp luật...",
    key="chat_input_box",
)

if prompt:
    handle_query(prompt)

# ============================================================
# FOOTER DISCLAIMER
# ============================================================
st.markdown(
    """
    <div class="disclaimer">
    Rightly - trợ lý pháp luật thử nghiệm · Câu trả lời chỉ mang tính tham khảo, không thay thế tư vấn chính thức
    </div>
    """,
    unsafe_allow_html=True,
)