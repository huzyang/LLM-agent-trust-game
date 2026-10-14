"""Offline audit of archived decisions; never rewrite experimental outcomes."""
import argparse
import ast
from collections import Counter
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from .decisions import NUMBER, normalize_decision


def audit_file(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    summary_path = path.with_name("summary.json")
    scenario = json.loads(summary_path.read_text(encoding="utf-8-sig")).get("scenario", {}) if summary_path.exists() else {}
    counts = Counter(turns=0, original_parse_failures=0, truncated=0,
                     recovered_complete_failures=0, remaining_complete_failures=0,
                     changed_complete_decisions=0, changed_complete_unflagged=0, budget_unavailable=0)
    issues = []
    for round_key, agents in data["dialogs"].items():
        for agent_key, stages in agents.items():
            for stage_key, turn in stages.items():
                counts["turns"] += 1
                stage = stage_key.removeprefix("as_")
                original = {int(k): v for k, v in turn["executed_decision"].items()}
                neighbors = list(original)  # Same ordered IDs as the original prompt.
                truncated = turn.get("finish_reason") == "length"
                complete = turn.get("finish_reason", "stop") == "stop"
                failed = bool(turn.get("parse_failed"))
                counts["original_parse_failures"] += failed
                counts["truncated"] += truncated
                reasons = []
                if failed:
                    reasons.append("original_parse_failed")
                if not complete:
                    reasons.append("output_truncated" if truncated else "incomplete_response")
                match = re.search(r"you received\s*:\s*(" + NUMBER + r")", turn["prompt"], re.I)
                budget = "5" if stage == "investor" else match[1] if match else None
                if stage == "trustee":
                    sent = re.search(r"Neighbors sent:\s*(\{[^{}]*\})", turn["prompt"])
                    if sent:
                        # Old prompts used float sums (14.399999999999999), but
                        # the engine's real budget used exact decimal sums.
                        amounts = ast.literal_eval(sent[1])
                        budget = str(3 * sum((Decimal(str(v)) for v in amounts.values()), Decimal(0)))
                decision = None
                if budget is None:
                    reasons.append("budget_unavailable")
                    counts["budget_unavailable"] += 1
                else:
                    decision = normalize_decision(turn["content"], neighbors, stage,
                                                  agent_key.rsplit("_", 1)[-1], budget)
                    if complete and failed:
                        counts["remaining_complete_failures" if decision.parse_failed else
                               "recovered_complete_failures"] += 1
                    if complete and decision.amounts != original:
                        reasons.append("complete_decision_changed")
                        counts["changed_complete_decisions"] += 1
                        counts["changed_complete_unflagged"] += not failed
                    if complete and decision.parse_failed:
                        reasons.append("still_unparseable")
                if not reasons:
                    continue
                issues.append({
                    "dialogue_path": str(path), "batch": path.parent.parent.name,
                    "run": path.parent.name, "proportion": scenario.get("proportion", ""),
                    "round": int(round_key.removeprefix("round_")),
                    "agent_id": int(agent_key.split("_")[1]), "restriction": agent_key.rsplit("_", 1)[-1],
                    "stage": stage, "issues": reasons, "finish_reason": turn.get("finish_reason", ""),
                    "original_parse_failed": failed, "original_decision": original,
                    "original_corrections": turn.get("corrections", []), "original_budget": budget,
                    "candidate_decision": decision.amounts if decision else None,
                    "candidate_parse_failed": decision.parse_failed if decision else None,
                    "candidate_parse_method": decision.parse_method if decision else None,
                    "candidate_corrections": decision.corrections if decision else None,
                    "response_id": turn.get("response_id", ""), "content": turn["content"],
                })
    return {"dialogue_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "batch": path.parent.parent.name, "run": path.parent.name,
            "proportion": scenario.get("proportion"), **counts}, issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="dialogue.json or experiment/output directory")
    parser.add_argument("--output-dir", required=True, help="New directory for audit reports")
    args = parser.parse_args(argv)
    source, output = Path(args.input).resolve(), Path(args.output_dir).resolve()
    paths = [source] if source.is_file() else sorted(source.rglob("dialogue.json"))
    if not paths:
        parser.error("No dialogue.json files found")
    if output.exists():
        parser.error("Audit output directory must be new")
    reports, issues = [], []
    for path in paths:
        report, rows = audit_file(path)
        reports.append(report)
        issues.extend(rows)
    output.mkdir(parents=True)
    by_batch = {}
    totals = Counter()
    for report in reports:
        counts = {k: report[k] for k in ("turns", "original_parse_failures", "truncated",
                  "recovered_complete_failures", "remaining_complete_failures",
                  "changed_complete_decisions", "changed_complete_unflagged", "budget_unavailable")}
        totals.update(counts)
        by_batch.setdefault(report["batch"], Counter()).update(counts)
    summary = {"files": len(paths), "totals": dict(totals),
               "parser_sha256": hashlib.sha256(Path(__file__).with_name("decisions.py").read_bytes()).hexdigest(),
               "batches": {k: dict(v) for k, v in by_batch.items()}, "sources": reports,
               "note": "Candidates use original recorded budgets, not counterfactual budgets. "
                       "Truncated responses must not execute. Recovered intentions are NOT corrected "
                       "experiment results: earlier errors changed subsequent prompts and behavior."}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "issues.jsonl").open("w", encoding="utf-8") as handle:
        for row in issues:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    if issues:
        with (output / "issues.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(issues[0]))
            writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()} for row in issues)
    print(json.dumps({"files": len(paths), "totals": dict(totals), "batches": summary["batches"],
                      "output_dir": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
