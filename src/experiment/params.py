"""
实验参数
"""
from enum import Enum
from src.utils import CommonUtils
from dotenv import load_dotenv
import os
from mesa.experimental.scenarios import Scenario

class ModelType(Enum):
    QWEN3_6_FLASH = "qwen3.6-flash"
    QWEN3_6_PLUS = "qwen3.6-plus"
    QWEN3_5_FLASH = "qwen3.5-flash"
    QWEN3_5_MAX = "qwen3.5-max"
    QWEN3_MAX = "qwen3-max"

    DEEPSEEK_V_4_FLASH = "deepseek-v4-flash"
    DEEPSEEK_V_4_PRO = "deepseek-v4-pro"
    GLM_5_1 = "glm-5.1"
    KIMI_K2_5 = "kimi-k2.5"

    @property
    def is_openai(self) -> bool:
        r"""Returns whether this type of models is an OpenAI-released model."""
        return self in {
            ModelType.QWEN3_6_FLASH, ModelType.QWEN3_5_MAX,
        }

    @property
    def token_limit(self) -> int:
        r"""Returns the maximum token limit for a given model.
        Returns:
            int: The maximum token limit for the given model.
        """
        if self is ModelType.QWEN3_6_FLASH:
            return 8192
        elif self is ModelType.QWEN3_5_FLASH:
            return 4096
        else:
            raise ValueError("Unknown model type")


class GameType(Enum):
    PDG = "pd_game"
    TRUST = "trust_game"


class GameScenario(Scenario):
    """Scenario for model."""
    num_agents: int = 9
    width: int = int(num_agents ** 0.5)  # 根号 N
    height: int = width
    torus: bool = True
    model_type: str = ModelType.QWEN3_MAX.value
    game_type: str = GameType.TRUST.value
    proportion: float = 0.5  # 自由节点比例

    run_id: int = 1
    iteration: int = 1


class Params:

    def __init__(self):
        self.num_agents = 36
        self.width: int = int(self.num_agents ** 0.5)  # 根号 N
        self.height: int = self.width
        self.proportions = [0.5, 0.75, 1]  # 自由节点比例 0, 0.25, 0.5, 0.75, 1
        self.model_type_list = [ModelType.DEEPSEEK_V_4_FLASH.value]
        self.game_type = GameType.TRUST.value
        self.rounds = 20  # 游戏轮数
        self.iterations = 1
        self.report_bdi = False
        self.total_round_info = False

        ################# LLM 参数 ####################
        load_dotenv()
        self.api_key = os.getenv("DEEPSEEK_API_KEY")  # QWEN_API_KEY_130, QWEN_API_KEY_131, DEEPSEEK_API_KEY
        if not self.api_key:
            raise ValueError("请设置环境变量 QWEN_API_KEY")
        self.api_base_url = os.getenv("DEEPSEEK_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")  # QWEN_API_BASE_URL, DEEPSEEK_API_BASE_URL
        self.temperature = 1.0
        self.max_tokens = 131072 # 65536, 131072

    @property
    def model_init_params(self):
        return {
            'num_agents': self.num_agents,
            'width': self.width,
            'height': self.height,
            'game_type': self.game_type,
            'proportion': self.proportions,
            'rounds': self.rounds
        }

    def print_model_init_params(self):
        """打印模型初始化参数"""
        print(f"\n模型初始化参数:")
        for key, value in self.model_init_params.items():
            print(f"  {key} = {value}")

    def print_all_params(self):
        """打印所有参数"""
        pass

    def record_params(self):
        """将参数转换为字典"""
        str_result = ""
        str_result += f"\n    \"N\" =  {self.num_agents} "
        str_result += f"\n    \"proportions\" =  {self.proportions} "
        str_result += f"\n    \"rounds\" =  {self.rounds} "

        return str_result

    def to_dict(self):
        """将参数转换为字典"""
        return self.__dict__
