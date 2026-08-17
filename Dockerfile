# Streamlit Cloud / HF Spaces deployment (F3) — CPU-only, <500MB.
# Build: docker build -t rightly .
# Run: docker run -p 8501:8501 --env-file .env rightly

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# System deps for sentence-transformers (lightweight)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt requirements-streamlit.txt ./
RUN pip install --no-cache-dir -r requirements-streamlit.txt

# Copy application code
COPY app/ ./app/
COPY data/ ./data/
COPY .streamlit/ ./.streamlit/

# Streamlit expects the main script at the root or specified path
# Cloud config: main file is app/ui.py
EXPOSE 8501

# Non-root user (good practice)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["streamlit", "run", "app/ui.py", "--server.address=0.0.0.0", "--server.port=8501"]