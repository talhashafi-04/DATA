FROM public.ecr.aws/docker/library/ubuntu:24.04@sha256:0d39fcc8335d6d74d5502f6df2d30119ff4790ebbb60b364818d5112d9e3e932

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3=3.12.3-0ubuntu2.1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/data/raw /app/data/normalized

COPY generate_files.py /app/generate_files.py
RUN python3 /app/generate_files.py

RUN test "$(find /app/data/raw -type f -name '*.txt' | wc -l)" = "12" \
    && find /app/data/raw -type f -name '*.txt' -exec test -s {} \; \
    && rm /app/generate_files.py

USER root
