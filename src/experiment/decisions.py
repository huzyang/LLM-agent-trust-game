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
    parse_method: str = "dictionary"


def parse_decision(answer):
    text = (answer or "").strip().strip('`').strip()
    if text.rfind("{") > text.rfind("}"):
        return None  # Do not fall back to a historical dict when the final one is unfinished.
    for candidate in reversed(re.findall(r"\{[^{}]*\}", text)):
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(candidate)
                if isinstance(parsed, dict) and any(_decision_key(k) for k in parsed):
                    return parsed
            except (ValueError, SyntaxError, TypeError):
                pass
        pairs = re.findall(r"(?<![\w])['\"]?((?:N)?\d+(?:_ID)?|total_return|return)['\"]?\s*:\s*(" + NUMBER + r")(?=\s*[,}])", candidate, re.I)
        if pairs:
            return dict(pairs)
    scalar = re.fullmatch(NUMBER, text)
    labelled = re.fullmatch(r"(?:\{\s*)?['\"]?(?:total_)?return['\"]?\s*:\s*(" + NUMBER + r")\s*\}?", text, re.I)
    if scalar or labelled:
        return {"total_return": scalar.group(0) if scalar else labelled.group(1)}
    return None


def _decision_key(key):
    return (not isinstance(key, bool) and
            re.fullmatch(r"(?:N)?\d+(?:_ID)?|total_return|return", str(key), re.I) is not None)


def _prose_decision(answer, neighbor_ids, stage):
    """Recover explicit final actions only; never infer amounts from BDI beliefs."""
    text = re.sub(r"[*`]", "", answer or "")
    if text.count("{") != text.count("}"):
        return None, "failed"  # An unfinished final dictionary is not a decision.
    headings = list(re.finditer(r"(?:^|\n)\s*(?:Final decision|My decision|Decision|Return amount|Intention)\s*:\s*", text, re.I))
    if not headings:
        return None, "failed"
    text = text[headings[-1].end():].strip()
    # A complete final neighbor list, including lists embedded in a sentence.
    pairs = list(re.finditer(r"\b(?:neighbor|ID)\s+(\d+)\s*:\s*(" + NUMBER + r")\b", text, re.I))
    if len(pairs) == len(neighbor_ids) and {int(m[1]) for m in pairs} == set(neighbor_ids):
        lead = re.split(r"\n|(?<=[.!?])\s+", text[:pairs[0].start()])[-1].strip()
        contiguous = all(re.fullmatch(r"[\s,;\-]*", text[a.end():b.start()]) for a, b in zip(pairs, pairs[1:]))
        action = "send" if stage == "investor" else "return"
        if contiguous and re.fullmatch(r"(?:(?:I\s+will\s+)?" + action + r"\s*:?)?", lead, re.I):
            return {m[1]: m[2] for m in pairs}, "prose_neighbors"
    # Require an explicit action at a sentence/line start, excluding "If I ...",
    # "I considered ...", and all the historical amounts in Belief/Desire.
    action = "send" if stage == "investor" else "return"
    boundary = r"(?:^|[\n.!?]\s+)(?!\d)"
    prefix = (r"(?:(?:I\s+will|I'll|I\s+intend\s+to)\s+)?(?:again\s+)?"
              r"(?:attempt\s+to\s+|state\s+an\s+intention\s+to\s+)?" + action)
    equal = list(re.finditer(
        boundary + r"(?:" + prefix + r"|I\s+will\s+state\s+a\s+return\s+of|I\s+choose)\s+(" + NUMBER +
        r")\s*(?:tokens?\s*)?(?:to\s+)?each(?:\s+(?:of\s+(?:my\s+)?(?:four|4)\s+)?neighbors?)?\b", text, re.I))
    if equal:
        return {str(n): equal[-1].group(1) for n in neighbor_ids}, "prose_equal"
    if stage == "trustee":
        total = list(re.finditer(
            boundary + r"(?:Total\s+returned\s*=|Return\s+total\s*:|" + prefix +
            r"\s+(?:a\s+)?total\s+of)\s*(" + NUMBER + r")\b|" +
            boundary + prefix + r"\s+(" + NUMBER + r")\s*(?:tokens?\s*)?total\b", text, re.I))
        if total:
            return {"total_return": next(v for v in total[-1].groups() if v is not None)}, "prose_total"
        if re.fullmatch(r"State\s+0(?:\.0+)?\s+to\s+all\s+four\s+neighbors\s+as\s+my\s+trustee\s+return.*", text, re.I):
            return {"total_return": "0"}, "prose_total"
    return None, "failed"


def normalize_decision(answer, neighbor_ids, stage, restriction, budget):
    parsed = parse_decision(answer)
    method = "dictionary"
    if parsed is None:
        parsed, method = _prose_decision(answer, neighbor_ids, stage)
    failed = parsed is None
    corrections = ["parse_failed_zero_decision"] if failed else []
    if method.startswith("prose_"):
        corrections.append("parsed_explicit_prose")
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

    total_key = next((k for k in parsed if str(k).lower() in ("total_return", "return")), None)
    if total_key is not None:
        total = nonnegative(parsed[total_key])
        values = {nid: total / len(neighbor_ids) for nid in neighbor_ids}
        if stage == "investor":
            corrections.append("scalar_total_distributed_equally")
    else:
        found = set()
        # N1_ID ... N4_ID in the prompt are slots, not actual IDs. Other N<ID>_ID
        # and <ID>_ID spellings explicitly refer to the numbered neighbor.
        positional = {str(k).upper() for k in parsed} == {
            f"N{i+1}_ID" for i in range(len(neighbor_ids))}
        for key, value in parsed.items():
            try:
                match = re.fullmatch(r"(N)?(\d+)(_ID)?", str(key), re.I)
                if isinstance(key, bool) or not match:
                    raise ValueError
                nid = neighbor_ids[int(match[2])-1] if positional else int(match[2])
            except (ValueError, TypeError):
                corrections.append("unknown_key_ignored")
                continue
            if nid not in values:
                corrections.append("non_neighbor_ignored")
                continue
            if match[1] or match[3]:
                corrections.append("neighbor_alias_resolved")
            if nid in found:
                corrections.append("duplicate_neighbor_last_value_used")
            found.add(nid)
            values[nid] = nonnegative(value)
        if found != set(neighbor_ids) and not failed:
            corrections.append("missing_neighbors_to_zero")
        if not found:
            failed = True
            method = "failed"
            corrections.append("parse_failed_zero_decision")
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
    return Decision({nid: float(v) for nid, v in rounded.items()}, raw, list(dict.fromkeys(corrections)), failed, method)
