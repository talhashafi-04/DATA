#!/usr/bin/env bash
# Reference solution: fix all three bugs in pipeline.py.
#
# Bug A — _PIPELINE_CTRL.wait() in _compute_worker:
#   Workers block before processing any item because the Event is never set.
#   task_q.join() hangs immediately.
#   Fix: remove the _PIPELINE_CTRL.wait() call (and the unused Event).
#
# Bug B — result_q = mp.Queue(maxsize=POOL_SIZE - 1):
#   Only POOL_SIZE-1 slots available for POOL_SIZE workers.
#   The last worker to reach its sentinel blocks on result_q.put() before
#   calling task_q.task_done(), so task_q.join() never returns.
#   Fix: mp.Queue() (unbounded) or maxsize=POOL_SIZE.
#
# Bug C — range(POOL_SIZE - 1) sentinels:
#   One too few shutdown tokens means one worker is left blocked on
#   task_q.get() forever; the drain loop (result_q.get() * POOL_SIZE)
#   then also hangs waiting for that worker's subtotal.
#   Fix: range(POOL_SIZE).

cat > /app/pipeline.py << 'PYEOF'
#!/usr/bin/env python3
"""Parallel aggregation pipeline."""

import multiprocessing as mp

PARALLEL_THRESHOLD = 50
_MIN_WORKERS = 2
_MAX_WORKERS = 5
POOL_SIZE = max(_MIN_WORKERS, min(_MAX_WORKERS, mp.cpu_count() or _MIN_WORKERS))
_STOP = None


def _compute_worker(task_q, result_q):
    """Worker process: consume integers from task_q; accumulate sum of squares."""
    subtotal = 0
    while True:
        item = task_q.get()
        if item is _STOP:
            result_q.put(subtotal)
            task_q.task_done()
            return
        subtotal += item * item
        task_q.task_done()


def run_parallel(n: int) -> int:
    """Distribute sum-of-squares across POOL_SIZE worker processes."""
    task_q = mp.JoinableQueue()
    result_q = mp.Queue()

    workers = [
        mp.Process(target=_compute_worker, args=(task_q, result_q), daemon=True)
        for _ in range(POOL_SIZE)
    ]
    for w in workers:
        w.start()

    for i in range(n):
        task_q.put(i)
    for _ in range(POOL_SIZE):
        task_q.put(_STOP)

    task_q.join()

    total = sum(result_q.get() for _ in range(POOL_SIZE))
    for w in workers:
        w.join()
    return total


def run_sequential(n: int) -> int:
    """Single-threaded fallback: sum(i*i for i in range(n))."""
    return sum(i * i for i in range(n))


def run_batch(n: int) -> int:
    """Route to the appropriate computation strategy."""
    if n <= PARALLEL_THRESHOLD:
        return run_sequential(n)
    return run_parallel(n)
PYEOF
