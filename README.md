# CTC-Food-Insufficiency

A replication and extension of Shafer et al. (2022), *Association of the Implementation of Child Tax Credit Advance Payments With Food Insufficiency in US Households* (JAMA Network Open 5(1): e2143296), using public Census Household Pulse Survey microdata.
---
*Final project for CSS 211 (Statistical Methods), M.S. in Computational Social Science course at UC San Diego*

## Summary

The expanded Child Tax Credit (CTC) began paying families monthly in July 2021. Shafer et al. compared food insufficiency (not having enough to eat in the last 7 days) among U.S. households with and without children, before and after the first advance payment on July 15, 2021, and reported a 3.7-percentage-point (about 26%) reduction for households with children.

This repository reproduces their analytic sample and main estimates exactly at the paper's reported precision, then tests how robust those estimates are.

| Quantity | Paper | This replication |
|---|---|---|
| Analytic sample (n) | 585,170 | 585,170 |
| Food insufficiency, households with children, week 33 / 34 | 14.3% / 9.9% | 14.3% / 9.9% |
| Event-study estimate, week 34 (95% CI) | -0.037 (-0.055 to -0.019) | -0.037 (-0.055 to -0.019) |
| Pooled difference-in-differences | -0.022 (P = .001) | -0.022 (p = .0006) |

**Beyond the original paper:**

- **The size of the effect depends on the comparison period.** Pre-payment event-study coefficients reject parallel trends under state-clustered standard errors (p = .001). Re-estimating against different reference periods gives effects of 2.2 to 3.7 percentage points; all are negative and statistically significant. The paper's week-33 reference gives the largest estimate, which may be appropriate if the June rise in the gap reflects children losing school meals over the summer.
- **Census replicate-weight standard errors (Extension b)** are 6-7% larger than state-clustered ones; the week-34 effect remains significant (p < .001). The parallel-trends test is no longer rejected at the 0.05 level (p = .097), so the evidence against parallel trends depends on the variance method.
- **State heterogeneity (Extension a):** there is no detectable variation in the effect across states (Cochran's Q = 58.4 on 50 df, p = .19), though the test has limited power.
- **Survey weights matter:** the unweighted estimate is about a third of the weighted one, suggesting the association was concentrated among groups that respond to the survey less often, such as lower-income households.
- **Undocumented choices surfaced by the replication:** the paper's missing-data handling (only rows missing the outcome or marital status are dropped; other covariates keep missing as a category) and its inference method (state-clustered standard errors with a t-distribution and 50 degrees of freedom) are not stated in its Methods but are needed to reproduce its numbers.

## Repository structure

```
CTC-Food-Insufficiency/
├── data/                   # not tracked by git (see Data below)
│   ├── raw/                # Census zip files and their extracted CSVs
│   └── processed/          # analysis files and cached replicate-weight results
├── figures/                # figures saved by the notebooks
├── modules/
│   ├── get_data.py         # download and unzip the Census files
│   ├── prepare_pulse.py    # stack weeks, harmonize variables, build the analytic sample
│   ├── analysis.py         # replication models (DiD, event study, sensitivity checks)
│   └── extensions.py       # replicate-weight inference and state heterogeneity
├── notebooks/
│   ├── data_prep.ipynb     # 1. build the analysis files
│   ├── replication.ipynb   # 2. reproduce the paper's estimates
│   └── extensions.ipynb    # 3. Extensions (a) and (b)
├── requirements.txt
└── README.md
```

## Data

The analysis uses the U.S. Census Bureau Household Pulse Survey public use files for **weeks 22-34** (January 6 - August 2, 2021), CSV format. The data is public and de-identified; it is not included in this repository because of its size (about 1 GB).

Each week's zip contains the main data file, a replicate-weight file, and a data dictionary. There are two ways to get them:

1. **Automatic:** set `DOWNLOAD = True` in the first step of `notebooks/data_prep.ipynb` to download all 13 zips from Census into `data/raw/`.
2. **Manual:** download the weeks 22-34 CSV zips from the [Census 2021 Household Pulse Survey data page](https://www.census.gov/programs-surveys/household-pulse-survey/data/datasets.2021.html) and place them, still zipped and with their original names (e.g. `HPS_Week22_PUF_CSV.zip`), in `data/raw/`.

The notebook unzips the files and builds everything else.

## Setup

Requires Python 3 with the packages in `requirements.txt`:

```bash
git clone git@github.com:Roseyroseo/CTC-Food-Insufficiency.git
cd CTC-Food-Insufficiency
pip install -r requirements.txt
```

The models fit on about 585,000 rows; 8 GB of RAM or more is recommended. The state-level model in `extensions.ipynb` needs roughly 2-3 GB on its own.

## Reproducing the analysis

Run the notebooks in order:

1. **`data_prep.ipynb`:** downloads (optionally) and unzips the raw files, checks variable names across weeks, stacks the 13 weeks, builds derived variables, and saves the analytic sample. It stops with an error if the sample does not reproduce the paper's n = 585,170.
2. **`replication.ipynb`:** unadjusted rates, the pooled difference-in-differences, the event study and its parallel-trends test, a logistic robustness check, and the sensitivity of the week-34 estimate to the reference period.
3. **`extensions.ipynb`:** Extension (b), Census replicate-weight standard errors, and Extension (a), state heterogeneity. Replicate-weight results are cached in `data/processed/replicate_cache/`, so only the first run is slow.

## Figures

| File | Shows |
|---|---|
| `unadjusted_food_insufficiency.png` | Weekly food insufficiency for households with and without children |
| `event_study_estimates.png` | Event-study coefficients with 95% CIs |
| `beta34_by_reference.png` | The week-34 estimate under different reference periods |
| `replicate_vs_cluster_ci.png` | State-clustered vs. replicate-weight confidence intervals |
| `state_effects.png` | State-specific effects of the first payment |

## Methods notes

- **Models:** weighted linear probability models with wave and state fixed effects and the paper's covariates. Weights are the household weight divided by 13 for pooled weeks.
- **Inference:** state-clustered standard errors with a t-distribution and 50 degrees of freedom (replication); Census successive-difference-replication standard errors with 80 replicate weights (Extension b).
- **Extension (a):** the proposal planned a mixed model with a state random slope. It could not be estimated reliably with statsmodels at this sample size, so the same hypothesis is tested by estimating a separate effect for each state and applying Cochran's Q test. Details are in the appendix of `extensions.ipynb`.

## References

- Shafer, P. R., Gutiérrez, K. M., Ettinger de Cuba, S., Bovell-Ammon, A., & Raifman, J. (2022). Association of the implementation of Child Tax Credit advance payments with food insufficiency in US households. *JAMA Network Open, 5*(1), e2143296. https://doi.org/10.1001/jamanetworkopen.2021.43296
- U.S. Census Bureau. (2021a). *Household Pulse Survey public use files, weeks 22-34* [Data set]. https://www.census.gov/programs-surveys/household-pulse-survey/data/datasets.2021.html
- U.S. Census Bureau. (2021b). *Source of the data and accuracy of the estimates for the Household Pulse Survey - Phase 3.1* [Week 33]. https://www2.census.gov/programs-surveys/demo/technical-documentation/hhp/Phase3-1_Source_and_Accuracy_Week_33.pdf
- Cameron, A. C., & Miller, D. L. (2015). A practitioner's guide to cluster-robust inference. *Journal of Human Resources, 50*(2), 317-372.
- Seabold, S., & Perktold, J. (2010). statsmodels: Econometric and statistical modeling with Python. *Proceedings of the 9th Python in Science Conference* (pp. 92-96). https://doi.org/10.25080/Majora-92bf1922-011

## Author

Rosey A Gutierrez
