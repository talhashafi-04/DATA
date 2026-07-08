#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp "$SCRIPT_DIR/normalize_archive.py" /app/normalize_archive.py
python3 /app/normalize_archive.py /app/data/raw /app/data/normalized
