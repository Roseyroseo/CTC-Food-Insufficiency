"""
Stack Household Pulse Survey weeks 22–34 (Jan 6 – Aug 2, 2021) into analysis files
for the replication of Shafer et al. (2022).

Outputs (in data/processed/):
  pulse_w22_34.parquet   analysis variables, one row per respondent-week
  repwgt_w22_34.parquet  HWEIGHT1–80 keyed by SCRAM + WEEK (Extension b only)
Falls back to .pkl if pyarrow is not installed.

Use from a notebook:
    from modules.prepare_pulse import build_analysis_file, build_repwgt_file, replication_checks
or from the command line (from the repo root):
    python -m modules.prepare_pulse
"""
from pathlib import Path

import numpy as np
import pandas as pd

from modules.get_data import RAW_DIR, ROOT, WEEKS, find_week_files

OUT_DIR = ROOT / "data" / "processed"
N_WAVES = len(WEEKS) 
MISSING_CODES = [-99, -88]    # -99 = seen but not answered, -88 = missing / skipped

# (harmonized name, candidate column names in priority order).
# Names that change across phases are matched to whichever the week uses.
VARS = [
    ("SCRAM",         ["SCRAM"]),
    ("WEEK",          ["WEEK"]),
    ("EST_ST",        ["EST_ST"]),
    ("HWEIGHT",       ["HWEIGHT"]),
    ("CURFOODSUF",    ["CURFOODSUF"]),
    ("THHLD_NUMKID",  ["THHLD_NUMKID"]),
    ("THHLD_NUMADLT", ["THHLD_NUMADLT"]),
    ("TBIRTH_YEAR",   ["TBIRTH_YEAR"]),
    ("RRACE",         ["RRACE"]),
    ("RHISPANIC",     ["RHISPANIC"]),
    ("EEDUC",         ["EEDUC"]),
    ("MS",            ["MS"]),
    ("INCOME",        ["INCOME"]),
    ("ANYWORK",       ["ANYWORK"]),
    ("SNAP_YN",       ["SNAP_YN"]),
    ("FREEFOOD",      ["FREEFOOD"]),
    ("SEX_RAW",       ["EGENDER", "EGENID_BIRTH"]),   # week 34 uses EGENID_BIRTH
    ("UI_SPND",       ["SPNDSRC5", "SPND_SRC5"]),     # renamed in week 34
    ("STIM_SPND",     ["SPNDSRC6", "SPND_SRC6"]),
] + [(f"HLTHINS{i}", [f"HLTHINS{i}"]) for i in range(1, 9)]

CONTROLS = ["female", "age", "RRACE", "RHISPANIC", "EEDUC", "MS", "THHLD_NUMADLT",
            "THHLD_NUMKID", "ANYWORK", "UI_SPND", "STIM_SPND", "SNAP_YN", "FREEFOOD",
            "EST_ST", "insured"]

REQUIRED = ["food_insuf", "MS"]
MISSING_AS_CATEGORY = ["INCOME", "insured", "SNAP_YN", "FREEFOOD", "ANYWORK"]

def analytic_sample(d):
    """Paper's sample: under 65; complete on outcome + marital status; other gaps kept as a 'missing' category."""
    s = d[d["age"] < 65].dropna(subset=REQUIRED).copy()
    for c in MISSING_AS_CATEGORY:
        s[c] = s[c].fillna(-1).astype(int)    # -1 = missing / not reported
    return s

def add_insured(d):
    h = d[[f"HLTHINS{i}" for i in range(1, 9)]]
    d["insured"] = np.select(
        [(h == 1).any(axis=1),          # covered by any type
         (h == 2).all(axis=1)],         # answered "no" to every type
        [1, 0], default=np.nan)         # otherwise: unknown
    return d

def load_week(week, raw_dir=RAW_DIR):
    """Read one week's analysis variables. Returns (DataFrame, list of variables not found)."""
    puf_path, _ = find_week_files(week, raw_dir)
    header = pd.read_csv(puf_path, nrows=0).columns
    usecols, rename, missing = [], {}, []
    for name, candidates in VARS:
        hit = next((c for c in candidates if c in header), None)
        if hit is None:
            missing.append(name)
        else:
            usecols.append(hit)
            rename[hit] = name
    df = pd.read_csv(puf_path, usecols=usecols).rename(columns=rename)
    df["SEX_SOURCE"] = next((c for c in ["EGENDER", "EGENID_BIRTH"] if c in header), None)
    # Select-all items: 1 = selected, -99 = seen but not selected (= no), -88 = missing.
    # Recoded per week so a week that never asked the item stays NaN.
    for c in ["UI_SPND", "STIM_SPND"]:
        if c in df:
            df[c] = np.where(df[c] == 1, 1.0, np.where(df[c] == -99, 0.0, np.nan))
    return df, missing


def variable_report(weeks=WEEKS, raw_dir=RAW_DIR):
    """Table of which source column each harmonized variable comes from, by week."""
    rows = {}
    for w in weeks:
        puf_path, _ = find_week_files(w, raw_dir)
        header = pd.read_csv(puf_path, nrows=0).columns
        rows[w] = {name: next((c for c in cands if c in header), "— missing —") for name, cands in VARS}
    return pd.DataFrame(rows).T.rename_axis("week")


def add_derived(d):
    """Derived variables from Section 4 of the proposal."""
    d = d.replace(MISSING_CODES, np.nan)
    d["age"] = 2021 - d["TBIRTH_YEAR"]                       # approximate: birth year only
    d["food_insuf"] = d["CURFOODSUF"].map({1: 0, 2: 0, 3: 1, 4: 1})
    d["kids"] = (d["THHLD_NUMKID"] > 0).astype(int)
    d["post"] = (d["WEEK"] == 34).astype(int)
    d["kids_post"] = d["kids"] * d["post"]
    d["female"] = d["SEX_RAW"].map({1: 0, 2: 1})            # verify coding in each dictionary
    d = add_insured(d)                                       # single health insurance covariate
    d["w"] = d["HWEIGHT"] / N_WAVES                         # pooled weight (paper + Census guidance)
    return d


def build_analysis_file(weeks=WEEKS, raw_dir=RAW_DIR, verbose=True):
    """Stack all weeks, add derived variables. Returns (DataFrame, dict week -> missing vars)."""
    frames, missing_by_week = [], {}
    for w in weeks:
        df, missing = load_week(w, raw_dir)
        frames.append(df)
        missing_by_week[w] = missing
        if verbose:
            print(f"week {w}: {len(df):>7,} rows | sex from {df['SEX_SOURCE'].iat[0]} | "
                  f"missing vars: {missing or 'none'}")
    return add_derived(pd.concat(frames, ignore_index=True)), missing_by_week


def build_repwgt_file(weeks=WEEKS, raw_dir=RAW_DIR, verbose=True):
    """Stack replicate weights (float32) and check each week merges 1:1 with the main file."""
    cols = ["SCRAM", "WEEK"] + [f"HWEIGHT{i}" for i in range(1, 81)]
    reps = []
    for w in weeks:
        puf_path, rep_path = find_week_files(w, raw_dir)
        rep = pd.read_csv(rep_path, usecols=cols, dtype={c: "float32" for c in cols[2:]})
        scram = pd.read_csv(puf_path, usecols=["SCRAM"])
        chk = scram.merge(rep[["SCRAM"]], on="SCRAM", how="outer", indicator=True, validate="1:1")
        unmatched = int((chk["_merge"] != "both").sum())
        if verbose:
            print(f"week {w}: {len(rep):>7,} replicate rows | unmatched: {unmatched}")
        reps.append(rep)
    return pd.concat(reps, ignore_index=True)


def save(df, stem, out_dir=OUT_DIR):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = out_dir / f"{stem}.parquet"
        df.to_parquet(path, index=False)
    except ImportError:
        path = out_dir / f"{stem}.pkl"
        df.to_pickle(path)
    print(f"saved {path}")
    return path


def load(stem, out_dir=OUT_DIR):
    """Load a processed file saved by save(), whichever format was used."""
    out_dir = Path(out_dir)
    if (out_dir / f"{stem}.parquet").exists():
        return pd.read_parquet(out_dir / f"{stem}.parquet")
    return pd.read_pickle(out_dir / f"{stem}.pkl")


def replication_checks(d):
    """First checks against Shafer et al. (2022): sample size and unadjusted rates."""
    u65 = d[d["age"] < 65]
    k = u65[u65["kids"] == 1]
    rows = [{"check": "Respondents under 65, all weeks (before exclusions)",
             "ours": f"{len(u65):,}", "paper": "667,836"}]
    for wk, target in [(33, "14.3%"), (34, "9.9%")]:
        s = k[k["WEEK"] == wk].dropna(subset=["food_insuf"])
        rate = np.average(s["food_insuf"], weights=s["HWEIGHT"]) if len(s) else np.nan
        rows.append({"check": f"Food insufficiency, households with kids, week {wk} (weighted)",
                     "ours": f"{100 * rate:.1f}%", "paper": target})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    data, _ = build_analysis_file()
    save(data, "pulse_w22_34")
    save(build_repwgt_file(), "repwgt_w22_34")
    print(replication_checks(data).to_string(index=False))
