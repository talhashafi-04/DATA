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
    product = mp_from_float(a) * mp_from_float(b)
    result = product + mp_from_float(c)
    if result == 0:
        if product == 0 and c == 0.0:
            product_negative = signbit(a) ^ signbit(b)
            return (-0.0 if product_negative and signbit(c) else 0.0).hex()
        return (0.0).hex()
    return round_binary64(result).hex()


def row(label: str, a: float, b: float, c: float) -> dict[str, str]:
    a_text = a.hex()
    b_text = b.hex()
    c_text = c.hex()
    return {
        "label": label,
        "a": a_text,
        "b": b_text,
        "c": c_text,
        "expected": expected_hex(a_text, b_text, c_text),
    }


def build_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for i in range(4):
        exponent = i - 2
        a = math.ldexp(1.0 + math.ldexp(3.0 + i, -29), exponent)
        b = 1.0 - math.ldexp(5.0 + i, -30)
        cases.append(row("cancellation-gap", a, b, -math.ldexp(1.0, exponent)))
    for i in range(4):
        a = float.fromhex("0x1.fffffffffffffp1023")
        b = 1.0 + math.ldexp(33.0 + i, -52)
        c = -math.ldexp(33.0 + i, 952)
        cases.append(row("overflow-edge", a if i % 2 == 0 else -a, b, c if i % 2 == 0 else -c))
    quad_gap_triples = [
        ("0x1.0000002000000p-4", "0x1.ffffffc000000p-1", "-0x1.0000000000000p-4"),
        ("0x1.0000002000000p-4", "0x1.ffffff4000000p-1", "-0x1.ffffff7fffffep-5"),
        ("0x1.0000002000000p-4", "0x1.fffffec000000p-1", "-0x1.fffffeffffffep-5"),
        ("0x1.0000002000000p-4", "0x1.fffffe4000000p-1", "-0x1.fffffe7fffffcp-5"),
    ]
    for a_text, b_text, c_text in quad_gap_triples:
        cases.append(row("quad-gap", float.fromhex(a_text), float.fromhex(b_text), float.fromhex(c_text)))
    for i in range(4):
        a = float.fromhex(f"0x1.000000abc0{i + 1:x}0p-1022")
        b = math.ldexp(1.0 + i / 32.0, -55)
        c = float.fromhex(f"0x0.000000def0{i + 1:x}0p-1022")
        cases.append(row("underflow-edge", -a if i == 0 else a, b, c))
    cases.sort(key=lambda item: (item["label"], item["a"]))
    return cases


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: fma_replay_builder.py OUTPUT_PATH", file=sys.stderr)
        return 2
    Path(sys.argv[1]).write_text(json.dumps(build_cases(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
