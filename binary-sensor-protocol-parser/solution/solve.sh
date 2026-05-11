#!/usr/bin/env bash
set -e
# Verify binary integrity before parsing
sha256sum -c /app/data/sensor_dump.bin.sha256
mkdir -p /app/output
python3 /solution/parser.py /app/data/sensor_dump.bin /app/output/results.json
