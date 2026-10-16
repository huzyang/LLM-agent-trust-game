# Figure 5 reproduction

**Main script: `fig5.py`.** Requires Python 3.10–3.12, numpy, pandas, openpyxl; native rendering additionally requires originpro/OriginExt and physical Windows with Origin 2021+. Use existing project `.venv` for preparation and the EditaPlot managed Python for rendering. No packages are installed by this pipeline.

From the repository root:

```powershell
& .venv\Scripts\python.exe -m src.analysis.fig5 prepare --llm-session outputs\20261015_190032_041570_llm_BDI_payoff-5\agent_rounds.csv
& .venv\Scripts\python.exe -m unittest src.analysis.test_fig5_data_contract
```

Preparation creates a fresh timestamped folder beside the source CSV; it never overwrites raw data or an existing output directory. The human source defaults to `human_experiment_datas/2024_NHB_model_Trust Game.xlsx`. A separate hash-validated wealth cache in that folder stores full experimental payoff histories and group identities. Participant-information sheets are not read. Existing Fig3/Fig4 caches are not modified.

New native routes require an isolated full probe (`render --probe`), exported-image review and a passed `origin_readback.json`. The formal render must receive that same-source probe report via `--route-evidence`. Run the EditaPlot doctor and isolated origin-smoke before rendering. Use the exact current-user command approval when the automation process reports a sandbox identity. Never attach/reset another Origin project. Once a probe passes, `all --llm-session <CSV> --human <XLSX> --origin-python <OriginPython> --route-evidence <probe report>` performs raw-data preparation and native plotting in one command. Formal source snapshots include the approved `verified_route_evidence.json`; reuse is allowed only when the renderer, shared module and installed Origin version match the probe.

`run_fig5.ps1` supplies preparation and rendering stages. In a source snapshot, run `python fig5.py ...` instead of `python -m src.analysis.fig5 ...`, and pass `--human` explicitly if the original repository location is unavailable. The launcher also accepts the original absolute human source.

The delivered source package also has `run_this_fig5.ps1`: a convenience entry point with this machine's raw CSV, human workbook and Python paths prefilled. Run it to create a fresh complete reproduction; its parameters allow paths to be changed on another compatible Windows machine. `fig5.py` remains the main implementation. The package includes plotting/data dependencies but does not redistribute either raw dataset or install Origin.

Four editable native layers: LLM wealth, Human wealth, LLM Gini, Human Gini. Both populations use cumulative payoffs at round 20 (validated against the sum of rounds 1–20). Constrained/Free/Combined are distinct display groups; Combined intentionally duplicates the two component samples. Wealth error bars describe individual dispersion (sample SD), not session uncertainty. Gini is calculated within each session first, then averaged across sessions with equal session weights. Black Gini markers show actual session values. Endpoint-absent groups remain absent. Negative wealth is retained, as explicitly approved by the user; any observed coefficient outside 0–1 or a nonpositive group total stops the workflow for scientific review without automatically changing the data. No trimming, normalization, pooling sessions for Gini, pseudoreplication-based inference or finite-size Gini correction. Figure captions and exact group sample sizes are in the output tables and notes.

Colors match Fig4 by nominal p separately for each population. Shape/offset/lightness identify the three groups; the individual Y observations and exact SD bounds are preserved. Horizontal jitter alone uses deterministic randomness.
