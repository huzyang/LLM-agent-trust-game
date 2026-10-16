# Complete three-session Figure3

**Main implementation: `fig3_complete.py`**. Scientific tables and the native quartile-box/scatter/CI route reuse `fig3.py`; the earlier Fig3/4/5/6 scripts and their palette constants are not modified. The new static renderer changes the LLM condition palette to Fig4, uses opaque marks for EPS compatibility, gives upper distributions and lower mean comparisons appropriate common scales across populations, and exports only tight PDF/EPS as formal figures.

Data: the three `agent_rounds_session_1/2/3.csv` files in `outputs/llm_experiment_datas_summary`. Each is verified against one hash-identical original run CSV. Original configurations must agree; all events are scanned for `response_model`. A conflicting copied config is preserved and documented, not used to override runtime provenance. The source workbook for Human data defaults to `human_experiment_datas/2024_NHB_model_Trust Game.xlsx`; validated first20-round tables are loaded from the existing cache.

Both populations use first20 rounds, three sessions and49 individuals per session per p. All147 individual20-round means per p are retained. Upper: native25–75% boxes plus raw individual means and horizontal mean marks, no CI. Lower: overall mean and conventional95% t interval across individual means (n=147), as previously approved. The interval does not model within-network dependence and is not a between-session interval. Independent session summaries are retained separately. No source changes, averaging of agent IDs across sessions, smoothing, exclusions or invented repeats.

```powershell
# From repository root. Preparation creates a new timestamped folder.
.venv\Scripts\python.exe -m src.analysis.fig3_complete prepare --root outputs\llm_experiment_datas_summary
```

Run EditaPlot doctor and an isolated origin-smoke before rendering. Use the existing Origin-capable Python (originpro/OriginExt) to run `render --output-dir <prepared> --probe`. After actual visual review, pass the same-source probe report to formal rendering with `--route-evidence <probe/origin_readback.json>`. `all --root <data root> --origin-python <OriginPython> --route-evidence <probe>` performs the entire pipeline. Source snapshots include all project-local helper modules and the passed probe report. Use `python fig3_complete.py ...` rather than module syntax in a standalone snapshot, and provide `--human` explicitly.

The preparation interpreter needs numpy, pandas, scipy and openpyxl; these already exist in the project environment. Rendering uses the existing EditaPlot Python. Internal editable OPJU and PNG used for native save/reopen and visual checks live in the temporary QA directory recorded in `origin_readback.json`; formal graph exports beside the selected data are PDF/EPS only. Tight bounding boxes are requested with `expGraph tr.Margin=1`. No installation or modification of Origin is performed.
