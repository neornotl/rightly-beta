import os
os.environ['RETRIEVAL_BACKEND'] = 'bm25'
os.environ['TTS_BACKEND'] = 'mock'
os.environ['LLM_BACKEND'] = 'mock'

from app.config import load_settings
from app.pipeline import Pipeline, make_retriever

s = load_settings()
retriever = make_retriever(s)
p = Pipeline(s)
p.retriever = retriever
p.faq = None

tests = [
    'mức lương cơ sở hiện nay',
    'lương tối thiểu vùng 2026',
    'tuổi nghỉ hưu',
]

for q in tests:
    chunks = retriever.search(q, top_k=3)
    print('Q: ' + q)
    print('  Top: ' + str([(c.source_id, round(c.score,2)) for c in chunks]))
    sid = p.create_session()
    r = p.process_text(sid, q)
    srcs = r.answer.source_ids if r.answer else 'None'
    ans = r.answer.answer_text[:150] if r.answer else 'None'
    print('  Sources: ' + str(srcs))
    print('  Answer: ' + ans)
    print()