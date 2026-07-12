# ============================================================
# speaker-helper — REST API server image.
#
# Runs `speaker-helper serve` (FastAPI + uvicorn). This container is a thin
# client of a Voicebox engine, which runs as its own service — point it at
# one with SPEAKER_HELPER_VOICEBOX_HOST / SPEAKER_HELPER_VOICEBOX_PORT.
#
#   docker build -t speaker-helper .
#   docker run --rm -p 8080:8080 \
#     -e SPEAKER_HELPER_VOICEBOX_HOST=host.docker.internal \
#     -e SPEAKER_HELPER_VOICEBOX_PORT=17600 \
#     speaker-helper
# ============================================================
FROM python:3.11-slim

# libsndfile backs the `soundfile` wheel used to measure/concatenate audio.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY speaker_helper ./speaker_helper
RUN pip install --no-cache-dir ".[server]"

# The server reaches Voicebox on the host by default; override as needed.
ENV SPEAKER_HELPER_VOICEBOX_HOST=host.docker.internal \
    SPEAKER_HELPER_VOICEBOX_PORT=17600 \
    LOG_LEVEL=info

EXPOSE 8080

CMD ["speaker-helper", "serve", "--host", "0.0.0.0", "--port", "8080"]
