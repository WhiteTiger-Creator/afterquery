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

# Numerical stack only. No cheminformatics toolkit: reading the structure out of a SMILES
# string is part of the work, and there is no network at run time to fetch one.
RUN pip install --no-cache-dir \
        numpy==2.1.3 \
        scipy==1.14.1 \
        scikit-learn==1.5.2 \
        joblib==1.4.2

# The installer drops the binary under /root/.local/bin, which is not on the default
# PATH. Link it somewhere already on PATH and set PATH too, then run it once: a CLI that
# cannot be launched must break the build here rather than fail every trial later.
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && /usr/local/bin/claude --version

ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

COPY molprop /app/molprop
COPY data /app/data
COPY train.sh /app/train.sh
COPY predict.sh /app/predict.sh
COPY selfcheck.py /app/selfcheck.py
COPY selfcheck.sh /app/selfcheck.sh
COPY scoring.json /app/scoring.json
COPY README.md /app/README.md

RUN chmod +x /app/train.sh /app/predict.sh /app/selfcheck.sh

# Bake the shipped model so the workspace arrives with a working pipeline rather than an
# empty one, and so an untouched workspace predicts exactly what the baseline describes.
RUN /app/train.sh && ls -l /app/model

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
