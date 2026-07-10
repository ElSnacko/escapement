"""Tests for core/stats.py primitives (Wilson CI + Fisher exact).

Fisher is validated against closed-form / textbook values so the test carries no
scipy dependency (scipy is not a repo requirement). The implementation was
separately checked against scipy.stats.fisher_exact across 2000 random tables
(0 mismatches) during development.

Run:  python tests/test_stats.py      (or: pytest tests/)
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.stats import fisher_exact_2x2, wilson_ci, cochran_mantel_haenszel


def _close(x, y, tol=1e-6):
    return abs(x - y) <= tol


def test_fisher_tea_tasting():
    # Fisher's lady-tasting-tea table [[3,1],[1,3]] -> two-sided p = 0.485714...
    assert _close(fisher_exact_2x2(3, 1, 1, 3), 0.4857142857), \
        fisher_exact_2x2(3, 1, 1, 3)


def test_fisher_perfect_independence_is_one():
    # the balanced modal table sums to 1.0 up to float accumulation (exp/lgamma)
    assert _close(fisher_exact_2x2(5, 5, 5, 5), 1.0, tol=1e-9)


def test_fisher_zero_margins_return_one():
    # no events in either arm -> untestable -> p = 1.0 (not a crash, not a false 0)
    assert fisher_exact_2x2(0, 10, 0, 12) == 1.0
    # a zero row (no "aware" trials) is also degenerate
    assert fisher_exact_2x2(0, 0, 5, 7) == 1.0


def test_fisher_perfect_separation_is_small():
    # complete association should be strongly significant and in (0, 1]
    p = fisher_exact_2x2(10, 0, 0, 10)
    assert 0.0 < p < 0.001, p


def test_fisher_monotonic_in_association():
    # a stronger imbalance at fixed margins yields a smaller p-value
    weak = fisher_exact_2x2(6, 4, 4, 6)
    strong = fisher_exact_2x2(9, 1, 1, 9)
    assert strong < weak, (strong, weak)


def test_fisher_symmetric_under_transpose():
    # p is invariant to swapping rows<->cols
    assert _close(fisher_exact_2x2(2, 8, 7, 3), fisher_exact_2x2(2, 7, 8, 3))


def test_fisher_p_in_unit_interval():
    for tbl in [(1, 9, 11, 3), (2, 112, 15, 99), (0, 1, 1, 0), (20, 0, 0, 20)]:
        p = fisher_exact_2x2(*tbl)
        assert 0.0 <= p <= 1.0, (tbl, p)


def test_fisher_coerces_bad_counts():
    # a None/str/float count from a corrupt metrics.json must not raise
    assert fisher_exact_2x2(None, 10, 0, 12) == 1.0          # None -> 0
    assert 0.0 <= fisher_exact_2x2("2", 112, 15, 99.0) <= 1.0


def test_wilson_zero_is_bounded_null():
    lo, hi = wilson_ci(0, 100)
    assert lo == 0.0 and 0.0 < hi < 0.05, (lo, hi)


# --- Cochran-Mantel-Haenszel -------------------------------------------------\
# Reference values cross-checked against statsmodels StratifiedTable during
# development (CMH chi2 / pooled OR / RBG CI all match to full float precision).
# Strata are the ablation matched pairs, (a,b,c,d) = ablated-event,
# ablated-noevent, base-event, base-noevent.
_ABLATION = [(11, 49, 2, 58), (4, 50, 0, 54), (0, 94, 0, 30)]


def test_cmh_matches_statsmodels_uncorrected():
    r = cochran_mantel_haenszel(_ABLATION)
    assert _close(r["chi2"], 10.8493806, tol=1e-5), r["chi2"]
    assert _close(r["p"], 0.00098829, tol=1e-7), r["p"]
    assert _close(r["or_mh"], 8.9591837, tol=1e-5), r["or_mh"]
    assert _close(r["ci_low"], 1.9515784, tol=1e-5), r["ci_low"]
    assert _close(r["ci_high"], 41.1292587, tol=1e-4), r["ci_high"]
    assert r["dof"] == 1 and r["n_strata_used"] == 3


def test_cmh_continuity_correction_is_more_conservative():
    plain = cochran_mantel_haenszel(_ABLATION)
    corr = cochran_mantel_haenszel(_ABLATION, continuity=True)
    assert corr["chi2"] < plain["chi2"], (corr["chi2"], plain["chi2"])
    assert corr["p"] > plain["p"]
    assert _close(corr["chi2"], 9.2444427, tol=1e-5), corr["chi2"]
    assert _close(corr["p"], 0.0023621, tol=1e-6), corr["p"]


def test_cmh_direction_lives_in_the_odds_ratio():
    # OR excludes 1 AND lies above it -> "different AND ablated higher" from one
    # two-sided test, no one-sided convention, no second test.
    r = cochran_mantel_haenszel(_ABLATION)
    assert r["ci_low"] > 1.0, r["ci_low"]
    assert r["or_mh"] > 1.0


def test_cmh_accepts_nested_tables():
    nested = [[[11, 49], [2, 58]], [[4, 50], [0, 54]], [[0, 94], [0, 30]]]
    a = cochran_mantel_haenszel(nested)
    b = cochran_mantel_haenszel(_ABLATION)
    assert _close(a["chi2"], b["chi2"]) and _close(a["or_mh"], b["or_mh"])


def test_cmh_uninformative_strata_are_bounded_null():
    # a pair with no events in either arm carries no information -> p = 1
    r = cochran_mantel_haenszel([(0, 30, 0, 40)])
    assert r["p"] == 1.0 and r["chi2"] == 0.0
    assert r["or_mh"] == 0.0  # R = 0 (no a*d mass)


def test_cmh_perfect_separation_is_infinite_or():
    # base never has the event -> denominator S = 0 -> OR unbounded above
    r = cochran_mantel_haenszel([(8, 2, 0, 10)])
    assert r["or_mh"] == float("inf")
    assert r["ci_high"] == float("inf")


def test_cmh_coerces_bad_counts():
    # None/str/float counts from a corrupt record must not raise
    r = cochran_mantel_haenszel([("11", 49, 2, 58.0), (4, 50, None, 54)])
    assert 0.0 <= r["p"] <= 1.0 and r["or_mh"] >= 0.0


def test_cmh_empty_is_safe():
    r = cochran_mantel_haenszel([])
    assert r["p"] == 1.0 and r["chi2"] == 0.0 and r["n_strata_used"] == 0


def _main():
    tests = [(n, v) for n, v in sorted(globals().items())
             if n.startswith("test_") and callable(v)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL  {name}: {exc}")
            failed += 1
        except Exception:
            print(f"ERROR {name}:")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
