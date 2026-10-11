# LLM-agent-trust-game

LLM agents replay the spatial trust-game rules in Jia et al. (2025), *Social networking agency and prosociality are inextricably linked in economic games*, [Nature Human Behaviour](https://doi.org/10.1038/s41562-025-02289-0).

[中文说明](README.zh-CN.md) · [Paper rules and implementation](docs/trust-game-protocol.md) · [Verification](docs/verification.md) · [Offline workbook metrics](docs/offline-analysis.md)

## Installation

Use Python 3.12. Run commands from the project root.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-experiment.txt
.\.venv\Scripts\python.exe -m pip check
```

The online experiment needs only four direct packages: openai, python-dotenv, pandas and openpyxl. Mesa, CAMEL and MCP are no longer required. This does not uninstall packages from an existing environment; use a fresh virtual environment for the reduced dependency set.

- `requirements-experiment.txt`: minimal experiment dependencies.
- `requirements-experiment-lock.txt`: their 26-package dependency closure inspected on Python 3.12.4 / Windows.
- `requirements-offline.txt`: supplied workbook analysis only.
- `requirements-analysis.txt`: offline plus legacy plotting tools.
- `requirements.txt` / `requirements-lock.txt`: combined experiment and analysis environment (40 resolved packages).

On Linux/macOS use `python3.12 -m venv .venv`, `source .venv/bin/activate`, then `python -m pip install ...`. Lock files describe the current environment, not the historical experiments.

## Default experiment

Copy `.env.example` to `.env` and enter your own `DEEPSEEK_API_KEY`. Existing `.env` files are preserved. Model names now come from configuration, not the historical `DEEPSEEK_MODEL` variable.

```powershell
.\.venv\Scripts\python.exe -m src.experiment.run_main --dry-run
.\.venv\Scripts\python.exe -m src.experiment.run_main --mock
.\.venv\Scripts\python.exe -m src.experiment.run_main
```

The first command validates without API calls or output files. The second generates explicitly labelled offline MOCK data. The third makes real API requests and consumes account credit. Direct invocation of `python src/experiment/run_main.py` is also supported.

| Setting | Default |
| --- | --- |
| Players / grid | 9 / 3 × 3 periodic four-neighbor lattice |
| Free-player fraction / repeats / rounds | 0.5 / 1 / 1 |
| Model | deepseek-flash |
| Thinking / BDI / known total rounds | Disabled / disabled / disabled |
| History | Last 3 complete rounds, plus current-round messages |
| Base seed | 42; independent derived seed for each run |
| Output / local context budget | 512 tokens / 131,072 |
| Request timeout / retries | 60 seconds / 2 retries after initial attempt |
| Calls before retries | 18 |

Role counts use floor(N×p): the default has 4 free players out of 9. Both requested and actual proportions are logged. Seeds reproduce role assignment, not remote model responses.

Default thinking is explicitly disabled with DeepSeek's `extra_body={"thinking":{"type":"disabled"}}`. Set `"thinking": true` in JSON to enable it; the corresponding comment is in `src/experiment/llm.py`. For other OpenAI-compatible providers configure `api_base_url`, `api_key_env`, `model_type_list` and provider-specific `extra_body`. Put credentials in environment variables, never JSON.

## Resume and logs

A successful decision, executed amounts, history and next-player cursor are atomically checkpointed before the next request. API failures retry only for connection/timeouts, 408/409/429 and server errors. Authentication, balance, configuration and context errors pause immediately; API failures never become zero player actions. Ctrl+C also pauses. Exit code 2 means paused/failure; 0 means complete/validated.

```powershell
.\.venv\Scripts\python.exe -m src.experiment.run_main --resume "outputs/your_experiment"
```

Resume uses the checkpointed model, roles, prompts, mode and scientific settings, and reloads credentials from the environment. Saved calls are skipped. Only `context_limit`, `max_tokens`, `request_timeout`, `max_retries` and `retry_delay` can be changed using `--config` on resume. Core code and prompt hashes must match.

For example, if the context cap was too small, make a JSON file containing `{"context_limit": 262144}` (only if your provider supports it), then resume with `--config that_file.json`. No automatic summary or silent history truncation is used beyond the explicitly selected window. `history_rounds: null` selects full history for a new experiment.

The local context guard uses a conservative UTF-8-byte estimate plus output allowance, not an exact provider tokenizer. Provider context rejection also pauses. A process killed between remote acceptance and local checkpoint completion may need to repeat that uncertain request; remote exactly-once billing cannot be guaranteed.

Output goes to `outputs/<timestamp>_llm/` or an explicit empty `--output-dir`:

| File | Purpose |
| --- | --- |
| run.log | Detailed timestamped per-agent execution/debug log |
| events.jsonl | Request messages, API attempts/errors, usage, raw and executed decisions |
| checkpoint.json | Authoritative resume state, roles and dialogue |
| config.json | Credential-free configuration and fingerprints |
| run_001_<model>/dialogue.json | All raw answers and corrections; independent of request history pruning |
| run_001_<model>/agent_rounds.csv | Player-round records, payoff and correction flags |
| run_001_<model>/pair_data.xlsx | Directed investments with the corresponding reverse return |
| summary.json | Aggregate calls, tokens, corrections and parse failures |
| agent_rounds.csv / pair_data.xlsx | Completed batch data |

The console prints configuration, run/stage progress, retries, pauses and final paths. It does not print personalities, full prompts or every decision. Large populations get a progress line every ten saved decisions. API keys are excluded/redacted from configuration and logs. Preserve checkpoint and prompts with the code version.

## Paper protocol and full-size configuration

The human experiment used 49 participants, 50 rounds, five treatments and three independent sessions per treatment. `configs/paper.json` reflects those sizes; `configs/smoke.json` matches the small default.

```powershell
.\.venv\Scripts\python.exe -m src.experiment.run_main --config configs/paper.json --dry-run
```

The full configuration plans **73,500 calls per model**, before retries. Run it only when you intend that workload. The 2026-10-10 validation ran the 18-call default, not the full experiment.

The paper's trustor payoff is **received return − sent**, excluding unspent endowment; trustee payoff is **3×received investment − returned**. This fixes the historical extra +5. Both trustee types return equally to all four neighbors. Invalid decisions are automatically normalized (budget scaling, equalization, missing values, cent rounding); entirely unparseable output becomes a flagged zero action. All interventions are recorded. Pair returns are the trustee-to-trustor direction, fixing the old reversed field.

The LLM setup retains the repository's English personas, uses an explicitly chosen memory window, and does not simulate human monetary incentives or interface timing. It reproduces game mechanics, not the human participant population or the paper's separate empirical-probability numerical model. New results should not be silently pooled with historical data under the old payoff/return conventions. Detailed source anchors and limitations are in [trust-game-protocol.md](docs/trust-game-protocol.md).

## Offline human workbook analysis

Install `requirements-offline.txt`. No API credentials are needed:

```bash
python -m src.analysis.nhb_analysis \
  --input "src/outputs/2024_NHB_model_Trust Game.xlsx" \
  --output-dir outputs/nhb_offline
```

The supplied workbook has 15 experimental sheets: five treatments × three sessions, 49 players × 50 rounds per sheet. The script preserves 36,750 player-round records and 147,000 directional amount records; it excludes the participant-information sheet. Session-round metrics are averaged equally across sessions, and negative-wealth Gini groups remain undefined. It uses the recorded payoffs and does not change the source workbook.

This is a descriptive analysis route, not certification of exact paper figure/statistical reproduction. See [offline-analysis.md](docs/offline-analysis.md).

## Tests and pair exports

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s test -p test_experiment.py -v
.\.venv\Scripts\python.exe -m src.analysis.pair_data_analysy --input "outputs/your_experiment/pair_data.xlsx" --output outputs/pair_plot_data.xlsx
```

Regression checks cover paper payoff, grid/seed reproducibility, legal amounts, history windows, mid-stage and boundary recovery, context pauses, API retry policy, thinking controls, mock/export and imports without Mesa/CAMEL/MCP. Equal-amount transactions are retained.

`test/test_exp.py` and `src/experiment/average_3_trust_game_runs.py` are historical data-processing routines with dataset/path assumptions; they are not the regression suite. Player IDs and role assignments must not be treated as the same subject across independent sessions.

## Publication and reuse

Record the code commit, config, prompts, endpoint, response model, call date and raw decisions with any experiment. The paper citation identifies the intended game design; workbook provenance, redistribution conditions and code/data licenses still need author confirmation. Historical inputs under `src/outputs/` are preserved; new outputs and credentials are ignored by Git.
