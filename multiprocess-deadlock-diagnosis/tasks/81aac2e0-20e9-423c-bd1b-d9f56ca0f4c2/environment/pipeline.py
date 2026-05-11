#!/usr/bin/env python3
"""Parallel batch aggregation pipeline.

This file contains the reference implementation.
Read it to understand the architecture, then write your fixed version
to /app/solution_pipeline.py.
"""

import multiprocessing as mp


class _StopToken:
    pass


_STOP = _StopToken()

PARALLEL_THRESHOLD = 50
_MIN_WORKERS = 2
_MAX_WORKERS = 5
POOL_SIZE = max(_MIN_WORKERS, min(_MAX_WORKERS, mp.cpu_count() or _MIN_WORKERS))

# Gate event used to coordinate worker startup.
_PIPELINE_CTRL = mp.Event()          # Bug A: never set — workers block forever


def _compute_worker(task_q, result_q):
    _PIPELINE_CTRL.wait()            # blocks indefinitely (Bug A)
    subtotal = 0
    while True:
        item = task_q.get()
        if item is _STOP:            # Bug D: pickle round-trip breaks `is` identity
            result_q.put(subtotal)
            task_q.task_done()
            return
        subtotal += item * item
        task_q.task_done()


def run_parallel(n: int) -> int:
    task_q = mp.JoinableQueue()
    result_q = mp.Queue(maxsize=POOL_SIZE - 1)   # Bug B: one slot short, blocks put()

    workers = [
        mp.Process(target=_compute_worker, args=(task_q, result_q), daemon=True)
        for _ in range(POOL_SIZE)
    ]
    for w in workers:
        w.start()

    for i in range(1, n + 1):       # Bug E: dispatches 1..n instead of 0..n-1
        task_q.put(i)
    for _ in range(POOL_SIZE - 1):  # Bug C: one sentinel short — one worker waits forever
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
