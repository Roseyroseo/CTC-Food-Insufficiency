"""
Model helpers for the replication of Shafer et al. (2022).

All replication models are weighted linear probability models (WLS on a 0/1 outcome)
with wave fixed effects, state fixed effects, and standard errors clustered by state,
matching the paper. Weights are the pooled household weight w = HWEIGHT / 13.
"""
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

REF_WEEK = 33                      # last wave before the first advance payment (Jul 15, 2021)
PRE_WEEKS = list(range(22, 33))    # 22..32: pre-period event-study coefficients
POST_WEEK = 34
ALL_WEEKS = list(range(22, 35))


WEEK_START = {22: "Jan 6", 23: "Jan 20", 24: "Feb 3", 25: "Feb 17", 26: "Mar 3", 27: "Mar 17",
              28: "Apr 14", 29: "Apr 28", 30: "May 12", 31: "May 26", 32: "Jun 9", 33: "Jun 23",
              34: "Jul 21"}

# Covariates listed in the paper's Methods. Categorical terms use C(); variables recoded with
# -1 = missing (INCOME, insured, SNAP_YN, FREEFOOD, ANYWORK) keep missing as its own category.
CONTROLS = ("C(female) + C(agegrp) + C(race_eth) + C(EEDUC) + C(INCOME) + C(MS)"
            " + n_adults + n_kids + C(ANYWORK) + UI_SPND + STIM_SPND"
            " + C(SNAP_YN) + C(FREEFOOD) + C(insured)")


def add_model_vars(a):
    """Model-ready variables from the analytic sample."""
    a = a.copy()
    a["agegrp"] = pd.cut(a["age"], [17, 24, 44, 64], labels=["18-24", "25-44", "45-64"]).astype(str)
    hisp = a["RHISPANIC"] == 2                       # 1 = not Hispanic, 2 = Hispanic
    a["race_eth"] = np.select(
        [hisp, a["RRACE"] == 1, a["RRACE"] == 2, a["RRACE"] == 3],
        ["Hispanic", "NH White", "NH Black", "NH Asian"], default="NH other/multiple")
    a["n_adults"] = a["THHLD_NUMADLT"]
    a["n_kids"] = a["THHLD_NUMKID"]
    a["state"] = a["EST_ST"].astype(int)             # cluster / fixed-effect identifier
    return a


def fit_wls(formula, a, weight="w", cluster="state", use_t=True): # make use_t=True to be more consistent with the paper
    """Weighted least squares with cluster-robust standard errors."""
    return smf.wls(formula, data=a, weights=a[weight]).fit(
        cov_type="cluster", cov_kwds={"groups": a[cluster]}, use_t=use_t)


def did_formula(controls=CONTROLS, state_fe=True):
    # post is absorbed by the wave fixed effects, so only kids_post enters
    f = f"food_insuf ~ kids + kids_post + C(WEEK) + {controls}"
    return f + (" + C(state)" if state_fe else "")


def event_study_formula(controls=CONTROLS, ref=REF_WEEK, state_fe=True):
    f = f"food_insuf ~ kids * C(WEEK, Treatment({ref})) + {controls}"
    return f + (" + C(state)" if state_fe else "")


def event_study_table(fit, ref=REF_WEEK):
    """kids x week coefficients with 95% CIs; the reference week is added as 0."""
    names = [n for n in fit.params.index if n.startswith("kids:C(WEEK")]
    week = [int(n.split("[T.")[1].rstrip("]")) for n in names]
    ci = fit.conf_int().loc[names]
    t = pd.DataFrame({"week": week, "coef": fit.params[names].values, "se": fit.bse[names].values,
                      "lo": ci[0].values, "hi": ci[1].values, "p": fit.pvalues[names].values})
    t = pd.concat([t, pd.DataFrame([{"week": ref, "coef": 0.0, "se": 0.0, "lo": 0.0, "hi": 0.0, "p": np.nan}])])
    t = t.sort_values("week").reset_index(drop=True)
    t["start"] = t["week"].map(WEEK_START)
    return t


def pretrend_test(fit, weeks=PRE_WEEKS):
    """Joint Wald (F) test that all pre-period kids x week coefficients are zero."""
    names = [n for n in fit.params.index if n.startswith("kids:C(WEEK")
             and int(n.split("[T.")[1].rstrip("]")) in weeks]
    R = np.zeros((len(names), len(fit.params)))
    for i, n in enumerate(names):
        R[i, fit.params.index.get_loc(n)] = 1
    return fit.f_test(R)


def weighted_rates(a, by=("WEEK", "kids"), weight="HWEIGHT"):
    """Weighted food insufficiency rate (%) by week and group."""
    s = a.assign(_wy=a["food_insuf"] * a[weight]).groupby(list(by))[["_wy", weight]].sum()
    out = 100 * s["_wy"] / s[weight]
    return out.unstack("kids").rename(columns={0: "No children", 1: "Children"})


def did_logit_ame(a, controls=CONTROLS, weight="w", cluster="state"):
    """
    Robustness: weighted logistic DiD. Returns the fitted model and the average marginal
    effect of kids_post among treated rows (households with children in week 34), in
    probability units so it is comparable with the linear probability estimate.
    """
    fit = smf.glm(did_formula(controls), data=a, family=sm.families.Binomial(),
                  var_weights=a[weight]).fit(cov_type="cluster", cov_kwds={"groups": a[cluster]})
    treated = a[a["kids_post"] == 1]
    p1 = fit.predict(treated.assign(kids_post=1))
    p0 = fit.predict(treated.assign(kids_post=0))
    ame = np.average(p1 - p0, weights=treated[weight])
    return fit, ame

def fit_event_study_ref(a, ref_weeks, controls=CONTROLS, state_fe=True):
    """
    Event study with any reference period. Households with children get their own
    indicator for every week NOT in ref_weeks, so each coefficient is the children-vs-none
    gap in that week relative to the average gap across ref_weeks.
      ref_weeks=[33]          -> the paper's specification
      ref_weeks=[32]          -> a different single reference week
      ref_weeks=range(22, 27) -> pooled January-early March reference
      ref_weeks=range(22, 34) -> all pre-payment weeks pooled (equivalent to the DiD)
    Returns (fit, names of the kids-by-week terms).
    """
    ref_weeks = list(ref_weeks)
    est_weeks = [w for w in ALL_WEEKS if w not in ref_weeks]
    terms = {f"kw{w}": (a["kids"] * (a["WEEK"] == w)).astype(int) for w in est_weeks}
    d = a.assign(**terms)
    f = f"food_insuf ~ kids + C(WEEK) + {' + '.join(terms)} + {controls}"
    f += " + C(state)" if state_fe else ""
    return fit_wls(f, d), list(terms)


def joint_test(fit, names):
    """Joint F-test that all the named coefficients are zero."""
    R = np.zeros((len(names), len(fit.params)))
    for i, n in enumerate(names):
        R[i, fit.params.index.get_loc(n)] = 1
    return fit.f_test(R)


def beta34_by_reference(a, references):
    """β34 and the pre-trend test under each reference period. references: {label: ref_weeks}."""
    rows = []
    for label, ref in references.items():
        fit, names = fit_event_study_ref(a, ref)
        pre = [n for n in names if n != "kw34"]
        ci = fit.conf_int().loc["kw34"]
        pt = joint_test(fit, pre) if pre else None
        rows.append({"reference": label, "beta34": fit.params["kw34"], "lo": ci[0], "hi": ci[1],
                     "p": fit.pvalues["kw34"], "n_pre_coefs": len(pre),
                     "pretrend_F": float(np.squeeze(pt.fvalue)) if pt else np.nan,
                     "pretrend_p": float(pt.pvalue) if pt else np.nan})
    return pd.DataFrame(rows)
