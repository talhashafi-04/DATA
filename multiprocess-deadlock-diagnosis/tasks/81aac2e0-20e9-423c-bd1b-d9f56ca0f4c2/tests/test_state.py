"""Grader: tests solution_pipeline.py written by the agent."""

import ast
import importlib.util
import sys

import pytest

SOLUTION = "/app/solution_pipeline.py"
TIMEOUT_S = 5  # generous; a correct solution finishes in < 0.5 s


def _load_solution():
    """Import solution_pipeline from the agent's written file."""
    spec = importlib.util.spec_from_file_location("solution_pipeline", SOLUTION)
    if spec is None:
        pytest.fail(f"{SOLUTION} not found — agent did not write the solution file")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        pytest.fail(f"Failed to import {SOLUTION}: {e}")
    return mod


def _run_batch(n: int):
    """Call solution_pipeline.run_batch(n) with a hard timeout."""
    import multiprocessing as mp

    result_q = mp.Queue()

    def _target():
        try:
            mod = _load_solution()
            result_q.put(("ok", mod.run_batch(n)))
        except Exception as exc:
            result_q.put(("err", str(exc)))

    p = mp.Process(target=_target, daemon=True)
    p.start()
    p.join(timeout=TIMEOUT_S)
    if p.is_alive():
        p.terminate()
        p.join(1)
        pytest.fail(
            f"run_batch({n}) deadlocked — did not return within {TIMEOUT_S} s"
        )
    if result_q.empty():
        pytest.fail(f"run_batch({n}) process exited without returning a value")
    status, value = result_q.get_nowait()
    if status == "err":
        pytest.fail(f"run_batch({n}) raised: {value}")
    return value


def _expected(n: int) -> int:
    return sum(i * i for i in range(n))


# ---------------------------------------------------------------------------
# Structural checks (run first — fast failures before expensive execution)
# ---------------------------------------------------------------------------

def _get_solution_ast():
    try:
        with open(SOLUTION) as f:
            return ast.parse(f.read()), f.name
    except FileNotFoundError:
        pytest.fail(f"{SOLUTION} not found — agent did not write the solution file")


def test_solution_file_exists():
    """Agent must have created /app/solution_pipeline.py."""
    import os
    assert os.path.isfile(SOLUTION), f"{SOLUTION} does not exist"


def test_parallel_architecture_preserved():
    """solution_pipeline.py must retain JoinableQueue, mp.Process, cpu_count clamping."""
    tree, _ = _get_solution_ast()

    # PARALLEL_THRESHOLD must be a plain int literal <= 50
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "PARALLEL_THRESHOLD"
        ):
            assert isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, int
            ), "PARALLEL_THRESHOLD must be a plain integer literal"
            assert node.value.value <= 50, (
                f"PARALLEL_THRESHOLD={node.value.value} must be <= 50"
            )
            break
    else:
        raise AssertionError("PARALLEL_THRESHOLD not found in solution_pipeline.py")

    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "JoinableQueue"
        for n in ast.walk(tree)
    ), "JoinableQueue must be used in solution_pipeline.py"

    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "Process"
        for n in ast.walk(tree)
    ), "mp.Process must be used in solution_pipeline.py"

    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "cpu_count"
        for n in ast.walk(tree)
    ), "mp.cpu_count() must be called in solution_pipeline.py"

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in ("_MIN_WORKERS", "_MAX_WORKERS")
        ):
            assert isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, int
            ), f"{node.targets[0].id} must be a plain integer literal"


def test_stdlib_only():
    """No third-party imports allowed."""
    tree, path = _get_solution_ast()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in sys.stdlib_module_names, (
                    f"non-stdlib import in {path}: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            assert top in sys.stdlib_module_names, (
                f"non-stdlib import in {path}: from {node.module}"
            )


def test_no_sleep_hack():
    """time.sleep must not appear in solution_pipeline.py."""
    tree, path = _get_solution_ast()
    sleep_aliases: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "time":
            for alias in node.names:
                if alias.name == "sleep":
                    sleep_aliases.add(alias.asname if alias.asname else "sleep")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "sleep"
            and isinstance(func.value, ast.Name)
            and func.value.id == "time"
        ):
            raise AssertionError(f"time.sleep() in {path} — not permitted")
        if isinstance(func, ast.Name) and func.id in sleep_aliases:
            raise AssertionError(f"{func.id}() is time.sleep in {path} — not permitted")


# ---------------------------------------------------------------------------
# Correctness: sequential path
# ---------------------------------------------------------------------------

def test_zero_batch():
    assert _run_batch(0) == 0


def test_small_batch_correct():
    assert _run_batch(10) == _expected(10)


def test_small_batch_2():
    assert _run_batch(50) == _expected(50)


# ---------------------------------------------------------------------------
# Correctness: parallel path (n > PARALLEL_THRESHOLD=50)
# Dead solutions exit fast because the grader runs in a separate process
# with a TIMEOUT_S hard join — no terminal blocking possible.
# ---------------------------------------------------------------------------

def test_boundary_batch():
    """batch=51 just crosses into the parallel path."""
    assert _run_batch(51) == _expected(51)


def test_large_batch():
    assert _run_batch(500) == _expected(500)


def test_extra_large_batch():
    assert _run_batch(2000) == _expected(2000)


def test_large_batch_2():
    assert _run_batch(1000) == _expected(1000)


def test_run_batch_callable():
    """solution_pipeline must expose run_batch as a callable."""
    mod = _load_solution()
    assert callable(getattr(mod, "run_batch", None)), "run_batch not found/callable"


def test_parallel_threshold_routes_correctly():
    """Values at exactly PARALLEL_THRESHOLD use sequential; above use parallel."""
    mod = _load_solution()
    pt = getattr(mod, "PARALLEL_THRESHOLD", None)
    assert pt is not None, "PARALLEL_THRESHOLD not found"
    # At threshold: must still be correct
    assert _run_batch(pt) == _expected(pt)
    # Just above: parallel path must also be correct
    assert _run_batch(pt + 1) == _expected(pt + 1)


def test_pool_size_clamped():
    """POOL_SIZE must be between _MIN_WORKERS and _MAX_WORKERS inclusive."""
    mod = _load_solution()
    pool = getattr(mod, "POOL_SIZE", None)
    lo = getattr(mod, "_MIN_WORKERS", None)
    hi = getattr(mod, "_MAX_WORKERS", None)
    assert pool is not None, "POOL_SIZE not found"
    assert lo is not None, "_MIN_WORKERS not found"
    assert hi is not None, "_MAX_WORKERS not found"
    assert lo <= pool <= hi, f"POOL_SIZE={pool} not in [{lo}, {hi}]"
