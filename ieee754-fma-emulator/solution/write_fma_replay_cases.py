from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import mpmath as mp

mp.mp.prec = 256


def mp_from_float(value: float) -> mp.mpf:
    numerator, denominator = value.as_integer_ratio()
    return mp.mpf(numerator) / mp.mpf(denominator)


def round_binary64(value: mp.mpf) -> float:
    if mp.isnan(value):
        return math.nan
    if value == mp.inf:
        return math.inf
    if value == -mp.inf:
        return -math.inf
    try:
        return float(value)
    except OverflowError:
        return math.copysign(math.inf, -1.0 if value < 0 else 1.0)


def signbit(value: float) -> bool:
    return math.copysign(1.0, value) < 0.0


def expected_hex(a_text: str, b_text: str, c_text: str) -> str:
    a = float.fromhex(a_text)
    b = float.fromhex(b_text)
    c = float.fromhex(c_text)
    if math.isnan(a) or math.isnan(b) or math.isnan(c):
        return "nan"
    if (math.isinf(a) and b == 0.0) or (math.isinf(b) and a == 0.0):
        return "nan"
    product_is_infinite = math.isinf(a) or math.isinf(b)
    if product_is_infinite:
        product_negative = signbit(a) ^ signbit(b)
        if math.isinf(c) and signbit(c) != product_negative:
            return "nan"
        return ("-" if product_negative else "") + "inf"
    if math.isinf(c):
        return c.hex()
    result = mp_from_float(a) * mp_from_float(b) + mp_from_float(c)
    if result == 0:
        return (0.0).hex()
    return round_binary64(result).hex()


def row(label: str, a: float, b: float, c: float) -> dict[str, str]:
    a_text = a.hex()
    b_text = b.hex()
    c_text = c.hex()
    return {"label": label, "a": a_text, "b": b_text, "c": c_text, "expected": expected_hex(a_text, b_text, c_text)}


def build_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for i in range(4):
        exponent = i + 1
        a = math.ldexp(1.0 + math.ldexp(11.0 + i, -30), exponent)
        b = 1.0 - math.ldexp(13.0 + i, -31)
        rounded_product = float(a * b)
        cases.append(row("cancellation-gap", a, b, -rounded_product + math.ldexp(1.0 + i, exponent - 140)))
    for i in range(4):
        a = float.fromhex("0x1.fffffffffffffp1023")
        b = 1.0 + math.ldexp(17.0 + i, -52)
        c = -math.ldexp(17.0 + i, 964)
        cases.append(row("overflow-edge", a if i % 2 else -a, b, c if i % 2 else -c))
    quad_gap_triples = [
        ("0x1.0000003000000p-3", "0x1.ffffffa000000p-1", "-0x1.0000000000000p-3"),
        ("0x1.0000003000000p-3", "0x1.ffffff2000000p-1", "-0x1.ffffff9fffffep-4"),
        ("0x1.0000003000000p-3", "0x1.fffffea000000p-1", "-0x1.ffffff1fffffcp-4"),
        ("0x1.0000003000000p-3", "0x1.fffffe2000000p-1", "-0x1.fffffe9fffffcp-4"),
    ]
    for a_text, b_text, c_text in quad_gap_triples:
        cases.append(row("quad-gap", float.fromhex(a_text), float.fromhex(b_text), float.fromhex(c_text)))
    for i in range(4):
        a = float.fromhex(f"0x1.00000000000{i + 2:x}0p-1022")
        b = math.ldexp(1.0 + i / 32.0, -54)
        c = float.fromhex(f"0x0.00000000000{i + 2:x}0p-1022")
        cases.append(row("underflow-edge", a, b, c))
    cases.sort(key=lambda item: (item["label"], item["a"]))
    return cases


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: write_fma_replay_cases.py OUTPUT_PATH", file=sys.stderr)
        return 2
    Path(sys.argv[1]).write_text(json.dumps(build_cases(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
