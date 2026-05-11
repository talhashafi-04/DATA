# Parallel Pipeline — Deadlock Diagnosis

The file `/app/pipeline.py` is a parallel batch aggregation pipeline. It computes `sum(i*i for i in range(batch_size))` using a pool of worker processes for large inputs. The implementation contains **multiple bugs** that cause it to hang.

## Your task

1. **Read `/app/pipeline.py`** to understand the code.
2. **Write a fully corrected implementation to `/app/solution_pipeline.py`** — a new file you create from scratch.

Do not modify `/app/pipeline.py`. Your graded output is `/app/solution_pipeline.py`.

## What your solution must do

`solution_pipeline.py` must define `run_batch(n: int) -> int` that:
- Returns the exact integer `sum(i*i for i in range(n))` for all `n ≥ 0`
- Uses the sequential path for `n <= PARALLEL_THRESHOLD`
- Uses the parallel worker path for `n > PARALLEL_THRESHOLD`

## Architecture to preserve

Keep this structure from `pipeline.py`:
- `PARALLEL_THRESHOLD = 50` (plain integer literal, value ≤ 50)
- `POOL_SIZE` derived from `mp.cpu_count()` clamped between `_MIN_WORKERS` and `_MAX_WORKERS`
- A `JoinableQueue` for dispatching work items
- Multiple `mp.Process` workers

## Testing your solution

After writing `/app/solution_pipeline.py`, verify it:

```
timeout 5 python3 -c "import sys; sys.path.insert(0,'/app'); from solution_pipeline import run_batch; print(run_batch(10))"
timeout 5 python3 -c "import sys; sys.path.insert(0,'/app'); from solution_pipeline import run_batch; print(run_batch(200))"
```

Expected outputs: `285`, then `2646700`. If the command times out or prints nothing, the parallel path still has bugs — keep debugging.

## Requirements

1. Correct output for all non-negative `n`
2. Parallel architecture preserved (see above)
3. Standard library only — no third-party packages
4. No `time.sleep` used as a fix
