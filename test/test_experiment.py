"""Protocol, amount safety, API payload and interruption/recovery regression tests."""
import hashlib
import io
from contextlib import redirect_stderr
from decimal import Decimal
import json
import logging
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI
from src.experiment.decisions import normalize_decision
from src.experiment.llm import ExperimentPaused, MockChat, OpenAIChat, LLMResponse
from src.experiment.model import GameModel
from src.experiment.params import GameScenario, Params
from src.experiment.persistence import atomic_json
from src.experiment.run_main import CORE_FILES, build_scenarios, main, scrub

ROOT = Path(__file__).resolve().parents[1]


def setUpModule():
    (ROOT / "outputs").mkdir(exist_ok=True)
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)


def params(rounds=1):
    result = Params(require_credentials=False)
    result.rounds = rounds
    result.retry_delay = 0
    result.validate()
    return result


class CountingMock(MockChat):
    def __init__(self, p, pause_at=None):
        super().__init__(p, "deepseek-flash")
        self.calls = []
        self.pause_at = pause_at

    def complete(self, messages, **kwargs):
        key = (kwargs["round_number"], kwargs["stage"], kwargs["agent"].unique_id)
        if len(self.calls) == self.pause_at:
            raise ExperimentPaused("injected_failure")
        self.calls.append(key)
        return super().complete(messages, **kwargs)


class ProtocolTests(unittest.TestCase):
    def test_fixed_torus_seed_and_neighbors(self):
        for side in (3, 6, 7):
            p = params()
            scenario = GameScenario(num_agents=side**2, width=side, height=side, seed=51)
            a = GameModel(scenario, p, MockChat(p, "mock"))
            b = GameModel(scenario, p, MockChat(p, "mock"))
            self.assertEqual([x.type_restriction for x in a.agents], [x.type_restriction for x in b.agents])
            for agent in a.agents:
                self.assertEqual(len(set(agent.neighbor_ids)), 4)
                self.assertNotIn(agent.unique_id, agent.neighbor_ids)
                for nid in agent.neighbor_ids:
                    self.assertIn(agent.unique_id, a.get_agent(nid).neighbor_ids)
            self.assertEqual(a.get_agent(0).neighbor_ids, sorted([1, side-1, side, side*(side-1)]))

    def test_seed_derivation_is_stable_and_independent(self):
        p = params()
        p.iterations = 3
        first = build_scenarios(p)
        self.assertEqual(first, build_scenarios(p))
        self.assertEqual(len(set(s["seed"] for s in first)), 3)
        p.seed += 1
        self.assertNotEqual(first, build_scenarios(p))

    def test_paper_payoff_and_pair_return_direction(self):
        p = params()
        class Scripted:
            def complete(self, messages, *, agent, round_number, stage):
                values = ({i: 0.25 for i in agent.neighbor_ids} if stage == "investor" else
                          {i: agent.unique_id/100 for i in agent.neighbor_ids})
                return LLMResponse(json.dumps(values))
        model = GameModel(params=p, gateway=Scripted())
        rows, pairs, _ = model.run_model()
        self.assertEqual((len(rows), len(pairs)), (9, 36))
        self.assertAlmostEqual(sum(r["round_payoff"] for r in rows), 18)
        row = next(r for r in pairs if r["trustor_id"] == 0 and r["trustee_id"] == 1)
        self.assertEqual(row["returned_amount"], 0.01)  # B -> A, not A -> B (0).
        for agent in model.agents:
            self.assertEqual(agent.trustor_payoff, round(agent.total_received_return-agent.total_sent, 2))
            self.assertEqual(agent.balance, agent.round_payoff)

    def test_history_keeps_three_complete_rounds_and_current_stage(self):
        p = params(5)
        gateway = CountingMock(p)
        model = GameModel(params=p, gateway=gateway)
        model.run_model()
        agent = model.get_agent(0)
        messages = agent.messages(6, "CURRENT", 3)
        self.assertEqual(len(messages), 14)  # system + 3*(2 stages*2 messages) + current
        self.assertEqual([t["round"] for t in agent.history if t["round"] >= 3], [3,3,4,4,5,5])
        model2 = GameModel(params=p, gateway=CountingMock(p))
        p.history_rounds = None
        model2.run_model()
        self.assertEqual(len(model2.get_agent(0).messages(6, "CURRENT", None)), 22)

    def test_resume_mid_stages_skips_saved_calls_and_preserves_prompts(self):
        for failed_call in (2, 9, 13, 18, 27):
            with self.subTest(failed_call=failed_call), tempfile.TemporaryDirectory() as temp:
                p = params(2)
                reference = GameModel(params=p, gateway=CountingMock(p))
                expected = reference.run_model()
                path = Path(temp) / "checkpoint.json"
                first_gateway = CountingMock(p, pause_at=failed_call)
                first = GameModel(params=p, gateway=first_gateway,
                                  checkpoint=lambda m: atomic_json(path, m.to_state()))
                with self.assertRaises(ExperimentPaused):
                    first.run_model()
                state = json.loads(path.read_text(encoding="utf-8"))
                next_gateway = CountingMock(p)
                resumed = GameModel(GameScenario(**state["scenario"]), p, next_gateway, state=state)
                actual = resumed.run_model()
                self.assertEqual(actual, expected)
                self.assertEqual(len(first_gateway.calls)+len(next_gateway.calls), 36)
                self.assertEqual(len(set(first_gateway.calls+next_gateway.calls)), 36)

    def test_resume_after_stage_or_round_checkpoint_is_idempotent(self):
        for target in (("investor", 9, 1), ("trustee", 0, 1), ("trustee", 9, 1),
                       ("finalize", 0, 1), ("investor", 0, 2), ("complete", 0, 3)):
            p = params(2)
            reference = GameModel(params=p, gateway=CountingMock(p))
            expected = reference.run_model()
            captured = []
            def save(model):
                if not captured and (model.phase, model.next_agent, model.step) == target:
                    captured.append(json.loads(json.dumps(model.to_state())))
                    raise ExperimentPaused("injected_checkpoint_pause")
            first_gateway = CountingMock(p)
            first = GameModel(params=p, gateway=first_gateway, checkpoint=save)
            with self.assertRaises(ExperimentPaused):
                first.run_model()
            gateway = CountingMock(p)
            resumed = GameModel(GameScenario(**captured[0]["scenario"]), p, gateway, state=captured[0])
            self.assertEqual(resumed.run_model(), expected)
            self.assertEqual(len(first_gateway.calls)+len(gateway.calls), 36)


class DecisionTests(unittest.TestCase):
    neighbors = [1, 2, 3, 4]

    def norm(self, text, stage="investor", restriction="free", budget=5):
        return normalize_decision(text, self.neighbors, stage, restriction, budget)

    def test_budget_scaling_preserves_proportions(self):
        d = self.norm('{1: 6, 2: 3, 3: 1, 4: 0}')
        self.assertEqual(d.amounts, {1:3.0, 2:1.5, 3:0.5, 4:0.0})
        self.assertIn("scaled_to_budget", d.corrections)

    def test_equal_payments_negative_missing_unknown_and_precision(self):
        d = self.norm('{1: -1, 2: 2.005, 99: 8}', restriction="constrained")
        self.assertEqual(d.amounts, {i:0.50 for i in self.neighbors})
        self.assertIn("negative_to_zero", d.corrections)
        self.assertIn("non_neighbor_ignored", d.corrections)
        self.assertIn("missing_neighbors_to_zero", d.corrections)
        self.assertEqual(self.norm('{1:1,2:2,3:3,4:4}',stage="trustee",budget=3).amounts,
                         {i:0.75 for i in self.neighbors})

    def test_unparseable_and_nonfinite(self):
        self.assertTrue(self.norm("sorry, no decision").parse_failed)
        self.assertEqual(self.norm("sorry, no decision").amounts, {i:0 for i in self.neighbors})
        d = self.norm('{"1": NaN, "2": Infinity, "3": true, "4": "abc"}')
        self.assertEqual(d.amounts, {i:0 for i in self.neighbors})

    def test_total_return_and_final_bdi_dictionary(self):
        self.assertEqual(self.norm('{"total_return": 1.03}', stage="trustee",budget=3).amounts,
                         {i:0.25 for i in self.neighbors})
        self.assertEqual(self.norm('explanation {1: 9} final {1:1,2:1,3:1,4:1}').amounts,
                         {i:1 for i in self.neighbors})

    def test_generated_decisions_always_obey_invariants(self):
        rng = random.Random(71)
        for _ in range(150):
            for stage in ("investor", "trustee"):
                restriction = rng.choice(["free", "constrained"])
                budget = Decimal(rng.randint(0,6000))/100 if stage == "trustee" else Decimal(5)
                raw = {str(i): rng.uniform(-10,100) for i in self.neighbors + [99]}
                d = self.norm(json.dumps(raw), stage, restriction, budget)
                values = [Decimal(str(v)) for v in d.amounts.values()]
                self.assertEqual(set(d.amounts), set(self.neighbors))
                self.assertTrue(all(v >= 0 and v == v.quantize(Decimal('.01')) for v in values))
                self.assertLessEqual(sum(values), budget)
                if stage == "trustee" or restriction == "constrained":
                    self.assertEqual(len(set(values)), 1)


class APITests(unittest.TestCase):
    def client(self, handler):
        return OpenAI(api_key="test-secret", base_url="https://test.invalid/v1",
                      http_client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0)

    def response(self):
        return {"id":"test-response", "object":"chat.completion", "created":0, "model":"flash-test",
                "choices":[{"index":0,"message":{"role":"assistant","content":"{1:0,2:0,3:0,4:0}"},
                            "finish_reason":"stop"}],
                "usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}

    def request(self, gateway):
        return gateway.complete([{"role":"system","content":"test"},{"role":"user","content":"decide"}],
                                agent=SimpleNamespace(unique_id=0),round_number=1,stage="investor")

    def test_deepseek_thinking_disabled_and_generic_compatibility(self):
        bodies=[]
        def handler(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200,json=self.response())
        p=params()
        with self.client(handler) as client:
            gateway=OpenAIChat(p,"deepseek-flash",client)
            result=self.request(gateway)
            self.assertEqual(result.usage["total_tokens"],15)
            self.assertEqual(bodies[-1]["thinking"],{"type":"disabled"})
            p.thinking=True
            self.request(gateway)
            self.assertEqual(bodies[-1]["thinking"],{"type":"enabled"})
            self.assertNotIn("temperature",bodies[-1])
            self.request(OpenAIChat(p,"some-other-provider",client))
            self.assertNotIn("thinking",bodies[-1])

    def test_transient_retry_then_success_and_permanent_pause(self):
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(429,json={"error":{"message":"busy","type":"rate_limit"}}) if len(calls)==1 else httpx.Response(200,json=self.response())
        with self.client(handler) as client:
            result=self.request(OpenAIChat(params(),"deepseek-flash",client))
            self.assertEqual((len(calls),result.attempts),(2,2))
        calls=[]
        def unauthorized(request):
            calls.append(request)
            return httpx.Response(401,json={"error":{"message":"no credit or auth","type":"auth"}})
        with self.client(unauthorized) as client:
            with self.assertRaises(ExperimentPaused):
                self.request(OpenAIChat(params(),"deepseek-flash",client))
        self.assertEqual(len(calls),1)

    def test_local_and_provider_context_limits_pause_without_zero_actions(self):
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(400,json={"error":{"message":"maximum context length exceeded","type":"context_length_exceeded"}})
        p=params()
        with self.client(handler) as client:
            p.context_limit=520
            with self.assertRaises(ExperimentPaused) as exc:
                self.request(OpenAIChat(p,"deepseek-flash",client))
            self.assertEqual(exc.exception.reason,"context_budget_exceeded")
            self.assertEqual(calls,[])
            p.context_limit=131072
            with self.assertRaises(ExperimentPaused) as exc:
                self.request(OpenAIChat(p,"deepseek-flash",client))
            self.assertEqual(exc.exception.reason,"provider_context_exceeded")
            self.assertEqual(len(calls),1)


class CLITests(unittest.TestCase):
    def test_legacy_byte_fingerprint_and_changed_source_rejection(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temp:
            out = Path(temp) / "fingerprint"
            self.assertEqual(main(["--mock", "--output-dir", str(out)]), 0)
            path = out / "checkpoint.json"
            saved = json.loads(path.read_text(encoding="utf-8"))
            saved["engine_sha256"] = hashlib.sha256(b"".join(
                (ROOT / "src/experiment" / name).read_bytes() for name in CORE_FILES)).hexdigest()
            atomic_json(path, saved)
            self.assertEqual(main(["--resume", str(out)]), 0)
            saved["engine_sha256"] = "0" * 64
            atomic_json(path, saved)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main(["--resume", str(out)])
            self.assertEqual(raised.exception.code, 2)

    def test_batch_resume_and_seed_export_precision(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temp:
            config = Path(temp) / "batch.json"
            config.write_text(json.dumps({"model_type_list": ["model-a", "model-b"]}), encoding="utf-8")
            out = Path(temp) / "batch"
            gateways = []
            def factory(p, name, **kwargs):
                gateway = CountingMock(p, pause_at=2 if name == "model-b" else None)
                gateways.append(gateway)
                return gateway
            with patch("src.experiment.run_main.MockChat", side_effect=factory):
                self.assertEqual(main(["--mock", "--config", str(config), "--output-dir", str(out)]), 2)
            saved = json.loads((out / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual((saved["scenario_index"], len(saved["completed"]), saved["current"]["next_agent"]), (1, 1, 2))
            self.assertEqual(main(["--resume", str(out)]), 0)
            import pandas as pd
            from openpyxl import load_workbook
            df = pd.read_csv(out / "agent_rounds.csv", dtype={"seed": "string"})
            self.assertEqual(len(df), 18)
            seeds = {str(s["seed"]) for s in saved["scenarios"]}
            self.assertEqual(set(df["seed"]), seeds)
            workbook = load_workbook(out / "pair_data.xlsx")
            sheet = workbook.active
            seed_col = next(cell.column for cell in sheet[1] if cell.value == "seed")
            values = {sheet.cell(row, seed_col).value for row in range(2, sheet.max_row + 1)}
            self.assertEqual(values, seeds)
            workbook.close()

    def test_mock_export_resume_and_context_pause(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temp:
            out=Path(temp)/"run"
            self.assertEqual(main(["--mock","--output-dir",str(out)]),0)
            saved=json.loads((out/"checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"],"complete")
            self.assertEqual(saved["completed"][0]["summary"]["accepted_calls"],18)
            event_lines=len((out/"events.jsonl").read_text(encoding="utf-8").splitlines())
            self.assertEqual(main(["--resume",str(out)]),0)
            self.assertEqual(len((out/"events.jsonl").read_text(encoding="utf-8").splitlines()),event_lines)
            config=Path(temp)/"small_context.json"
            config.write_text(json.dumps({"context_limit":600}),encoding="utf-8")
            out2=Path(temp)/"paused"
            self.assertEqual(main(["--mock","--config",str(config),"--output-dir",str(out2)]),2)
            saved=json.loads((out2/"checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["current"]["next_agent"],0)
            config.write_text(json.dumps({"context_limit":131072}),encoding="utf-8")
            self.assertEqual(main(["--resume",str(out2),"--config",str(config)]),0)

    def test_experiment_imports_without_mesa_camel_or_analysis(self):
        script='''import sys, importlib.abc
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path, target=None):
  if fullname.split('.')[0] in {'mesa','camel','mcp','tiktoken','matplotlib','seaborn','sklearn'}:
   raise AssertionError('unwanted dependency: '+fullname)
sys.meta_path.insert(0,Deny())
from src.experiment.run_main import main
raise SystemExit(main(['--dry-run']))
'''
        result=subprocess.run([sys.executable,"-c",script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_redaction_and_bad_configs(self):
        self.assertEqual(scrub({1:"secret", "api_key":"secret"},"secret"),{1:"[REDACTED]"})
        for config in ({"num_agents":4},{"proportions":0.5},{"history_rounds":0},{"seed":True},
                       {"request_timeout":0},{"game_type":"pd_game"},{"max_retries":-1}):
            with self.assertRaises(ValueError):
                params().update(config)


if __name__ == "__main__":
    unittest.main()
