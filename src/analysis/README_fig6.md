# Figure 6

**Main implementation: `fig6.py`.** Native Origin figure, two rows by four columns. Formal figure formats are PDF and EPS only; tight export margins are explicit. Internal editable OPJU and PNG for save/reopen and visual checks are stored in the OS temporary folder, outside the delivery folder.

Current three-session project-only workflow: prepare with `--reuse-fig3 <verified Fig3 directory>` to reuse all three source paths and hashes; only the necessary directional LLM columns absent from allocation-only tables are read. Human directional records and derived phenotype tables both reuse their verified caches. Source-file indexes distinguish identical agent/iteration identifiers across experiments. Fit the LLM clusters jointly across all selected sessions and p levels, separately for each role, using the unchanged approved feature and imputation definitions.

Render with `--project-only --probe` for first-route validation. This delivers `Fig6.opju` directly in the result folder, keeps its owned Origin instance open, and creates only a temporary visual QA PNG; no PDF/EPS is exported. Profile titles a/e are exactly `Entrusted`; c/g are exactly `Returned`. The observed radial values remain in tokens. `verify_fig6_data.py <output directory>` independently recomputes the observed features, counts, imputation lineage and profile summaries.

Corrected incoming units (2026-10-16): LLM raw `received_send_from_n1..4` store pre-multiplier investment. Convert each by 3 before extracting Returned B/C and assert their sum matches the already-tripled `total_received_send`. Human directional receipts already undergo the same conversion. The independent verifier anchors Returned B/C directly to the raw post-tripling aggregate column, rather than relying only on the converted directional table. A boundary regression test checks that pre-tripling total 2 becomes 6 and belongs to B, while pre-tripling total 1 becomes 3 and belongs to C; an already-tripled input is rejected. Use `Fig6_corrected_Origin_20261016` instead of the earlier `Fig6_complete_Origin_20261016` for the complete three-session figure.

Requirements: numpy, pandas, openpyxl, scikit-learn for data preparation. The existing project Python environment already has these. Origin external rendering uses originpro/OriginExt in the existing EditaPlot environment, and does not require scikit-learn. Do not install or modify Origin.

From repository root:

```powershell
.venv\Scripts\python.exe -m unittest src.analysis.test_fig6_data_contract
.venv\Scripts\python.exe -m src.analysis.fig6 prepare --llm outputs\20261015_190032_041570_llm_BDI_payoff-5\agent_rounds.csv
```

The default human source is `human_experiment_datas/2024_NHB_model_Trust Game.xlsx`. A separate, hash-validated phenotype cache stores all 50 rounds of experimental directional records; only the first20 are selected for this figure. Its rounds_20 subfolder caches human observed factors and both imputation-based classification results. Source, feature/fit code hashes and scikit-learn version invalidate stale derived tables. No participant-information worksheet is read, and existing Fig3/4/5 caches remain unchanged.

Run doctor and origin-smoke before a new Origin workflow. First run `render --output-dir <prepared> --probe` under the Origin Python in the current interactive Windows user context. Inspect the temporary PNG, then record the actual visual review in `origin_readback.json`. Formal rendering requires this probe report and identical renderer/shared-module hashes. `all --llm <CSV> --origin-python <OriginPython> --route-evidence <report>` prepares a fresh source-adjacent folder and renders the complete figure. No existing figure is overwritten. The formal source snapshot includes `verified_route_evidence.json`. Use direct `python fig6.py` commands in the snapshot, with `--human` pointing at the actual source workbook; package modules are also included.

See `Fig6_notes.md`, `analysis_plan.json`, `observed_features.csv`, `observed_profiles.csv`, and `missingness_sensitivity.json` for exact definitions and limitations. This is the original A–F/K=3 framework adapted to the user-approved missing-conditional-mean rule; it does not claim an exact recovery of the original authors' implementation. Clusters are relative within population and role; raw profiles contain no imputed observations. Returned B/C use actual tripled receipts; previous-round temporal comparison for Returned D–F compares sends at t−1 with t−2. These interpretation choices are explicitly recorded for review.

No inference of personality, common absolute phenotype thresholds, smoothing, outlier exclusion, or invented replication. No image generation is used. Origin plot data are native worksheet-linked scatter/line/fill objects; radar X/Y are explicit polar-to-Cartesian display coordinates. EPS fills are opaque.
