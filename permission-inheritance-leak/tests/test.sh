#!/usr/bin/env bash
set -u

mkdir -p /logs/verifier
echo "0.0" > /logs/verifier/reward.txt
cat > /logs/verifier/ctrf.json <<'JSON'
{"results":{"tool":{"name":"python-unittest"},"summary":{"tests":0,"passed":0,"failed":1,"skipped":0},"tests":[{"name":"test_runner","status":"failed","duration":0,"message":"test runner did not complete"}]}}
JSON
export PYTHONDONTWRITEBYTECODE=1

if timeout 180s python3 /tests/test_state.py
then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi
