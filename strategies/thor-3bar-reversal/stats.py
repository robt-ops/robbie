"""
Statistics for deciding whether a backtest result is an edge or luck.

No scipy dependency — normal CDF via math.erf, inverse CDF via Acklam's
rational approximation refined with one Halley step.

Three things live here:

  1. Session block bootstrap — confidence intervals that respect the fact
     that intraday trades cluster inside a session, so N trades are worth
     fewer than N independent bets.
  2. Probabilistic / Deflated Sharpe (Bailey & Lopez de Prado 2014) —
     discounts a Sharpe ratio for non-normal returns, short samples, and
     for the number of variants you tried before picking the winner.
  3. Power — how many trades you actually need before a result can be
     separated from noise.

All Sharpe inputs/outputs here are PER-TRADE (non-annualized). The PSR
formula is only valid on the same frequency as the return series it was
computed from, and annualizing first silently breaks it.
"""

import math

import numpy as np

EULER_MASCHERONI = 0.5772156649015329


# ---------------------------------------------------------------- normal dist

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00)
_P_LOW = 0.02425


def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"norm_ppf needs 0 < p < 1, got {p}")

    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    elif p <= 1.0 - _P_LOW:
        q = p - 0.5
        r = q * q
        x = (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
            (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
             ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)

    # One Halley refinement — pushes relative error to ~1e-15.
    e = norm_cdf(x) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    return x - u / (1.0 + x * u / 2.0)


# ------------------------------------------------------------------ bootstrap

def block_bootstrap_mean(values, blocks, n_boot: int = 10_000,
                         seed: int = 0, alpha: float = 0.05) -> dict:
    """
    Bootstrap the mean of `values` by resampling whole blocks with replacement.

    `blocks` is a same-length sequence of block labels (use the session date
    for intraday trades). Blocks are drawn with replacement until the same
    NUMBER OF BLOCKS as the original sample is reached, so each replicate has
    a variable trade count — that is the point: it carries the clustering
    through into the interval.

    Passing a unique label per value gives the naive iid bootstrap.
    """
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        raise ValueError("no values to bootstrap")

    order = np.argsort(np.asarray(blocks, dtype=object).astype(str), kind="stable")
    sorted_vals = values[order]
    sorted_keys = np.asarray(blocks, dtype=object).astype(str)[order]
    _, starts = np.unique(sorted_keys, return_index=True)
    groups = np.split(sorted_vals, starts[1:])

    rng = np.random.default_rng(seed)
    n_blocks = len(groups)
    sums = np.array([g.sum() for g in groups])
    counts = np.array([g.size for g in groups])

    idx = rng.integers(0, n_blocks, size=(n_boot, n_blocks))
    boot_means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)

    lo, hi = np.percentile(boot_means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {
        "mean": float(values.mean()),
        "se": float(boot_means.std(ddof=1)),
        "ci_lo": float(lo),
        "ci_hi": float(hi),
        "p_le_zero": float((boot_means <= 0).mean()),
        "n": int(values.size),
        "n_blocks": n_blocks,
    }


def effective_sample_size(n: int, se_iid: float, se_block: float) -> float:
    """
    How many independent bets the trade count is really worth.

    Standard error scales as 1/sqrt(n), so inflating the SE by a factor k is
    equivalent to shrinking n by k^2. Clamped to [1, n]: a block SE *smaller*
    than the iid SE means no measurable clustering, not extra information.
    """
    if se_block <= 0 or se_iid <= 0:
        return float(n)
    return float(min(n, max(1.0, n * (se_iid / se_block) ** 2)))


# ------------------------------------------------------- Sharpe, PSR, and DSR

def sharpe_moments(returns) -> dict:
    """Per-observation Sharpe plus the population moments PSR needs."""
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 2:
        raise ValueError("need at least 2 observations")
    sd = r.std(ddof=1)
    if sd == 0:
        raise ValueError("zero dispersion — Sharpe undefined")
    z = (r - r.mean()) / r.std(ddof=0)
    return {
        "n": n,
        "mean": float(r.mean()),
        "sd": float(sd),
        "sharpe": float(r.mean() / sd),
        "skew": float((z ** 3).mean()),
        "kurtosis": float((z ** 4).mean()),  # non-excess: 3.0 for a normal
    }


def probabilistic_sharpe_ratio(sharpe: float, benchmark: float, n: int,
                               skew: float, kurtosis: float) -> float:
    """
    P(true Sharpe > benchmark), adjusted for skew, fat tails, and sample size.

    `kurtosis` is non-excess (3.0 == normal). `sharpe` and `benchmark` must be
    on the same per-observation basis as the series `n` counts.
    """
    denom_sq = 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe ** 2
    if denom_sq <= 0:
        return float("nan")
    return norm_cdf(((sharpe - benchmark) * math.sqrt(n - 1)) / math.sqrt(denom_sq))


def expected_max_sharpe(sharpe_variance: float, n_trials: int) -> float:
    """
    Sharpe the best of `n_trials` worthless variants would post by luck alone.

    E[max SR] under the null, from the Gumbel approximation to the maximum of
    n_trials iid normals with variance `sharpe_variance`.
    """
    if n_trials <= 1:
        return 0.0
    g = EULER_MASCHERONI
    z1 = norm_ppf(1.0 - 1.0 / n_trials)
    z2 = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(max(sharpe_variance, 0.0)) * ((1.0 - g) * z1 + g * z2)


def deflated_sharpe_ratio(sharpe: float, sharpe_variance: float, n_trials: int,
                          n: int, skew: float, kurtosis: float) -> dict:
    """
    PSR measured against E[max SR] instead of against zero.

    `sharpe_variance` is the variance of the Sharpe estimates ACROSS the
    variants tried, and `n_trials` the honest count of variants tried — not
    just the ones that survived to be written down.
    """
    sr_star = expected_max_sharpe(sharpe_variance, n_trials)
    return {
        "dsr": probabilistic_sharpe_ratio(sharpe, sr_star, n, skew, kurtosis),
        "sr_star": sr_star,
        "n_trials": n_trials,
    }


# ---------------------------------------------------------------------- power

def n_for_expectancy(mean_r: float, sd_r: float, alpha: float = 0.05,
                     power: float = 0.80, one_sided: bool = True) -> float:
    """
    Trades needed to detect a mean-R edge of `mean_r` with dispersion `sd_r`.

    This is the metric to power against for breakout systems: they win 35-45%
    of the time and make money on payoff asymmetry, so a win-rate test has no
    bearing on whether they work.
    """
    if mean_r <= 0:
        return float("inf")
    z_a = norm_ppf(1 - alpha) if one_sided else norm_ppf(1 - alpha / 2)
    return ((z_a + norm_ppf(power)) * sd_r / mean_r) ** 2


def n_for_win_rate(p_alt: float, p_null: float = 0.5, alpha: float = 0.05,
                   power: float = 0.80, one_sided: bool = True) -> float:
    """Trades needed to tell a win rate of `p_alt` from `p_null`."""
    if p_alt == p_null:
        return float("inf")
    z_a = norm_ppf(1 - alpha) if one_sided else norm_ppf(1 - alpha / 2)
    z_b = norm_ppf(power)
    return ((z_a * math.sqrt(p_null * (1 - p_null))
             + z_b * math.sqrt(p_alt * (1 - p_alt))) / (p_alt - p_null)) ** 2
