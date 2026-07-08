FROM public.ecr.aws/docker/library/ubuntu:24.04@sha256:0d39fcc8335d6d74d5502f6df2d30119ff4790ebbb60b364818d5112d9e3e932

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3=3.12.3-0ubuntu2.1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY task-deps/tmux /usr/local/bin/tmux
COPY task-deps/tmux-libs/ /usr/local/lib/
COPY task-deps/checksums.sha256 /tmp/task-deps-checksums.sha256

RUN sha256sum -c /tmp/task-deps-checksums.sha256 \
    && chmod 0755 /usr/local/bin/tmux \
    && ldconfig \
    && rm /tmp/task-deps-checksums.sha256

COPY task-deps/access_control.py /app/access_control.py

WORKDIR /app

CMD ["sleep", "infinity"]
