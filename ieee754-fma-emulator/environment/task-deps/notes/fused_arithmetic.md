The emulator is a fused operation rather than a multiply followed by an add.

Useful checkpoints while debugging:

1. Classify each operand from its binary64 fields before considering arithmetic.
2. Handle invalid operations and NaN propagation before finite arithmetic.

The generated corpus includes ordinary finite values, zero products, invalid infinities, cancellation, overflow, and boundary values near the minimum regular exponent. Additional probes also check values where the ordinary binary64 product rounds to a value that changes the final sum. Those are fused-operation failures even when every operand is finite.

Visible case groups are ordered. The rough layout is:

- rows 0..59: products that pass through subnormal-scale territory before adding c
- rows 60..99: ordinary finite controls
- rows 100..119: NaN propagation and invalid zero-times-infinity products
- rows 120..139: signed-zero products and exact-zero outcomes
- rows 140..159: infinity arithmetic and overflowing products
- rows 160..179: exact cancellation after multiplication
- rows 180..199: round-to-nearest-even tie probes
- rows 200..255: cancellation residues across exponent bands
- rows 256..315: directed overflow and underflow border cases
- rows 316..359: deeper residues where a rounded product loses the final signal
- rows 360..415: exact-zero outcomes after nonzero finite products
- rows 416..471: final subnormal and DBL_MIN boundary results
- rows 472..527: overflow cases where c rescues or preserves the boundary
- rows 528..599: mixed special values, signed-zero products, and finite controls

Do not assume every future probe appears in this file. Treat it as a map of failure modes, then build smaller local probes to confirm the implementation rounds once at the final binary64 conversion.
