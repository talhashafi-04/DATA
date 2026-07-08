FROM public.ecr.aws/docker/library/ubuntu:24.04@sha256:0d39fcc8335d6d74d5502f6df2d30119ff4790ebbb60b364818d5112d9e3e932

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential=12.10ubuntu1 \
    libgmp-dev=2:6.3.0+dfsg-2ubuntu6.1 \
    libmpfr-dev=4.2.1-1build1.1 \
    python3=3.12.3-0ubuntu2.1 \
    python3-pip=24.0+dfsg-1ubuntu1.3 \
    python3-pytest=7.4.4-1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --break-system-packages \
    mpmath==1.3.0 \
    pytest-json-ctrf==0.5.0

RUN mkdir -p /logs/verifier && chmod 777 /logs /logs/verifier

WORKDIR /app

COPY generate_cases.py /app/generate_cases.py
COPY softfma.c /app/softfma.c
COPY fma_runner.c /app/fma_runner.c
COPY Makefile /app/Makefile
COPY task-deps /app/task-deps

RUN python3 /app/generate_cases.py
RUN make clean && make all

USER root
