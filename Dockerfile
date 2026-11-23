FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The embedding model for hybrid search, baked in so the app never downloads it at runtime.
ENV FASTEMBED_CACHE_PATH=/app/.fastembed
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/.fastembed')"

COPY . .

RUN mkdir -p logs

EXPOSE 8000

# Apply any pending migrations (idempotent), then serve. A failed migration is logged, the app still starts.
CMD ["sh", "-c", "alembic upgrade head || echo \"alembic upgrade failed\"; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
