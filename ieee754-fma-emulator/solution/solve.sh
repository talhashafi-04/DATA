#!/usr/bin/env bash
set -euo pipefail

solution_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

make -C /app clean all >/tmp/fma_build_before.log 2>&1 || true
initial_runner_output="$(/app/fma_runner /app/data/cases.json 2>/tmp/fma_runner_before.err || true)"
initial_lab_output="$(python3 /app/task-deps/tools/case_lab.py /app/data/cases.json 2>/tmp/fma_lab_before.err || true)"
failing_product_class="$(printf '%s\n' "$initial_lab_output" | awk '/failure groups/{flag=1; next} flag && NF >= 2 {gsub(":", "", $1); print $1 " product"; exit}')"
if [ -z "$failing_product_class" ]; then
    failing_product_class="$(printf '%s\n' "$initial_runner_output" | awk '$4 == "fail" {print "finite product"; found=1; exit} END {if (!found) print "precision-sensitive product"}')"
fi
regression_probe="$(printf '%s\n' "$initial_runner_output" | awk '$4 == "fail" {print $1; exit}')"
if [ -z "$regression_probe" ]; then
    regression_probe="local fused-operation probe"
fi

perl -0pi -e 's{\nstatic long double magnitude_ld\(long double value\) \{.*?\nstatic int legacy_tininess_gate\(long double value\) \{.*?\n\}\n}{}s' /app/softfma.c
perl -0pi -e 's{#include <string.h>\n}{#include <string.h>\n#include <mpfr.h>\n}s' /app/softfma.c
perl -0pi -e 's{    long double product = to_extended\(a\) \* to_extended\(b\);\n    uint64_t product_sign = abits\.sign \^ bbits\.sign;\n\n    if \(legacy_tininess_gate\(product\)\) \{\n        product = \(product_sign != 0\) \? -0\.0L : 0\.0L;\n    \}\n\n    long double result = product \+ to_extended\(c\);\n    double rounded = \(double\)result;\n    return rounded;\n}{    if (is_zero_bits(abits) \&\& is_zero_bits(cbits)) {\n        return bits_to_double(((abits.sign ^ bbits.sign) \& cbits.sign) << 63);\n    }\n    if (is_zero_bits(bbits) \&\& is_zero_bits(cbits)) {\n        return bits_to_double(((abits.sign ^ bbits.sign) \& cbits.sign) << 63);\n    }\n\n    mpfr_t ma;\n    mpfr_t mb;\n    mpfr_t mc;\n    mpfr_t mr;\n    mpfr_inits2(8192, ma, mb, mc, mr, (mpfr_ptr)0);\n    mpfr_set_d(ma, a, MPFR_RNDN);\n    mpfr_set_d(mb, b, MPFR_RNDN);\n    mpfr_set_d(mc, c, MPFR_RNDN);\n    mpfr_mul(mr, ma, mb, MPFR_RNDN);\n    mpfr_add(mr, mr, mc, MPFR_RNDN);\n    double rounded = mpfr_get_d(mr, MPFR_RNDN);\n    mpfr_clears(ma, mb, mc, mr, (mpfr_ptr)0);\n    return rounded;\n}s' /app/softfma.c
cat "$solution_dir/softfma_rounded_append.c" >> /app/softfma.c

make -C /app clean all

mkdir -p /app/reports
{
    printf 'failing_product_class=%s\n' "visible $failing_product_class loses fused low residue before final addition"
    printf 'rounding_boundary=%s\n' 'round once at final binary64 conversion, including final subnormal results'
    printf 'precision_strategy=%s\n' 'carry the product and addend with arbitrary precision before final conversion'
    printf 'regression_probe=%s\n' "hex probe $regression_probe reproduces the pre-fix failure"
    printf 'changed_file=%s\n' '/app/softfma.c'
} > /app/reports/fma_triage.txt

cp "$solution_dir/fma_replay_builder.py" /app/reports/fma_replay_builder.py
python3 /app/reports/fma_replay_builder.py /tmp/fma_replay_builder_reference.json
python3 "$solution_dir/write_fma_replay_cases.py" /app/reports/fma_replay_cases.json
