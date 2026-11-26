"""
CSS 211 – Replication of Shafer et al. (2022): data preparation.

Stacks Household Pulse Survey PUFs for weeks 22–34 (Jan 6 – Aug 2, 2021) into
two analysis files:
  data/processed/pulse_w22_34.parquet     -> analysis variables (one row per respondent-week)
  data/processed/repwgt_w22_34.parquet    -> HWEIGHT1–80 keyed by SCRAM + WEEK (Extension b only)

Expected folder layout (unzip each week's CSV zip into data/raw/):
  data/raw/HPS_Week22_PUF_CSV/pulse2021_puf_22.csv
  data/raw/HPS_Week22_PUF_CSV/pulse2021_repwgt_puf_22.csv
  ...
  data/raw/HPS_Week34_PUF_CSV/pulse2021_puf_34.csv

Run:  python prepare_pulse.py
Needs: pandas, numpy, pyarrow (for parquet; falls back to .pkl if missing).
"""
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path("data/raw")
OUT = Path("data/processed")
WEEKS = list(range(22, 35))          # 22..34 -> 13 waves
N_WAVES = len(WEEKS)

# Variables used in the proposal. Some names change across phases; the
# first name found in a week's file is used and harmonized below.
#   (harmonized_name, [candidate column names in priority order])
VARS = [
    ("SCRAM",        ["SCRAM"]),
    ("WEEK",         ["WEEK"]),
    ("EST_ST",       ["EST_ST"]),
    ("HWEIGHT",      ["HWEIGHT"]),
    ("CURFOODSUF",   ["CURFOODSUF"]),
    ("THHLD_NUMKID", ["THHLD_NUMKID"]),
    ("THHLD_NUMADLT",["THHLD_NUMADLT"]),
    ("TBIRTH_YEAR",  ["TBIRTH_YEAR"]),
    ("RRACE",        ["RRACE"]),
    ("RHISPANIC",    ["RHISPANIC"]),
    ("EEDUC",        ["EEDUC"]),
    ("MS",           ["MS"]),
    ("INCOME",       ["INCOME"]),
    ("ANYWORK",      ["ANYWORK"]),
    ("SNAP_YN",      ["SNAP_YN"]),
    ("FREEFOOD",     ["FREEFOOD"]),
    ("SEX_RAW",      ["EGENDER", "EGENID_BIRTH"]),     # week 34 uses EGENID_BIRTH
    ("UI_SPND",      ["SPNDSRC5", "SPND_SRC5"]),       # renamed in week 34
    ("STIM_SPND",    ["SPNDSRC6", "SPND_SRC6"]),
] + [(f"HLTHINS{i}", [f"HLTHINS{i}"]) for i in range(1, 9)]

MISSING_CODES = [-99, -88]            # -99 = seen but not answered, -88 = missing / skipped


def week_dir(w):
    return RAW / f"HPS_Week{w}_PUF_CSV"


def load_week(w):
    puf_path = week_dir(w) / f"pulse2021_puf_{w}.csv"
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
    # Spending-source items are select-all: 1 = selected, -99 = seen but not selected (= no),
    # -88 = item missing. Recode here, per week, so a week that never asked the item stays NaN.
    for c in ["UI_SPND", "STIM_SPND"]:
        if c in df:
            df[c] = np.where(df[c] == 1, 1.0, np.where(df[c] == -99, 0.0, np.nan))
    return df, missing


def load_repwgt(w):
    path = week_dir(w) / f"pulse2021_repwgt_puf_{w}.csv"
    cols = ["SCRAM", "WEEK"] + [f"HWEIGHT{i}" for i in range(1, 81)]
    return pd.read_csv(path, usecols=cols, dtype={f"HWEIGHT{i}": "float32" for i in range(1, 81)})


def save(df, stem):
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(OUT / f"{stem}.parquet", index=False)
        print(f"  saved {OUT / (stem + '.parquet')}")
    except ImportError:
        df.to_pickle(OUT / f"{stem}.pkl")
        print(f"  pyarrow not installed; saved {OUT / (stem + '.pkl')}")


def main():
    frames, reps = [], []
    for w in WEEKS:
        df, missing = load_week(w)
        rep = load_repwgt(w)
        # 1:1 check between PUF and replicate-weight file
        chk = df[["SCRAM"]].merge(rep[["SCRAM"]], on="SCRAM", how="outer",
                                  indicator=True, validate="1:1")
        bad = (chk["_merge"] != "both").sum()
        print(f"week {w}: {len(df):>7,} rows | sex from {df['SEX_SOURCE'].iat[0]} | "
              f"unmatched repwgt rows: {bad} | missing vars: {missing or 'none'}")
        frames.append(df)
        reps.append(rep)

    d = pd.concat(frames, ignore_index=True)
    d = d.replace(MISSING_CODES, np.nan)

    # --- derived variables (Section 4 of the proposal) ---
    d["age"] = 2021 - d["TBIRTH_YEAR"]
    d["food_insuf"] = d["CURFOODSUF"].map({1: 0, 2: 0, 3: 1, 4: 1})
    d["kids"] = (d["THHLD_NUMKID"] > 0).astype(int)
    d["post"] = (d["WEEK"] == 34).astype(int)
    d["kids_post"] = d["kids"] * d["post"]
    d["w"] = d["HWEIGHT"] / N_WAVES          # pooled weight, as in the paper and Census guidance
    # Sex: both items code 1 = male, 2 = female (verify in each week's dictionary)
    d["female"] = d["SEX_RAW"].map({1: 0, 2: 1})

    save(d, "pulse_w22_34")
    save(pd.concat(reps, ignore_index=True), "repwgt_w22_34")

    # --- quick checks against the paper ---
    u65 = d[d["age"] < 65]
    print(f"\nRespondents under 65, all weeks: {len(u65):,}   (paper: 667,836 before exclusions)")
    k = u65[u65["kids"] == 1]
    for wk in (33, 34):
        s = k[k["WEEK"] == wk].dropna(subset=["food_insuf"])
        rate = np.average(s["food_insuf"], weights=s["HWEIGHT"])
        target = {33: 14.3, 34: 9.9}[wk]
        print(f"Weighted food insufficiency, households with kids, week {wk}: "
              f"{100 * rate:.1f}%   (paper: {target}%)")


if __name__ == "__main__":
    main()
