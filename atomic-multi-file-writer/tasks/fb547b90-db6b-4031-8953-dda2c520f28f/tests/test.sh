#!/usr/bin/env bash
# Run the full atomic_write.sh test suite.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd /app

mkdir -p /logs/verifier

if python3 -m pytest "$SCRIPT_DIR/test_state.py" -v --tb=short; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
