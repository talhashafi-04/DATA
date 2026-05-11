FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive


# Install all dependencies in one apt transaction.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux=3.4-1build1 \
    bash=5.2.21-2ubuntu4 \
    coreutils=9.4-3ubuntu6.2 \
    python3=3.12.3-0ubuntu2.1 \
    python3-pytest=7.4.4-1 \
    passwd=1:4.13+dfsg1-4ubuntu3.2 \
    util-linux=2.39.3-9ubuntu6.5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Ephemeral sandboxes for tests; not on the sticky /tmp tree so unprivileged
# recovery can replace files after permission changes.
RUN mkdir -p /sandbox && chmod 777 /sandbox
