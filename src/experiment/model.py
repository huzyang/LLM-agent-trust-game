"""Trust-game engine: fixed lattice, explicit stages and serializable progress."""
from dataclasses import asdict
import json
import logging
from pathlib import Path
import random
from .agents import BaseAgent, amount_sum
from .decisions import normalize_decision
from .llm import ExperimentPaused, OpenAIChat
from .params import Params, GameScenario
from .persistence import defer_interrupt
from src.utils import CommonUtils

logger = logging.getLogger("experiment")
PROMPT_PATH = Path(CommonUtils.get_project_root_path()) / "src/prompts/all_prompts.json"
exp_prompts = json.loads(PROMPT_PATH.read_text(encoding="utf-8"))
p_characters = exp_prompts["Character"]
p_like_people = exp_prompts["Like-people"]
p_experiment_info = exp_prompts["Experiment_context"]
p_game_rules = exp_prompts["Gameplay_rule"]
p_settings = exp_prompts["Settings"]
p_output_requirements = exp_prompts["Output requirements"]
p_decision_stages = exp_prompts["Decision stages"]
p_end = exp_prompts["End"]
p_decision = exp_prompts["Decision"]
p_result = exp_prompts["Result"]


class GameModel:
    def __init__(self, scenario=None, params=None, gateway=None, checkpoint=None, event=None, state=None):
        self.params = params or Params(require_credentials=False)
        self.params.validate()
        self.scenario = scenario or GameScenario(
            num_agents=self.params.num_agents, width=self.params.width, height=self.params.height,
            seed=self.params.seed, model_type=self.params.model_type_list[0])
        scenario = self.scenario
        if (not scenario.torus or scenario.game_type != "trust_game" or
                scenario.width < 3 or scenario.height < 3 or
                scenario.width * scenario.height != scenario.num_agents):
            raise ValueError("Trust game requires a periodic lattice with four distinct neighbors")
        if scenario.num_agents > len(p_characters):
            raise ValueError(f"Only {len(p_characters)} character prompts available")
        self.num_agents, self.width, self.height = scenario.num_agents, scenario.width, scenario.height
        self.model_type, self.game_type = scenario.model_type, scenario.game_type
        self.proportion, self.run_id, self.iteration = scenario.proportion, scenario.run_id, scenario.iteration
        self.random = random.Random(scenario.seed)
        self._checkpoint = checkpoint or (lambda model: None)
        self.event = event or (lambda *a, **kw: None)
        self.gateway = gateway or OpenAIChat(self.params, self.model_type, event=self.event)
        self.agents = []
        for i in range(self.num_agents):
            x, y = divmod(i, self.height)  # Preserve original Mesa coordinate/ID mapping.
            neighbors = sorted([
                ((x-1) % self.width)*self.height+y, ((x+1) % self.width)*self.height+y,
                x*self.height+(y-1) % self.height, x*self.height+(y+1) % self.height])
            self.agents.append(BaseAgent(self, i, (x, y), neighbors))
        types = ["free"] * int(self.num_agents * self.proportion)
        types += ["constrained"] * (self.num_agents - len(types))
        self.random.shuffle(types)
        for agent, restriction in zip(self.agents, types):
            agent.type_restriction = restriction
        self.initial_sys_prompt = {}
        self.init_chat_agent()
        self.step = 1
        self.phase = "investor"
        self.next_agent = 0
        self.dialogs = {}
        self.agents_invested_amounts = {}
        self.agents_returned_amounts = {}
        self.all_data = []
        self.pair_game_data = []
        self.token_usage = []
        self.corrected_calls = 0
        self.parse_failures = 0
        if state is not None:
            self.restore(state)

    def get_agent(self, agent_id):
        return self.agents[agent_id]

    def init_chat_agent(self):
        for agent in self.agents:
            neighbors = agent.neighbor_id_type
            context = (p_experiment_info["total_round_info"].format(rounds=self.params.rounds)
                       if self.params.total_round_info else p_experiment_info["no_total_round_info"])
            output = p_output_requirements["General"] + p_output_requirements[
                "BDI" if self.params.report_bdi else "Simple"]
            for index, nid in enumerate(agent.neighbor_ids, 1):
                output = output.replace(f"N{index}_ID", f'"{nid}"')
            output += ("\nUse the actual numeric neighbor IDs shown above as JSON keys. "
                       "Replace v1, v2, v3, v4 with numeric amounts, never ID placeholders.")
            if self.params.report_bdi:
                output += "\nKeep Belief, Desire, and Intention to one or two sentences each; finish with the amount dictionary."
            setting = p_settings.format(focal=agent.id_type,
                                        **{f"n{i+1}": value for i, value in enumerate(neighbors)})
            content = (p_characters[agent.unique_id] + p_like_people + context +
                       p_game_rules[self.game_type].format(width=self.width, height=self.height) +
                       setting + output + "\nRespond in English.")
            agent.system_prompt = content
            self.initial_sys_prompt[self.agent_key(agent)] = content

    @staticmethod
    def agent_key(agent):
        return f"agent_{agent.unique_id}_{agent.type_restriction}"

    def run_model(self, max_round=None):
        if max_round is not None and max_round != self.params.rounds:
            raise ValueError("rounds must match the checkpointed configuration")
        while self.phase != "complete":
            if self.phase == "investor":
                self.role_stage("investor")
                with defer_interrupt():
                    self.record_agent_investment()
                    self.phase, self.next_agent = "trustee", 0
                    self._checkpoint(self)
            elif self.phase == "trustee":
                self.role_stage("trustee")
                with defer_interrupt():
                    self.record_agent_return()
                    self.phase, self.next_agent = "finalize", 0
                    self._checkpoint(self)
            elif self.phase == "finalize":
                with defer_interrupt():
                    for agent in self.agents:
                        agent.update_balance_and_last_balance()
                    self._collect_data()
                    logger.info("Round %s/%s | mean sent=%.2f mean payoff=%.2f",
                                self.step, self.params.rounds,
                                sum(a.total_sent for a in self.agents)/self.num_agents,
                                sum(a.round_payoff for a in self.agents)/self.num_agents)
                    self.event("round_complete", round=self.step, rows=len(self.all_data))
                    self.step += 1
                    self.phase = "complete" if self.step > self.params.rounds else "investor"
                    self._checkpoint(self)
            else:
                raise ValueError(f"Unknown checkpoint phase: {self.phase}")
        return self.all_data, self.pair_game_data, {
            "initial_sys_prompt": self.initial_sys_prompt, "dialogs": self.dialogs}

    def role_stage(self, player_type="investor"):
        key = f"round_{self.step}"
        self.dialogs.setdefault(key, {})
        self.agents_invested_amounts.setdefault(key, {})
        self.agents_returned_amounts.setdefault(key, {})
        logger.info("Round %s/%s | %-8s | saved %s/%s; running",
                    self.step, self.params.rounds, player_type, self.next_agent, self.num_agents)
        start_corrected, start_failed = self.corrected_calls, self.parse_failures
        for i in range(self.next_agent, self.num_agents):
            agent = self.get_agent(i)
            prompt = self.prepare_prompt(agent, player_type)
            # Tell the player the EXECUTED action after automatic corrections.
            if agent.history and agent.history[-1]["corrections"]:
                last = agent.history[-1]
                prompt = (f"Your previous {last['stage']} action was executed as "
                          f"{last['executed_decision']} after enforcing game rules.\n" + prompt)
            messages = agent.messages(self.step, prompt, self.params.history_rounds)
            self.event("request_start", round=self.step, stage=player_type, agent_id=i,
                       messages=messages)
            response = self.gateway.complete(messages, agent=agent, round_number=self.step, stage=player_type)
            if response.finish_reason not in ("", "stop"):
                details = {"round": self.step, "stage": player_type, "agent_id": i,
                           "content": response.content, "reasoning_content": response.reasoning_content,
                           "usage": response.usage, "response_id": response.response_id,
                           "response_model": response.model, "finish_reason": response.finish_reason,
                           "max_tokens": self.params.max_tokens}
                self.event("decision_not_accepted", **details)
                reason = "output_truncated" if response.finish_reason == "length" else "incomplete_response"
                raise ExperimentPaused(reason, details)
            budget = 5 if player_type == "investor" else agent.total_received_as_trustee
            decision = normalize_decision(response.content, agent.neighbor_ids, player_type,
                                          agent.type_restriction, budget)
            with defer_interrupt():
                agent_key = self.agent_key(agent)
                if player_type == "investor":
                    agent.invested_amounts.append(decision.amounts)
                    self.agents_invested_amounts[key][agent_key] = decision.amounts
                else:
                    agent.returned_to_neighbors.append(decision.amounts)
                    self.agents_returned_amounts[key][agent_key] = decision.amounts
                record = {
                    "prompt": prompt, "content": response.content,
                    "reasoning_content": response.reasoning_content,
                    "raw_decisions": decision.raw_decisions, "executed_decision": decision.amounts,
                    "corrections": decision.corrections, "parse_failed": decision.parse_failed,
                    "parse_method": decision.parse_method,
                    "usage": response.usage, "response_id": response.response_id,
                    "response_model": response.model, "finish_reason": response.finish_reason,
                    "attempts": response.attempts,
                }
                self.dialogs[key].setdefault(agent_key, {})[f"as_{player_type}"] = record
                agent.history.append({"round": self.step, "stage": player_type, **record})
                agent.prune_history(self.step, self.params.history_rounds)
                self.token_usage.append(response.usage.get("total_tokens", 0) or 0)
                self.corrected_calls += bool(decision.corrections)
                self.parse_failures += decision.parse_failed
                self.next_agent = i + 1
                # Atomic accepted response+action+history+cursor before next request.
                self._checkpoint(self)
            self.event("decision_saved", round=self.step, stage=player_type, agent_id=i,
                       content=response.content, raw_decisions=decision.raw_decisions,
                       executed_decision=decision.amounts, corrections=decision.corrections,
                       parse_failed=decision.parse_failed, parse_method=decision.parse_method,
                       response_id=response.response_id)
            logger.debug("Agent %s | round=%s stage=%s decision=%s corrections=%s",
                         i, self.step, player_type, decision.amounts, decision.corrections)
            if self.num_agents >= 25 and self.next_agent % 10 == 0:
                logger.info("Round %s | %-8s | saved %s/%s", self.step, player_type, self.next_agent, self.num_agents)
        logger.info("Round %s/%s | %-8s | saved %s/%s; corrected=%s parse_failed=%s",
                    self.step, self.params.rounds, player_type, self.num_agents, self.num_agents,
                    self.corrected_calls-start_corrected, self.parse_failures-start_failed)

    def record_agent_investment(self):
        for agent in self.agents:
            agent.received_from_neighbors.append({
                nid: self.get_agent(nid).invested_amounts[-1][agent.unique_id] for nid in agent.neighbor_ids})

    def record_agent_return(self):
        for agent in self.agents:
            agent.received_returns.append({
                nid: self.get_agent(nid).returned_to_neighbors[-1][agent.unique_id] for nid in agent.neighbor_ids})

    def to_state(self):
        fields = ("step", "phase", "next_agent", "dialogs", "initial_sys_prompt", "all_data",
                  "pair_game_data", "token_usage", "corrected_calls", "parse_failures",
                  "agents_invested_amounts", "agents_returned_amounts")
        return {**{k: getattr(self, k) for k in fields},
                "scenario": asdict(self.scenario),
                "agents": [a.to_state() for a in self.agents]}

    def restore(self, state):
        if state["scenario"] != asdict(self.scenario):
            raise ValueError("Checkpoint scenario does not match")
        for key in ("step", "phase", "next_agent", "dialogs", "initial_sys_prompt", "all_data",
                    "pair_game_data", "token_usage", "corrected_calls", "parse_failures",
                    "agents_invested_amounts", "agents_returned_amounts"):
            setattr(self, key, state[key])
        for agent, saved in zip(self.agents, state["agents"]):
            agent.restore(saved)
        for players in self.dialogs.values():
            for stages in players.values():
                for turn in stages.values():
                    turn["executed_decision"] = {int(k): v for k, v in turn["executed_decision"].items()}

    def prepare_prompt(self, agent, player_type, additional_info="") -> str:

        prompt = additional_info
        if self.step == 1:
            if player_type == "investor":
                decision_stages = p_decision_stages.get("investor").format(step=self.step)
                prompt = decision_stages + p_end

            elif player_type == "trustee":
                send_amounts = agent.received_from_neighbors[-1]
                total_value = amount_sum(send_amounts.values())
                investor_decision = p_decision.format(step=self.step, send_amounts=send_amounts, total=total_value, received=agent.total_received_as_trustee)
                decision_stages = p_decision_stages.get("trustee")
                prompt = investor_decision + decision_stages + p_end

        else:
            if player_type == "investor":

                round_result = p_result.format(
                    I_invested_1=agent.invested_amounts[-1],
                    I_received_4=agent.received_returns[-1],
                    total_send=agent.total_sent,
                    i_total_received=agent.total_received_return,
                    trustor_payoff=agent.trustor_payoff,
                    T_received_2=agent.received_from_neighbors[-1],
                    T_returned_3=agent.returned_to_neighbors[-1],
                    t_total_received=agent.total_received_as_trustee,
                    total_returned=agent.total_returned,
                    trustee_payoff=agent.trustee_payoff,
                    last_balance=agent.last_balance,
                    balance=agent.balance
                )
                decision_stages = p_decision_stages.get("investor").format(step=self.step)
                prompt = round_result + decision_stages + p_end

            elif player_type == "trustee":
                received_amounts = agent.received_from_neighbors[-1]
                total_value = amount_sum(received_amounts.values())
                investor_decision = p_decision.format(
                    step=self.step,
                    send_amounts=received_amounts,
                    total=total_value,
                    received=agent.total_received_as_trustee
                )
                decision_stages = p_decision_stages.get("trustee")
                prompt = investor_decision + decision_stages + p_end

        return prompt

    def _collect_data(self):
        """
        收集当前轮次所有两两博弈的数据（每个方向一条记录）。
        每条记录对应一次投资者-受托者博弈。
        """
        for agent in self.agents:
            # 获取邻居ID列表（按排序顺序）
            neighbor_ids = agent.neighbor_ids

            # 获取当前轮次的各项数据
            invested_dict = agent.invested_amounts[-1] if agent.invested_amounts else {}
            received_returns_dict = agent.received_returns[-1] if agent.received_returns else {}
            received_from_neighbors_dict = agent.received_from_neighbors[-1] if agent.received_from_neighbors else {}
            returned_dict = agent.returned_to_neighbors[-1] if agent.returned_to_neighbors else {}

            # 提取发送给每个邻居的金额（按邻居顺序）
            sent_values = [invested_dict.get(nid, 0) for nid in neighbor_ids]
            received_return_values = [received_returns_dict.get(nid, 0) for nid in neighbor_ids]
            received_send_values = [received_from_neighbors_dict.get(nid, 0) for nid in neighbor_ids]
            returned_values = [returned_dict.get(nid, 0) for nid in neighbor_ids]

            row_1 = {
                "run_id": self.run_id,
                "iteration": self.iteration,
                "round": self.step,
                "num_agents": self.num_agents,
                "proportion": self.proportion,
                "agent_id": agent.unique_id,
                "agent_type": agent.type_restriction,
                "neighbor_1_id": neighbor_ids[0] if len(neighbor_ids) > 0 else None,
                "neighbor_2_id": neighbor_ids[1] if len(neighbor_ids) > 1 else None,
                "neighbor_3_id": neighbor_ids[2] if len(neighbor_ids) > 2 else None,
                "neighbor_4_id": neighbor_ids[3] if len(neighbor_ids) > 3 else None,
                "sent_to_n1": sent_values[0] if len(sent_values) > 0 else 0,
                "sent_to_n2": sent_values[1] if len(sent_values) > 1 else 0,
                "sent_to_n3": sent_values[2] if len(sent_values) > 2 else 0,
                "sent_to_n4": sent_values[3] if len(sent_values) > 3 else 0,
                "total_sent": agent.total_sent,

                "received_return_from_n1": received_return_values[0] if len(received_return_values) > 0 else 0,
                "received_return_from_n2": received_return_values[1] if len(received_return_values) > 1 else 0,
                "received_return_from_n3": received_return_values[2] if len(received_return_values) > 2 else 0,
                "received_return_from_n4": received_return_values[3] if len(received_return_values) > 3 else 0,
                "total_received_return": agent.total_received_return,

                "received_send_from_n1": received_send_values[0] if len(received_send_values) > 0 else 0,
                "received_send_from_n2": received_send_values[1] if len(received_send_values) > 1 else 0,
                "received_send_from_n3": received_send_values[2] if len(received_send_values) > 2 else 0,
                "received_send_from_n4": received_send_values[3] if len(received_send_values) > 3 else 0,
                "total_received_send": agent.total_received_as_trustee,

                "returned_to_n1": returned_values[0] if len(returned_values) > 0 else 0,
                "returned_to_n2": returned_values[1] if len(returned_values) > 1 else 0,
                "returned_to_n3": returned_values[2] if len(returned_values) > 2 else 0,
                "returned_to_n4": returned_values[3] if len(returned_values) > 3 else 0,
                "total_returned": agent.total_returned,

                "trustor_payoff": agent.trustor_payoff,
                "trustee_payoff": agent.trustee_payoff,
                "round_payoff": agent.round_payoff,
                "last_accumulate_payoff": agent.last_balance,
                "accumulate_payoff": agent.balance,
            }
            audit = self.dialogs[f"round_{self.step}"][self.agent_key(agent)]
            row_1.update({
                "seed": self.scenario.seed, "actual_proportion": sum(a.type_restriction == "free" for a in self.agents)/self.num_agents,
                "investor_corrected": bool(audit["as_investor"]["corrections"]),
                "trustee_corrected": bool(audit["as_trustee"]["corrections"]),
                "investor_parse_failed": audit["as_investor"]["parse_failed"],
                "trustee_parse_failed": audit["as_trustee"]["parse_failed"],
            })
            self.all_data.append(row_1)

            for neighbor_id in agent.neighbor_ids:

                invested_amount = invested_dict.get(neighbor_id, 0)
                returned_amount = received_returns_dict.get(neighbor_id, 0)

                row_2 = {
                    "round": self.step,
                    "num_agents": self.num_agents,
                    "proportion": self.proportion,
                    "trustor_id": agent.unique_id,
                    "trustor_type": agent.type_restriction,
                    "trustee_id": neighbor_id,
                    "sent_amount": invested_amount,
                    "returned_amount": returned_amount,
                }
                row_2.update({"run_id": self.run_id, "iteration": self.iteration,
                              "seed": self.scenario.seed,
                              "trustee_type": self.get_agent(neighbor_id).type_restriction})
                self.pair_game_data.append(row_2)
