# Rightly web deployment: lightweight FastAPI HTML UI.
# Streamlit remains available as a secondary local UI, but is not the
# production entrypoint because eager model loading can kill a free container.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8010 \
    APP_MODE=local \
    ASR_BACKEND=mock \
    RETRIEVAL_BACKEND=bm25 \
    LLM_BACKEND=mock \
    TTS_BACKEND=mock

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt

COPY app/ ./app/
COPY data/ ./data/
COPY web/ ./web/
COPY webhook_server.py ./webhook_server.py

EXPOSE 8010

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["sh", "-c", "uvicorn webhook_server:app --host 0.0.0.0 --port ${PORT:-8010}"]
