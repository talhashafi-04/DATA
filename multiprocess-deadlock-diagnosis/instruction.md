# Batch Worker Deadlock

The batch processing application in `/app/` computes `sum(i*i for i in range(batch_size))` and prints the result. The entry point is `/app/batch_worker.py`.

Small inputs complete correctly through a sequential path. Larger inputs are routed to a parallel path that distributes work across multiple worker processes, but the program **hangs indefinitely** on those inputs and never produces output.

## Usage

```
python3 /app/batch_worker.py <batch_size>
```

`batch_size` must be a non-negative integer.

## Examples

```bash
python3 /app/batch_worker.py 10
# 285

python3 /app/batch_worker.py 200
# 2646700
```

## Requirements

1. **Fix the deadlock** so that large-batch runs complete and print the correct integer result followed by a newline.
2. **Preserve the parallel architecture**: the fix must keep `multiprocessing`, a `JoinableQueue`, and multiple spawned worker processes for large batches. The worker pool size must use `multiprocessing.cpu_count()` clamped by the `_MIN_WORKERS` and `_MAX_WORKERS` constants already defined in `pipeline.py`. `PARALLEL_THRESHOLD` must remain a plain integer literal no greater than `50`.
3. **Standard library only** — do not add third-party dependencies.
4. **No timing hacks** — do not use `time.sleep` (by any import alias) as the fix.
5. **Exit codes**: exit `0` on success; exit non-zero with an error message on stderr for invalid invocations (wrong argument count, non-integer argument, or negative batch size).
