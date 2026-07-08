Start the investigation from the generated case corpus and treat the first failing line as one symptom of the complete failure mode.

The runner reports exact hexadecimal floats so that decimal formatting keeps one-bit errors visible. Use `./fma_runner /app/data/cases.json` to get the raw failures, then use `python3 /app/task-deps/tools/case_lab.py /app/data/cases.json` to group inputs by exponent class and product class. The helper prints ranges rather than a fix.

The implementation is expected to round only once, after the product and addend have both contributed to the exact mathematical result. Several categories in the corpus are intentionally boring; they are there to keep nearby special-case handling from regressing while you isolate the failing transition.

Construct a few targeted probes that isolate where a rounded multiply-then-add could diverge from a fused result before trusting a broad rewrite.
