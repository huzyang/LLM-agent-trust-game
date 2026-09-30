# Local verification

Checked on 2026-09-30 using a new Python 3.12.14 virtual environment. Direct dependencies are in `requirements.txt`; the installed package versions are in `requirements-lock.txt`.

Completed checks:

- Dependency installation and `python -m pip check`: no broken requirements.
- Import of the simulation model and pair-data analysis module.
- Full and small JSON configuration dry-runs: 7,200 and 18 planned agent-stage calls respectively; no API requests.
- Offline workbook analysis: 36,750 player-round rows, 147,000 directed rows, 750 session-round summaries, 250 treatment-round summaries.
- Summary row counts and across-session means checked against the original player records for each treatment's first round.
- Sum of directed sends checked against the recorded total sends.
- Known Gini examples checked: equal values yield 0; [0, 1] yields 0.5. Negative-payoff groups remain undefined.
- Equal-amount transactions checked to remain present in grouped pair exports.
- A nine-agent, one-round simulation with locally replaced model/chat objects and zero decisions: nine agent-round records, 36 pair records, payoff of 5 per agent. No remote API requests; this validates local flow only.
- The documented matplotlib plotting example executed and its PNG inspected. This is a descriptive example, not a publication-layout certification; automated PDF collision QA was unavailable because the audit runtime lacks PyMuPDF.
- Python source syntax and `git diff --check`.

Not verified:

- DeepSeek authentication, balance, model availability, SDK response parsing against a live endpoint, or a paid experiment.
- Exact correspondence between the example indicators/figures and a manuscript.
- Recovery of historical dependency versions, original workbook provenance, or redistribution permissions.

The current checks use the working-tree prompt templates, which include author edits made before this documentation task. Before a paper release, freeze the intended prompts together with the code and data versions.
