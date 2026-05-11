#!/usr/bin/env python3
"""Batch worker: prints sum(i*i for i in range(batch_size)) to stdout.

Entry point only.  All computation logic lives in pipeline.py.
"""

import sys

from pipeline import run_batch


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <batch_size>", file=sys.stderr)
        sys.exit(1)
    try:
        n = int(sys.argv[1])
    except ValueError:
        print("Error: batch_size must be an integer.", file=sys.stderr)
        sys.exit(1)
    if n < 0:
        print("Error: batch_size must be non-negative.", file=sys.stderr)
        sys.exit(1)

    print(run_batch(n))


if __name__ == "__main__":
    main()
