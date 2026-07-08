The JSON corpus is generated during the Docker build. It is visible so you can reproduce failures, but it is not a complete specification.

The helper script groups rows into seven consecutive bands:

0 through 59 exercise tiny nonzero products with nearby addends.
60 through 99 exercise ordinary finite values.
100 through 119 exercise NaN and invalid-operation propagation.
120 through 139 exercise signed-zero outcomes.
140 through 159 exercise infinite operands and overflow.
160 through 179 exercise exact cancellation.
180 through 199 exercise round-to-nearest-even boundaries.

Keep the JSON as an input corpus. Rebuild the C binary after editing `softfma.c`.
