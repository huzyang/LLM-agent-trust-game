""""""
import os
import json
import re
import sys
import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from camel.models import ModelFactory
from camel.types import ModelPlatformType
from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.types.enums import RoleType

import mesa
from mesa.discrete_space import OrthogonalVonNeumannGrid
from agents import BaseAgent
from params import Params, GameScenario
from src.utils import CommonUtils

logger = logging.getLogger('experiment')
if not logger.handlers:
    logger.setLevel(logging.INFO)
    logger.propagate = False

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setStream(sys.stdout)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

with open(os.path.join(CommonUtils.get_project_root_path(), "src/prompts/all_prompts.json"), "r", encoding="utf-8") as f:
    exp_prompts = json.load(f)

p_characters = exp_prompts.get("Character", [])
# random.shuffle(p_characters)
p_characters_student = exp_prompts.get("Character_student", [])
p_like_people = exp_prompts.get("Like-people", "")
p_experiment_info = exp_prompts.get("Experiment_context", "")
p_goal = exp_prompts.get("Individual_goal", "")
p_game_rules = exp_prompts.get("Gameplay_rule", "")
p_settings = exp_prompts.get("Settings", "")
p_output_requirements = exp_prompts.get("Output requirements", "")  # neighbors

p_decision_stages = exp_prompts.get("Decision stages", "")  # step, type
p_end = exp_prompts.get("End", "")
p_decision = exp_prompts.get("Decision", "")  # step, received_amounts
p_result = exp_prompts.get("Result", "")  # I_invested_1,I_received_4,T_received_2,T_returned_3,payoff


class GameModel(mesa.Model):

    def __init__(
            self,
            scenario: GameScenario = GameScenario,
    ):
        """

        """
        super().__init__(scenario=scenario)

        # 初始化model
        self.params = Params()
        self.num_agents = scenario.num_agents
        self.height = scenario.height
        self.width = scenario.width
        self.model_type = scenario.model_type
        self.game_type = scenario.game_type
        self.proportion = scenario.proportion
        self.step: int = 0
        self.run_id = scenario.run_id
        self.iteration = scenario.iteration

        self.agents_invested_amounts = {}  # 记录所有代理的投资金额
        self.agents_returned_amounts = {}  # 记录所有代理的返还金额

        # 初始化记录数据结构
        self.initial_sys_prompt = {}
        self.dialogs = {}  # 存储每轮次对话数据
        self.all_data = []  # 存储所有轮次的数据行
        self.pair_game_data = []
        self.token_usage = []  # 存储每轮次的token使用情况

        # 创建网格
        self.grid = OrthogonalVonNeumannGrid((scenario.width, scenario.height), torus=True, random=self.random)
        BaseAgent.create_agents(self, n=self.num_agents, cell=self.grid.all_cells.cells)
        self.init_player_type()

        # 创建LLM模型
        self.llm_model = ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
            model_type=self.model_type,
            url=self.params.api_base_url,
            api_key=self.params.api_key,
            model_config_dict={
                "temperature": self.params.temperature,
                "max_tokens": self.params.max_tokens,
                # "extra_body": {
                #     "enable_thinking": False  # 关闭思维链
                # }
            },
        )

        # 创建智能体、给智能体设置ChatAgent（1、人物 2、根据不同的博弈类型设置初始提示词（不是第一轮））
        self.init_chat_agent()
        # self.datacollector = mesa.DataCollector(
        #     agent_reporters={
        #         "Invested amount": lambda a: a.invested_amounts,
        #         "Received amount": lambda a: a.received_amounts,
        #     }
        # )

        # 创建评价智能体
        # self.critic_agent = ChatAgent(
        #     BaseMessage(
        #         role_name="critic",
        #         role_type=RoleType.ASSISTANT,
        #         meta_dict={},
        #         content="格式化输出",
        #     ),
        #     model=self.llm_model,
        #     output_language="Chinese",
        # )

    def init_player_type(self):
        # 创建限制类型列表：前num_free_players个为自由玩家，其余为受限玩家
        num_free_players = int(self.num_agents * self.proportion)
        restriction_set = []
        for i in range(self.num_agents):
            if i < num_free_players:
                restriction_set.append("free")
            else:
                restriction_set.append("constrained")

        # 随机打乱顺序以随机分配玩家类型
        random.shuffle(restriction_set)
        for i in range(self.num_agents):
            agent = self.get_agent(i)
            agent.unique_id = agent.unique_id - 1
            agent.type_restriction = restriction_set[i]

    def init_chat_agent(self):
        for agent in self.agents:
            id_type = agent.id_type
            neighbors_id_type = agent.neighbor_id_type
            rounds = self.params.rounds
            # 系统提示词组成： p_characters[i] + p_like_people + p_experiment_info + p_game_rules.get("trust_game") + p_behavioral_objective + p_output_requirements + p_consistency
            character = p_characters[agent.unique_id]
            # character = random.choice(p_characters_student[:2])  # 测试使用

            if self.params.total_round_info:
                experiment_info = p_experiment_info.get("total_round_info").format(rounds=rounds)
            else:
                experiment_info = p_experiment_info.get("no_total_round_info")
            game_play_rules = p_game_rules.get(self.game_type).format(width=self.width, height=self.height)
            agent_setting = p_settings.format(focal=id_type, n1=neighbors_id_type[0], n2=neighbors_id_type[1], n3=neighbors_id_type[2], n4=neighbors_id_type[3])
            if self.params.report_bdi:
                output_requirements = p_output_requirements.get("General") + p_output_requirements.get("BDI")  # BDI 格式
            else:
                output_requirements = p_output_requirements.get("General") + p_output_requirements.get("Simple")  # 极简格式

            content: str = character + p_like_people + experiment_info + game_play_rules + agent_setting + output_requirements

            # 设置ChatAgent
            llm_agent = ChatAgent(
                    BaseMessage(
                        role_name=f"Player_{agent.unique_id}",
                        role_type=RoleType.SYSTEM,
                        meta_dict={},
                        content=content
                    ),
                    model=self.llm_model,
                    token_limit=131072,  # 根据实际模型支持的长度设置，例如 32K
                    output_language="English",
                )
            agent.set_llm_agent(llm_agent)

            # 记录人物特征与初始系统提示词 initial_sys_prompt
            self.initial_sys_prompt[f"agent_{agent.unique_id}_{agent.type_restriction}"] = content

    def _step(self):
        """模型每一步的执行"""
        self.step += 1
        # 初始化当前轮次的记录字典
        round_key = f"round_{self.step}"
        self.dialogs[round_key] = {}
        self.agents_invested_amounts[round_key] = {}
        self.agents_returned_amounts[round_key] = {}

        # 1. 依次扮演信托者
        self.role_stage(player_type="investor")

        # 2. 整理所有信托者的回复
        self.record_agent_investment()

        # 3. 依次扮演受托人
        self.role_stage(player_type="trustee")

        # 4. 整理所有受托人的回复
        self.record_agent_return()

        # 5. 计算收益
        self.agents.do("update_balance_and_last_balance")

        # 6：收集当前轮次数据
        self._collect_data()

        # 7. 收集数据
        # self.agents.do("reset_record")

    def role_stage(self, player_type="investor"):

        logger.info(f"\n{'=' * 60}")
        logger.info(f"📊 实验共{self.params.rounds}轮，第 {self.step} 轮博弈 - {player_type} 阶段开始")
        logger.info(f"{'=' * 60}")

        round_key = f"round_{self.step}"
        if round_key not in self.dialogs:
            self.dialogs[round_key] = {}

        # 准备所有任务的参数
        tasks = []
        for i in range(self.num_agents):
            focal_agent = self.get_agent(i)
            add_info = ''
            prompt = self.prepare_prompt(agent=focal_agent, player_type=player_type, additional_info=add_info)
            tasks.append({
                'index': i,
                'agent': focal_agent,
                'prompt': prompt,
                'player_type': player_type
            })

        # 使用线程池并行执行所有任务
        max_workers = min(self.num_agents, 1)  # 限制最大并发数为10，避免API限流
        results = {}

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"{player_type}_worker") as executor:
            # 提交所有任务
            future_to_index = {
                executor.submit(self._call_llm, task['agent'], task['prompt'], task['player_type']): task['index']
                for task in tasks
            }

            # 收集结果
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    focal_agent_response = future.result(timeout=60)  # 60秒超时
                    results[index] = focal_agent_response
                except Exception as e:
                    logger.error(f"❌ Agent {tasks[index]['agent'].unique_id} 调用失败: {str(e)}")
                    # 失败时使用默认值
                    results[index] = None

        # 按顺序处理结果
        for i in range(self.num_agents):
            focal_agent = self.get_agent(i)
            focal_agent_response = results.get(i)
            agent_key = f"agent_{focal_agent.unique_id}_{focal_agent.type_restriction}"
            if agent_key not in self.dialogs[round_key]:
                self.dialogs[round_key][agent_key] = {}

            if focal_agent_response is None:
                send_amounts = {}
                for neighbor_id in focal_agent.neighbor_ids:
                    send_amounts[neighbor_id] = 0
                logger.warning(f"⚠️ Agent {focal_agent.unique_id} 响应为空，使用默认决策{send_amounts}")
                content_str = "ERROR"
                reasoning_str = "ERROR"
            else:
                send_amounts = self.extract_decisions_regex(focal_agent_response.content if hasattr(focal_agent_response, 'content') else str(focal_agent_response), focal_agent, player_type)
                content_str = str(focal_agent_response.content)
                reasoning_str = str(focal_agent_response.reasoning_content) if hasattr(focal_agent_response, 'reasoning_content') else ""

            if player_type == "investor":
                logger.info(f"📝 investor agent_{focal_agent.unique_id} 的决策为: {send_amounts}")
                focal_agent.invested_amounts.append(send_amounts)
                self.agents_invested_amounts[round_key][agent_key] = send_amounts

            elif player_type == "trustee":
                logger.info(f"📝 trustee agent_{focal_agent.unique_id} 的决策为: {send_amounts}")
                focal_agent.returned_to_neighbors.append(send_amounts)
                self.agents_returned_amounts[round_key][agent_key] = send_amounts

            self.dialogs[round_key][agent_key][f"as_{player_type}"] = {
                "prompt": tasks[i]['prompt'],
                "content": content_str,
                "reasoning_content": reasoning_str
            }

        logger.info(f"✅ 实验共{self.params.rounds}轮，第 {self.step} 轮-{player_type} 阶段完成！\n")

    def prepare_prompt(self, agent, player_type, additional_info="") -> str:

        prompt = additional_info
        if self.step == 1:
            if player_type == "investor":
                decision_stages = p_decision_stages.get("investor").format(step=self.step)
                prompt = decision_stages + p_end

            elif player_type == "trustee":
                send_amounts = agent.received_from_neighbors[-1]
                total_value = sum(send_amounts.values())
                investor_decision = p_decision.format(step=self.step, send_amounts=send_amounts, total=total_value, received=3 * total_value)
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
                total_value = sum(received_amounts.values())
                investor_decision = p_decision.format(
                    step=self.step,
                    send_amounts=received_amounts,
                    total=total_value,
                    received=3 * total_value
                )
                decision_stages = p_decision_stages.get("trustee")
                prompt = investor_decision + decision_stages + p_end

        return prompt

    def _call_llm(self, focal_agent, prompt, player_type="Investor"):
        test_mode = False
        try:
            # 测试模式：构造模拟的response_obj
            if test_mode:
                response_obj = self._create_mock_response(focal_agent, prompt)
            else:
                response_obj = focal_agent.llm_agent.step(prompt)

            focal_agent_response = response_obj.msgs[0]

            # 提取token使用信息
            token_usage = None
            if hasattr(response_obj, 'info') and response_obj.info:
                info = response_obj.info
                if 'usage' in info:
                    token_usage = info['usage']
                elif 'raw_response' in info:
                    raw_resp = info['raw_response']
                    if isinstance(raw_resp, dict) and 'usage' in raw_resp:
                        token_usage = raw_resp['usage']
                    elif hasattr(raw_resp, 'usage'):
                        token_usage = raw_resp.usage

            # 记录token使用情况
            if token_usage:
                prompt_tokens = token_usage.get('prompt_tokens', 0) if isinstance(token_usage, dict) else getattr(token_usage, 'prompt_tokens', 0)
                completion_tokens = token_usage.get('completion_tokens', 0) if isinstance(token_usage, dict) else getattr(token_usage, 'completion_tokens', 0)
                total_tokens = token_usage.get('total_tokens', 0) if isinstance(token_usage, dict) else getattr(token_usage, 'total_tokens', 0)
                self.token_usage.append(total_tokens)

                # logger.info(f"✅ [{player_type}] Agent {focal_agent.unique_id} 调用完成 - "
                #             f"Tokens: {total_tokens}(输入:{prompt_tokens}, 输出:{completion_tokens})")

            return focal_agent_response
        except Exception as e:
            logger.error(f"❌ [{player_type}] Agent {focal_agent.unique_id} 调用失败 - 错误: {str(e)}")
            raise

    def _create_mock_response(self, focal_agent, prompt):
        """构造模拟的response_obj用于测试"""
        import time
        from types import SimpleNamespace

        # 生成随机投资决策
        neighbor_ids = focal_agent.neighbor_ids
        if focal_agent.type_restriction == "constrained":
            # 受限玩家：所有邻居发送相同金额
            amount = random.randint(0, 5)
            send_amounts = {nid: amount for nid in neighbor_ids}
        else:
            # 自由玩家：可以给不同邻居发送不同金额
            send_amounts = {nid: random.randint(0, 5) for nid in neighbor_ids}

        # 构造消息内容
        content = str(send_amounts)

        # 构造msgs
        msg = SimpleNamespace(
            content=content,
            reasoning_content=None,
            role='assistant'
        )

        # 构造info（包含token使用信息）
        info = {
            'usage': {
                'prompt_tokens': len(prompt.split()),
                'completion_tokens': len(content.split()),
                'total_tokens': len(prompt.split()) + len(content.split())
            }
        }

        # 构造response_obj
        response_obj = SimpleNamespace(
            msgs=[msg],
            info=info
        )

        logger.debug(f"🧪 [TEST] Agent {focal_agent.unique_id} 使用模拟响应: {send_amounts}")

        return response_obj


    def record_agent_investment(self):
        """记录所有代理从邻居收到的投资金额"""
        for i in range(self.num_agents):
            focal_agent = self.get_agent(i)

            # 从每个邻居那里收集投资金额
            received_from_neighbors = {}
            for neighbor_id in focal_agent.neighbor_ids:
                neighbor_agent = self.get_agent(neighbor_id)

                # 获取邻居上一轮的投资决策
                if neighbor_agent.invested_amounts:
                    last_investment = neighbor_agent.invested_amounts[-1]
                    amount_to_focal = last_investment.get(focal_agent.unique_id, 0)
                    received_from_neighbors[neighbor_id] = amount_to_focal

            # 记录到当前代理的收到列表中
            focal_agent.received_from_neighbors.append(received_from_neighbors)

            logger.debug(f"Agent {i} 收到邻居投资: {received_from_neighbors}")

    def record_agent_return(self):
        """记录所有代理从邻居收到的返还金额"""
        for i in range(self.num_agents):
            focal_agent = self.get_agent(i)

            # 从每个邻居那里收集返还金额
            returned_from_neighbors = {}
            for neighbor_id in focal_agent.neighbor_ids:
                neighbor_agent = self.get_agent(neighbor_id)

                # 获取邻居上一轮的返还款项
                if neighbor_agent.returned_to_neighbors:
                    last_return = neighbor_agent.returned_to_neighbors[-1]
                    amount_to_focal = last_return.get(focal_agent.unique_id, 0)
                    returned_from_neighbors[neighbor_id] = amount_to_focal

            # 记录到当前代理的收到返还列表中
            focal_agent.received_returns.append(returned_from_neighbors)

            logger.debug(f"Agent {i} 收到邻居返还: {returned_from_neighbors}")

    def extract_decisions_regex(self, answer, agent, player_type):
        result = {}
        # 清空两边空白、统一格式
        answer = answer.strip().strip('"').strip()

        # 1. 优先匹配：直接包含 {key: value} 字典格式（格式1、2）
        dict_pattern = r"\{([^}]+)\}"
        dict_match = re.search(dict_pattern, answer)

        if dict_match:
            content = dict_match.group(1)

            # 1.1 先尝试匹配带引号的键名格式 {"3":1, "27":2}
            quoted_pairs = re.findall(r'"(\d+)"\s*:\s*(\d+(?:\.\d+)?)', content)
            if quoted_pairs:
                result = {int(k): float(v) for k, v in quoted_pairs}
                logger.debug(f"提取发送金额决策(带引号键名): {result}")
                return self._decisions_check(result, agent, player_type)

            # 1.2 再尝试匹配带单引号的键名格式 {'1': 1.00, '3': 1.00}
            single_quoted_pairs = re.findall(r"'(\d+)'\s*:\s*(\d+(?:\.\d+)?)", content)
            if single_quoted_pairs:
                result = {int(k): float(v) for k, v in single_quoted_pairs}
                logger.debug(f"提取发送金额决策(带单引号键名): {result}")
                return self._decisions_check(result, agent, player_type)

            # 1.2 再尝试匹配不带引号的键名格式 {3:1, 27:2}
            pairs = re.findall(r"(\d+)\s*:\s*(\d+(?:\.\d+)?)", content)
            if pairs:
                result = {int(k): float(v) for k, v in pairs}
                logger.debug(f"提取发送金额决策: {result}")
                return self._decisions_check(result, agent, player_type)

            # 1.3 匹配 return/total_return 格式 {return: 5} 或 {total_return: 5}
            return_pattern = r"(?:total_)?return\s*:\s*(\d+(?:\.\d+)?)"
            return_match = re.search(return_pattern, content, re.IGNORECASE)
            if return_match:
                value = float(return_match.group(1))
                result = {int(nid): value / 4 for nid in agent.neighbor_ids}
                logger.debug(f"提取return格式决策，总值{value}，平均分配: {result}")
                return self._decisions_check(result, agent, player_type)

        # 2. 尝试提取任意单个数字（通用匹配）
        all_numbers = re.findall(r'\b(\d+(?:\.\d+)?)\b', answer)
        if len(all_numbers) == 1:
            value = float(all_numbers[0])
            result = {int(nid): value / 4 for nid in agent.neighbor_ids}
            return self._decisions_check(result, agent, player_type)

        # 3. 匹配：分别发送给不同邻居（格式4）
        multi_pattern = r"(\d+(?:\.\d+)?)\s*tokens?\s*to\s*neighbor\s*(\d+)"
        multi_matches = re.findall(multi_pattern, answer, re.IGNORECASE)

        if multi_matches:
            result = {}
            for amount, neighbor_id in multi_matches:
                result[int(neighbor_id)] = float(amount)
            logger.debug(f"提取分开发送金额决策: {result}")
            return self._decisions_check(result, agent, player_type)

        # 所有格式都不匹配
        logger.warning(f"agent_{agent.unique_id}回复未匹配到任何发送金额格式，原始响应: {answer[-100:]}")
        return self._decisions_check(result, agent, player_type)

    def _decisions_check(self, result, agent, player_type):
        if not result:
            result = {}

        total_amount = sum(result.values())

        if player_type == "trustor":
            max_total = 5
            default_per_neighbor = 1.25
        elif player_type == "trustee":
            max_total = 3 * sum(agent.received_from_neighbors[-1].values())
            default_per_neighbor = max_total / 4
        else:
            return result

        if total_amount > max_total:
            logger.warning(f"{player_type.capitalize()},agent_{agent.unique_id}发送总额{total_amount}, 超过最大值{max_total}，调整为每邻居{default_per_neighbor}")
            return {int(nid): default_per_neighbor for nid in agent.neighbor_ids}

        return result

    def run_model(self, max_round=50) -> tuple[list, list, dict]:
        """运行模型指定步数"""
        import time
        import tqdm

        logger.info(f"\n{'=' * 70}")
        logger.info(f"🚀 开始运行信任博弈实验")
        logger.info(f"{'=' * 70}")
        logger.info(f"  • 模型类型: {self.model_type}")
        logger.info(f"  • 博弈类型: {self.game_type}")
        logger.info(f"  • 智能体数量: {self.num_agents}")
        logger.info(f"  • 网格大小: {self.width} x {self.height}")
        logger.info(f"  • 自由玩家比例: {self.proportion}")
        logger.info(f"  • 运行轮次: {max_round}")
        logger.info(f"  • Run ID: {self.run_id}")
        logger.info(f"  • Iteration: {self.iteration}")
        logger.info(f"{'=' * 70}\n")

        start_time = time.time()

        for _ in tqdm.trange(max_round):
            self._step()

        elapsed_time = time.time() - start_time

        # 计算统计信息
        total_records = len(self.all_data)

        if total_records > 0:
            # 基础统计
            avg_sent = sum(row['total_sent'] for row in self.all_data) / total_records
            avg_received_return = sum(row['total_received_return'] for row in self.all_data) / total_records
            avg_received_send = sum(row['total_received_send'] for row in self.all_data) / total_records
            avg_returned = sum(row['total_returned'] for row in self.all_data) / total_records

            # 收益统计
            avg_trustor_payoff = sum(row['trustor_payoff'] for row in self.all_data) / total_records
            avg_trustee_payoff = sum(row['trustee_payoff'] for row in self.all_data) / total_records
            avg_round_payoff = sum(row['round_payoff'] for row in self.all_data) / total_records

            # 按智能体类型统计
            free_agents_data = [row for row in self.all_data if row['agent_type'] == 'free']
            constrained_agents_data = [row for row in self.all_data if row['agent_type'] == 'constrained']

            avg_sent_free = sum(row['total_sent'] for row in free_agents_data) / len(free_agents_data) if free_agents_data else 0
            avg_sent_constrained = sum(row['total_sent'] for row in constrained_agents_data) / len(constrained_agents_data) if constrained_agents_data else 0

            avg_payoff_free = sum(row['round_payoff'] for row in free_agents_data) / len(free_agents_data) if free_agents_data else 0
            avg_payoff_constrained = sum(row['round_payoff'] for row in constrained_agents_data) / len(constrained_agents_data) if constrained_agents_data else 0

            # Token使用统计
            total_tokens = sum(self.token_usage) if self.token_usage else 0
            avg_tokens_per_call = total_tokens / len(self.token_usage) if self.token_usage else 0
        else:
            avg_sent = avg_received_return = avg_received_send = avg_returned = 0
            avg_trustor_payoff = avg_trustee_payoff = avg_round_payoff = 0
            avg_sent_free = avg_sent_constrained = 0
            avg_payoff_free = avg_payoff_constrained = 0
            total_tokens = avg_tokens_per_call = 0

        all_dialogue = {
            "initial_sys_prompt": self.initial_sys_prompt,
            "dialogs": self.dialogs,
            # "agent_invested_amounts": self.agents_invested_amounts,
            # "agent_returned_amounts": self.agents_returned_amounts,
        }

        # 打印最终统计
        logger.info(f"\n{'=' * 70}")
        logger.info(f"🎉 实验运行完成！")
        logger.info(f"{'=' * 70}")

        logger.info(f"📊 核心指标统计:")
        logger.info(f"  • 总记录数: {total_records}")
        logger.info(f"  • 平均发送金额: {avg_sent:.3f} / 5.0")
        logger.info(f"  • 平均收到返还: {avg_received_return:.3f}")
        logger.info(f"  • 平均收到投资(3倍): {avg_received_send:.3f}")
        logger.info(f"  • 平均返还金额: {avg_returned:.3f}")
        logger.info(f"  • 投资者平均收益: {avg_trustor_payoff:.3f}")
        logger.info(f"  • 受托者平均收益: {avg_trustee_payoff:.3f}")
        logger.info(f"  • 每轮平均总收益: {avg_round_payoff:.3f}")

        logger.info(f"\n👥 分类型统计:")
        logger.info(f"  • 自由玩家平均发送: {avg_sent_free:.3f}")
        logger.info(f"  • 受限玩家平均发送: {avg_sent_constrained:.3f}")
        logger.info(f"  • 发送差异: {abs(avg_sent_free - avg_sent_constrained):.3f}")
        logger.info(f"  • 自由玩家平均收益: {avg_payoff_free:.3f}")
        logger.info(f"  • 受限玩家平均收益: {avg_payoff_constrained:.3f}")
        logger.info(f"  • 收益差异: {abs(avg_payoff_free - avg_payoff_constrained):.3f}")

        logger.info(f"\n💰 Token使用统计:")
        logger.info(f"  • 总Token消耗: {total_tokens}")
        logger.info(f"  • 平均每次调用: {avg_tokens_per_call:.1f} tokens")

        logger.info(f"\n⏱️ 性能统计:")
        logger.info(f"  • 总耗时: {elapsed_time:.2f}秒")
        logger.info(f"  • 平均每轮耗时: {elapsed_time / max_round:.2f}秒")
        logger.info(f"  • 平均每记录耗时: {elapsed_time / total_records * 1000:.2f}毫秒" if total_records > 0 else "  • 无记录")

        logger.info(f"\n💾 数据记录:")
        logger.info(f"  • 对话轮次: {len(self.dialogs)} 轮")
        logger.info(f"  • 数据行数: {total_records}")
        logger.info(f"  • Token记录: {len(self.token_usage)} 次")
        logger.info(f"{'=' * 70}\n")

        return self.all_data, self.pair_game_data, all_dialogue


    def get_agent(self, agent_id):
        """根据ID获取智能体"""
        return self.agents[agent_id]

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
            self.all_data.append(row_1)

            for neighbor_id in agent.neighbor_ids:

                invested_amount = invested_dict.get(neighbor_id, 0)
                returned_amount = returned_dict.get(neighbor_id, 0)

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
                self.pair_game_data.append(row_2)

    def reset_record(self):
        """重置记录"""
        pass

