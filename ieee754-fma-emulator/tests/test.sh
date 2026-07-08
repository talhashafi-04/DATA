#!/usr/bin/env bash
set -u

LOGROOT=/logs/verifier
CTRF="$LOGROOT/ctrf.json"

emit_reward() {
    local score="$1"
    mkdir -p "$LOGROOT"
    printf '%s\n' "$score" >"$LOGROOT/reward.txt"
    printf '{"reward": %s}\n' "$score" >"$LOGROOT/reward.json"
}

mkdir -p "$LOGROOT"

if python3 -m pytest -p no:cacheprovider --ctrf "$CTRF" /tests/test_state.py -v --tb=short -rA; then
    emit_reward 1
    exit 0
else
    emit_reward 0
    exit 1
fi
