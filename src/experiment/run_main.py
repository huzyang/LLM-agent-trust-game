"""Run or resume checkpointed trust-game experiments from the project root."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import sys

# Both "python -m src.experiment.run_main" and "python src/experiment/run_main.py".
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.experiment.llm import ExperimentPaused, MockChat, OpenAIChat
from src.experiment.model import GameModel, PROMPT_PATH
from src.experiment.params import Params, GameScenario
from src.experiment.persistence import atomic_json, session_lock
from src.utils import CommonUtils

logger = logging.getLogger("experiment")
SCHEMA_VERSION = 2
CORE_FILES = ("agents.py", "decisions.py", "llm.py", "model.py", "params.py", "persistence.py")
RESUME_OVERRIDES = {"context_limit", "max_tokens", "request_timeout", "max_retries", "retry_delay"}


def scrub(value, secret):
    if isinstance(value, dict):
        return {k: scrub(v, secret) for k, v in value.items()
                if str(k).lower() not in {"api_key", "authorization", "access_token", "password"}}
    if isinstance(value, list):
        return [scrub(v, secret) for v in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


class Redact(logging.Filter):
    def __init__(self, params):
        super().__init__()
        self.params = params

    def filter(self, record):
        record.msg = scrub(record.getMessage(), self.params.api_key)
        record.args = ()
        return True


def setup_logging(directory, params):
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    file_handler = logging.FileHandler(Path(directory) / "run.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"))
    for handler in (file_handler, console):
        handler.addFilter(Redact(params))
        logger.addHandler(handler)
    # SDK transport logs are not useful stage progress and may include request bodies.
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def fingerprints():
    # Git may check out CRLF on Windows: normalize line endings for fingerprints.
    source = "".join((Path(__file__).parent / name).read_text(encoding="utf-8") for name in CORE_FILES).encode("utf-8")
    return {"engine_sha256": hashlib.sha256(source).hexdigest(),
            "prompt_sha256": hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()}


def build_scenarios(params):
    scenarios = []
    for model in params.model_type_list:
        for proportion in params.proportions:
            for iteration in range (1, params.iterations + 1):
                run_id = len(scenarios) + 1
                # Stable independent seeds, not Python's process-randomized hash().
                seed = int.from_bytes(hashlib.sha256(f"{params.seed}:{run_id}".encode()).digest()[:8], "big")
                scenarios.append(asdict(GameScenario(
                    num_agents=params.num_agents, width=params.width, height=params.height,
                    model_type=model, proportion=proportion, run_id=run_id,
                    iteration=iteration, seed=seed)))
    return scenarios


def export_run(directory, model, mock):
    import pandas as pd
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", model.model_type)
    subdir = Path(directory) / f"run_{model.run_id:03d}_{safe_name}"
    subdir.mkdir(exist_ok=True)
    rows, pairs, dialogue = model.run_model()
    source = "mock" if mock else "llm"
    pd.DataFrame([{**r, "data_source": source} for r in rows]).to_csv(subdir / "agent_rounds.csv", index=False)
    # Excel numbers retain only ~15 significant digits; store 64-bit seeds as text.
    pd.DataFrame([{**r, "seed": str(r["seed"]), "data_source": source} for r in pairs]).to_excel(
        subdir / "pair_data.xlsx", index=False, sheet_name="sent_returned_amount", engine="openpyxl")
    atomic_json(subdir / "dialogue.json", {**dialogue, "data_source": source})
    summary = {
        "scenario": asdict(model.scenario), "data_source": source,
        "agent_rows": len(rows), "pair_rows": len(pairs),
        "accepted_calls": len(model.token_usage), "total_tokens": sum(model.token_usage),
        "corrected_calls": model.corrected_calls, "parse_failures": model.parse_failures,
        "actual_free_count": sum(a.type_restriction == "free" for a in model.agents),
        "actual_proportion": sum(a.type_restriction == "free" for a in model.agents) / model.num_agents,
        "mean_round_payoff": sum(r["round_payoff"] for r in rows) / len(rows),
        "history_rounds": model.params.history_rounds,
        "payoff_convention": "trustor=received_return-sent; trustee=3*received_send-returned",
    }
    atomic_json(subdir / "summary.json", summary)
    return {"directory": subdir.name, "summary": summary}


def export_batch(directory, completed):
    import pandas as pd
    directory = Path(directory)
    frames = [pd.read_csv(directory / run["directory"] / "agent_rounds.csv", dtype={"seed": "string"})
              for run in completed]
    pair_frames = [pd.read_excel(directory / run["directory"] / "pair_data.xlsx", dtype={"seed": "string"})
                   for run in completed]
    pd.concat(frames, ignore_index=True).to_csv(directory / "agent_rounds.csv", index=False)
    pd.concat(pair_frames, ignore_index=True).to_excel(directory / "pair_data.xlsx", index=False,
                                                      sheet_name="sent_returned_amount", engine="openpyxl")
    atomic_json(directory / "summary.json", {
        "runs": len(completed),
        "data_source": completed[0]["summary"]["data_source"],
        "accepted_calls": sum(r["summary"]["accepted_calls"] for r in completed),
        "total_tokens": sum(r["summary"]["total_tokens"] for r in completed),
        "corrected_calls": sum(r["summary"]["corrected_calls"] for r in completed),
        "parse_failures": sum(r["summary"]["parse_failures"] for r in completed),
    })


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def run_session(directory, params, saved, mock, *, resuming=False):
    directory = Path(directory)
    checkpoint_path = directory / "checkpoint.json"
    with session_lock(directory):
        if resuming:
            # Re-read after acquiring the lock so a stale read cannot rewind progress.
            latest = read_json(checkpoint_path)
            if latest["status"] == "complete":
                logger.info("Experiment already complete | %s", directory)
                return 0
            saved = latest
        saved["params"] = params.to_dict()
        saved["status"] = "running"
        saved.pop("pause", None)
        atomic_json(checkpoint_path, saved)
        atomic_json(directory / "config.json", {"params": params.to_dict(), "mock": mock,
                    "schema_version": SCHEMA_VERSION, **fingerprints()})

        def event(kind, **details):
            record = {"time": datetime.now(timezone.utc).isoformat(), "event": kind,
                      "run_index": saved["scenario_index"], **details}
            with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(scrub(record, params.api_key), ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()

        def checkpoint(model):
            saved["current"] = model.to_state()
            atomic_json(checkpoint_path, saved)

        model = None
        gateway = None
        event("session_resume" if resuming else "session_start", mock=mock, params=params.to_dict())
        logger.info("Trust game | %s | agents=%s rounds=%s proportions=%s repeats=%s",
                    "MOCK / offline" if mock else "LLM / online",
                    params.num_agents, params.rounds, params.proportions, params.iterations)
        logger.info("Models=%s | history=%s | thinking=%s | seed=%s | planned calls=%s (before retries)",
                    params.model_type_list, params.history_rounds or "full",
                    params.thinking, params.seed, params.planned_calls)
        logger.info("Output | %s", directory)
        if params.report_bdi and params.max_tokens <= 512:
            logger.warning("BDI output limit=%s | replies may truncate; consider max_tokens=2048", params.max_tokens)
        try:
            if not mock:
                params.load_credentials()
            for index in range(saved["scenario_index"], len(saved["scenarios"])):
                saved["scenario_index"] = index
                scenario = GameScenario(**saved["scenarios"][index])
                gateway = (MockChat if mock else OpenAIChat)(params, scenario.model_type, event=event)
                model = GameModel(scenario, params, gateway, checkpoint, event, saved["current"])
                checkpoint(model)
                actual_free = sum(a.type_restriction == "free" for a in model.agents)
                logger.info("Run %s/%s | %s | requested p=%.2f actual=%s/%s | derived seed=%s",
                            scenario.run_id, len(saved["scenarios"]), scenario.model_type,
                            scenario.proportion, actual_free, scenario.num_agents, scenario.seed)
                model.run_model()
                exported = export_run(directory, model, mock)
                saved["completed"].append(exported)
                saved["current"] = None
                saved["scenario_index"] = index + 1
                atomic_json(checkpoint_path, saved)
                gateway.close()
                gateway = None
                logger.info("Run %s complete | tokens=%s corrected=%s parse_failed=%s",
                            scenario.run_id, sum(model.token_usage), model.corrected_calls, model.parse_failures)
            export_batch(directory, saved["completed"])
            saved["status"] = "complete"
            atomic_json(checkpoint_path, saved)
            event("session_complete")
            logger.info("Complete | %s/summary.json", directory)
            return 0
        except (ExperimentPaused, KeyboardInterrupt, ValueError) as exc:
            # Disk snapshot is authoritative: no partially-mutated live object.
            saved = read_json(checkpoint_path)
            reason = exc.reason if isinstance(exc, ExperimentPaused) else (
                "user_interrupt" if isinstance(exc, KeyboardInterrupt) else "configuration_error")
            details = exc.details if isinstance(exc, ExperimentPaused) else (
                {} if isinstance(exc, KeyboardInterrupt) else {"message": scrub(str(exc), params.api_key)})
            saved["status"] = "paused"
            saved["pause"] = {"reason": reason, "details": details}
            atomic_json(checkpoint_path, saved)
            event("session_paused", reason=reason, details=details)
            cursor = saved.get("current") or {}
            logger.error("Paused | %s | round=%s stage=%s saved=%s/%s",
                         reason, cursor.get("step", 1), cursor.get("phase", "initialization"),
                         cursor.get("next_agent", 0), params.num_agents)
            if reason == "output_truncated":
                logger.error("Truncated reply archived; increase max_tokens using --config before resuming")
            logger.error('Resume | python -m src.experiment.run_main --resume "%s"', directory)
            return 2
        except Exception:
            # Never convert an implementation/export error into a player's zero action.
            saved = read_json(checkpoint_path)
            saved["status"] = "paused"
            saved["pause"] = {"reason": "internal_or_export_error"}
            atomic_json(checkpoint_path, saved)
            logger.exception("Unexpected failure; last accepted decision remains checkpointed")
            return 2
        finally:
            if gateway is not None:
                gateway.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="LLM trust game with atomic checkpoints and resume")
    parser.add_argument("--config", help="JSON settings; on resume only request/context limits may change")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; no API, no output files")
    parser.add_argument("--mock", action="store_true", help="Deterministic offline simulation, labelled MOCK")
    parser.add_argument("--resume", help="Existing output directory or checkpoint.json")
    parser.add_argument("--output-dir", help="New experiment directory (must not contain previous outputs)")
    args = parser.parse_args(argv)
    params = Params(require_credentials=False)
    saved = None
    try:
        config = read_json(args.config) if args.config else {}
        if args.resume:
            if args.output_dir:
                raise ValueError("--resume and --output-dir cannot be combined")
            resume_path = Path(args.resume).resolve()
            directory = resume_path.parent if resume_path.is_file() else resume_path
            saved = read_json(directory / "checkpoint.json")
            if saved["schema_version"] != SCHEMA_VERSION:
                raise ValueError("Unsupported checkpoint version")
            current_fingerprints = fingerprints()
            # Accept pre-normalization checkpoints only when the exact current
            # bytes match their stored hash; actual code changes still fail.
            legacy_hash = hashlib.sha256(b"".join(
                (Path(__file__).parent / name).read_bytes() for name in CORE_FILES)).hexdigest()
            if (saved["prompt_sha256"] != current_fingerprints["prompt_sha256"] or
                    saved["engine_sha256"] not in (current_fingerprints["engine_sha256"], legacy_hash)):
                raise ValueError("Engine or prompts changed; use the original code to resume this experiment")
            params.update({k: v for k, v in saved["params"].items() if k not in ("width", "height")})
            if set(config) - RESUME_OVERRIDES:
                raise ValueError(f"Resume may only change: {sorted(RESUME_OVERRIDES)}")
            if args.mock and not saved["mock"]:
                raise ValueError("Cannot resume a real experiment as mock")
            mock = saved["mock"]
        else:
            mock = args.mock
        params.update(config)
        # Prompt coverage validation even in dry-run, before paying for requests.
        characters = read_json(PROMPT_PATH)["Character"]
        if params.num_agents > len(characters):
            raise ValueError(f"Only {len(characters)} character prompts available")
        if args.dry_run:
            print(json.dumps(params.to_dict(), ensure_ascii=False, indent=2))
            print(f"Planned agent-stage calls (excluding retries): {params.planned_calls}")
            print("Validation only: no model requests and no output files.")
            return 0
        if not saved:
            suffix = "_mock" if mock else "_llm"
            directory = Path(args.output_dir).resolve() if args.output_dir else (
                Path(CommonUtils.get_project_root_path()) / "outputs" /
                (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + suffix))
            if directory.exists() and any(directory.iterdir()):
                raise ValueError("Output directory must be empty; use --resume for existing experiments")
            directory.mkdir(parents=True, exist_ok=True)
            saved = {"schema_version": SCHEMA_VERSION, **fingerprints(), "mock": mock,
                     "params": params.to_dict(), "scenarios": build_scenarios(params),
                     "scenario_index": 0, "current": None, "completed": [], "status": "new"}
        setup_logging(directory, params)
        try:
            return run_session(directory, params, saved, mock, resuming=bool(args.resume))
        finally:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
