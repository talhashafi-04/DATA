#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


def bits(value: float) -> int:
    return struct.unpack(">Q", struct.pack(">d", value))[0]


def cls(value: float) -> str:
    raw = bits(value)
    exp = (raw >> 52) & 0x7FF
    frac = raw & 0x000FFFFFFFFFFFFF
    if exp == 0x7FF:
        return "nan" if frac else "inf"
    if exp == 0:
        return "zero" if frac == 0 else "subnormal"
    return "normal"


def product_class(a_text: str, b_text: str) -> str:
    a = float.fromhex(a_text)
    b = float.fromhex(b_text)
    if math.isnan(a) or math.isnan(b):
        return "nan"
    if (math.isinf(a) and b == 0.0) or (math.isinf(b) and a == 0.0):
        return "invalid"
    if math.isinf(a) or math.isinf(b):
        return "inf"
    product = a * b
    return cls(product)


def run_binary(path: Path) -> list[str]:
    result = subprocess.run(
        ["/app/fma_runner", str(path)],
        cwd="/app",
        text=True,
        capture_output=True,
        check=False,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: case_lab.py /app/data/cases.json", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    cases = json.loads(path.read_text(encoding="utf-8"))
    lines = run_binary(path)
    status_by_index = {}
    for index, line in enumerate(lines):
        fields = line.split()
        if len(fields) == 4:
            status_by_index[index] = fields[3]

    product_counts: Counter[str] = Counter()
    failure_groups: defaultdict[str, list[int]] = defaultdict(list)
    for index, case in enumerate(cases):
        pcls = product_class(case["a"], case["b"])
        product_counts[pcls] += 1
        if status_by_index.get(index) == "fail":
            failure_groups[pcls].append(index)

    print("product-class counts")
    for name, count in sorted(product_counts.items()):
        print(f"  {name}: {count}")
    print("failure groups")
    for name, indexes in sorted(failure_groups.items()):
        first = indexes[:8]
        suffix = "" if len(indexes) <= len(first) else " ..."
        print(f"  {name}: {len(indexes)} rows {first}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
