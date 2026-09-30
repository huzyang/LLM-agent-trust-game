"""Offline descriptive analysis of the supplied NHB trust-game workbook.

Only TG experiment sheets are loaded; participant information is not processed.
This example does not claim to reproduce a manuscript's exact figures or tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from src.utils import CommonUtils

METRICS = {
    "player.send_T": "total_sent",
    "player.return_T": "total_returned",
    "player.receive_send_T": "total_received_send",
    "player.receive_return_T": "total_received_return",
    "player.payoff": "round_payoff",
    "player.accumulate_payoff": "accumulate_payoff",
}


def gini(values):
    """Gini on nonnegative payoffs; undefined for groups containing negatives."""
    x = np.sort(np.asarray(values, dtype=float))
    if not np.isfinite(x).all():
        raise ValueError("Gini requires finite payoffs")
    if (x < 0).any():
        return float("nan")
    if x.sum() == 0:
        return 0.0
    n = len(x)
    return float(2 * np.dot(np.arange(1, n + 1), x) / (n * x.sum()) - (n + 1) / n)


def load_workbook(path):
    frames = []
    inventory = []
    workbook = pd.ExcelFile(path)
    for sheet in workbook.sheet_names:
        match = re.fullmatch(r"TG (\d+)% free session(\d+)", sheet)
        if not match:
            continue
        frame = pd.read_excel(workbook, sheet_name=sheet)
        required = {"player.id_in_group", "subsession.round_number", *METRICS}
        required.update(f"player.{kind}_{direction}" for kind in ("send", "return") for direction in "LURD")
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{sheet}: missing columns {sorted(missing)}")
        frame = frame.dropna(how="all").copy()
        for column in required:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
            if frame[column].isna().any() or not np.isfinite(frame[column]).all():
                raise ValueError(f"{sheet}: missing or nonfinite values in {column}")
        ids = ["player.id_in_group", "subsession.round_number"]
        if frame.duplicated(ids).any():
            raise ValueError(f"{sheet}: duplicate player-round keys")
        frame["proportion"] = int(match[1]) / 100
        frame["session"] = int(match[2])
        frame["source_sheet"] = sheet
        inventory.append({"sheet": sheet, "rows": len(frame),
                          "players": int(frame[ids[0]].nunique()),
                          "rounds": int(frame[ids[1]].nunique())})
        frames.append(frame)
    if not frames:
        raise ValueError("No 'TG <percent>% free session<number>' sheets found")
    result = pd.concat(frames, ignore_index=True)
    result = result.rename(columns={**METRICS, "player.id_in_group": "player_id",
                                    "subsession.round_number": "round"})
    return result, inventory


def analyze(path, output):
    data, inventory = load_workbook(path)
    output.mkdir(parents=True, exist_ok=True)
    keys = ["proportion", "session", "round"]
    metrics = list(METRICS.values())
    session_round = data.groupby(keys, as_index=False)[metrics].mean()
    inequalities = data.groupby(keys)["accumulate_payoff"].apply(gini).rename("gini_accumulate_payoff").reset_index()
    session_round = session_round.merge(inequalities, on=keys, validate="one_to_one")
    all_metrics = metrics + ["gini_accumulate_payoff"]
    summary = session_round.groupby(["proportion", "round"])[all_metrics].agg(["mean", "std", "count"])
    summary.columns = [f"{metric}_{stat}" for metric, stat in summary.columns]
    summary = summary.reset_index()
    # Equal amounts on different directions remain separate observations.
    pairs = []
    for direction in "LURD":
        part = data[["proportion", "session", "round", "player_id", "source_sheet"]].copy()
        part["direction"] = direction
        part["sent_amount"] = data[f"player.send_{direction}"]
        part["returned_amount"] = data[f"player.return_{direction}"]
        pairs.append(part)
    pair_data = pd.concat(pairs, ignore_index=True)
    data.to_csv(output / "player_round.csv", index=False)
    pair_data.to_csv(output / "directed_amounts.csv", index=False)
    session_round.to_csv(output / "session_round_metrics.csv", index=False)
    summary.to_csv(output / "round_summary.csv", index=False)
    pd.DataFrame(inventory).to_csv(output / "sheet_inventory.csv", index=False)
    manifest = {"input_name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "player_round_rows": len(data), "directed_rows": len(pair_data),
                "session_round_rows": len(session_round), "summary_rows": len(summary),
                "proportions": sorted(data.proportion.unique().tolist()),
                "aggregation": "Within-session player mean, then equal-weight session mean and sample SD (ddof=1).",
                "deduplication": False,
                "gini_undefined_groups": int(session_round.gini_accumulate_payoff.isna().sum()),
                "gini_policy": "Groups with negative accumulated payoffs are undefined (empty CSV cell); no observations are dropped or shifted.",
                "excluded": "Non-TG sheets, including Participant information"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return summary


def main():
    root = Path(CommonUtils.get_project_root_path())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=root / "src/outputs/2024_NHB_model_Trust Game.xlsx")
    parser.add_argument("--output-dir", type=Path, default=root / "outputs/nhb_offline")
    args = parser.parse_args()
    analyze(args.input, args.output_dir)


if __name__ == "__main__":
    main()
