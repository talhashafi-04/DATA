FROM public.ecr.aws/docker/library/ubuntu:24.04@sha256:0d39fcc8335d6d74d5502f6df2d30119ff4790ebbb60b364818d5112d9e3e932

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3=3.12.3-0ubuntu2.1 \
    python3-pip=24.0+dfsg-1ubuntu1.3 \
    python3-pytest=7.4.4-1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --break-system-packages \
    pytest-json-ctrf==0.5.0

WORKDIR /app

COPY capnp_decoder.py /app/capnp_decoder.py
COPY task-deps/ /app/task-deps/
COPY data/messages.bin /app/data/messages.bin

RUN mkdir -p /app/data /logs/verifier \
    && chmod 777 /logs /logs/verifier /app/data \
    && chmod 666 /app/data/messages.bin

USER root
