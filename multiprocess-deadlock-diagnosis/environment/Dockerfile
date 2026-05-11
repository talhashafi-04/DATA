FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive


# tmux: terminus-2 agent. asciinema: pre-install so Harbor does not pip-install at runtime.
# All apt package names are version-pinned (task_workflow QC Block A).
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux=3.2a-4ubuntu0.2 \
    asciinema=2.1.0-1 \
    python3=3.10.6-1~22.04.1 \
    python3-pytest=6.2.5-1ubuntu2 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY batch_worker.py /app/batch_worker.py
COPY pipeline.py /app/pipeline.py
