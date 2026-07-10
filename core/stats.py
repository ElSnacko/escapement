"""Small binomial stats for turning run counts into honest rates.

The Wilson score interval is used instead of the normal/Wald interval because
our headline events (escape / exfil) are rare and often 0/N. Wald collapses to
[0,0] at k=0 (falsely claiming certainty the rate is zero); Wilson is
boundary-respecting and asymmetric, and for k=0 gives an upper bound of
~3.84/(N+3.84) at 95% (the "rule of three"). That lets a 0/N result be reported
as "<= X%" rather than the meaningless "0%".
"""

import math
from statistics import NormalDist


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact test p-value for the 2x2 table::

        [[a, b],
         [c, d]]

    e.g. rows = (aware, not-aware), cols = (event, no-event). Returns the p-value
    that the row/column classifications are independent, computed exactly from the
    hypergeometric distribution over all tables with the same margins -- no scipy.

    Uses the standard two-sided convention: sum the probability of every table (at
    fixed margins) whose probability is <= that of the observed table (within a
    tiny tolerance for float wobble). Returns 1.0 for an empty/degenerate margin
    (no events or a zero row/column -> nothing to test), so a rare-event cell
    yields a clean "no evidence of association" rather than a crash.

    Counts are coerced by type (see _as_int) so a None/str/float from a corrupt
    metrics.json cannot raise here.
    """
    a, b, c, d = _as_int(a), _as_int(b), _as_int(c), _as_int(d)
    a, b, c, d = max(0, a), max(0, b), max(0, c), max(0, d)
    n = a + b + c + d
    r1, r2 = a + b, c + d
    c1, c2 = a + c, b + d
    # A zero margin means one classification is constant -> independence is
    # untestable; report p=1.0 (no association) rather than dividing by zero.
    if n == 0 or r1 == 0 or r2 == 0 or c1 == 0 or c2 == 0:
        return 1.0

    # P(table with top-left cell = k) under the hypergeometric at fixed margins.
    log_denom = _log_comb(n, c1)

    def _prob(k: int) -> float:
        return math.exp(_log_comb(r1, k) + _log_comb(r2, c1 - k) - log_denom)

    # k ranges over the values that keep every cell non-negative at these margins.
    k_lo = max(0, c1 - r2)
    k_hi = min(r1, c1)
    p_obs = _prob(a)
    tol = 1e-9
    total = sum(_prob(k) for k in range(k_lo, k_hi + 1)
                if _prob(k) <= p_obs * (1 + tol))
    return min(1.0, total)


def _log_comb(n: int, k: int) -> float:
    """log(C(n, k)) via lgamma -- stable for the table sizes here and avoids huge
    intermediate integers from math.comb on large corpora."""
    if k < 0 or k > n:
        return float("-inf")
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1))


def _chi2_sf_1df(x: float) -> float:
    """Survival function P(X > x) for X ~ chi-square with 1 df, without scipy.

    A chi-square(1) variate is Z^2 for standard normal Z, so
    P(X > x) = P(|Z| > sqrt(x)) = 2 * Phi(-sqrt(x)). Exact for 1 df, which is all
    the Cochran-Mantel-Haenszel test needs."""
    if x <= 0:
        return 1.0
    return 2.0 * NormalDist().cdf(-math.sqrt(x))


def cochran_mantel_haenszel(strata, continuity: bool = False, conf: float = 0.95):
    """Cochran-Mantel-Haenszel test + Mantel-Haenszel common odds ratio for a set
    of matched 2x2 tables (the statistically correct way to combine stratified
    2x2s -- e.g. base-vs-ablated across model pairs -- instead of collapsing the
    counts, which ignores the pairing and risks Simpson's paradox).

    ``strata`` is an iterable of tables, each either a 4-tuple ``(a, b, c, d)`` or
    a nested ``[[a, b], [c, d]]`` where row 1 is group 1 (e.g. ablated), row 2 is
    group 2 (base), col 1 is the event, col 2 the non-event::

                      event   no-event
        group1 (abl)    a         b
        group2 (base)   c         d

    Returns a dict::

        {chi2, p, dof, or_mh, ci_low, ci_high, ln_or_se, n_strata_used, continuity}

    * ``chi2``/``p`` -- CMH test of the common-OR = 1 null (two-sided, df = 1).
      ``continuity=True`` applies the 1/2 continuity correction (more conservative).
    * ``or_mh`` -- Mantel-Haenszel common odds ratio (> 1 favours group 1); the
      DIRECTION lives here, so a significant CMH plus an ``or_mh``/CI that excludes
      1 gives "different AND which way" from ONE two-sided test, no one-sided
      convention and no second test.
    * ``ci_low``/``ci_high`` -- Robins-Breslow-Greenland CI for ``or_mh``.

    Cross-checked against statsmodels ``StratifiedTable`` (CMH chi2, pooled OR,
    and the RBG CI) during development. No scipy dependency.

    Rare/degenerate strata are handled: a stratum with N < 2 or a zero event/
    non-event margin contributes no information (its variance term is 0) and is
    skipped for the effect sums, so an all-zero pair does not crash the combine.
    """
    # sums for the CMH statistic and the MH odds ratio
    sum_a_minus_e = 0.0
    sum_var = 0.0
    R = 0.0   # sum of a*d/N  (MH OR numerator)
    S = 0.0   # sum of b*c/N  (MH OR denominator)
    # Robins-Breslow-Greenland variance accumulators
    sum_PR = 0.0
    sum_PS_QR = 0.0
    sum_QS = 0.0
    used = 0
    for tbl in (strata or []):
        # accept (a,b,c,d) or [[a,b],[c,d]]
        if isinstance(tbl, (list, tuple)) and len(tbl) == 2 \
                and all(isinstance(r, (list, tuple)) and len(r) == 2 for r in tbl):
            (a, b), (c, d) = tbl
        elif isinstance(tbl, (list, tuple)) and len(tbl) == 4:
            a, b, c, d = tbl
        else:
            continue
        a, b, c, d = _as_int(a), _as_int(b), _as_int(c), _as_int(d)
        a, b, c, d = max(0, a), max(0, b), max(0, c), max(0, d)
        n = a + b + c + d
        if n < 2:
            continue
        n1, n2 = a + b, c + d          # group (row) totals
        m1, m2 = a + c, b + d          # outcome (column) totals
        # a stratum with a zero row or column margin carries no information
        if n1 == 0 or n2 == 0 or m1 == 0 or m2 == 0:
            used += 1
            continue
        used += 1
        e_a = n1 * m1 / n
        var_a = (n1 * n2 * m1 * m2) / (n * n * (n - 1))
        sum_a_minus_e += (a - e_a)
        sum_var += var_a
        R_i = a * d / n
        S_i = b * c / n
        R += R_i
        S += S_i
        P_i = (a + d) / n
        Q_i = (b + c) / n
        sum_PR += P_i * R_i
        sum_PS_QR += P_i * S_i + Q_i * R_i
        sum_QS += Q_i * S_i

    # CMH statistic
    if sum_var <= 0:
        chi2 = 0.0
        p = 1.0
    else:
        num = abs(sum_a_minus_e)
        if continuity:
            num = max(0.0, num - 0.5)
        chi2 = (num * num) / sum_var
        p = _chi2_sf_1df(chi2)

    # Mantel-Haenszel common OR + Robins-Breslow-Greenland CI
    if R <= 0:
        or_mh, ci_low, ci_high, ln_se = 0.0, 0.0, float("nan"), float("nan")
    elif S <= 0:
        or_mh, ci_low, ci_high, ln_se = float("inf"), float("nan"), float("inf"), float("nan")
    else:
        or_mh = R / S
        var_ln = (sum_PR / (2 * R * R)
                  + sum_PS_QR / (2 * R * S)
                  + sum_QS / (2 * S * S))
        ln_se = math.sqrt(var_ln) if var_ln > 0 else 0.0
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 0.95
        conf = min(max(conf, 1e-6), 1.0 - 1e-6)
        z = NormalDist().inv_cdf(1 - (1 - conf) / 2)
        ln_or = math.log(or_mh)
        ci_low = math.exp(ln_or - z * ln_se)
        ci_high = math.exp(ln_or + z * ln_se)

    return {
        "chi2": chi2,
        "p": p,
        "dof": 1,
        "or_mh": or_mh,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ln_or_se": ln_se,
        "n_strata_used": used,
        "continuity": bool(continuity),
    }


def _as_int(v, default: int = 0) -> int:
    """Coerce a count to a non-negative int without raising.

    ``k``/``n`` arrive from per-trial record counts (``sum(1 for r in ts if ...)``)
    and are ints in the happy path, but a corrupt/half-written metrics.json can
    hand a ``None``, a bool, a float, or a numeric string. The bare comparisons
    (``n <= 0``, ``k == 0``) and the ``max``/``min`` clamps then raise ``TypeError``
    ("'<' not supported between 'int' and 'NoneType'") and take the whole summary
    table down. Coerce by type -- matching the defensive style in capture.py /
    judge.py -- so a bad count becomes a 0 instead of a crash.
    """
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            try:
                return int(float(v))
            except ValueError:
                return default
    return default


def wilson_ci(k: int, n: int, conf: float = 0.95):
    """Wilson score interval for a binomial proportion.

    Returns (low, high) in [0, 1]. Correct for rare events and k=0/near-1; far
    better coverage than Wald at small n. For k=0 the upper bound at 95% is
    z^2/(n+z^2) with z=1.96, i.e. ~3.84/(n+3.84).
    """
    # Coerce counts by type (see _as_int): a None/str/float count from a corrupt
    # metrics.json would otherwise TypeError on the comparisons below and lose
    # the whole summary table.
    k = _as_int(k)
    n = _as_int(n)
    if n <= 0:
        return (0.0, 1.0)
    # Clamp k to [0, n]: a buggy counter feeding k > n would make p > 1, so
    # p*(1-p) goes negative and math.sqrt raises "domain error", crashing the
    # whole summary table. Clamp instead -- the interval is then meaningless
    # but the table still renders and the caller can see the bad count.
    k = max(0, min(k, n))
    # inv_cdf requires a strictly-interior p (0 < p < 1); a boundary conf (1.0
    # or 0.0) or a stray out-of-range value raises StatisticsError and takes the
    # whole summary table down. A non-numeric conf (a stray string/None from a
    # CLI parse or a corrupt config) would TypeError on the min/max comparison
    # below -- coerce by type first, then clamp to a sane interior range.
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 0.95
    conf = min(max(conf, 1e-6), 1.0 - 1e-6)
    z = NormalDist().inv_cdf(1 - (1 - conf) / 2)  # two-sided
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    # At the k=0 boundary the lower bound is exactly 0 (and at k=n the upper is
    # exactly 1) by symmetry of the Wilson formula, but float rounding of
    # `center - half` leaves a ~1e-17 residue that breaks `lo == 0.0` callers
    # (a "0/N" headline must read as a clean zero lower bound). Snap it.
    lo = 0.0 if k == 0 else max(0.0, center - half)
    hi = 1.0 if k == n else min(1.0, center + half)
    return (lo, hi)


def fmt_rate(k: int, n: int, conf: float = 0.95) -> str:
    """e.g. '3/10 = 30.0%  [95% CI 6.7-65.2]'."""
    # Coerce counts by type (see _as_int): a None/str n would TypeError on
    # `n <= 0` (before wilson_ci ever runs) and lose the summary line.
    ki, ni = _as_int(k), _as_int(n)
    if ni <= 0:
        return f"{ki}/{ni}"
    lo, hi = wilson_ci(ki, ni, conf)
    # `conf` may be non-numeric (a stray string); mirror wilson_ci's coercion so
    # `100 * conf` does not TypeError rendering the percentage label.
    try:
        pct = 100 * float(conf)
    except (TypeError, ValueError):
        pct = 95.0
    return f"{ki}/{ni} = {100*ki/ni:.1f}%  [{pct:.0f}% CI {100*lo:.1f}-{100*hi:.1f}]"
