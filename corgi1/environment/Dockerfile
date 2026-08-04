FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# System packages: curl for the CLI install, the compression tools the reference
# baseline uses, and enough build tooling for anything that wants a C extension.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        bzip2 \
        xz-utils \
        zstd \
        procps \
        time \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies, pinned. No network is available at run time, so everything the
# task can possibly need has to be here.
RUN pip install --no-cache-dir \
        chess==1.11.1 \
        numpy==2.1.3 \
        scipy==1.14.1

# The installer drops the binary under /root/.local/bin, which is not on the default
# PATH. Link it somewhere already on PATH and set PATH too, then run it once: a CLI that
# cannot be launched must break the build here rather than fail every trial later.
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && /usr/local/bin/claude --version

ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

COPY pgnpack /app/pgnpack
COPY corpus /app/corpus
COPY compress.sh /app/compress.sh
COPY decompress.sh /app/decompress.sh
COPY selfcheck.py /app/selfcheck.py
COPY selfcheck.sh /app/selfcheck.sh
COPY scoring.json /app/scoring.json
COPY manifest.json /app/manifest.json
COPY README.md /app/README.md

RUN chmod +x /app/compress.sh /app/decompress.sh /app/selfcheck.sh

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
