"""Deterministic parsing and enforcement of paper rules, without extra LLM calls."""
import ast
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import json
import re

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
CENT = Decimal("0.01")


@dataclass
class Decision:
    amounts: dict
    raw_decisions: dict
    corrections: list
    parse_failed: bool


def parse_decision(answer):
    text = (answer or "").strip().strip('`').strip()
    for candidate in reversed(re.findall(r"\{[^{}]*\}", text)):
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except (ValueError, SyntaxError, TypeError):
                pass
        pairs = re.findall(r"['\"]?(\d+)['\"]?\s*:\s*(" + NUMBER + r")(?=\s*[,}])", candidate)
        if pairs:
            return dict(pairs)
    scalar = re.fullmatch(NUMBER, text)
    labelled = re.fullmatch(r"(?:\{\s*)?['\"]?(?:total_)?return['\"]?\s*:\s*(" + NUMBER + r")\s*\}?", text, re.I)
    if scalar or labelled:
        return {"total_return": scalar.group(0) if scalar else labelled.group(1)}
    return None


def normalize_decision(answer, neighbor_ids, stage, restriction, budget):
    parsed = parse_decision(answer)
    failed = parsed is None
    corrections = ["parse_failed_zero_decision"] if failed else []
    parsed = parsed or {}
    budget = Decimal(str(budget))
    values = {nid: Decimal(0) for nid in neighbor_ids}
    raw = {str(k): str(v) for k, v in parsed.items()}

    def nonnegative(value):
        try:
            if isinstance(value, bool):
                raise ValueError
            amount = Decimal(str(value))
            if not amount.is_finite():
                raise ValueError
            if amount < 0:
                corrections.append("negative_to_zero")
                return Decimal(0)
            return amount
        except (InvalidOperation, ValueError, TypeError):
            corrections.append("invalid_amount_to_zero")
            return Decimal(0)

    total_key = next((k for k in ("total_return", "return") if k in parsed), None)
    if total_key is not None and stage == "trustee":
        total = nonnegative(parsed[total_key])
        values = {nid: total / len(neighbor_ids) for nid in neighbor_ids}
    elif "total_return" in parsed and stage == "investor":
        total = nonnegative(parsed["total_return"])
        values = {nid: total / len(neighbor_ids) for nid in neighbor_ids}
        corrections.append("scalar_total_distributed_equally")
    else:
        found = set()
        for key, value in parsed.items():
            try:
                if isinstance(key, bool) or not re.fullmatch(r"\d+", str(key)):
                    raise ValueError
                nid = int(key)
            except (ValueError, TypeError):
                corrections.append("unknown_key_ignored")
                continue
            if nid not in values:
                corrections.append("non_neighbor_ignored")
                continue
            if nid in found:
                corrections.append("duplicate_neighbor_last_value_used")
            found.add(nid)
            values[nid] = nonnegative(value)
        if found != set(neighbor_ids) and not failed:
            corrections.append("missing_neighbors_to_zero")
    total = sum(values.values())
    if total > budget:
        values = {nid: value * budget / total for nid, value in values.items()}
        total = budget
        corrections.append("scaled_to_budget")
    if (stage == "trustee" or restriction == "constrained") and len(set(values.values())) > 1:
        values = {nid: total / len(neighbor_ids) for nid in neighbor_ids}
        corrections.append("equalized_neighbors")
    rounded = {nid: value.quantize(CENT, rounding=ROUND_DOWN) for nid, value in values.items()}
    if rounded != values:
        corrections.append("rounded_down_to_cents")
    # Downward rounding never exceeds budget or breaks equal payments.
    return Decision({nid: float(v) for nid, v in rounded.items()}, raw, list(dict.fromkeys(corrections)), failed)
