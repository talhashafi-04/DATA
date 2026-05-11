FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux=3.2a-4ubuntu0.2 \
    asciinema=2.1.0-1 \
    python3=3.10.6-1~22.04.1 \
    python3-pytest=6.2.5-1ubuntu2 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pipeline.py /app/pipeline.py
