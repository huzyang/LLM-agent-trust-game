import random
from typing import Optional
from camel.agents import ChatAgent
from mesa.discrete_space import CellAgent


class BaseAgent(CellAgent):
    """Agent member of the iterated, spatial prisoner's dilemma model."""

    def __init__(self, model, cell=None):
        """
        Create a new Base agent.
        """
        super().__init__(model)
        # self.unique_id = unique_id
        self.cell = cell

        self.invested_amounts = []
        self.received_from_neighbors = []
        self.returned_to_neighbors = []
        self.received_returns = []
        self.last_balance = 0.0
        self.balance = 0.0
        self.type_restriction = ""
        self.llm_agent: Optional[ChatAgent] = None

    def __str__(self):
        return f"Agent {self.unique_id}: Position: {self.cell.coordinate}; Neighbors: {self.neighbor_ids}; Payoff: {self.payoff:.2f}"

    @property
    def id_type(self) -> dict:
        return {"id": self.unique_id, "player type": self.type_restriction}
    @property
    def neighbor_id_type(self) -> list:
        ids = self.neighbor_ids
        neighbors_id_type = []
        for id in ids:
            neighbors_id_type.append({"id": id, "player type": self.model.get_agent(id).type_restriction})
        return neighbors_id_type

    @property
    def total_sent(self) -> float:
        """上一轮发送的总金额"""
        return sum(self.invested_amounts[-1].values())

    @property
    def total_received_return(self) -> float:
        """上一轮收到的返还总额"""
        return sum(self.received_returns[-1].values())

    @property
    def total_received_as_trustee(self) -> float:
        """上一轮作为受托者收到的总额（邻居发送的3倍）"""
        return sum(self.received_from_neighbors[-1].values()) * 3

    @property
    def total_returned(self) -> float:
        """上一轮返还的总额"""
        return sum(self.returned_to_neighbors[-1].values())

    @property
    def trustor_payoff(self) -> float:
        """作为投资者的收益"""
        return 5 + self.total_received_return - self.total_sent

    @property
    def trustee_payoff(self) -> float:
        """作为受托者的收益"""
        return self.total_received_as_trustee - self.total_returned

    @property
    def round_payoff(self) -> float:
        """本轮总收益"""
        return self.trustor_payoff + self.trustee_payoff

    def set_llm_agent(self, llm_agent: ChatAgent) -> None:
        self.llm_agent = llm_agent

    @property
    def neighbor_ids(self):
        # 邻居id列表
        return sorted([agent.unique_id for agent in self.cell.neighborhood.agents])
    def update_balance_and_last_balance(self):
        """更新累计余额和上一轮余额"""
        # 保存当前余额为上一轮余额
        self.last_balance = self.balance

        # 如果有本轮收益数据，则累加到余额
        self.balance += self.round_payoff



    def step(self):
        pass
    def reset_record(self):
        """
        根据游戏类型和上下文做出决策。
        """
        self.invested_amounts = []
        self.received_from_neighbors = []
        self.returned_to_neighbors = []
        self.received_returns = []


    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用LLM获取原始响应"""
        pass
