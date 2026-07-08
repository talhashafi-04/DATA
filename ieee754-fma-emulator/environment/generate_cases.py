#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import struct

import mpmath as mp

mp.mp.prec = 256


def bits_to_float(bits: int) -> float:
    return struct.unpack(">d", bits.to_bytes(8, "big"))[0]


def hex_float(text: str) -> float:
    return float.fromhex(text)


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


def fused_expected(a: float, b: float, c: float) -> float:
    if math.isnan(a) or math.isnan(b) or math.isnan(c):
        return math.nan
    if (math.isinf(a) and b == 0.0) or (math.isinf(b) and a == 0.0):
        return math.nan
    product_inf = math.isinf(a) or math.isinf(b)
    if product_inf:
        product_sign = math.copysign(1.0, a) * math.copysign(1.0, b)
        if math.isinf(c) and math.copysign(1.0, c) != product_sign:
            return math.nan
        return math.copysign(math.inf, product_sign)
    if math.isinf(c):
        return c

    product = mp_from_float(a) * mp_from_float(b)
    result = product + mp_from_float(c)
    if result == 0:
        if product == 0 and c == 0.0:
            product_negative = signbit(a) ^ signbit(b)
            return -0.0 if product_negative and signbit(c) else 0.0
        return 0.0
    return round_binary64(result)


def row(a: float, b: float, c: float) -> dict[str, str]:
    return {
        "a": a.hex(),
        "b": b.hex(),
        "c": c.hex(),
        "expected": fused_expected(a, b, c).hex(),
    }


def add_unique(cases: list[dict[str, str]], seen: set[tuple[str, str, str]], a: float, b: float, c: float) -> None:
    item = row(a, b, c)
    key = (item["a"], item["b"], item["c"])
    if key not in seen:
        seen.add(key)
        cases.append(item)


def build_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    # 0..59: products that are nonzero but below DBL_MIN before c is added.
    subnormal_products = [
        (bits_to_float(0x0010000000000000 + i * 0x1000000000000), bits_to_float(0x3CB0000000000000 + i), bits_to_float(0x0000000000000100 + i))
        for i in range(20)
    ]
    subnormal_products += [
        (bits_to_float(0x0008000000000000 + i * 0x100000000000), hex_float("0x1.0p-512"), -bits_to_float(0x0000000000000001 + i))
        for i in range(20)
    ]
    subnormal_products += [
        (-bits_to_float(0x0010000000000000 + i * 0x800000000000), bits_to_float(0x3CB8000000000000 + i), bits_to_float(0x0000000000000200 + i))
        for i in range(20)
    ]
    for triple in subnormal_products:
        add_unique(cases, seen, *triple)

    # 60..99: ordinary normal finite inputs.
    for i in range(40):
        a = math.ldexp(((-1.0) ** (i & 1)) * (1.125 + (i % 7) / 64.0), (i % 19) - 9)
        b = math.ldexp(0.875 + (i % 11) / 32.0, (i % 17) - 8)
        c = math.ldexp(((-1.0) ** ((i >> 1) & 1)) * (0.5 + (i % 5) / 16.0), (i % 13) - 7)
        add_unique(cases, seen, a, b, c)

    # 100..119: NaN propagation, including bit patterns that encode quiet and signaling NaNs.
    qnan = bits_to_float(0x7FF8000000001234)
    snan = bits_to_float(0x7FF0000000005678)
    for i in range(20):
        variant = float(i + 1)
        nan_triples = [
            (qnan, 2.0 + variant, 3.0),
            (2.0, qnan, 3.0 + variant),
            (2.0 + variant, 3.0, qnan),
            (snan, -2.0 - variant, 3.0),
            (2.0, snan, -3.0 - variant),
            (-2.0 - variant, 3.0, snan),
            (math.inf, 0.0, variant),
            (0.0, -math.inf, variant),
            (math.inf, 2.0 + variant, -math.inf),
            (-math.inf, 2.0 + variant, math.inf),
        ]
        add_unique(cases, seen, *nan_triples[i % len(nan_triples)])

    # 120..139: signed zero and exact-zero outcomes.
    for i in range(20):
        scale = 1.0 + i
        zero_triples = [
            (0.0, 3.0 + scale, 0.0),
            (-0.0, 3.0 + scale, 0.0),
            (0.0, -3.0 - scale, 0.0),
            (-0.0, -3.0 - scale, -0.0),
            (1.0 + scale, -0.0, 0.0),
            (-1.0 - scale, 0.0, -0.0),
            (bits_to_float(0x0000000000000001 + i), -0.5, 0.0),
            (-bits_to_float(0x0000000000000001 + i), 0.5, -0.0),
            (2.0 + scale, 0.0, -0.0),
            (-2.0 - scale, -0.0, 0.0),
        ]
        add_unique(cases, seen, *zero_triples[i % len(zero_triples)])

    # 140..159: products that overflow and infinity arithmetic.
    for i in range(20):
        scale = float(i + 1)
        infinity_triples = [
            (hex_float("0x1.0p1023"), 4.0 + scale, -hex_float("0x1.0p1023")),
            (-hex_float("0x1.0p1023"), 4.0 + scale, hex_float("0x1.0p1023")),
            (math.inf, 1.5 + scale, 2.0),
            (-math.inf, 1.5 + scale, -2.0),
            (hex_float("0x1.fffffffffffffp1023"), 2.0 + scale, -math.inf),
            (-hex_float("0x1.fffffffffffffp1023"), 2.0 + scale, math.inf),
            (math.inf, -2.0 - scale, math.inf),
            (-math.inf, -2.0 - scale, -math.inf),
            (hex_float("0x1.8p700"), hex_float("0x1.8p400"), -scale),
            (-hex_float("0x1.8p700"), hex_float("0x1.8p400"), scale),
        ]
        add_unique(cases, seen, *infinity_triples[i % len(infinity_triples)])

    # 160..179: exact cancellation with large and small magnitudes.
    for i in range(20):
        a = math.ldexp(1.0 + (i % 8) / 16.0, (i % 31) - 15)
        b = math.ldexp(1.0 + (i % 5) / 8.0, (i % 29) - 14)
        product = round_binary64(mp_from_float(a) * mp_from_float(b))
        add_unique(cases, seen, a, b, -product)

    # 180..199: round-to-nearest-even tie probes near one ulp boundaries.
    for i in range(20):
        base = bits_to_float(0x3FF0000000000000 + i)
        half_ulp = math.ldexp(1.0, -53)
        tweak = math.ldexp(1.0, -1100 + i)
        add_unique(cases, seen, base, 1.0, half_ulp if i % 2 == 0 else -half_ulp + tweak)

    # 200..255: cancellation residues spread across exponent bands.
    for i in range(56):
        exponent = (i % 41) - 20
        left = math.ldexp(1.0 + math.ldexp(7.0 + (i % 11), -30), exponent)
        right = 1.0 - math.ldexp(5.0 + (i % 13), -31)
        rounded_product = float(left * right)
        residue = math.ldexp(1.0 + (i % 5), exponent - 128 - (i % 7))
        add_unique(cases, seen, left if i % 2 else -left, right, -rounded_product + residue)

    # 256..315: directed overflow and underflow border cases.
    for i in range(60):
        if i % 2 == 0:
            a = hex_float("0x1.fffffffffffffp1023")
            b = 1.0 + math.ldexp(1.0 + (i % 9), -52)
            c = -math.ldexp(1.0 + (i % 17), 965 + (i % 5))
            add_unique(cases, seen, a if i % 4 else -a, b, c if i % 4 else -c)
        else:
            a = bits_to_float(0x0010000000000000 + ((i * 0x13579) & 0x000FFFFFFFFFFFFF))
            b = math.ldexp(1.0 + (i % 7) / 32.0, -53 - (i % 4))
            c = bits_to_float(0x0000000000000001 + (i % 29))
            add_unique(cases, seen, a if i % 5 else -a, b, c)

    # 316..359: products where a separately rounded multiply hides the final fused residue.
    for i in range(44):
        left = 1.0 + math.ldexp(19.0 + (i % 17), -31)
        right = 1.0 - math.ldexp(23.0 + (i % 19), -32)
        rounded_product = float(left * right)
        residue = math.ldexp(1.0 + (i % 7), -145 - (i % 11))
        add_unique(cases, seen, left, right, -rounded_product - residue)

    # 360..415: exact-zero outcomes after nonzero finite products.
    for i in range(56):
        exponent = (i % 49) - 24
        a = math.ldexp(1.0 + (i % 13) / 32.0, exponent)
        b = math.ldexp(1.0 + (i % 11) / 64.0, -exponent + (i % 5) - 2)
        exact_product = round_binary64(mp_from_float(a) * mp_from_float(b))
        sign = -1.0 if i % 2 else 1.0
        add_unique(cases, seen, sign * a, b, -sign * exact_product)

    # 416..471: final results around the smallest subnormal and DBL_MIN boundary.
    for i in range(56):
        normal_edge = bits_to_float(0x0010000000000000 + ((i * 0x2468B) & 0x000FFFFFFFFFFFFF))
        scale = math.ldexp(1.0 + (i % 15) / 64.0, -53 - (i % 4))
        addend = bits_to_float(0x0000000000000001 + (i % 53))
        signed_edge = -normal_edge if i % 6 in (0, 1) else normal_edge
        signed_addend = -addend if i % 5 == 0 else addend
        add_unique(cases, seen, signed_edge, scale, signed_addend)

    # 472..527: overflow cases where the addend rescues or preserves the boundary.
    for i in range(56):
        a = hex_float("0x1.fffffffffffffp1023")
        b = 1.0 + math.ldexp(1.0 + (i % 15), -52)
        c = -math.ldexp(1.0 + (i % 23), 964 + (i % 7))
        sign = -1.0 if i % 2 else 1.0
        add_unique(cases, seen, sign * a, b, sign * c)

    # 528..599: mixed special values, signed zero products, and finite controls.
    qnan2 = bits_to_float(0x7FF800000000BEEF)
    snan2 = bits_to_float(0x7FF000000000C0DE)
    for i in range(72):
        variant = float(i + 33)
        specials = [
            (qnan2, -variant, variant / 3.0),
            (variant, snan2, -variant / 5.0),
            (math.inf, -0.0, variant),
            (-0.0, -math.inf, -variant),
            (math.inf, -variant, -math.inf),
            (-math.inf, -variant, math.inf),
            (0.0, -variant, -0.0),
            (-0.0, -variant, 0.0),
            (math.ldexp(1.0 + (i % 7) / 16.0, (i % 37) - 18), -1.0, math.ldexp(1.0, (i % 31) - 15)),
        ]
        add_unique(cases, seen, *specials[i % len(specials)])

    filler = 0
    while len(cases) < 600:
        a = math.ldexp(1.0 + (filler % 17) / 31.0, (filler % 43) - 21)
        b = math.ldexp(-1.0 - (filler % 13) / 37.0, (filler % 39) - 19)
        c = math.ldexp(0.25 + (filler % 11) / 29.0, (filler % 35) - 17)
        add_unique(cases, seen, a, b, c)
        filler += 1

    if len(cases) != 600:
        raise RuntimeError(f"expected 600 cases, generated {len(cases)}")
    return cases


def main() -> None:
    os.makedirs("/app/data", exist_ok=True)
    with open("/app/data/cases.json", "w", encoding="utf-8") as handle:
        json.dump(build_cases(), handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
