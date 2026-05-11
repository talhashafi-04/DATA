"""Tests for multiprocess-deadlock-diagnosis."""

import ast
import subprocess
import sys

import pytest

SCRIPT = "/app/batch_worker.py"
PIPELINE = "/app/pipeline.py"
PYTHON = sys.executable
# Correct solutions finish in well under 1 s even on a single-CPU container.
# 8 s is generous; it eliminates 100 s+ stuck-process tails from wrong solutions.
TIMEOUT = 8


def _run(*args, timeout=TIMEOUT):
    """Run the script with the given args; fail immediately if it deadlocks."""
    try:
        return subprocess.run(
            [PYTHON, SCRIPT, *[str(a) for a in args]],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"batch_worker.py {' '.join(str(a) for a in args)!r} "
            f"deadlocked — did not exit within {timeout} s (Req 1)"
        )


def _expected(n: int) -> int:
    """Closed-form sum of squares: n*(n-1)*(2n-1)//6."""
    return n * (n - 1) * (2 * n - 1) // 6 if n else 0


# ---------------------------------------------------------------------------
# Req 1 + Req 5: correct result and exit 0 for small (sequential) inputs
# ---------------------------------------------------------------------------

def test_small_batch_exits_zero():
    """Req 5: a valid small-batch invocation must terminate with exit code 0."""
    r = _run(10)
    assert r.returncode == 0, f"expected exit 0, got {r.returncode}; stderr: {r.stderr}"


def test_small_batch_correct_result():
    """Req 1: small batch must print sum(i*i for i in range(10)) = 285."""
    r = _run(10)
    assert r.stdout.strip() == str(_expected(10))


def test_zero_batch_exits_zero():
    """Req 5: batch_size=0 is a valid non-negative integer and must exit 0."""
    assert _run(0).returncode == 0


def test_zero_batch_correct_result():
    """Req 1: sum(i*i for i in range(0)) is 0; script must print exactly '0'."""
    assert _run(0).stdout.strip() == "0"


# ---------------------------------------------------------------------------
# Req 1: batch just above the parallel threshold exercises the parallel path
# ---------------------------------------------------------------------------

def test_boundary_batch():
    """Req 1: batch=51 (just above PARALLEL_THRESHOLD=50) must complete and be correct.

    A single subprocess call asserts both exit-0 and the correct integer output so
    a deadlocked process contributes exactly one 8 s wait rather than two.  The buggy
    pipeline has multiple interacting concurrency defects in pipeline.py that prevent
    the parallel path from ever completing; all must be fixed.
    """
    r = _run(51, timeout=TIMEOUT)
    assert r.returncode == 0, f"expected exit 0; stderr: {r.stderr}"
    assert r.stdout.strip() == str(_expected(51)), (
        f"expected {_expected(51)}, got {r.stdout.strip()!r}"
    )


# ---------------------------------------------------------------------------
# Req 1: large batch (parallel path) must complete and produce correct output
# ---------------------------------------------------------------------------

def test_large_batch():
    """Req 1: batch=200 must complete and print the correct sum.

    A single subprocess call asserts both exit-0 and numeric accuracy, capping
    hang time at one TIMEOUT per size.  Multiple interacting bugs in pipeline.py
    must all be identified and corrected; fixing only some will still produce a hang.
    """
    r = _run(200, timeout=TIMEOUT)
    assert r.returncode == 0, f"expected exit 0, got {r.returncode}; stderr: {r.stderr}"
    assert r.stdout.strip() == str(_expected(200)), (
        f"expected {_expected(200)}, got {r.stdout.strip()!r}"
    )


def test_extra_large_batch():
    """Req 1: batch=500 is well above the parallel threshold and must complete correctly."""
    r = _run(500, timeout=TIMEOUT)
    assert r.returncode == 0, f"expected exit 0; stderr: {r.stderr}"
    assert r.stdout.strip() == str(_expected(500)), (
        f"expected {_expected(500)}, got {r.stdout.strip()!r}"
    )


# ---------------------------------------------------------------------------
# Req 2: parallel architecture must be preserved (checks pipeline.py via AST)
# ---------------------------------------------------------------------------

def test_parallel_architecture_preserved():
    """Req 2: pipeline.py must retain JoinableQueue, mp.Process, mp.cpu_count(),
    _MIN_WORKERS, _MAX_WORKERS; PARALLEL_THRESHOLD must be an integer literal <= 50.

    AST-level checks prevent:
      (a) raising PARALLEL_THRESHOLD to bypass the parallel path for tested sizes (>= 51)
      (b) removing JoinableQueue or mp.Process
      (c) removing the cpu_count()-based pool sizing or the _MIN/_MAX_WORKERS clamp
    """
    with open(PIPELINE) as f:
        source = f.read()
    tree = ast.parse(source)

    # Guard (a): PARALLEL_THRESHOLD <= 50
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
                f"PARALLEL_THRESHOLD={node.value.value} bypasses the parallel path "
                "for all tested batch sizes (>= 51)"
            )
            break
    else:
        raise AssertionError("PARALLEL_THRESHOLD constant not found in pipeline.py")

    # Guard (b): JoinableQueue must be instantiated
    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "JoinableQueue"
        for n in ast.walk(tree)
    ), "JoinableQueue must be instantiated in pipeline.py"

    # Guard (b): mp.Process must be used to spawn workers
    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "Process"
        for n in ast.walk(tree)
    ), "mp.Process must be used to spawn worker processes in pipeline.py"

    # Guard (c): mp.cpu_count() must be called
    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "cpu_count"
        for n in ast.walk(tree)
    ), "mp.cpu_count() must be called to derive POOL_SIZE in pipeline.py"

    # Guard (c): _MIN_WORKERS must be an integer literal
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_MIN_WORKERS"
        ):
            assert isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, int
            ), "_MIN_WORKERS must be a plain integer literal"
            break
    else:
        raise AssertionError("_MIN_WORKERS constant not found in pipeline.py")

    # Guard (c): _MAX_WORKERS must be an integer literal
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_MAX_WORKERS"
        ):
            assert isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, int
            ), "_MAX_WORKERS must be a plain integer literal"
            break
    else:
        raise AssertionError("_MAX_WORKERS constant not found in pipeline.py")


# ---------------------------------------------------------------------------
# Req 3: standard library only (both source files)
# ---------------------------------------------------------------------------

def test_stdlib_only():
    """Req 3: no third-party imports in batch_worker.py or pipeline.py.

    Walks the AST of both files and checks every import against
    sys.stdlib_module_names (available since Python 3.10).
    """
    for path in ("/app/batch_worker.py", PIPELINE):
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top == "pipeline":
                        continue
                    assert top in sys.stdlib_module_names, (
                        f"non-stdlib import in {path}: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top == "pipeline":
                    continue
                assert top in sys.stdlib_module_names, (
                    f"non-stdlib import in {path}: from {node.module}"
                )


# ---------------------------------------------------------------------------
# Req 4: no timing hacks (both source files)
# ---------------------------------------------------------------------------

def test_no_sleep_hack():
    """Req 4: time.sleep must not appear in batch_worker.py or pipeline.py.

    Uses AST analysis to catch both:
      - time.sleep(...)                      (attribute call)
      - from time import sleep; sleep(...)   (direct name after import)
    This is deterministic and immune to string-splitting or comment tricks.
    """
    for path in ("/app/batch_worker.py", PIPELINE):
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)

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
                raise AssertionError(
                    f"time.sleep() detected in {path} — not permitted (Req 4)"
                )
            if isinstance(func, ast.Name) and func.id in sleep_aliases:
                raise AssertionError(
                    f"{func.id}() is time.sleep in {path} — not permitted (Req 4)"
                )


# ---------------------------------------------------------------------------
# Req 5: non-zero exit and stderr message on every invalid invocation form
# ---------------------------------------------------------------------------

def test_no_args_nonzero_exit():
    """Req 5: invoking with no arguments must exit non-zero with an error on stderr."""
    r = subprocess.run([PYTHON, SCRIPT], capture_output=True, text=True, timeout=TIMEOUT)
    assert r.returncode != 0
    assert r.stderr.strip(), "expected a non-empty error message on stderr"


def test_non_integer_arg_nonzero_exit():
    """Req 5: a non-integer argument must cause a non-zero exit with a stderr message."""
    r = _run("abc")
    assert r.returncode != 0
    assert r.stderr.strip(), "expected a non-empty error message on stderr"


def test_negative_arg_nonzero_exit():
    """Req 5: a negative batch_size must exit non-zero with a stderr message."""
    r = _run(-1)
    assert r.returncode != 0
    assert r.stderr.strip(), "expected a non-empty error message on stderr"


def test_too_many_args_nonzero_exit():
    """Req 5: more than one positional argument must exit non-zero with a stderr message."""
    r = subprocess.run(
        [PYTHON, SCRIPT, "10", "20"], capture_output=True, text=True, timeout=TIMEOUT
    )
    assert r.returncode != 0
    assert r.stderr.strip(), "expected a non-empty error message on stderr"
