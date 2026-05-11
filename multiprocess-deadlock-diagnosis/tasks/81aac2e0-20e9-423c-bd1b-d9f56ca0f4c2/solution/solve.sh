#!/usr/bin/env bash
# Reference solution: write a corrected implementation to /app/solution_pipeline.py
cat > /app/solution_pipeline.py << 'PYEOF'
#!/usr/bin/env python3
"""Corrected parallel batch aggregation pipeline."""

import multiprocessing as mp


class _StopToken:
    pass


_STOP = _StopToken()

PARALLEL_THRESHOLD = 50
_MIN_WORKERS = 2
_MAX_WORKERS = 5
POOL_SIZE = max(_MIN_WORKERS, min(_MAX_WORKERS, mp.cpu_count() or _MIN_WORKERS))


def _compute_worker(task_q, result_q):
    # Fix A: removed _PIPELINE_CTRL.wait() — no gate needed
    subtotal = 0
    while True:
        item = task_q.get()
        # Fix D: isinstance() works across pickle round-trip; `is` does not
        if isinstance(item, _StopToken):
            result_q.put(subtotal)
            task_q.task_done()
            return
        subtotal += item * item
        task_q.task_done()


def run_parallel(n: int) -> int:
    task_q = mp.JoinableQueue()
    result_q = mp.Queue(maxsize=POOL_SIZE)   # Fix B: capacity = POOL_SIZE (not POOL_SIZE-1)

    workers = [
        mp.Process(target=_compute_worker, args=(task_q, result_q), daemon=True)
        for _ in range(POOL_SIZE)
    ]
    for w in workers:
        w.start()

    for i in range(n):                       # Fix E: 0..n-1 (not 1..n)
        task_q.put(i)
    for _ in range(POOL_SIZE):               # Fix C: one sentinel per worker (not POOL_SIZE-1)
        task_q.put(_STOP)

    task_q.join()

    total = sum(result_q.get() for _ in range(POOL_SIZE))
    for w in workers:
        w.join()
    return total


def run_sequential(n: int) -> int:
    return sum(i * i for i in range(n))


def run_batch(n: int) -> int:
    if n <= PARALLEL_THRESHOLD:
        return run_sequential(n)
    return run_parallel(n)
PYEOF
