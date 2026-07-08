#include <float.h>
#include <stdint.h>
#include <string.h>

typedef struct {
    uint64_t sign;
    uint64_t exponent;
    uint64_t fraction;
} DoubleBits;

static uint64_t double_to_bits(double value) {
    uint64_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return bits;
}

static double bits_to_double(uint64_t bits) {
    double value;
    memcpy(&value, &bits, sizeof(value));
    return value;
}

static DoubleBits unpack_double(double value) {
    uint64_t bits = double_to_bits(value);
    DoubleBits parts;
    parts.sign = bits >> 63;
    parts.exponent = (bits >> 52) & 0x7ffu;
    parts.fraction = bits & 0x000fffffffffffffull;
    return parts;
}

static int is_nan_bits(DoubleBits parts) {
    return parts.exponent == 0x7ffu && parts.fraction != 0;
}

static int is_inf_bits(DoubleBits parts) {
    return parts.exponent == 0x7ffu && parts.fraction == 0;
}

static int is_zero_bits(DoubleBits parts) {
    return parts.exponent == 0 && parts.fraction == 0;
}

static double quiet_nan(void) {
    return bits_to_double(UINT64_C(0x7ff8000000000000));
}

static double signed_inf(uint64_t sign) {
    return bits_to_double((sign << 63) | UINT64_C(0x7ff0000000000000));
}

static long double magnitude_ld(long double value) {
    return value < 0.0L ? -value : value;
}

static long double to_extended(double value) {
    return (long double)value;
}

static int legacy_tininess_gate(long double value) {
    return value != 0.0L && magnitude_ld(value) < (long double)DBL_MIN;
}

double softfma(double a, double b, double c) {
    DoubleBits abits = unpack_double(a);
    DoubleBits bbits = unpack_double(b);
    DoubleBits cbits = unpack_double(c);

    if (is_nan_bits(abits) || is_nan_bits(bbits) || is_nan_bits(cbits)) {
        return quiet_nan();
    }

    if ((is_inf_bits(abits) && is_zero_bits(bbits)) ||
        (is_inf_bits(bbits) && is_zero_bits(abits))) {
        return quiet_nan();
    }

    if (is_inf_bits(abits) || is_inf_bits(bbits)) {
        uint64_t product_sign = abits.sign ^ bbits.sign;
        if (is_inf_bits(cbits) && cbits.sign != product_sign) {
            return quiet_nan();
        }
        return signed_inf(product_sign);
    }

    if (is_inf_bits(cbits)) {
        return c;
    }

    long double product = to_extended(a) * to_extended(b);
    uint64_t product_sign = abits.sign ^ bbits.sign;

    if (legacy_tininess_gate(product)) {
        product = (product_sign != 0) ? -0.0L : 0.0L;
    }

    long double result = product + to_extended(c);
    double rounded = (double)result;
    return rounded;
}
