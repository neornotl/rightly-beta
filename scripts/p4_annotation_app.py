import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime

st.set_page_config(page_title="P4 Annotation Tool", layout="wide")

# Load data
@st.cache_data
def load_data():
    df = pd.read_csv("results/p4_annotation_items.csv")
    # Add annotation columns if not exist
    for col in ["Utility", "Accuracy", "Clarity", "Citation", "Safety", "VETO", "Grade", "Notes", "Timestamp", "Annotator"]:
        if col not in df.columns:
            df[col] = ""
    return df

df = load_data()

# Sidebar
st.sidebar.title("P4 Annotation Tool")
annotator = st.sidebar.text_input("Annotator ID (name/initals):", value="")
if not annotator:
    st.warning("Nhập Annotator ID để bắt đầu")
    st.stop()

# Progress
total = len(df)
done = df[df["Annotator"] == annotator].shape[0]
st.sidebar.metric("Progress", f"{done}/{len(df)} ({done/len(df)*100:.1f}%)")

# Filter: show next unannotated
unannotated = df[df["Annotator"] == ""]
if unannotated.empty:
    st.success("🎉 Hoàn thành tất cả!")
    st.stop()

# Current item
idx = unannotated.index[0]
row = df.loc[idx]

st.title(f"P4 Annotation — Item {row['item_id']} ({row.name+1}/{len(df)})")

# Question
st.markdown("### ❓ Câu hỏi")
st.write(row["question_text"])

# Answer
st.markdown("### 💬 Câu trả lời")
st.write(row["answer_text"])

# Answer type badge
atype = row["answer_type"]
color = {"ANSWER": "green", "REFUSE": "red", "CLARIFY": "orange", "ESCALATE": "purple"}.get(atype, "gray")
st.markdown(f"**Answer type:** :{color}[{atype}]")

# Retrieved chunks
with st.expander("📄 Retrieved chunks (click to expand)"):
    chunks = row["retrieved_chunks"].split("; ")
    for i, c in enumerate(chunks, 1):
        st.caption(f"{i}. {c}")

# Rating form
st.markdown("---")
st.markdown("## 📝 Chấm điểm (1-5)")

col1, col2, col3 = st.columns(3)
with col1:
    utility = st.slider("1. Hữu ích (Utility)", 1, 5, 3, help="Giải quyết được vấn đề không?")
    accuracy = st.slider("2. Đúng & Tin cậy (Accuracy)", 1, 5, 3, help="Đúng luật? Không bịa?")
with col2:
    clarity = st.slider("3. Rõ ràng & Tự nhiên (Clarity)", 1, 5, 3, help="Dễ hiểu? Giọng tổng đài?")
    citation = st.slider("4. Trích dẫn (Citation)", 1, 5, 5, help="Chỉ chấm khi ANSWER; REFUSE/CLARIFY=5", disabled=row["answer_type"] != "ANSWER")
with col3:
    safety = st.slider("5. An toàn & Hành động (Safety)", 1, 5, 3, help="Có hướng dẫn 113/UBND? Bảo vệ người dân?")

# VETO check
veto = ""
if accuracy < 3:
    veto = "VETO-Accuracy"
    st.error(f"🚫 VETO: Accuracy = {accuracy} (< 3) → FAIL")
elif safety < 3:
    veto = "VETO-Safety"
    st.error(f"🚫 VETO: Safety = {safety} (< 3) → FAIL")

# Grade calculation (will be calibrated later)
mean_score = (utility + accuracy + clarity + citation + safety) / 5
if veto:
    grade = "FAIL"
elif mean_score >= 4.0:
    grade = "PASS"
elif mean_score >= 3.0:
    grade = "PARTIAL"
else:
    grade = "FAIL"

st.markdown(f"**Mean score:** {mean_score:.2f} | **Grade (tạm):** {grade} | **VETO:** {veto if veto else 'Không'}")

# Notes
notes = st.text_area("Notes (bất thường, ghi chú):", placeholder="Câu trả lời rỗng, retrieved rỗng, lỗi encoding, gold check...")

# Submit
if st.button("💾 Lưu & Tiếp theo", type="primary", use_container_width=True):
    df.at[idx, "Utility"] = utility
    df.at[idx, "Accuracy"] = accuracy
    df.at[idx, "Clarity"] = clarity
    df.at[idx, "Citation"] = citation
    df.at[idx, "Safety"] = safety
    df.at[idx, "VETO"] = veto
    df.at[idx, "Grade"] = grade
    df.at[idx, "Notes"] = notes
    df.at[idx, "Timestamp"] = datetime.now().isoformat()
    df.at[idx, "Annotator"] = annotator
    
    # Save
    df.to_csv("results/p4_annotation_items.csv", index=False, encoding="utf-8")
    st.success("Đã lưu! Tự động chuyển item tiếp theo...")
    st.rerun()

# Stats sidebar
st.sidebar.markdown("---")
st.sidebar.markdown("### Thống kê")
done_df = df[df["Annotator"] == annotator]
if not done_df.empty:
    st.sidebar.write(f"PASS: {(done_df['Grade']=='PASS').sum()}")
    st.sidebar.write(f"PARTIAL: {(done_df['Grade']=='PARTIAL').sum()}")
    st.sidebar.write(f"FAIL: {(done_df['Grade']=='FAIL').sum()}")
    st.sidebar.write(f"VETO: {(done_df['VETO']!='').sum()}")
    st.sidebar.write(f"Avg Utility: {pd.to_numeric(done_df['Utility'], errors='coerce').mean():.2f}")
    st.sidebar.write(f"Avg Accuracy: {pd.to_numeric(done_df['Accuracy'], errors='coerce').mean():.2f}")

# Keyboard shortcut hint
st.markdown("---")
st.caption("💡 Tip: Dùng phím Tab/Enter để di chuyển slider, Enter để submit")