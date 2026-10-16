"""Validated settings; credentials never enter exported configuration."""
from dataclasses import dataclass
from enum import Enum
import math
import os
from pathlib import Path
from dotenv import load_dotenv
from src.utils import CommonUtils


class ModelType(Enum):
    DEEPSEEK_FLASH = "deepseek-flash"
    DEEPSEEK_V_4_FLASH = "deepseek-v4-flash"
    DEEPSEEK_V_4_PRO = "deepseek-v4-pro"


class GameType(Enum):
    TRUST = "trust_game"
    PDG = "pd_game"  # Historical label; this runner implements trust game only.


@dataclass
class GameScenario:
    num_agents: int = 9
    width: int = 3
    height: int = 3
    torus: bool = True
    model_type: str = "deepseek-flash"
    game_type: str = "trust_game"
    proportion: float = 0.5
    run_id: int = 1
    iteration: int = 1
    seed: int = 42


class Params:
    def __init__(self, require_credentials=True):
        load_dotenv(Path(CommonUtils.get_project_root_path()) / ".env")
        self.num_agents = 49
        self.width = self.height = 7
        self.proportions = [0, 0.25, 0.5, 0.75, 1.0]
        self.rounds = 20
        self.iterations = 1
        self.game_type = "trust_game"
        self.model_type_list = ["deepseek-flash"]
        self.report_bdi = True
        self.total_round_info = False
        self.seed = 42
        self.history_rounds = 3  # null means full history, never summarized.
        self.temperature = 1.0
        self.max_tokens = 2048  # Allow BDI + final decision; thinking may need a larger cap.
        self.context_limit = 131072  # Conservative configurable input+output cap.
        self.thinking = False
        self.extra_body = {}
        self.request_timeout = 60.0
        self.max_retries = 2  # After initial attempt; SDK retries disabled.
        self.retry_delay = 2.0
        self.api_base_url = os.getenv("DEEPSEEK_API_BASE_URL") or "https://api.deepseek.com"
        self.api_key_env = "DEEPSEEK_API_KEY"
        self.api_key = None
        if require_credentials:
            self.load_credentials()

    def update(self, config):
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a JSON object")
        unknown = set(config) - (set(self.to_dict()) - {"width", "height"})
        if unknown:
            raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
        for key, value in config.items():
            setattr(self, key, value)
        self.validate()

    def validate(self):
        for key in ("num_agents", "rounds", "iterations", "max_tokens", "context_limit"):
            value = getattr(self, key)
            if type(value) is not int or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        side = math.isqrt(self.num_agents)
        if side < 3 or side * side != self.num_agents:
            raise ValueError("num_agents must be a perfect square >= 9")
        self.width = self.height = side
        if self.game_type != "trust_game":
            raise ValueError("Only trust_game is implemented")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        if self.history_rounds is not None and (type(self.history_rounds) is not int or self.history_rounds < 1):
            raise ValueError("history_rounds must be a positive integer or null")
        if type(self.max_retries) is not int or self.max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer")
        for key in ("temperature", "request_timeout", "retry_delay"):
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be finite and nonnegative")
        if self.request_timeout <= 0 or not 0 <= self.temperature <= 2:
            raise ValueError("request_timeout must be > 0; temperature must be in [0, 2]")
        if self.max_tokens >= self.context_limit:
            raise ValueError("max_tokens must be less than context_limit")
        if not isinstance(self.proportions, list) or not self.proportions or any(
            type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in self.proportions
        ):
            raise ValueError("proportions must be a nonempty list of values in [0, 1]")
        if not isinstance(self.model_type_list, list) or not self.model_type_list or any(
            not isinstance(m, str) or not m.strip() for m in self.model_type_list
        ):
            raise ValueError("model_type_list must contain model names")
        for key in ("report_bdi", "total_round_info"):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key} must be boolean")
        if self.thinking is not None and type(self.thinking) is not bool:
            raise ValueError("thinking must be boolean or null")
        if not isinstance(self.extra_body, dict):
            raise ValueError("extra_body must be an object")
        if not isinstance(self.api_base_url, str) or not self.api_base_url.startswith(("https://", "http://")):
            raise ValueError("api_base_url must be an HTTP(S) endpoint")
        if not isinstance(self.api_key_env, str) or not self.api_key_env:
            raise ValueError("api_key_env must name the credential environment variable")

    def load_credentials(self):
        self.api_key = os.getenv(self.api_key_env)
        if not self.api_key:
            raise ValueError(f"Set {self.api_key_env} in .env or the environment")

    @property
    def planned_calls(self):
        return 2 * self.num_agents * self.rounds * len(self.proportions) * self.iterations * len(self.model_type_list)

    def to_dict(self):
        return {key: value for key, value in vars(self).items() if key != "api_key"}
