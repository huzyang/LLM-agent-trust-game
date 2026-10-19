# Fig. 2 reproduction

Main entry: `fig2.py`; raw-data/statistics entry: `fig2_prepare.py`.
`fig2_screening.py` reconstructs legacy allocation dictionaries and indexes text.
`fig3.py` supplies the established isolated Origin lifecycle and helpers.

From the repository root, with a Python containing numpy/pandas:

```powershell
python -m src.analysis.fig2 prepare --input 'PATH\llm_base' --output 'PATH\Fig2_output'
```

Optionally reuse the previously verified text/allocation cache with `--cache PATH`.
Its input hashes must match the five raw JSONs. A missing/stale cache is rebuilt.
The original JSONs are never written. No human-data workbook is needed.

With the existing external Origin-capable Python, in the interactive Windows session:

```powershell
python -m src.analysis.fig2 render --output 'PATH\Fig2_output'
```

Use `all` with both `--input` and `--output` to run both stages. Figures are native
editable Origin layers. A new isolated instance is owned by this script; no existing
user project is attached/reset. The successful instance remains open. Delivery is
project only, following the established user preference; a temporary PNG is for QA.

Text coding is automated and conservative, not independently human validated.
Positive labels: explicit_current / possible_adopted. Controls: no_detected_current.
uncertain_or_conflicting is retained and excluded from e/f comparisons, but remains
in the c/d denominator (36). BDI is primary; reasoning_content is separate.
Amounts are the recorded dictionaries; unknown execution corrections are not invented.

For adjudication, copy adjudication_template.csv and fill reviewed_label, reviewer,
review_notes for the selected rows. Leave unused reviewed_label cells blank.
Pass that file with --adjudication during prepare/all. Overrides are logged, including
the prior automated label; no existing manual labels are silently replaced.

e: current entrusted total minus preceding-three-round individual mean.
f: current returned fraction minus mean of valid ratios from preceding three rounds.
Returned fraction = total returned / (three times the investment received).
Zero denominators are undefined, not zero; groups retain n and valid n in source data.
Only rounds 10/20 are displayed in e/f. One supplied session per p; no independent-
repeat errors or significance tests. Small points: individuals; large: group mean.

The delivered source/ directory is also a Python package. From its parent directory,
`python -m source.fig2 ...` works with the same options. See analysis_plan.json,
data_verification.json and origin_readback.json for provenance/checks.
