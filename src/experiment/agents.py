"""Plain Python agents on a fixed periodic four-neighbor lattice."""
from dataclasses import dataclass, field
from decimal import Decimal


def amount_sum(values):
    return float(sum((Decimal(str(v)) for v in values), Decimal(0)))


@dataclass
class BaseAgent:
    model: object
    unique_id: int
    coordinate: tuple
    neighbor_ids: list
    type_restriction: str = "constrained"
    invested_amounts: list = field(default_factory=list)
    received_from_neighbors: list = field(default_factory=list)
    returned_to_neighbors: list = field(default_factory=list)
    received_returns: list = field(default_factory=list)
    history: list = field(default_factory=list)
    balance: float = 0.0
    last_balance: float = 0.0
    system_prompt: str = ""

    @property
    def id_type(self):
        return {"id": self.unique_id, "player type": self.type_restriction}

    @property
    def neighbor_id_type(self):
        return [self.model.get_agent(i).id_type for i in self.neighbor_ids]

    @property
    def total_sent(self):
        return amount_sum(self.invested_amounts[-1].values())

    @property
    def total_received_return(self):
        return amount_sum(self.received_returns[-1].values())

    @property
    def total_received_as_trustee(self):
        return float(Decimal(str(amount_sum(self.received_from_neighbors[-1].values()))) * 3)

    @property
    def total_returned(self):
        return amount_sum(self.returned_to_neighbors[-1].values())

    @property
    def trustor_payoff(self):
        # Paper SI Appendix A: returned - sent. Unsent endowment is excluded.
        return round(self.total_received_return - self.total_sent, 2)

    @property
    def trustee_payoff(self):
        return round(self.total_received_as_trustee - self.total_returned, 2)

    @property
    def round_payoff(self):
        return round(self.trustor_payoff + self.trustee_payoff, 2)

    def update_balance_and_last_balance(self):
        self.last_balance = self.balance
        self.balance = round(self.balance + self.round_payoff, 2)

    def messages(self, round_number, prompt, history_rounds):
        earliest = 1 if history_rounds is None else max(1, round_number - history_rounds)
        messages = [{"role": "system", "content": self.system_prompt}]
        for turn in self.history:
            if turn["round"] >= earliest:
                messages.extend([{"role": "user", "content": turn["prompt"]},
                                 {"role": "assistant", "content": turn["content"]}])
        messages.append({"role": "user", "content": prompt})
        return messages

    def prune_history(self, round_number, history_rounds):
        if history_rounds is not None:
            self.history[:] = [t for t in self.history if t["round"] >= max(1, round_number - history_rounds)]

    def to_state(self):
        return {k: v for k, v in vars(self).items() if k != "model"}

    def restore(self, state):
        for key, value in state.items():
            if key in ("invested_amounts", "received_from_neighbors", "returned_to_neighbors", "received_returns"):
                value = [{int(k): v for k, v in record.items()} for record in value]
            if key == "coordinate":
                value = tuple(value)
            if key == "history":
                for turn in value:
                    turn["executed_decision"] = {int(k): v for k, v in turn["executed_decision"].items()}
            setattr(self, key, value)
