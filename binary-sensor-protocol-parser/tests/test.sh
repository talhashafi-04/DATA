#!/bin/bash

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set."
    exit 1
fi

mkdir -p /logs/verifier

bash /solution/solve.sh

python3 -m pytest /tests/test_state.py -v --tb=short

if [ $? -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
