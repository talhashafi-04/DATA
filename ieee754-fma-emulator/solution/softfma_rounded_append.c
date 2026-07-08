
double softfma_rounded(double a, double b, double c, int mode) {
    DoubleBits abits = unpack_double(a);
    DoubleBits bbits = unpack_double(b);
    DoubleBits cbits = unpack_double(c);

    if (is_nan_bits(abits) || is_nan_bits(bbits) || is_nan_bits(cbits)) {
        return softfma(a, b, c);
    }
    if ((is_inf_bits(abits) && is_zero_bits(bbits)) ||
        (is_inf_bits(bbits) && is_zero_bits(abits))) {
        return softfma(a, b, c);
    }
    if (is_inf_bits(abits) || is_inf_bits(bbits) || is_inf_bits(cbits)) {
        return softfma(a, b, c);
    }

    mpfr_rnd_t rnd = MPFR_RNDN;
    if (mode == 1) {
        rnd = MPFR_RNDZ;
    } else if (mode == 2) {
        rnd = MPFR_RNDU;
    } else if (mode == 3) {
        rnd = MPFR_RNDD;
    }

    mpfr_t ma;
    mpfr_t mb;
    mpfr_t mc;
    mpfr_t mr;
    mpfr_inits2(8192, ma, mb, mc, mr, (mpfr_ptr)0);
    mpfr_set_d(ma, a, MPFR_RNDN);
    mpfr_set_d(mb, b, MPFR_RNDN);
    mpfr_set_d(mc, c, MPFR_RNDN);
    mpfr_mul(mr, ma, mb, MPFR_RNDN);
    mpfr_add(mr, mr, mc, rnd);
    double rounded = mpfr_get_d(mr, rnd);
    mpfr_clears(ma, mb, mc, mr, (mpfr_ptr)0);
    return rounded;
}
