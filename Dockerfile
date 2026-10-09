FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY app ./app
COPY scripts ./scripts

ENV REEL_DB_PATH=/data/japan_reels.db
ENV WHISPER_MODEL_CACHE_DIR=/data/whisper_models
ENV AI_DEBUG_LOG_PATH=/data/ai_debug.log
ENV INSTAGRAM_COOKIES_PATH=/data/instagram_cookies.txt
VOLUME ["/data"]

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
