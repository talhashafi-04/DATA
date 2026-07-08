The replay artifact is a small maintainer-owned probe corpus that travels with the repair.

Each label covers a different fused-arithmetic failure mode:

- `cancellation-gap` covers products that lose low terms when multiplication rounds before addition.
- `overflow-edge` covers products near the largest finite binary64 value where the addend changes final overflow behavior.
- `quad-gap` covers finite products whose final result needs more precision than compiler quad intermediates provide.
- `underflow-edge` covers tiny final results where aligned product bits affect subnormal rounding.

Build probes with the runner, then keep the final artifact in `/app/reports/fma_replay_cases.json`.
