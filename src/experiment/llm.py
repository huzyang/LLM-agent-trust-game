"""OpenAI-compatible adapter with explicit timeout, retries and context guard."""
from dataclasses import dataclass, field
import hashlib
import json
import logging
import random
import time

logger = logging.getLogger("experiment")


class ExperimentPaused(RuntimeError):
    def __init__(self, reason, details=None):
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


@dataclass
class LLMResponse:
    content: str
    reasoning_content: str = ""
    usage: dict = field(default_factory=dict)
    response_id: str = ""
    model: str = ""
    finish_reason: str = ""
    attempts: int = 1


def context_upper_bound(messages):
    # Conservative UTF-8 byte estimate for common byte BPE tokenizers, not an
    # exact provider token count. Provider context errors also trigger a pause.
    return 64 + sum(32 + len(m["content"].encode("utf-8")) for m in messages)


class OpenAIChat:
    def __init__(self, params, model_name, client=None, event=None):
        self.params, self.model_name = params, model_name
        self.event = event or (lambda *a, **kw: None)
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=params.api_key, base_url=params.api_base_url,
                            timeout=params.request_timeout, max_retries=0)
        self.client = client

    def complete(self, messages, *, agent, round_number, stage):
        p = self.params
        estimated = context_upper_bound(messages)
        if estimated + p.max_tokens > p.context_limit:
            raise ExperimentPaused("context_budget_exceeded", {
                "estimated_input_upper_bound": estimated, "context_limit": p.context_limit,
                "reserved_output": p.max_tokens})
        extra_body = dict(p.extra_body)
        if self.model_name.startswith("deepseek") and p.thinking is not None:
            # 开启思考：配置 "thinking": true，等价于下面的 type="enabled"。
            # 其他供应商可用 extra_body 配置其专属开关，例如 enable_thinking。
            extra_body["thinking"] = {"type": "enabled" if p.thinking else "disabled"}
        kwargs = dict(model=self.model_name, messages=messages, max_tokens=p.max_tokens, stream=False)
        if not (self.model_name.startswith("deepseek") and p.thinking):
            kwargs["temperature"] = p.temperature
        if extra_body:
            kwargs["extra_body"] = extra_body
        for attempt in range(1, p.max_retries + 2):
            started = time.monotonic()
            try:
                response = self.client.chat.completions.create(**kwargs)
                if not response.choices:
                    raise ExperimentPaused("empty_api_choices")
                choice = response.choices[0]
                usage = response.usage.model_dump() if response.usage else {}
                result = LLMResponse(choice.message.content or "",
                                     getattr(choice.message, "reasoning_content", "") or "",
                                     usage, response.id, response.model, choice.finish_reason or "", attempt)
                self.event("api_success", agent_id=agent.unique_id, round=round_number, stage=stage,
                           attempt=attempt, duration_seconds=round(time.monotonic()-started, 3),
                           response_id=result.response_id, response_model=result.model, usage=usage,
                           estimated_input_upper_bound=estimated, finish_reason=result.finish_reason)
                return result
            except ExperimentPaused:
                raise
            except Exception as exc:
                status, code = getattr(exc, "status_code", None), getattr(exc, "code", None)
                message = str(exc)
                if p.api_key:
                    message = message.replace(p.api_key, "[REDACTED]")
                message = message[:1500]
                context_error = status == 400 and any(s in message.lower() for s in (
                    "context_length", "context length", "maximum context", "context window", "too many tokens"))
                retryable = status in (408, 409, 429) or (isinstance(status, int) and status >= 500) or type(exc).__name__ in (
                    "APIConnectionError", "APITimeoutError", "TimeoutError", "ConnectionError")
                details = dict(error_type=type(exc).__name__, status_code=status,
                               error_code=code, message=message, attempt=attempt)
                self.event("api_error", agent_id=agent.unique_id, round=round_number, stage=stage, **details)
                if context_error:
                    raise ExperimentPaused("provider_context_exceeded", details) from None
                if not retryable or attempt > p.max_retries:
                    raise ExperimentPaused("api_request_failed", details) from None
                delay = min(p.retry_delay * 2 ** (attempt - 1), 30)
                logger.warning("Request retry | round=%s stage=%s agent=%s attempt=%s/%s status=%s wait=%.1fs",
                               round_number, stage, agent.unique_id, attempt, p.max_retries + 1, status, delay)
                time.sleep(delay)

    def close(self):
        self.client.close()


class MockChat:
    """Deterministic offline simulation, explicitly labelled as mock data."""
    def __init__(self, params, model_name, **kwargs):
        self.params, self.model_name = params, model_name

    def complete(self, messages, *, agent, round_number, stage):
        estimated = context_upper_bound(messages)
        if estimated + self.params.max_tokens > self.params.context_limit:
            raise ExperimentPaused("context_budget_exceeded", {"estimated_input_upper_bound": estimated})
        digest = hashlib.sha256(f"{agent.model.scenario.seed}:{round_number}:{stage}:{agent.unique_id}".encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        if stage == "investor":
            total = rng.randint(0, 500) / 100
            weights = [rng.random() for _ in agent.neighbor_ids]
            amounts = {nid: total*w/sum(weights) for nid, w in zip(agent.neighbor_ids, weights)}
        else:
            total = agent.total_received_as_trustee * rng.random()
            amounts = {nid: total / 4 for nid in agent.neighbor_ids}
        return LLMResponse(json.dumps(amounts), usage={"total_tokens": 0},
                           model="MOCK", response_id="mock", finish_reason="stop")

    def close(self):
        pass
