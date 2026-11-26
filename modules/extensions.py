"""
Extensions to the Shafer et al. (2022) replication.

Extension (b): Census replicate-weight standard errors.
    Each model is re-estimated with each of the 80 household replicate weights.
    Var(b) = (4/80) * sum_r (b_r - b)^2   (Census Source and Accuracy Statement, Phase 3.1, pp. 12-13)
    For pooled weeks, every week's full and replicate weights are divided by the number of weeks (13).
    For speed, the design matrix is built once and the weighted least squares solution
    b_r = (X'W_r X)^-1 X'W_r y is computed directly with NumPy for each replicate.

Extension (a): state heterogeneity with a mixed model.
    State random intercept + random slope on kids_post, fit unweighted (statsmodels MixedLM
    does not accept survey weights) and compared with an unweighted state fixed-effects model.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

from modules import analysis
from modules.prepare_pulse import N_WAVES, OUT_DIR, load

N_REP = 80
SDR_FACTOR = 4 / N_REP          # successive difference replication multiplier
REP_COLS = [f"HWEIGHT{i}" for i in range(1, N_REP + 1)]
CACHE_DIR = OUT_DIR / "replicate_cache"


# --------------------------------------------------------------------------- #
# Extension (b): replicate-weight standard errors
# --------------------------------------------------------------------------- #
def attach_replicate_weights(a, n_waves=N_WAVES):
    """Merge the 80 replicate weights onto the analytic sample (1:1 on SCRAM + WEEK), pooled / 13."""
    rep = load("repwgt_w22_34")
    m = a.merge(rep, on=["SCRAM", "WEEK"], how="left", validate="1:1")
    if m[REP_COLS].isna().any().any():
        raise ValueError("Some analytic-sample rows have no replicate weights.")
    m[REP_COLS] = m[REP_COLS].astype("float64") / n_waves
    return m


def _wls_beta(X, y, w):
    """Weighted least squares coefficients via the normal equations."""
    Xw = X * w[:, None]
    return np.linalg.solve(Xw.T @ X, Xw.T @ y)


def replicate_coefficients(formula, a, name, weight="w", use_cache=True, verbose=True):
    """
    Full-sample and 80 replicate coefficient vectors for a WLS model.
    Returns (b_full: Series, b_reps: DataFrame 80 x k). Cached to data/processed/replicate_cache/.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{name}.npz"
    model = smf.wls(formula, data=a, weights=a[weight])     # builds X once (same columns as fit_wls)
    names = list(model.exog_names)
    if use_cache and cache.exists():
        z = np.load(cache, allow_pickle=True)
        if list(z["names"]) == names:
            if verbose:
                print(f"{name}: loaded cached replicate coefficients")
            return pd.Series(z["b_full"], index=names), pd.DataFrame(z["b_reps"], columns=names)

    rows = model.data.row_labels                           # rows kept by the formula
    X, y = model.exog, model.endog
    b_full = _wls_beta(X, y, a.loc[rows, weight].to_numpy("float64"))
    b_reps = np.empty((N_REP, len(names)))
    for r, col in enumerate(REP_COLS):
        b_reps[r] = _wls_beta(X, y, a.loc[rows, col].to_numpy("float64"))
        if verbose and (r + 1) % 10 == 0:
            print(f"{name}: {r + 1}/{N_REP} replicates")
    np.savez(cache, names=np.array(names, dtype=object), b_full=b_full, b_reps=b_reps)
    return pd.Series(b_full, index=names), pd.DataFrame(b_reps, columns=names)


def replicate_inference(b_full, b_reps, terms, df=N_REP):
    """
    SDR standard errors, t-tests (H0: coefficient = 0) and 95% CIs for the named terms.
    Uses a t-distribution with `df` degrees of freedom (80 replicates by default).
    """
    se = np.sqrt(SDR_FACTOR * ((b_reps[terms] - b_full[terms]) ** 2).sum())
    t = b_full[terms] / se
    tcrit = stats.t.ppf(0.975, df)
    return pd.DataFrame({"coef": b_full[terms], "se_rep": se, "t": t,
                         "p": 2 * stats.t.sf(np.abs(t), df),
                         "lo": b_full[terms] - tcrit * se, "hi": b_full[terms] + tcrit * se})


def replicate_joint_test(b_full, b_reps, terms, df=N_REP):
    """
    Wald test that all named coefficients are zero, using the replicate covariance matrix
    V = (4/80) * sum_r (b_r - b)(b_r - b)'. Returns F, p with F(q, df) reference distribution.
    """
    d = (b_reps[terms] - b_full[terms]).to_numpy()
    V = SDR_FACTOR * d.T @ d
    b = b_full[terms].to_numpy()
    q = len(terms)
    F = float(b @ np.linalg.solve(V, b)) / q
    return F, float(stats.f.sf(F, q, df))


def compare_se(fit_cluster, rep_table, terms):
    """Side-by-side: state-clustered vs replicate-weight inference for the named terms."""
    ci = fit_cluster.conf_int().loc[terms]
    out = pd.DataFrame({
        "coef": fit_cluster.params[terms],
        "se_cluster": fit_cluster.bse[terms], "p_cluster": fit_cluster.pvalues[terms],
        "lo_cluster": ci[0], "hi_cluster": ci[1],
        "se_rep": rep_table["se_rep"], "p_rep": rep_table["p"],
        "lo_rep": rep_table["lo"], "hi_rep": rep_table["hi"],
    })
    out["se_ratio (rep/cluster)"] = out["se_rep"] / out["se_cluster"]
    return out


# --------------------------------------------------------------------------- #
# Extension (a): state mixed model
# --------------------------------------------------------------------------- #
MIXED_FORMULA = f"food_insuf ~ kids + kids_post + C(WEEK) + {analysis.CONTROLS}"


def fit_mixed(a, random_slope=True, reml=False):
    """
    Unweighted linear mixed model with a state random intercept. If random_slope=True, adds an
    independent state random slope on kids_post (a variance component with no intercept-slope
    covariance). Kept for documentation: at this sample size statsmodels MixedLM returned singular
    covariance matrices and invalid log-likelihoods, so the notebook uses the two-stage approach below.
    """
    vc = {"kids_post_slope": "0 + kids_post"} if random_slope else None
    model = smf.mixedlm(MIXED_FORMULA, data=a, groups=a["state"], re_formula="1", vc_formula=vc)
    return model.fit(reml=reml, method=["lbfgs", "bfgs"])


def lr_test_random_slope(fit_slope, fit_int):
    """
    Likelihood-ratio test of the random slope (H0: slope variance = 0). The slope model adds one
    variance; because it cannot be negative, H0 lies on the boundary and the reference distribution
    is a 50:50 mixture of chi-square(0) and chi-square(1), i.e. the chi-square(1) p-value is halved.
    """
    if not (np.isfinite(fit_slope.llf) and np.isfinite(fit_int.llf)):
        raise ValueError(f"Non-finite log-likelihood: slope {fit_slope.llf}, intercept {fit_int.llf}")
    lr = max(2 * (fit_slope.llf - fit_int.llf), 0.0)
    return {"LR": lr, "p_naive_chi2(1)": stats.chi2.sf(lr, 1), "p_boundary_halved": 0.5 * stats.chi2.sf(lr, 1)}


def state_effects(fit_slope, a):
    """State-specific DiD effects: fixed kids_post effect + each state's random slope (BLUP)."""
    avg = fit_slope.fe_params["kids_post"]
    re = pd.DataFrame(fit_slope.random_effects).T
    slope_col = [c for c in re.columns if "slope" in str(c) or "kids_post" in str(c)][0]
    out = pd.DataFrame({"state": re.index, "effect": avg + re[slope_col].values})
    n = a.groupby("state").size()
    out["n"] = out["state"].map(n)
    return out.sort_values("effect").reset_index(drop=True)


def fit_fe_unweighted(a):
    """Unweighted DiD with state fixed effects and state-clustered SEs: the comparison for the mixed model."""
    b = a.assign(_one=1.0)
    return analysis.fit_wls(analysis.did_formula(), b, weight="_one")


# --------------------------------------------------------------------------- #
# Extension (a), two-stage version: state-specific effects + heterogeneity test
# --------------------------------------------------------------------------- #
STATE_DID_FORMULA = (f"food_insuf ~ C(state) * kids + C(state):kids_post + C(WEEK) + {analysis.CONTROLS}")


def state_slopes_replicate(a, use_cache=True):
    """
    One weighted regression with a separate DiD effect (kids_post) for every state, plus
    state-specific baselines and state-specific gaps between households with and without children.
    Standard errors come from the 80 replicate weights (SDR). Returns a DataFrame with one row
    per state: effect, se_rep, n.
    """
    b_full, b_reps = replicate_coefficients(STATE_DID_FORMULA, a, name="state_did", use_cache=use_cache)
    terms = [n for n in b_full.index if n.startswith("C(state)[") and n.endswith(":kids_post")]
    rep = replicate_inference(b_full, b_reps, terms)
    out = pd.DataFrame({
        "state": [int(n.split("[")[1].split("]")[0]) for n in terms],
        "effect": rep["coef"].values, "se_rep": rep["se_rep"].values,
        "lo": rep["lo"].values, "hi": rep["hi"].values,
    })
    out["n"] = out["state"].map(a.groupby("state").size())
    out["n_kids_wk34"] = out["state"].map(a[(a.kids == 1) & (a.WEEK == 34)].groupby("state").size())
    return out.sort_values("effect").reset_index(drop=True)


def heterogeneity_test(effect, se):
    """
    Cochran's Q test of H0: all states share one true effect (between-state variance tau^2 = 0),
    with the DerSimonian-Laird estimate of tau^2 and I^2 (share of variation beyond sampling error).
    Also returns the random-effects pooled mean, the analogue of the mixed model's average effect.
    """
    effect, se = np.asarray(effect, float), np.asarray(se, float)
    k = len(effect)
    w = 1 / se**2
    fixed_mean = np.sum(w * effect) / np.sum(w)
    Q = float(np.sum(w * (effect - fixed_mean) ** 2))
    df = k - 1
    tau2 = max(0.0, (Q - df) / (np.sum(w) - np.sum(w**2) / np.sum(w)))
    w_re = 1 / (se**2 + tau2)
    re_mean = np.sum(w_re * effect) / np.sum(w_re)
    re_se = np.sqrt(1 / np.sum(w_re))
    return {"k": k, "Q": Q, "df": df, "p": float(stats.chi2.sf(Q, df)),
            "tau": float(np.sqrt(tau2)), "I2": max(0.0, (Q - df) / Q) if Q > 0 else 0.0,
            "re_mean": float(re_mean), "re_se": float(re_se)}


STATE_ABBR = {1: "AL", 2: "AK", 4: "AZ", 5: "AR", 6: "CA", 8: "CO", 9: "CT", 10: "DE", 11: "DC", 12: "FL",
              13: "GA", 15: "HI", 16: "ID", 17: "IL", 18: "IN", 19: "IA", 20: "KS", 21: "KY", 22: "LA",
              23: "ME", 24: "MD", 25: "MA", 26: "MI", 27: "MN", 28: "MS", 29: "MO", 30: "MT", 31: "NE",
              32: "NV", 33: "NH", 34: "NJ", 35: "NM", 36: "NY", 37: "NC", 38: "ND", 39: "OH", 40: "OK",
              41: "OR", 42: "PA", 44: "RI", 45: "SC", 46: "SD", 47: "TN", 48: "TX", 49: "UT", 50: "VT",
              51: "VA", 53: "WA", 54: "WV", 55: "WI", 56: "WY"}
