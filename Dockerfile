# ============================================================
# speaker-helper — the voice, served.
#
# This image used to be a thin client of a Voicebox engine running somewhere
# else, and most of its configuration existed to find that engine. There is
# no engine elsewhere now: Kokoro runs in this container.
#
#   docker compose up -d
#   curl -s -X POST localhost:8080/synth -H 'content-type: application/json' \
#        -d '{"text": "Bonjour."}' -o out.wav
# ============================================================
FROM python:3.11-slim

# Two things pip cannot supply.
#
# espeak-ng: Kokoro phonemises through it. The `espeakng-loader` wheel carries
# a copy, and that copy is the fallback, not the plan — the code looks for the
# system one first because the wheel's was built on a CI runner and resolves
# its data to that machine's home directory. It is GPL, and it is reached as a
# separate binary through ctypes, the way a program calls ffmpeg; installing it
# here keeps that arrangement rather than linking it into anything.
#
# libsndfile: backs the `soundfile` wheel that decodes audio to lay a
# narration out.
RUN apt-get update && apt-get install -y --no-install-recommends \
        espeak-ng \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, for layer caching.
COPY pyproject.toml README.md ./
COPY speaker_helper ./speaker_helper
RUN pip install --no-cache-dir ".[all,server,mcp]"

# The weights, fetched at build time rather than on the first request. An
# image that downloads 340 MB the first time somebody calls it is an image
# whose first call times out — and in a scaled deployment, every replica
# downloads it again.
RUN speaker-helper install-voice --engine kokoro

ENV SPEAKER_HELPER_LANGUAGE=fr \
    LOG_LEVEL=info

EXPOSE 8080

# Serve what the image was built for. Override with any of the commands:
#
#   docker run --rm -v "$PWD:/work" IMAGE speaker-helper narrate /work/post.json
CMD ["speaker-helper", "serve", "--bind-host", "0.0.0.0", "--bind-port", "8080"]
