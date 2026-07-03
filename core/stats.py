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


def wilson_ci(k: int, n: int, conf: float = 0.95):
    """Wilson score interval for a binomial proportion.

    Returns (low, high) in [0, 1]. Correct for rare events and k=0/near-1; far
    better coverage than Wald at small n. For k=0 the upper bound at 95% is
    z^2/(n+z^2) with z=1.96, i.e. ~3.84/(n+3.84).
    """
    if n <= 0:
        return (0.0, 1.0)
    z = NormalDist().inv_cdf(1 - (1 - conf) / 2)  # two-sided
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def fmt_rate(k: int, n: int, conf: float = 0.95) -> str:
    """e.g. '3/10 = 30.0%  [95% CI 6.7-65.2]'."""
    if n <= 0:
        return f"{k}/{n}"
    lo, hi = wilson_ci(k, n, conf)
    pct = 100 * conf
    return f"{k}/{n} = {100*k/n:.1f}%  [{pct:.0f}% CI {100*lo:.1f}-{100*hi:.1f}]"
