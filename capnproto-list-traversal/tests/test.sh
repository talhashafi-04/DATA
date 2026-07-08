#!/usr/bin/env bash
set -euo pipefail

LOGROOT=/logs/verifier
CTRF="$LOGROOT/ctrf.json"

emit_reward() {
    local score="$1"
    mkdir -p "$LOGROOT"
    printf '%s\n' "$score" >"$LOGROOT/reward.txt"
}

trap 'emit_reward 0' ERR

mkdir -p "$LOGROOT"

if python3 -m pytest -p no:cacheprovider --ctrf "$CTRF" /tests/test_state.py -v --tb=short; then
    trap - ERR
    emit_reward 1
else
    emit_reward 0
    exit 1
fi
