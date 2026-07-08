"""Behavioral tests for the IEEE 754 software FMA emulator."""

from __future__ import annotations

import ctypes
import re
import json
import math
import struct
import subprocess
from collections import Counter
from fractions import Fraction
from pathlib import Path

import mpmath as mp

APP = Path("/app")
RUNNER = APP / "fma_runner"
CASE_PLAN = Path("/tests/hidden_data/case_plan.json")
REPLAY = APP / "reports" / "fma_replay_cases.json"
BUILDER = APP / "reports" / "fma_replay_builder.py"
mp.mp.prec = 256
REPLAY_LABELS = ("cancellation-gap", "overflow-edge", "quad-gap", "underflow-edge")
SUBPROCESS_TIMEOUT_SEC = 30

_CATEGORY_SIZES = {
    "subnormal_product": 60,
    "finite": 40,
    "nan_propagation": 20,
    "signed_zero": 20,
    "infinity": 20,
    "cancellation": 20,
    "tie_breaking": 20,
    "quad_precision_trap": 56,
    "overflow_underflow_boundary": 60,
    "deep_residue_trap": 44,
    "exact_zero_cancellation": 56,
    "subnormal_final_boundary": 56,
    "overflow_rescue_boundary": 56,
    "special_value_matrix": 72,
}


def _category_ranges() -> dict[str, range]:
    start = 0
    ranges: dict[str, range] = {}
    for name, size in _CATEGORY_SIZES.items():
        ranges[name] = range(start, start + size)
        start += size
    return ranges


CATEGORY_RANGES = _category_ranges()


def _signbit(value: float) -> bool:
    return math.copysign(1.0, value) < 0.0


def _mp_from_float(value: float) -> mp.mpf:
    numerator, denominator = value.as_integer_ratio()
    return mp.mpf(numerator) / mp.mpf(denominator)


def _round_binary64(value: mp.mpf) -> float:
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


def _expected_hex(a_text: str, b_text: str, c_text: str) -> str:
    a = float.fromhex(a_text)
    b = float.fromhex(b_text)
    c = float.fromhex(c_text)
    if math.isnan(a) or math.isnan(b) or math.isnan(c):
        return "nan"
    if (math.isinf(a) and b == 0.0) or (math.isinf(b) and a == 0.0):
        return "nan"
    product_is_infinite = math.isinf(a) or math.isinf(b)
    if product_is_infinite:
        product_negative = _signbit(a) ^ _signbit(b)
        if math.isinf(c) and _signbit(c) != product_negative:
            return "nan"
        return ("-" if product_negative else "") + "inf"
    if math.isinf(c):
        return c.hex()

    product = _mp_from_float(a) * _mp_from_float(b)
    result = product + _mp_from_float(c)
    if result == 0:
        if product == 0 and c == 0.0:
            product_negative = _signbit(a) ^ _signbit(b)
            return (-0.0 if product_negative and _signbit(c) else 0.0).hex()
        return (0.0).hex()
    return _round_binary64(result).hex()


def _bits_to_float(raw: int) -> float:
    return struct.unpack(">d", raw.to_bytes(8, "big"))[0]


def _hex_float(text: str) -> float:
    return float.fromhex(text)


def _case(a: float, b: float, c: float) -> dict[str, str]:
    a_text = a.hex()
    b_text = b.hex()
    c_text = c.hex()
    return {"a": a_text, "b": b_text, "c": c_text, "expected": _expected_hex(a_text, b_text, c_text)}


def _add_unique(cases: list[dict[str, str]], seen: set[tuple[str, str, str]], a: float, b: float, c: float) -> None:
    item = _case(a, b, c)
    key = (item["a"], item["b"], item["c"])
    seen.add(key)
    cases.append(item)


def _load_case_plan() -> dict[str, int]:
    plan = json.loads(CASE_PLAN.read_text(encoding="utf-8"))
    assert plan == _CATEGORY_SIZES
    return plan


def _baseline_cases() -> list[dict[str, str]]:
    _load_case_plan()
    cases = json.loads((APP / "data" / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) == sum(_CATEGORY_SIZES.values())
    assert len({(case["a"], case["b"], case["c"]) for case in cases}) == len(cases)
    for case in cases:
        assert set(case) == {"a", "b", "c", "expected"}
        assert case["expected"] == _expected_hex(case["a"], case["b"], case["c"])
    return cases


def _build_runner() -> None:
    build = subprocess.run(
        ["make", "clean", "all"],
        cwd=APP,
        text=True,
        capture_output=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    assert build.returncode == 0, build.stdout + build.stderr


def _write_cases(path: Path, cases: list[dict[str, str]]) -> None:
    path.write_text(json.dumps(cases, sort_keys=True), encoding="utf-8")


def _rounded_multiply_add_hex(case: dict[str, str]) -> str:
    a = float.fromhex(case["a"])
    b = float.fromhex(case["b"])
    c = float.fromhex(case["c"])
    result = float(float(a * b) + c)
    return "nan" if math.isnan(result) else result.hex()


def _run_runner(case_path: Path, expected_count: int) -> list[tuple[str, str, str, str]]:
    _build_runner()
    result = subprocess.run(
        [str(RUNNER), str(case_path)],
        cwd=APP,
        text=True,
        capture_output=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == expected_count, result.stdout + result.stderr
    parsed: list[tuple[str, str, str, str]] = []
    for line in lines:
        fields = line.split()
        assert len(fields) == 4, line
        parsed.append((fields[0], fields[1], fields[2], fields[3]))
    return parsed


def _assert_replay_cases_are_valid(cases: list[dict[str, str]], tmp_path: Path) -> None:
    assert len(cases) == 16
    assert cases == sorted(cases, key=lambda item: (item["label"], item["a"]))
    assert Counter(case["label"] for case in cases) == {label: 4 for label in REPLAY_LABELS}
    runner_cases: list[dict[str, str]] = []
    rounded_path_differences: Counter[str] = Counter()
    for case in cases:
        assert set(case) == {"label", "a", "b", "c", "expected"}
        for field in ("a", "b", "c"):
            value = float.fromhex(case[field])
            assert case[field] == value.hex()
        assert case["expected"] == _expected_hex(case["a"], case["b"], case["c"])
        if case["expected"] not in {"nan", "inf", "-inf"}:
            assert case["expected"] == float.fromhex(case["expected"]).hex()
        if case["label"] in {"cancellation-gap", "quad-gap"} and case["expected"] != _rounded_multiply_add_hex(case):
            rounded_path_differences[case["label"]] += 1
        if case["label"] == "overflow-edge":
            assert case["expected"] != "nan"
        if case["label"] == "underflow-edge":
            assert "p-1022" in case["expected"] or case["expected"] == "0x0.0p+0"
        runner_cases.append({key: case[key] for key in ("a", "b", "c", "expected")})
    assert rounded_path_differences["cancellation-gap"] == 4
    assert rounded_path_differences["quad-gap"] == 4
    replay_path = tmp_path / "replay_cases.json"
    _write_cases(replay_path, runner_cases)
    rows = _run_runner(replay_path, expected_count=len(runner_cases))
    failures = [row for row in rows if row[3] != "pass"]
    assert not failures, "\n".join(f"{inputs}: expected {expected}, got {actual}" for inputs, expected, actual, _ in failures)


def _assert_category_passes(category: str, tmp_path: Path) -> None:
    cases = _baseline_cases()
    case_path = tmp_path / f"{category}.json"
    _write_cases(case_path, cases)
    rows = _run_runner(case_path, expected_count=len(cases))
    failures = [rows[index] for index in CATEGORY_RANGES[category] if rows[index][3] != "pass"]
    assert not failures, "\n".join(f"{inputs}: expected {expected}, got {actual}" for inputs, expected, actual, _ in failures)


def test_subnormal_product_cases_pass(tmp_path: Path) -> None:
    """Verify fused semantics when a*b is subnormal, because this is where the product must survive until final rounding."""
    _assert_category_passes("subnormal_product", tmp_path)


def test_finite_cases_pass(tmp_path: Path) -> None:
    """Verify ordinary finite inputs still compute a single correctly rounded fused result."""
    _assert_category_passes("finite", tmp_path)


def test_nan_propagation_cases_pass(tmp_path: Path) -> None:
    """Verify quiet and signaling NaN inputs, invalid zero-times-infinity products, and infinity-minus-infinity produce NaN."""
    _assert_category_passes("nan_propagation", tmp_path)


def test_signed_zero_cases_pass(tmp_path: Path) -> None:
    """Verify exact zero results preserve the IEEE 754 sign required by zero products and zero addends."""
    _assert_category_passes("signed_zero", tmp_path)


def test_infinity_cases_pass(tmp_path: Path) -> None:
    """Verify overflowing products and infinite operands produce the required infinities or invalid-operation NaNs."""
    _assert_category_passes("infinity", tmp_path)


def test_cancellation_cases_pass(tmp_path: Path) -> None:
    """Verify exact cancellation is handled after the unrounded product is added to c."""
    _assert_category_passes("cancellation", tmp_path)


def test_round_to_nearest_even_ties_pass(tmp_path: Path) -> None:
    """Verify final rounding follows round-to-nearest-even at half-ulp boundaries."""
    _assert_category_passes("tie_breaking", tmp_path)


def test_quad_precision_trap_cases_pass(tmp_path: Path) -> None:
    """Verify cases that require more than compiler quad precision still round as one fused operation."""
    _assert_category_passes("quad_precision_trap", tmp_path)


def test_overflow_underflow_boundary_cases_pass(tmp_path: Path) -> None:
    """Verify directed overflow and underflow border cases round correctly instead of following a premature product."""
    _assert_category_passes("overflow_underflow_boundary", tmp_path)


def test_deep_residue_trap_cases_pass(tmp_path: Path) -> None:
    """Verify products where a separately rounded multiply hides a deeper fused residue."""
    _assert_category_passes("deep_residue_trap", tmp_path)


def test_exact_zero_cancellation_cases_pass(tmp_path: Path) -> None:
    """Verify exact zero results after finite cancellation are rounded from the fused result."""
    _assert_category_passes("exact_zero_cancellation", tmp_path)


def test_subnormal_final_boundary_cases_pass(tmp_path: Path) -> None:
    """Verify final results around the smallest subnormal and DBL_MIN boundary retain aligned product bits."""
    _assert_category_passes("subnormal_final_boundary", tmp_path)


def test_overflow_rescue_boundary_cases_pass(tmp_path: Path) -> None:
    """Verify near-overflow products where c changes the final finite-or-infinite decision."""
    _assert_category_passes("overflow_rescue_boundary", tmp_path)


def test_special_value_matrix_cases_pass(tmp_path: Path) -> None:
    """Verify a visible mixed matrix of NaNs, infinities, signed zero products, and finite controls."""
    _assert_category_passes("special_value_matrix", tmp_path)


def test_softfma_uses_allowed_software_precision() -> None:
    """Verify the prompt's software-emulator boundary by rejecting extended C types and fused-operation library shortcuts."""
    source = (APP / "softfma.c").read_text(encoding="utf-8")
    without_comments = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    without_strings = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', without_comments)
    assert "long double" not in without_strings
    assert "__float128" not in without_strings
    assert "_Float128" not in without_strings
    assert "quadmath" not in without_strings
    assert "__builtin_fma" not in without_strings
    assert "__builtin_fmaf" not in without_strings
    assert "__builtin_fmal" not in without_strings
    assert "mpfr_fma" not in without_strings
    assert not re.search(r"(?<!soft)\bfma[fl]?\s*\(", without_strings)
    forbidden_core_calls = (
        "fopen",
        "freopen",
        "fread",
        "fgets",
        "getline",
        "open(",
        "read(",
        "system(",
        "popen",
        "exec",
        "fork(",
        "getenv",
    )
    for token in forbidden_core_calls:
        assert token not in without_strings


def _exact_fma_fraction(a: float, b: float, c: float) -> Fraction:
    a_num, a_den = a.as_integer_ratio()
    b_num, b_den = b.as_integer_ratio()
    c_num, c_den = c.as_integer_ratio()
    product = Fraction(a_num, a_den) * Fraction(b_num, b_den)
    return product + Fraction(c_num, c_den)


def _directional_round_binary64(exact: Fraction, mode: int) -> float:
    max_finite = float.fromhex("0x1.fffffffffffffp+1023")
    try:
        nearest = float(exact)
    except OverflowError:
        if exact > 0:
            if mode in (0, 2):
                return math.inf
            return max_finite
        if mode in (0, 3):
            return -math.inf
        return -max_finite
    nearest_fraction = Fraction(*nearest.as_integer_ratio())
    if nearest_fraction == exact:
        return nearest
    if nearest_fraction > exact:
        ceiling_value = nearest
        floor_value = math.nextafter(nearest, -math.inf)
    else:
        floor_value = nearest
        ceiling_value = math.nextafter(nearest, math.inf)
    if mode == 0:
        return nearest
    if mode == 1:
        return floor_value if exact >= 0 else ceiling_value
    if mode == 2:
        return ceiling_value
    if mode == 3:
        return floor_value
    raise ValueError(f"unsupported mode {mode}")


def _build_softfma_library(tmp_path: Path) -> Path:
    lib_path = tmp_path / "libsoftfma.so"
    build = subprocess.run(
        ["gcc", "-O2", "-std=c11", "-shared", "-fPIC", str(APP / "softfma.c"), "-lmpfr", "-lgmp", "-o", str(lib_path)],
        text=True,
        capture_output=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return lib_path


def _load_softfma_rounded(tmp_path: Path):
    lib_path = _build_softfma_library(tmp_path)
    library = ctypes.CDLL(str(lib_path))
    library.softfma_rounded.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_int]
    library.softfma_rounded.restype = ctypes.c_double
    return library.softfma_rounded


def _load_softfma_functions(tmp_path: Path):
    lib_path = _build_softfma_library(tmp_path)
    library = ctypes.CDLL(str(lib_path))
    library.softfma.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
    library.softfma.restype = ctypes.c_double
    library.softfma_rounded.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_int]
    library.softfma_rounded.restype = ctypes.c_double
    return library.softfma, library.softfma_rounded


def test_softfma_rounded_matches_each_directional_mode(tmp_path: Path) -> None:
    """Verify the prompt-defined softfma_rounded ABI applies all four documented rounding modes at genuinely inexact boundaries."""
    softfma_rounded = _load_softfma_rounded(tmp_path)
    cases = [
        (1.1, 1.3, 0.7),
        (-1.1, 1.3, -0.7),
        (0.1, 0.2, 0.3),
        (-0.1, 0.2, -0.3),
        (123.456, 7.89, -10.11),
        (-123.456, 7.89, 10.11),
        (1.0000001, 0.9999999, 0.0000001),
        (-1.0000001, 0.9999999, -0.0000001),
    ]
    inexact_count = 0
    for a, b, c in cases:
        exact = _exact_fma_fraction(a, b, c)
        nearest = float(exact)
        if Fraction(*nearest.as_integer_ratio()) != exact:
            inexact_count += 1
        for mode in (0, 1, 2, 3):
            expected = _directional_round_binary64(exact, mode)
            actual = softfma_rounded(a, b, c, mode)
            assert struct.pack("<d", actual) == struct.pack("<d", expected), (a, b, c, mode, expected, actual)
    assert inexact_count >= 6


def test_softfma_rounded_handles_subnormal_directional_edges(tmp_path: Path) -> None:
    """Verify softfma_rounded applies the documented modes when the final binary64 result lands on subnormal boundaries."""
    softfma_rounded = _load_softfma_rounded(tmp_path)
    min_subnormal = float.fromhex("0x0.0000000000001p-1022")
    cases = []
    for i in range(1, 9):
        a = math.ldexp(1.0 + i / 16.0, -1022)
        b = math.ldexp(1.0 + (i % 3) / 8.0, -52 - (i % 2))
        c = min_subnormal * (i % 3 - 1)
        cases.append((a, b, c))
    for a, b, c in cases:
        exact = _exact_fma_fraction(a, b, c)
        expected_by_mode = [_directional_round_binary64(exact, mode) for mode in (0, 1, 2, 3)]
        assert len({struct.pack("<d", value) for value in expected_by_mode}) >= 2
        for mode, expected in enumerate(expected_by_mode):
            actual = softfma_rounded(a, b, c, mode)
            assert struct.pack("<d", actual) == struct.pack("<d", expected), (a.hex(), b.hex(), c.hex(), mode)


def test_softfma_rounded_handles_overflow_directional_edges(tmp_path: Path) -> None:
    """Verify softfma_rounded applies the documented modes when exact fused results cross the binary64 overflow edge."""
    softfma_rounded = _load_softfma_rounded(tmp_path)
    max_finite = float.fromhex("0x1.fffffffffffffp+1023")
    cases = [
        (max_finite, 1.0 + math.ldexp(1.0, -52), -math.ldexp(1.0, 970)),
        (max_finite, 1.0 + math.ldexp(3.0, -52), -math.ldexp(1.0, 969)),
        (-max_finite, 1.0 + math.ldexp(1.0, -52), math.ldexp(1.0, 970)),
        (-max_finite, 1.0 + math.ldexp(3.0, -52), math.ldexp(1.0, 969)),
    ]
    for a, b, c in cases:
        exact = _exact_fma_fraction(a, b, c)
        expected_by_mode = [_directional_round_binary64(exact, mode) for mode in (0, 1, 2, 3)]
        assert any(math.isinf(value) for value in expected_by_mode)
        assert any(math.isfinite(value) for value in expected_by_mode)
        for mode, expected in enumerate(expected_by_mode):
            actual = softfma_rounded(a, b, c, mode)
            assert struct.pack("<d", actual) == struct.pack("<d", expected), (a.hex(), b.hex(), c.hex(), mode)


def test_softfma_rounded_handles_mixed_finite_directional_matrix(tmp_path: Path) -> None:
    """Verify softfma_rounded applies all documented modes across a deterministic spread of finite inexact fused results."""
    softfma_rounded = _load_softfma_rounded(tmp_path)
    cases = []
    for i in range(36):
        sign = -1.0 if i % 2 else 1.0
        a = math.ldexp(sign * (1.0 + (i % 9) / 17.0), (i % 21) - 10)
        b = math.ldexp(0.75 + (i % 7) / 19.0, (i % 17) - 8)
        c = math.ldexp((-sign) * (0.5 + (i % 5) / 23.0), (i % 15) - 7)
        cases.append((a, b, c))
    for a, b, c in cases:
        exact = _exact_fma_fraction(a, b, c)
        expected_by_mode = [_directional_round_binary64(exact, mode) for mode in (0, 1, 2, 3)]
        for mode, expected in enumerate(expected_by_mode):
            actual = softfma_rounded(a, b, c, mode)
            assert struct.pack("<d", actual) == struct.pack("<d", expected), (a.hex(), b.hex(), c.hex(), mode)


def test_softfma_rounded_keeps_tiny_directed_perturbations(tmp_path: Path) -> None:
    """Verify directed modes observe finite addends that are too tiny to change round-to-nearest-even but still choose the next binary64 value."""
    softfma_rounded = _load_softfma_rounded(tmp_path)
    tiny_values = [
        float.fromhex("0x0.0000000000001p-1022"),
        float.fromhex("0x0.0000000000002p-1022"),
        float.fromhex("0x0.0000000000008p-1022"),
        float.fromhex("0x0.0000000000010p-1022"),
    ]
    cases = []
    for tiny in tiny_values:
        cases.extend(
            [
                (1.0, 1.0, tiny),
                (1.0, 1.0, -tiny),
                (-1.0, 1.0, tiny),
                (-1.0, 1.0, -tiny),
                (0.5, 1.0, tiny),
                (-0.5, 1.0, -tiny),
            ]
        )
    changed_directional_results = 0
    for a, b, c in cases:
        exact = _exact_fma_fraction(a, b, c)
        expected_by_mode = [_directional_round_binary64(exact, mode) for mode in (0, 1, 2, 3)]
        changed_directional_results += len({struct.pack("<d", value) for value in expected_by_mode}) > 1
        for mode, expected in enumerate(expected_by_mode):
            actual = softfma_rounded(a, b, c, mode)
            assert struct.pack("<d", actual) == struct.pack("<d", expected), (a.hex(), b.hex(), c.hex(), mode)
    assert changed_directional_results == len(cases)


def test_softfma_rounded_delegates_special_values_regardless_of_mode(tmp_path: Path) -> None:
    """Verify the prompt-defined softfma_rounded ABI matches softfma for NaN, infinite, and invalid zero-times-infinity inputs."""
    softfma, softfma_rounded = _load_softfma_functions(tmp_path)
    special_cases = [
        (math.nan, 2.0, 3.0),
        (math.inf, 2.0, 3.0),
        (math.inf, 0.0, 1.0),
        (-math.inf, 2.0, math.inf),
    ]
    for a, b, c in special_cases:
        baseline = softfma(a, b, c)
        for mode in (0, 1, 2, 3):
            value = softfma_rounded(a, b, c, mode)
            if math.isnan(baseline):
                assert math.isnan(value)
            else:
                assert struct.pack("<d", value) == struct.pack("<d", baseline)


def test_triage_report_identifies_the_failing_transition() -> None:
    """Verify the required diagnosis records substantive observations and changed_file records the exact edited path."""
    report = APP / "reports" / "fma_triage.txt"
    raw_text = report.read_text(encoding="utf-8")
    text = raw_text.lower()
    expected_keys = ("failing_product_class", "rounding_boundary", "precision_strategy", "regression_probe", "changed_file")
    lines: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip()
            assert key in expected_keys, key
            assert key not in lines, key
            lines[key] = value.strip()
            current_key = key
        else:
            assert current_key is not None, raw_line
            lines[current_key] = f"{lines[current_key]} {line}".strip()
    assert set(lines) == {"failing_product_class", "rounding_boundary", "precision_strategy", "regression_probe", "changed_file"}
    for key, value in lines.items():
        assert value.strip(), key
    assert lines["changed_file"].strip() == "/app/softfma.c"
    substantive_keys = ("failing_product_class", "rounding_boundary", "precision_strategy", "regression_probe")
    placeholders = {"n/a", "na", "none", "todo", "tbd", "unknown", "ok", "fixed", "see code"}
    required_terms = {
        "failing_product_class": ("product",),
        "rounding_boundary": ("round", "binary64"),
        "precision_strategy": ("precision",),
        "regression_probe": ("0x",),
    }
    for key in substantive_keys:
        value = lines[key].strip()
        assert value not in placeholders, key
        assert all(term in value for term in required_terms[key]), key


def test_replay_probe_artifact_is_replayable(tmp_path: Path) -> None:
    """Verify the required replay corpus has the prompt-defined schema, label intent from replay_artifact.md, and runner behavior."""
    cases = json.loads(REPLAY.read_text(encoding="utf-8"))
    _assert_replay_cases_are_valid(cases, tmp_path)


def test_replay_builder_generates_fresh_probe_artifact(tmp_path: Path) -> None:
    """Verify the required replay builder creates a fresh prompt-shaped corpus with the same label intent from replay_artifact.md."""
    output_path = tmp_path / "builder_replay_cases.json"
    result = subprocess.run(
        ["python3", str(BUILDER), str(output_path)],
        cwd=APP,
        text=True,
        capture_output=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    cases = json.loads(output_path.read_text(encoding="utf-8"))
    visible_cases = json.loads((APP / "data" / "cases.json").read_text(encoding="utf-8"))
    baseline_triples = {(case["a"], case["b"], case["c"]) for case in visible_cases}
    builder_triples = {(case["a"], case["b"], case["c"]) for case in cases}
    submitted_triples = {(case["a"], case["b"], case["c"]) for case in json.loads(REPLAY.read_text(encoding="utf-8"))}
    assert len(builder_triples) == len(cases)
    assert builder_triples.isdisjoint(baseline_triples)
    assert builder_triples != submitted_triples
    assert builder_triples.isdisjoint(submitted_triples)
    _assert_replay_cases_are_valid(cases, tmp_path)


def _hidden_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for i in range(96):
        mantissa = 0x0010000000000000 + ((i * 7919) & 0x000FFFFFFFFFFFFF)
        scale = 0x3CA0000000000000 + ((i * 104729) & 0x0000FFFFFFFFFFFF)
        addend = 0x0000000000000040 + i * 3
        sign = -1.0 if i % 3 == 0 else 1.0
        cases.append(_case(sign * _bits_to_float(mantissa), _bits_to_float(scale), _bits_to_float(addend)))
    for i in range(48):
        a = math.ldexp(1.0 + (i % 13) / 32.0, (i % 21) - 10)
        b = math.ldexp(-1.0 - (i % 7) / 64.0, (i % 17) - 8)
        c = math.ldexp(0.75 + (i % 5) / 16.0, (i % 19) - 9)
        cases.append(_case(a, b, c))
    for i in range(32):
        base = _bits_to_float(0x3FF0000000000100 + i * 17)
        tie = math.ldexp(1.0, -53)
        cases.append(_case(base, 1.0, tie if i % 2 == 0 else -tie))
    for i in range(96):
        left = 1.0 + math.ldexp(1.0 + (i % 5), -27)
        right = 1.0 - math.ldexp(1.0 + (i % 7), -27)
        rounded_product = float(left * right)
        c = -rounded_product
        cases.append(_case(left, right, c))
    for i in range(64):
        left = math.ldexp(1.0 + (i % 9) / 16.0, 480 + (i % 11))
        right = math.ldexp(1.0 - (i % 5) / 32.0, -530 - (i % 13))
        c = -math.ldexp(1.0 + (i % 3) / 64.0, -54 - (i % 7))
        cases.append(_case(left, right, c))
    for i in range(64):
        mantissa = 0x0008000000000000 + ((i * 6271) & 0x0007FFFFFFFFFFFF)
        scale = 0x3CB0000000000000 + ((i * 98317) & 0x00007FFFFFFFFFFF)
        addend = 0x0000000000000080 + i * 5
        sign = -1.0 if i % 5 == 2 else 1.0
        cases.append(_case(sign * _bits_to_float(mantissa), _bits_to_float(scale), -_bits_to_float(addend)))
    for i in range(48):
        left = 1.0 + math.ldexp(3.0 + (i % 11), -28)
        right = 1.0 - math.ldexp(5.0 + (i % 13), -28)
        rounded_product = float(left * right)
        residue = math.ldexp(1.0 + (i % 7), -160 - (i % 9))
        cases.append(_case(left, right, -rounded_product + residue))
    return cases


def _extreme_transition_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for i in range(128):
        high = math.ldexp(1.0 + (i % 17) / 64.0, 510 + (i % 9))
        low = math.ldexp(1.0 - (i % 11) / 128.0, -560 - (i % 7))
        c = -math.ldexp(1.0 + (i % 5) / 32.0, -55 - (i % 13))
        cases.append(_case(high if i % 2 else -high, low, c if i % 3 else -c))
    for i in range(96):
        left = 1.0 + math.ldexp(17.0 + (i % 19), -30)
        right = 1.0 - math.ldexp(11.0 + (i % 23), -31)
        rounded_product = float(left * right)
        residue = math.ldexp(1.0 + (i % 3), -130 - (i % 5))
        cases.append(_case(left, right, -rounded_product + residue))
    for i in range(80):
        a = float.fromhex("0x1.fffffffffffffp+1023")
        b = 1.0 + math.ldexp(1.0 + (i % 7), -52)
        c = -math.ldexp(1.0 + (i % 13), 966 + (i % 4))
        cases.append(_case(a if i % 2 else -a, b, c if i % 2 else -c))
    for i in range(80):
        a = _bits_to_float(0x0010000000000000 + ((i * 0x12345) & 0x000FFFFFFFFFFFFF))
        b = math.ldexp(1.0 + (i % 9) / 32.0, -53 - (i % 3))
        c = _bits_to_float(0x0000000000000001 + (i % 31))
        cases.append(_case(a if i % 4 else -a, b, c))
    for i in range(96):
        high = math.ldexp(1.0 + (i % 13) / 32.0, 490 + (i % 7))
        low = math.ldexp(1.0 - (i % 9) / 64.0, -545 - (i % 11))
        c = math.ldexp(1.0 + (i % 5) / 16.0, -53 - (i % 17))
        sign_a = -1.0 if i % 3 == 1 else 1.0
        sign_c = -1.0 if i % 7 < 3 else 1.0
        cases.append(_case(sign_a * high, low, sign_c * c))
    for i in range(64):
        left = 1.0 + math.ldexp(23.0 + (i % 29), -31)
        right = 1.0 - math.ldexp(13.0 + (i % 17), -32)
        rounded_product = float(left * right)
        residue = math.ldexp(1.0 + (i % 5), -150 - (i % 7))
        cases.append(_case(left, right, -rounded_product - residue))
    return cases


def _residue_stress_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for i in range(144):
        exponent = (i % 73) - 36
        left = math.ldexp(1.0 + math.ldexp(29.0 + (i % 31), -32), exponent)
        right = 1.0 - math.ldexp(17.0 + (i % 23), -33)
        rounded_product = float(left * right)
        residue = math.ldexp(1.0 + (i % 5), exponent - 155 - (i % 9))
        c = -rounded_product + (residue if i % 2 else -residue)
        cases.append(_case(left if i % 3 else -left, right, c))
    for i in range(96):
        mantissa = 0x0010000000000000 + ((i * 0x1F123) & 0x000FFFFFFFFFFFFF)
        scale = math.ldexp(1.0 + (i % 11) / 64.0, -54 - (i % 5))
        addend = _bits_to_float(0x0000000000000001 + (i % 47))
        cases.append(_case(_bits_to_float(mantissa) if i % 4 else -_bits_to_float(mantissa), scale, addend))
    return cases


def _subnormal_lattice_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    min_subnormal = _bits_to_float(0x0000000000000001)
    for i in range(160):
        a_bits = 0x0010000000000000 + ((i * 0x34567) & 0x000FFFFFFFFFFFFF)
        a = _bits_to_float(a_bits)
        b = math.ldexp(1.0 + (i % 17) / 64.0, -54 - (i % 5))
        c = math.ldexp(float((i % 9) - 4), -1074)
        cases.append(_case(-a if i % 7 in (0, 3) else a, b, c))
    for i in range(96):
        a = math.ldexp(1.0 + (i % 19) / 128.0, -1022)
        b = math.ldexp(1.0 + (i % 11) / 64.0, -52 - (i % 3))
        c = min_subnormal * float((i % 5) - 2)
        cases.append(_case(a if i % 4 else -a, b, c))
    return cases


def _special_value_permutation_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    qnans = [_bits_to_float(0x7FF8000000000001 + i * 0x101) for i in range(8)]
    snans = [_bits_to_float(0x7FF0000000000001 + i * 0x101) for i in range(8)]
    values = [
        math.inf,
        -math.inf,
        0.0,
        -0.0,
        _hex_float("0x1.fffffffffffffp+1023"),
        -_hex_float("0x1.fffffffffffffp+1023"),
    ]
    for i in range(96):
        nan = qnans[i % len(qnans)] if i % 2 else snans[i % len(snans)]
        finite = math.ldexp(1.0 + (i % 13) / 32.0, (i % 23) - 11)
        patterns = [
            (nan, finite, values[i % len(values)]),
            (finite, nan, -finite),
            (finite, -finite, nan),
            (math.inf, -0.0 if i % 2 else 0.0, finite),
            (-0.0 if i % 3 else 0.0, -math.inf, -finite),
            (math.inf, -finite, math.inf),
            (-math.inf, -finite, -math.inf),
            (values[i % len(values)], 0.0, -0.0),
        ]
        cases.append(_case(*patterns[i % len(patterns)]))
    return cases


def _overflow_rescue_lattice_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    max_finite = _hex_float("0x1.fffffffffffffp+1023")
    for i in range(160):
        b = 1.0 + math.ldexp(1.0 + (i % 31), -52)
        c = -math.ldexp(1.0 + (i % 37), 960 + (i % 11))
        sign = -1.0 if i % 2 else 1.0
        cases.append(_case(sign * max_finite, b, sign * c))
    for i in range(80):
        a = math.ldexp(1.0 + (i % 17) / 64.0, 600 + (i % 9))
        b = math.ldexp(1.0 + (i % 13) / 64.0, 430 + (i % 7))
        c = -math.ldexp(1.0 + (i % 19) / 32.0, 1018 + (i % 5))
        cases.append(_case(a if i % 3 else -a, b, c if i % 3 else -c))
    return cases


def test_verifier_generated_edge_vectors_pass(tmp_path: Path) -> None:
    """Verify the implementation generalizes beyond the visible JSON corpus and cannot hardcode those 600 rows."""
    hidden_path = tmp_path / "hidden_cases.json"
    cases = _hidden_cases()
    _write_cases(hidden_path, cases)
    rows = _run_runner(hidden_path, expected_count=len(cases))
    assert len(rows) == len(cases)
    failures = [row for row in rows if row[3] != "pass"]
    assert not failures, "\n".join(f"{inputs}: expected {expected}, got {actual}" for inputs, expected, actual, _ in failures)


def test_verifier_generated_residue_stress_vectors_pass(tmp_path: Path) -> None:
    """Verify prompt-covered fused residues and final subnormal transitions across a hidden deterministic matrix."""
    hidden_path = tmp_path / "residue_stress_cases.json"
    cases = _residue_stress_cases()
    _write_cases(hidden_path, cases)
    rows = _run_runner(hidden_path, expected_count=len(cases))
    assert len(rows) == len(cases)
    failures = [row for row in rows if row[3] != "pass"]
    assert not failures, "\n".join(f"{inputs}: expected {expected}, got {actual}" for inputs, expected, actual, _ in failures)


def test_verifier_generated_extreme_transition_vectors_pass(tmp_path: Path) -> None:
    """Verify the implementation handles the same prompt-covered fused gaps across wider exponent transitions and boundary residues."""
    hidden_path = tmp_path / "extreme_transition_cases.json"
    cases = _extreme_transition_cases()
    _write_cases(hidden_path, cases)
    rows = _run_runner(hidden_path, expected_count=len(cases))
    assert len(rows) == len(cases)
    failures = [row for row in rows if row[3] != "pass"]
    assert not failures, "\n".join(f"{inputs}: expected {expected}, got {actual}" for inputs, expected, actual, _ in failures)


def test_verifier_generated_subnormal_lattice_vectors_pass(tmp_path: Path) -> None:
    """Verify hidden subnormal lattices around zero, the minimum subnormal, and DBL_MIN boundaries."""
    hidden_path = tmp_path / "subnormal_lattice_cases.json"
    cases = _subnormal_lattice_cases()
    _write_cases(hidden_path, cases)
    rows = _run_runner(hidden_path, expected_count=len(cases))
    failures = [row for row in rows if row[3] != "pass"]
    assert not failures, "\n".join(f"{inputs}: expected {expected}, got {actual}" for inputs, expected, actual, _ in failures)


def test_verifier_generated_special_value_permutations_pass(tmp_path: Path) -> None:
    """Verify hidden NaN, infinity, invalid-product, and signed-zero permutations beyond the visible matrix."""
    hidden_path = tmp_path / "special_value_permutations.json"
    cases = _special_value_permutation_cases()
    _write_cases(hidden_path, cases)
    rows = _run_runner(hidden_path, expected_count=len(cases))
    failures = [row for row in rows if row[3] != "pass"]
    assert not failures, "\n".join(f"{inputs}: expected {expected}, got {actual}" for inputs, expected, actual, _ in failures)


def test_verifier_generated_overflow_rescue_lattice_pass(tmp_path: Path) -> None:
    """Verify hidden overflow-edge lattices where the addend decides between finite and infinite results."""
    hidden_path = tmp_path / "overflow_rescue_lattice.json"
    cases = _overflow_rescue_lattice_cases()
    _write_cases(hidden_path, cases)
    rows = _run_runner(hidden_path, expected_count=len(cases))
    failures = [row for row in rows if row[3] != "pass"]
    assert not failures, "\n".join(f"{inputs}: expected {expected}, got {actual}" for inputs, expected, actual, _ in failures)
