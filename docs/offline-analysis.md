# Offline workbook analysis

## Input and scope

Input: `src/outputs/2024_NHB_model_Trust Game.xlsx`.

SHA-256 of the workbook inspected for this example:

```text
daed227ca2702476e201b8b79e020e0dfcb374ae64b322350ddea28ae79e9a09
```

The workbook has 15 experiment sheets named `TG <percent>% free session<number>` and a separate participant-information sheet. Every experiment sheet has 49 players × 50 rounds = 2,450 rows. Treatment labels are 0%, 25%, 50%, 75%, and 100% free, with three sessions each. The labels describe the intended treatments; the script does not infer their meaning from participant demographics or relabel them using the observed role counts.

This is an author-supplied workbook. Its original publication citation, data-repository URL, redistribution license, and precise definitions of participant types have not yet been provided. The file name alone is not sufficient evidence for those details. The analysis reads only experiment sheets and does not export participant information. It preserves the original workbook unchanged.

## Fields

The observational key is **(treatment, session, player, round)**. IDs must not be matched across sessions as if they referred to the same participant.

| Workbook field | Exported name | Meaning used by this example |
| --- | --- | --- |
| Sheet name | `proportion`, `session`, `source_sheet` | Treatment fraction, session number, provenance |
| `player.id_in_group` | `player_id` | Player ID within a session |
| `subsession.round_number` | `round` | Round number |
| `player.send_T` | `total_sent` | Recorded total amount sent |
| `player.return_T` | `total_returned` | Recorded total amount returned |
| `player.receive_send_T` | `total_received_send` | Recorded total incoming send amount |
| `player.receive_return_T` | `total_received_return` | Recorded total incoming return amount |
| `player.payoff` | `round_payoff` | Recorded payoff in this round |
| `player.accumulate_payoff` | `accumulate_payoff` | Recorded accumulated payoff |
| `player.send_L/U/R/D` | `sent_amount` in directed export | Recorded outgoing amount for each direction |
| `player.return_L/U/R/D` | `returned_amount` in directed export | Recorded outgoing return for each direction |

The analysis uses the recorded payoff fields. It does not recompute the workbook's payoff from the LLM simulation's endowment and multiplier, since those two experiments have different configurations and the workbook's payoff conventions need source documentation. Incoming amounts are kept in their original units; no extra multiplier or normalization is applied.

The directed export contains `direction` and focal `player_id`. `sent_amount` and `returned_amount` in one row are the focal player's respective outgoing actions in that direction; they must not be interpreted as a matched investment and its reciprocated return from the neighbor. Equal amounts in different directions are all retained.

## Indicator calculation

For each treatment, session and round, the script calculates the arithmetic mean of each recorded total or payoff across players:

```text
session mean = sum(player values) / number of players in that session-round
```

It then calculates the equal-weight average of the three session means at the same treatment and round. `*_std` is the sample standard deviation across session means (`ddof=1`), and `*_count` is the number of nonmissing session means. It is not a standard error or confidence interval. Player observations and repeated rounds are not treated as independent replicates for a significance test.

Gini is calculated separately within each session-round from accumulated payoff. For sorted nonnegative values x[1] ... x[n]:

```text
G = 2 * sum(i * x[i]) / (n * sum(x)) - (n + 1) / n
```

If all values are zero, this example returns 0. If any payoff in the group is negative, the conventional nonnegative Gini is marked undefined (NaN / empty CSV cell). The script neither discards negative observations nor shifts them to zero. The supplied workbook has **79 of 750 session-round groups** with undefined Gini under this rule. In `round_summary.csv`, always check `gini_accumulate_payoff_count`; a mean based on fewer than three sessions is not a complete three-session comparison. Gini itself is averaged across sessions after calculating each session's Gini.

The script rejects missing/nonfinite required numeric values and duplicate player-round keys within a sheet. Entirely blank rows are ignored. This validation is distinct from monetary deduplication: repeated amounts are legitimate observations and are kept.

## Running the example

From the repository root, after installing `requirements-offline.txt`:

```bash
python -m src.analysis.nhb_analysis \
  --input "src/outputs/2024_NHB_model_Trust Game.xlsx" \
  --output-dir outputs/nhb_offline
```

Outputs:

- `player_round.csv`: original experimental observations with renamed totals and sheet provenance.
- `directed_amounts.csv`: four outgoing direction records per player-round, without deduplication.
- `session_round_metrics.csv`: six recorded means plus Gini within each session-round.
- `round_summary.csv`: across-session means, sample SDs and counts for each treatment-round.
- `sheet_inventory.csv`: sheets, row counts, player counts and round counts.
- `manifest.json`: input checksum, counts and analysis rules.

Re-running the command replaces these generated output files. Choose a new `--output-dir` to retain an earlier analysis.

For a quick numerical check, round 1 has the following across-session means (rounded to six decimals):

| Free proportion | Total sent | Total returned | Round payoff |
| --- | --- | --- | --- |
| 0 | 2.147755 | 2.309116 | 4.295510 |
| 0.25 | 3.040612 | 3.542041 | 6.081224 |
| 0.5 | 3.568776 | 3.887891 | 7.137551 |
| 0.75 | 3.618367 | 4.762449 | 7.236735 |
| 1 | 4.299864 | 5.625034 | 8.599728 |

These are checks of this example's aggregation, not independently verified manuscript results.

## Plotting the exported summaries

A basic line chart can be generated from `round_summary.csv` with the installed matplotlib dependency. Save the following as a local script, or run it in a Python notebook from the repository root:

```python
from pathlib import Path
import matplotlib
matplotlib.use("Agg")  # works on a machine without a desktop display
import matplotlib.pyplot as plt
import pandas as pd

out = Path("outputs/nhb_offline")
data = pd.read_csv(out / "round_summary.csv")
fig, ax = plt.subplots(figsize=(6, 4), layout="constrained")
for proportion, group in data.groupby("proportion", sort=True):
    group = group.sort_values("round")
    ax.plot(group["round"], group["total_sent_mean"],
            label=f"{proportion:.0%} free")
ax.set(xlabel="Round", ylabel="Mean total sent (recorded units)")
ax.legend(title="Treatment", fontsize=8, loc="upper left",
          bbox_to_anchor=(1.02, 1), frameon=False)
fig.savefig(out / "mean_total_sent.png", dpi=300)
fig.savefig(out / "mean_total_sent.pdf")
plt.close(fig)
```

Replace `total_sent_mean` with `total_returned_mean` or `round_payoff_mean` for other recorded indicators and change the labels/file names accordingly. For error bands, use the corresponding `*_std` and clearly label them **SD across sessions**, not a confidence interval. For Gini charts, omit or clearly flag treatment-round points where the count is below three.

A boxplot of `directed_amounts.csv` can describe outgoing amounts by treatment, retaining all four directions. Its many observations are dependent within players, rounds, and sessions; the boxplot's observation count must not be used as the independent sample size for a treatment significance test.

The chart above is a plotting example. Final manuscript figures require the author's exact metric, pooling, normalization, uncertainty and exclusion choices. This repository currently does not prescribe inferential tests for the NHB workbook or claim identical figure layouts.

## Historical LLM analysis

`src/analysis/analysy.py` expects the LLM CSV schema, not the NHB workbook. Its hard-coded demonstration path is historical. For a chosen LLM CSV, instantiate `TrustGameAnalyzer([csv_path])` in a separate script and call the desired plotting methods after reviewing their formulas.

`src/experiment/average_3_trust_game_runs.py` is also a historical utility. It checks row alignment and some IDs but can retain the first run's player-type column when types differ. Do not use its averaged rows for role-specific inference without adapting the analysis. The NHB example avoids that issue by summarising each independent session first.
