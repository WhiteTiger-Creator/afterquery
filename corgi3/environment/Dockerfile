FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        procps \
        time \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# A compiler and Cython, because a faster inner loop is one of the honest routes here.
# Deliberately absent: any library that already solves shortest paths. Importing somebody
# else's compiled Dijkstra is not the exercise.
RUN pip install --no-cache-dir \
        numpy==2.1.3 \
        cython==3.0.11 \
        setuptools==75.6.0

# The installer drops the binary under /root/.local/bin, which is not on the default
# PATH. Link it somewhere already on PATH and set PATH too, then run it once: a CLI that
# cannot be launched must break the build here rather than fail every trial later.
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && /usr/local/bin/claude --version

ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

COPY router /app/router
COPY data /app/data
COPY solve.sh /app/solve.sh
COPY prepare.sh /app/prepare.sh
COPY selfcheck.py /app/selfcheck.py
COPY selfcheck.sh /app/selfcheck.sh
COPY README.md /app/README.md

# A pristine copy of the shipped router, so the local check always has something honest to
# compare against however far the working copy has been rewritten.
COPY router /app/.reference/router

RUN chmod +x /app/solve.sh /app/prepare.sh /app/selfcheck.sh

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
