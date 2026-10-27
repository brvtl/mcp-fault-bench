"""Run an agent (via an adapter, default Claude Code) against clean and faulted MCP servers, grade runs, and summarize."""

from __future__ import annotations

import concurrent.futures
import json
import math
import os
import random
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from bench.adapters import (LEGACY_ADAPTER, AgentAdapter, available_adapters, get_adapter,  # noqa: F401
                            register_adapter, row_adapter)
from bench.adapters.claude_code import (CLAUDE_ENV, MODELS, STREAM_EVENTS, _event_type, _short_tool,  # noqa: F401
                                        claude_bin, claude_command, keep_stream_events, parse_stream)
from bench.scrub import scrub_file
from mcp_fault_bench.shim import load_shim_config

ROOT = Path(__file__).resolve().parents[1]
SHIM_PROFILE = ROOT / "profiles" / "shim.yaml"
RESULTS = ROOT / "results"
RUNS = RESULTS / "runs"
DEFAULT_MODELS = MODELS  # the claude-code adapter's models (round 1)
CONDITIONS = ("clean", "chaos", "chaos_scoped")  # headline conditions
SHIM_CONDITIONS = ("clean_shim", "chaos_shim", "chaos_scoped_shim")
CAP_CONDITIONS = ("chaos_cap3000",)  # sensitivity rerun only
ALL_CONDITIONS = CONDITIONS + SHIM_CONDITIONS + CAP_CONDITIONS
SHORT = {"clean": "c", "chaos": "x", "chaos_scoped": "s", "clean_shim": "C", "chaos_shim": "X",
         "chaos_scoped_shim": "S", "chaos_cap3000": "L"}
SCHEDULES = {"clean": "profiles/empty.yaml", "chaos": "profiles/paper_opp.yaml",
             "chaos_scoped": "profiles/paper_opp_scoped.yaml", "clean_shim": "profiles/empty.yaml",
             "chaos_shim": "profiles/paper_opp.yaml", "chaos_scoped_shim": "profiles/paper_opp_scoped.yaml",
             "chaos_cap3000": "profiles/paper_opp.yaml"}
SCOPED = ("chaos_scoped", "chaos_scoped_shim")
SHIM_CONFIG = "profiles/shim.yaml"
RUN_CAPS = {"chaos_cap3000": 3000}  # overrides --run-cap
# (shim condition, base condition) for the shim lift.
SHIM_PAIRS = (("chaos_shim", "chaos"), ("chaos_scoped_shim", "chaos_scoped"), ("clean_shim", "clean"))
HEADLINE_REPS = 10  # reps 1..10 are the paper-weighted headline sample; higher reps come from a rep file
WINNABLE_CONDITIONS = ("chaos", "chaos_shim")
FAULTED_CONDITIONS = ("chaos", "chaos_scoped", "chaos_shim", "chaos_scoped_shim")
# Pre-registered (docs/preregistration-shim.md): targets with a real fallback tool in profiles/shim.yaml.
FALLBACK_ELIGIBLE = ("get_price", "get_price_v2", "get_note", "list_notes")
SEED_SELECTED = "seed-selected, not paper-faithful"
DISPLAY_NAME = "MCP Fault Bench"
HEADLINE_PAIR = ("claude-opus-5-5", "claude-sonnet-5-5")  # headline between-model test (one-tool condition)
UNWINNABLE = "OP4/permanent"
OP4_ELIGIBLE = "OP4/permanent first draw × fallback-eligible target"
OP4_NO_FALLBACK = "OP4/permanent × no fallback"
FALLBACKS = {"get_price_v2": "get_price", "search_notes": "get_note"}
USAGE_FIELDS = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens",
                "thinkingTokens", "costUSD")
WALL_CLOCK_SECONDS = 600
HARNESS_FIELDS = ("id", "task", "model", "adapter", "effort", "condition", "rep", "seed", "target_tool", "outcome",
                  "wall_time")
ADAPTER_ENV = "MCP_FAULT_BENCH_ADAPTER"  # default for arena --adapter
_write_lock = threading.Lock()


def agent_fallbacks() -> dict[str, list[str]]:
    """The fallback tools the shim names in its errors (profiles/shim.yaml); used to classify post-error behaviour."""
    profile = yaml.safe_load(SHIM_PROFILE.read_text())
    return {tool: list(names) for tool, names in (profile.get("fallbacks") or {}).items()}


def target_behaviour(calls: list[dict[str, Any]], target: str | None,
                     fallbacks: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """What the agent did on the faulted target tool once an error result from it had come back.

    target_errored: some call to the target returned an error result. target_retried: a later call repeated a
    failed (target, arguments) pair after its error came back. target_fallback: after the first target error the
    agent called one of the target's fallback tools. target_after_error: "retried", "fallback", "both" or
    "stopped" (neither); None when the target never returned an error.
    """
    calls = [call for call in calls if call["name"].startswith("mcp__")]
    repeats = retry_counts(calls)
    errors = [call["result_at"] for call in calls
              if call["tool"] == target and call["is_error"] and call.get("result_at") is not None]
    base = {"target_errored": bool(errors), "target_repeated": target in repeats["repeated_tools"],
            "target_retried": target in repeats["retried_tools"], "target_fallback": False,
            "target_after_error": None}
    if not errors:
        return base
    first_error = min(errors)
    options = set((fallbacks if fallbacks is not None else agent_fallbacks()).get(target or "", []))
    fallback = any(call["tool"] in options and (call.get("issued_at") or 0) > first_error for call in calls)
    retried = base["target_retried"]
    kind = "both" if retried and fallback else "retried" if retried else "fallback" if fallback else "stopped"
    return {**base, "target_fallback": fallback, "target_after_error": kind}


def allowed_models(adapter: AgentAdapter | None = None) -> set[str] | None:
    """Models the arena accepts (None: any); override with ARENA_ALLOWED_MODELS=a,b,c."""
    configured = os.getenv("ARENA_ALLOWED_MODELS")
    if configured:
        return {model.strip() for model in configured.split(",")}
    return (adapter or get_adapter(LEGACY_ADAPTER)).allowed_models()


def resolve_adapter(name: str | None = None) -> AgentAdapter:
    """--adapter, else $MCP_FAULT_BENCH_ADAPTER, else claude-code; unknown names list the registered adapters."""
    return get_adapter(name or os.getenv(ADAPTER_ENV) or LEGACY_ADAPTER)


def load_runs(path: Path) -> list[dict[str, Any]]:
    """Result rows from a results file; rows written before adapters existed are tagged claude-code (in memory)."""
    return [{**row, "adapter": row_adapter(row)} for row in _read_jsonl(path)]


def run_seed(base_seed: Any, task_id: str, rep: int) -> str:
    """Seed string shared by every model and by chaos/chaos_scoped for one (task, rep)."""
    return f"{base_seed}:{task_id}:{rep}"


def pick_target(base_seed: Any, task: dict[str, Any], rep: int) -> str | None:
    """The single tool faulted in chaos_scoped for one (task, rep)."""
    targets = task.get("fault_targets") or []
    return random.Random(f"{base_seed}:{task['id']}:{rep}:target").choice(targets) if targets else None


def run_target(condition: str, base_seed: Any, task: dict[str, Any], rep: int) -> str | None:
    """Faulted tool for one run: chaos_scoped and chaos_scoped_shim draw the same target for the same seed."""
    return pick_target(base_seed, task, rep) if condition in SCOPED else None


def run_shim(condition: str) -> Path | None:
    """Shim config passed to the proxies: profiles/shim.yaml for every *_shim condition, else none."""
    return ROOT / SHIM_CONFIG if condition in SHIM_CONDITIONS else None


def shim_mode(condition: str) -> str | None:
    """The ``mode`` of the condition's shim config (None without a shim), read from this checkout."""
    if condition not in SHIM_CONDITIONS:
        return None
    return load_shim_config(str(Path(__file__).resolve().parents[1] / SHIM_CONFIG))["mode"]


def _load_state(states: dict[str, str], name: str) -> Any:
    try:
        return json.loads(Path(states[name]).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def grade(task: dict[str, Any], answer: str, states: dict[str, str]) -> bool:
    """Check the task's requested answer or persisted server side effects."""
    return _check(task["grade"], answer, states)


def _check(grading: dict[str, Any], answer: str, states: dict[str, str]) -> bool:
    kind = grading["type"]
    if kind == "all":
        return all(_check(check, answer, states) for check in grading["checks"])
    if kind == "answer_number":
        match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", answer or "")
        return bool(match and abs(float(match.group().replace(",", "")) - float(grading["value"])) < 0.005)
    state = _load_state(states, "inventory" if kind in ("order", "orders_exact") else "notes")
    if not isinstance(state, dict):
        return False
    if kind == "order":
        return any(order.get("sku") == grading["sku"] and order.get("quantity") == grading["quantity"]
                   for order in state.get("orders", []))
    if kind == "orders_exact":
        return state.get("orders", []) == grading["orders"]
    if kind == "note":
        return state.get(grading["key"]) == grading["value"]
    return False


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read valid JSON object lines, skipping incomplete or malformed lines."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def call_stats(calls: list[dict[str, Any]], proxy_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Tool calls, errored calls, retries, fallback and built-in tool usage for one run.

    A call counts as failed when Claude saw an error result or the proxy fired a fault on it
    (content faults such as OP2 do not look like errors to the agent). Proxy events are matched to
    MCP calls per tool in order.
    """
    proxy_calls: dict[str, list[dict[str, Any]]] = {}
    for event in proxy_events:
        if event.get("method", "tools/call") == "tools/call":
            proxy_calls.setdefault(event.get("tool", ""), []).append(event)
    positions: dict[str, int] = {}
    sequence: list[tuple[str, bool]] = []
    builtin: list[str] = []
    for call in calls:
        if not call["name"].startswith("mcp__"):
            builtin.append(call["name"])
            continue
        tool = call["tool"]
        position = positions.get(tool, 0)
        matching = proxy_calls.get(tool, [])
        faulted = position < len(matching) and bool(matching[position].get("fault"))
        positions[tool] = position + 1
        sequence.append((tool, bool(call["is_error"]) or faulted))
    used_fallback = False
    failed_tools: set[str] = set()
    for tool, failed in sequence:
        if FALLBACKS.get(tool) in failed_tools:
            used_fallback = True
        if failed:
            failed_tools.add(tool)
    repeats = retry_counts([call for call in calls if call["name"].startswith("mcp__")])
    return {"tool_calls": len(sequence), "errored_tool_calls": sum(1 for call in calls
                                                                   if call["name"].startswith("mcp__") and call["is_error"]),
            "retries": repeats["retries"], "retried_tools": repeats["retried_tools"],
            "same_args_repeats": repeats["same_args_repeats"], "repeated_tools": repeats["repeated_tools"],
            "used_fallback_tool": used_fallback,
            "builtin_tool_usage": bool(builtin), "builtin_tools": sorted(set(builtin))}


def retry_counts(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Retries: calls with the same tool and the same arguments as an earlier call whose error result had already
    come back when this call was issued. Calls in one parallel batch are issued before any of their results
    return, so a batch over several arguments is not a retry. same_args_repeats counts any repeat of an
    earlier (tool, arguments) pair, error or not, issued after it or alongside it."""
    retries, repeats = 0, 0
    retried: set[str] = set()
    repeated: set[str] = set()
    for index, call in enumerate(calls):
        earlier = [prior for prior in calls[:index] if prior["tool"] == call["tool"] and prior.get("args") == call.get("args")]
        if earlier:
            repeats += 1
            repeated.add(call["tool"])
        issued = call.get("issued_at")
        if any(prior["is_error"] and prior.get("result_at") is not None and issued is not None
               and prior["result_at"] < issued for prior in earlier):
            retries += 1
            retried.add(call["tool"])
    return {"retries": retries, "retried_tools": sorted(retried), "same_args_repeats": repeats,
            "repeated_tools": sorted(repeated)}


def proxy_draws(proxy_logs: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Drawn profile entries ("OP4/permanent") in draw order, merged across proxies by first use."""
    draws: list[tuple[float, str]] = []
    for events in proxy_logs.values():
        seen: set[int] = set()
        for event in events:
            index, entry = event.get("draw_index"), event.get("entry")
            if index is None or not isinstance(entry, dict) or index in seen:
                continue
            seen.add(index)
            draws.append((float(event.get("ts", 0)), entry.get("label", "")))
    return [label for _, label in sorted(draws, key=lambda item: item[0])]


def final_answer(text: str) -> str:
    lines = re.findall(r"(?m)^\W*FINAL:\s*(.*)$", text or "")
    return lines[-1].strip().strip("`*").strip() if lines else ""


def build_mcp_config(task: dict[str, Any], schedule: Path, seed: str, target: str | None,
                     artifact_dir: Path, states: dict[str, str], shim: Path | None = None) -> dict[str, Any]:
    servers = {}
    for name in task["servers"]:
        args = ["-m", "mcp_fault_bench", "proxy", "--schedule", str(schedule), "--seed", seed]
        if target:
            args += ["--target", target]
        if shim:
            args += ["--shim", str(shim)]
        args += ["--log", str(artifact_dir / f"{name}-proxy.jsonl"), "--", sys.executable, "-m", f"servers.{name}"]
        servers[name] = {"type": "stdio", "command": sys.executable, "args": args,
                         "env": {"CHAOS_STATE_FILE": states[name], "PYTHONPATH": str(ROOT)}}
    return {"mcpServers": servers}


PROMPT_SUFFIX = (" Use only the provided MCP tools. Your reply must end with a line that starts with `FINAL:`"
                 " followed by the answer.")


def run_one(task: dict[str, Any], model: str, condition: str, rep: int, base_seed: Any, effort: str,
            run_cap: float = WALL_CLOCK_SECONDS, adapter: AgentAdapter | None = None,
            runs_dir: Path | None = None) -> dict[str, Any]:
    """Run a single task/model/condition cell and persist its artifacts under runs_dir (default results/runs)."""
    adapter = adapter or get_adapter(LEGACY_ADAPTER)
    run_id = f"{task['id']}-{model}-{condition}-r{rep}-{uuid.uuid4().hex[:8]}"
    artifact_dir = (runs_dir or RUNS) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    states = {name: str(artifact_dir / f"{name}.json") for name in task["servers"]}
    for name, values in task.get("setup", {}).items():
        Path(states[name]).write_text(json.dumps(values), encoding="utf-8")
    seed = run_seed(base_seed, task["id"], rep)
    target = run_target(condition, base_seed, task, rep)
    shim = run_shim(condition)
    mcp_config = json.dumps(build_mcp_config(task, ROOT / SCHEDULES[condition], seed, target, artifact_dir, states,
                                             shim), indent=2)
    prompt = task["prompt"].strip() + PROMPT_SUFFIX
    (artifact_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    started = time.monotonic()
    timed_out = False
    environment = {**os.environ, **adapter.env, "PYTHONPATH": str(ROOT)}
    with tempfile.TemporaryDirectory(prefix="chaos-agent-") as workdir, \
            tempfile.TemporaryDirectory(prefix="chaos-config-") as config_dir, \
            (artifact_dir / adapter.artifact_name).open("w", encoding="utf-8") as stdout, \
            (artifact_dir / "stderr.log").open("w", encoding="utf-8") as stderr:
        # The live config needs absolute paths; the stored copy is scrubbed (see bench/scrub.py).
        mcp_path = Path(config_dir) / "mcp.json"
        mcp_path.write_text(mcp_config, encoding="utf-8")
        (artifact_dir / "mcp.json").write_text(mcp_config, encoding="utf-8")
        command = adapter.command(prompt, model, effort, mcp_path, task["servers"])
        process = subprocess.Popen(command, cwd=workdir, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, text=True, start_new_session=True)
        try:
            process.wait(timeout=run_cap)
        except subprocess.TimeoutExpired:
            timed_out = True
        try:  # always reap the whole group (proxies, servers, pending delay timers)
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    wall_time = time.monotonic() - started
    adapter.finalize(artifact_dir)
    _trim(artifact_dir / "stderr.log")
    for name in (adapter.artifact_name, "mcp.json", "stderr.log"):
        scrub_file(artifact_dir / name, ROOT)
    row = score_run(task, model, condition, rep, seed, target, effort, artifact_dir, states, wall_time, timed_out,
                    run_cap, adapter)
    row["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return row


def _keep_stream_events(path: Path) -> None:
    """Store only the stream events the scorer uses (Claude Code stream-json; see bench/adapters/claude_code.py)."""
    keep_stream_events(path)


def _trim(path: Path, limit: int = 20_000) -> None:
    """Keep stderr logs small: first and last part only."""
    if path.exists() and path.stat().st_size > limit:
        text = path.read_text(encoding="utf-8", errors="replace")
        path.write_text(text[: limit // 2] + "\n[... trimmed ...]\n" + text[-limit // 2:], encoding="utf-8")


def score_run(task: dict[str, Any], model: str, condition: str, rep: int, seed: str, target: str | None,
              effort: str, artifact_dir: Path, states: dict[str, str], wall_time: float,
              timed_out: bool, run_cap: float = WALL_CLOCK_SECONDS,
              adapter: AgentAdapter | None = None) -> dict[str, Any]:
    """Build the run row from stored artifacts (parsed by the adapter that produced them)."""
    adapter = adapter or get_adapter(LEGACY_ADAPTER)
    parsed = adapter.parse(artifact_dir)
    init, result = parsed["init"], parsed["result"] or {}
    proxy_logs = {path.name.removesuffix("-proxy.jsonl"): _read_jsonl(path)
                  for path in sorted(artifact_dir.glob("*-proxy.jsonl"))}
    all_events = [event for events in proxy_logs.values() for event in events]
    # Fault-layer events (one per downstream attempt) carry the injected faults; shim events (one per agent
    # call) are what the agent saw, so retries and fallbacks are counted from them when the shim is on.
    proxy_events = [event for event in all_events if event.get("layer") != "shim"]
    shim_events = [event for event in all_events if event.get("layer") == "shim"]
    stats = call_stats(parsed["calls"], agent_events(shim_events) if shim_events else proxy_events)
    shim = shim_stats(shim_events)
    behaviour = target_behaviour(parsed["calls"], target)
    fault_counts: dict[str, int] = {}
    for event in proxy_events:
        if event.get("fault"):
            fault_counts[event["fault"]] = fault_counts.get(event["fault"], 0) + 1
    drawn = proxy_draws(proxy_logs)
    answer = final_answer(result.get("result", ""))
    success = (not timed_out) and grade(task, answer, states)
    servers = init.get("mcp_servers") or []
    if timed_out:
        outcome = "timeout"
    elif (not parsed["result"] or (result.get("is_error") and stats["tool_calls"] == 0)
          or not init or any(server.get("status") != "connected" for server in servers)):
        outcome = "harness_error"  # the agent CLI exited before producing a result
    else:
        outcome = "ok" if success else "fail"
    model_usage = result.get("modelUsage") or {}
    return {"id": artifact_dir.name, "task": task["id"], "model": model, "adapter": adapter.name, "effort": effort,
            "condition": condition, "rep": rep, "seed": seed, "target_tool": target,
            "success": success, "outcome": outcome, "wall_time": round(wall_time, 2),
            "tool_calls": stats["tool_calls"], "faults": sum(fault_counts.values()), "faults_by_op": fault_counts,
            "drawn_entries": drawn, "first_entry": drawn[0] if drawn else None,
            "errored_tool_calls": stats["errored_tool_calls"], "retries": stats["retries"],
            "retried_tools": stats["retried_tools"], "same_args_repeats": stats["same_args_repeats"],
            "repeated_tools": stats["repeated_tools"], **behaviour,
            "recovered": bool(fault_counts) and success, "used_fallback_tool": stats["used_fallback_tool"],
            "builtin_tool_usage": stats["builtin_tool_usage"], "builtin_tools": stats["builtin_tools"],
            "final_answer": answer, "num_turns": result.get("num_turns"), "duration_ms": result.get("duration_ms"),
            "total_cost_usd": result.get("total_cost_usd"), "usage": result.get("usage"),
            "model_usage": model_usage, "models_seen": sorted(model_usage),
            "init_model": init.get("model"), "init_tools": init.get("tools"), "init_mcp_servers": servers,
            "run_cap": run_cap, "capped": outcome == "timeout", "shim": condition in SHIM_CONDITIONS,
            "shim_mode": shim_mode(condition), **shim,
            "artifact_dir": str(artifact_dir.relative_to(ROOT) if artifact_dir.is_relative_to(ROOT) else artifact_dir)}


def agent_events(shim_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One event per agent tools/call from shim logs, in call start order, flagged when the agent got a fault."""
    ordered = sorted(shim_events, key=lambda event: float(event.get("ts", 0)) - float(event.get("latency") or 0))
    events = []
    for event in ordered:
        shim = event.get("shim") or {}
        returned = (shim.get("attempt_faults") or [None])[-1] if shim.get("final") == "ok" else "shim_error"
        events.append({"method": "tools/call", "tool": event.get("tool", ""), "fault": returned})
    return events


def shim_stats(shim_events: list[dict[str, Any]]) -> dict[str, int]:
    """Per-run shim counters from the proxy logs."""
    blocks = [event.get("shim") or {} for event in shim_events]
    return {"shim_calls": len(blocks), "shim_retries": sum(int(block.get("retried", 0)) for block in blocks),
            "shim_validation_failures": sum(int(block.get("validation_failures", 0)) for block in blocks),
            "shim_timeouts": sum(bool(block.get("timed_out")) for block in blocks),
            "shim_errors": sum(block.get("final") == "error" for block in blocks)}


# ---------------------------------------------------------------------------------------------- summary

def wilson(successes: int, n: int, z: float = 1.96) -> list[float] | None:
    """Wilson score 95% interval for a binomial proportion."""
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _mean(rows: list[dict[str, Any]], key: str) -> float:
    return sum(float(row.get(key) or 0) for row in rows) / len(rows) if rows else 0.0


def _cell(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    successes = sum(bool(row.get("success")) for row in rows)
    return {"n": n, "successes": successes, "success_rate": successes / n if n else None,
            "ci95": wilson(successes, n), "mean_tool_calls": _mean(rows, "tool_calls"),
            "mean_retries": _mean(rows, "retries"), "mean_faults_fired": _mean(rows, "faults"),
            "mean_wall_time": _mean(rows, "wall_time"),
            "timeouts": sum(row.get("outcome") == "timeout" for row in rows),
            "builtin_tool_runs": sum(bool(row.get("builtin_tool_usage")) for row in rows)}


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    return numerator / denominator if numerator is not None and denominator else None


def _rep(row: dict[str, Any]) -> int:
    return int(row.get("rep") or 0)


def is_headline(row: dict[str, Any]) -> bool:
    """Reps 1..HEADLINE_REPS are the paper-weighted sample; rep-file extension reps are not."""
    return 1 <= _rep(row) <= HEADLINE_REPS


def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar p: binomial(b + c, 1/2) on the discordant pairs, unrounded."""
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def sign_test(improved: int, worsened: int) -> float:
    """Exact two-sided sign test on discordant pairs (McNemar exact)."""
    return round(mcnemar_exact(improved, worsened), 6)


def _bonferroni(p: float, family: int) -> float:
    return round(min(1.0, p * family), 6)


def _model_order(models: list[str]) -> list[str]:
    """Default models in their configured order (opus, sonnet, haiku), then any others sorted."""
    return [model for model in DEFAULT_MODELS if model in models] + sorted(set(models) - set(DEFAULT_MODELS))


def _faulted(row: dict[str, Any] | None) -> bool:
    return bool(row and row.get("faults"))


def faulted_only(rows: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    """Per condition and model: success among runs with faults > 0, plus the runs where no fault fired."""
    table: dict[str, dict[str, Any]] = {}
    for condition in FAULTED_CONDITIONS:
        group = [row for row in rows if row["condition"] == condition]
        if not group:
            continue
        for model in models:
            runs = [row for row in group if row["model"] == model]
            if not runs:
                continue
            unfaulted = [row for row in runs if not _faulted(row)]
            table.setdefault(condition, {})[model] = {
                **_small_cell([row for row in runs if _faulted(row)]), "runs": len(runs),
                "no_fault_fired": len(unfaulted), "no_fault_no_draw": sum(not row.get("first_entry") for row in unfaulted)}
    return table


def _paired_by_key(rows: list[dict[str, Any]], model: str, condition: str) -> dict[tuple[str, int], dict[str, Any]]:
    return {(row["task"], _rep(row)): row for row in rows if row["model"] == model and row["condition"] == condition}


def between_model_mcnemar(rows: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    """Exact McNemar for every model pair within clean, chaos and chaos_scoped, paired on (task, rep).

    b = first model succeeded and second failed, c = the reverse. Bonferroni ×3 = the 3 model pairs within one
    condition; ×9 = 3 pairs × 3 conditions, within one scope (all pairs, or faulted-only).
    """
    ordered = _model_order(models)
    pairs = [(a, b) for index, a in enumerate(ordered) for b in ordered[index + 1:]]
    result: dict[str, list[dict[str, Any]]] = {}
    for condition in CONDITIONS:
        for first, second in pairs:
            left, right = _paired_by_key(rows, first, condition), _paired_by_key(rows, second, condition)
            keys = sorted(set(left) & set(right))
            if not keys:
                continue
            for scope, chosen in (("all", keys), ("faulted_only", [key for key in keys
                                                                   if _faulted(left[key]) and _faulted(right[key])])):
                b = sum(bool(left[key].get("success")) and not right[key].get("success") for key in chosen)
                c = sum(not left[key].get("success") and bool(right[key].get("success")) for key in chosen)
                p = mcnemar_exact(b, c)
                result.setdefault(condition, []).append({
                    "model_a": first, "model_b": second, "scope": scope, "n_pairs": len(chosen),
                    "a_successes": sum(bool(left[key].get("success")) for key in chosen),
                    "b_successes": sum(bool(right[key].get("success")) for key in chosen),
                    "b": b, "c": c, "p": round(p, 6), "p_bonferroni_3": _bonferroni(p, 3),
                    "p_bonferroni_9": _bonferroni(p, 9)})
    return {"conditions": result, "b": "model_a succeeded, model_b failed", "c": "model_a failed, model_b succeeded",
            "test": "exact two-sided McNemar (binomial on discordant pairs)",
            "bonferroni_families": {"3": "the 3 model pairs within one condition and scope",
                                    "9": "3 model pairs × 3 conditions (clean, chaos, chaos_scoped) within one scope"}}


def headline_mcnemar(summary: dict[str, Any], condition: str = "chaos_scoped", scope: str = "all") -> dict[str, Any] | None:
    """The HEADLINE_PAIR test from summary["between_model_mcnemar"], or None if it is missing."""
    for item in ((summary.get("between_model_mcnemar") or {}).get("conditions") or {}).get(condition, []):
        if item["scope"] == scope and {item["model_a"], item["model_b"]} == set(HEADLINE_PAIR):
            return item
    return None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def _shim_cell(population: list[tuple[dict[str, Any], dict[str, Any] | None]], bonferroni: bool = False) -> dict[str, Any]:
    """Shim vs no-shim on (no-shim row, shim row or None) pairs; shim fields are None while the arm is pending."""
    matched = [(base, shim) for base, shim in population if shim is not None]
    cell: dict[str, Any] = {"baseline_n": len(population),
                            "baseline_successes": sum(bool(base.get("success")) for base, _ in population),
                            "status": "ok" if matched else "pending", "n_pairs": len(matched),
                            "base_successes": None, "shim_successes": None, "b": None, "c": None, "p": None,
                            "median_wall_base": None, "median_wall_shim": None}
    if bonferroni:
        cell["p_bonferroni_3"] = None
    if not matched:
        return cell
    b = sum(bool(shim.get("success")) and not base.get("success") for base, shim in matched)
    c = sum(bool(base.get("success")) and not shim.get("success") for base, shim in matched)
    p = mcnemar_exact(b, c)
    cell.update(base_successes=sum(bool(base.get("success")) for base, _ in matched),
                shim_successes=sum(bool(shim.get("success")) for _, shim in matched), b=b, c=c, p=round(p, 6),
                median_wall_base=_median([float(base.get("wall_time") or 0) for base, _ in matched]),
                median_wall_shim=_median([float(shim.get("wall_time") or 0) for _, shim in matched]))
    if bonferroni:
        cell["p_bonferroni_3"] = _bonferroni(p, 3)
    return cell


def shim_analysis(rows: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    """Pre-registered shim vs no-shim analysis (docs/preregistration-shim.md), per model, on (task, rep).

    Primary: chaos_scoped_shim vs chaos_scoped, pairs whose no-shim run had faults > 0 (faulted status is defined
    on the baseline). b = shim-only successes, c = no-shim-only successes; exact McNemar, Bonferroni ×3 across
    models. The same structure is reported for chaos_shim vs chaos; clean_shim vs clean uses all pairs.
    """
    comparisons = []
    for shim, base, faulted in (("chaos_scoped_shim", "chaos_scoped", True), ("chaos_shim", "chaos", True),
                                ("clean_shim", "clean", False)):
        per_model: dict[str, Any] = {}
        for model in _model_order(models):
            baseline, shimmed = _paired_by_key(rows, model, base), _paired_by_key(rows, model, shim)
            if not baseline:
                continue
            everything = [(baseline[key], shimmed.get(key)) for key in sorted(baseline)]
            primary = [pair for pair in everything if _faulted(pair[0])] if faulted else everything
            slices: dict[str, Any] = {}
            if faulted:
                families: dict[str, list[tuple[dict[str, Any], dict[str, Any] | None]]] = {}
                for pair in primary:
                    families.setdefault(pair[0].get("first_entry") or "no draw", []).append(pair)
                slices["by_first_entry"] = {family: _shim_cell(group) for family, group in sorted(families.items())}
                if base == "chaos_scoped":
                    slices["fallback_eligible_target"] = {
                        label: _shim_cell([pair for pair in primary
                                           if (pair[0].get("target_tool") in FALLBACK_ELIGIBLE) == eligible])
                        for label, eligible in (("eligible", True), ("not eligible", False))}
                    # The pre-registration's main prediction rows: OP4/permanent first draw crossed with the target.
                    slices["op4_permanent_by_target"] = {
                        label: _shim_cell([pair for pair in primary if pair[0].get("first_entry") == UNWINNABLE
                                           and (pair[0].get("target_tool") in FALLBACK_ELIGIBLE) == eligible])
                        for label, eligible in ((OP4_ELIGIBLE, True), (OP4_NO_FALLBACK, False))}
                # A pair joins once its shim run exists and is faulted; while pending it counts toward baseline_n.
                slices["both_faulted"] = _shim_cell([pair for pair in primary if pair[1] is None or _faulted(pair[1])])
                slices["all_pairs"] = _shim_cell(everything)
            per_model[model] = {"primary": _shim_cell(primary, bonferroni=True), "slices": slices}
        if per_model:
            comparisons.append({"shim": shim, "base": base, "confirmatory": base == "chaos_scoped",
                                "population": "no-shim run had faults > 0" if faulted else "all pairs",
                                "models": per_model})
    return {"reps": [1, HEADLINE_REPS], "comparisons": comparisons,
            "b": "shim succeeded, no-shim failed", "c": "no-shim succeeded, shim failed",
            "test": "exact two-sided McNemar (binomial on discordant pairs); Bonferroni ×3 across models",
            "fallback_eligible_targets": list(FALLBACK_ELIGIBLE),
            "note": "Primary analysis: chaos_scoped_shim vs chaos_scoped. Slices and the chaos/clean comparisons are "
                    "secondary (not confirmatory). Shim fields are null while the shim arm is pending."}


AFTER_ERROR_KINDS = ("stopped", "fallback", "retried", "both")


def _behaviour_cell(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errored = [row for row in rows if row.get("target_errored")]
    kinds = {kind: {"n": sum(row.get("target_after_error") == kind for row in errored),
                    "successes": sum(row.get("target_after_error") == kind and bool(row.get("success"))
                                     for row in errored)} for kind in AFTER_ERROR_KINDS}
    return {"n": len(rows), "same_args_repeat_runs": sum(bool(row.get("target_repeated")) for row in rows),
            "retry_runs": sum(bool(row.get("target_retried")) for row in rows),
            "retry_calls": sum(row.get("retries") or 0 for row in rows),
            "target_errored_runs": len(errored), "after_error": kinds}


def after_error_analysis(rows: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    """Post-error behaviour on the faulted target, chaos_scoped vs chaos_scoped_shim, pairs whose no-shim run was
    faulted. Retries are same tool + same arguments issued after that call's error result came back."""
    per_model: dict[str, Any] = {}
    for model in _model_order(models):
        baseline = _paired_by_key(rows, model, "chaos_scoped")
        shimmed = _paired_by_key(rows, model, "chaos_scoped_shim")
        keys = [key for key in sorted(baseline) if _faulted(baseline[key])]
        if not keys:
            continue
        arms = {}
        for name, source in (("no_shim", baseline), ("shim", shimmed)):
            arm_rows = [source[key] for key in keys if key in source]
            op4 = [source[key] for key in keys if key in source and baseline[key].get("first_entry") == UNWINNABLE
                   and baseline[key].get("target_tool") in FALLBACK_ELIGIBLE]
            arms[name] = {"all": _behaviour_cell(arm_rows), "op4_permanent_eligible": _behaviour_cell(op4)}
        per_model[model] = arms
    return {"reps": [1, HEADLINE_REPS], "population": "chaos_scoped pairs whose no-shim run had faults > 0",
            "retry_rule": "same tool, same arguments, issued after an error result for that call came back",
            "kinds": {"stopped": "neither retried nor called a fallback after the target's first error",
                      "fallback": "called a fallback tool named in profiles/shim.yaml after the first error",
                      "retried": "repeated a failed (target, arguments) call after its error came back",
                      "both": "retried and called a fallback"},
            "models": per_model}


def after_error_markdown(summary: dict[str, Any]) -> str:
    analysis = summary.get("after_error") or {}
    lines = ["| Model | Arm | Faulted pairs | Runs repeating a target call (same args) | Runs retrying after an error | "
             "Retry calls (any tool) | Target errored | Stopped (succ.) | Fallback (succ.) | Retried (succ.) | Both (succ.) |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for model, arms in (analysis.get("models") or {}).items():
        for arm, label in (("no_shim", "no shim"), ("shim", "shim")):
            cell = arms[arm]["all"]
            kinds = cell["after_error"]
            lines.append(f"| {model} | {label} | {cell['n']} | {cell['same_args_repeat_runs']} | {cell['retry_runs']} | "
                         f"{cell['retry_calls']} | {cell['target_errored_runs']} | "
                         + " | ".join(f"{kinds[kind]['n']} ({kinds[kind]['successes']})" for kind in AFTER_ERROR_KINDS)
                         + " |")
    lines += ["", f"{OP4_ELIGIBLE} (the pre-registered slice; first entry and target taken from the no-shim run; "
              "targets " + ", ".join(FALLBACK_ELIGIBLE) + "):", "",
              "| Model | Arm | Runs | Target errored | Stopped (succ.) | Fallback (succ.) | Retried (succ.) | Both (succ.) |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    for model, arms in (analysis.get("models") or {}).items():
        for arm, label in (("no_shim", "no shim"), ("shim", "shim")):
            cell = arms[arm]["op4_permanent_eligible"]
            kinds = cell["after_error"]
            lines.append(f"| {model} | {label} | {cell['n']} | {cell['target_errored_runs']} | "
                         + " | ".join(f"{kinds[kind]['n']} ({kinds[kind]['successes']})" for kind in AFTER_ERROR_KINDS)
                         + " |")
    return "\n".join(lines) + "\n"


def _small_cell(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    successes = sum(bool(row.get("success")) for row in rows)
    return {"n": n, "successes": successes, "success_rate": successes / n if n else None, "ci95": wilson(successes, n)}


def _pairs(rows: list[dict[str, Any]], model: str, shim: str, base: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(base row, shim row) for every (task, rep) the model has in both conditions."""
    keyed: dict[str, dict[tuple[str, int], dict[str, Any]]] = {shim: {}, base: {}}
    for row in rows:
        if row["model"] == model and row["condition"] in keyed:
            keyed[row["condition"]][(row["task"], _rep(row))] = row
    return [(keyed[base][key], keyed[shim][key]) for key in sorted(set(keyed[base]) & set(keyed[shim]))]


def _lift(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    n = len(pairs)
    base_successes = sum(bool(base.get("success")) for base, _ in pairs)
    shim_successes = sum(bool(shim.get("success")) for _, shim in pairs)
    improved = sum(not base.get("success") and bool(shim.get("success")) for base, shim in pairs)
    worsened = sum(bool(base.get("success")) and not shim.get("success") for base, shim in pairs)
    return {"n_pairs": n, "base_successes": base_successes, "shim_successes": shim_successes,
            "base_rate": base_successes / n if n else None, "shim_rate": shim_successes / n if n else None,
            "lift": (shim_successes - base_successes) / n if n else None,
            "improved": improved, "worsened": worsened, "sign_test_p": sign_test(improved, worsened)}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate runs.jsonl rows into the summary.json structure.

    The headline tables (models[].conditions, coverage, fault_families, paired) use reps 1..HEADLINE_REPS of
    clean/chaos/chaos_scoped only, so rep-file extension reps never enter the paper-weighted rates.
    """
    headline_rows = [row for row in rows if is_headline(row)]
    extension_rows = [row for row in rows if not is_headline(row)]
    models = sorted({row["model"] for row in rows})
    conditions = [condition for condition in CONDITIONS if any(row["condition"] == condition for row in headline_rows)]
    shim_conditions = [condition for condition in SHIM_CONDITIONS if any(row["condition"] == condition for row in rows)]
    tasks = sorted({row["task"] for row in rows})
    reps = max((_rep(row) for row in headline_rows), default=0)

    def select(source: list[dict[str, Any]] | None = None, **filters: Any) -> list[dict[str, Any]]:
        return [row for row in (headline_rows if source is None else source)
                if all(row.get(key) == value for key, value in filters.items())]

    per_model = []
    for model in models:
        cells = {condition: _cell(select(model=model, condition=condition)) for condition in conditions}
        clean_rate = cells.get("clean", {}).get("success_rate")
        per_model.append({
            "model": model, "effort": sorted({str(row.get("effort")) for row in select(rows, model=model)}),
            "conditions": cells,
            "shim_conditions": {condition: _cell(select(model=model, condition=condition))
                                for condition in shim_conditions if select(model=model, condition=condition)},
            "resilience_ratio": _ratio(cells.get("chaos", {}).get("success_rate"), clean_rate),
            "scoped_resilience_ratio": _ratio(cells.get("chaos_scoped", {}).get("success_rate"), clean_rate),
            "models_seen": sorted({name for row in select(rows, model=model) for name in row.get("models_seen") or []}),
        })

    coverage = []
    for model in models:
        for task in tasks:
            for condition in conditions:
                group = select(model=model, task=task, condition=condition)
                coverage.append({"model": model, "task": task, "condition": condition, "n": len(group),
                                 "successes": sum(bool(row.get("success")) for row in group),
                                 "incomplete": len(group) < reps})

    families: dict[str, dict[str, dict[str, Any]]] = {}
    for condition in ("chaos", "chaos_scoped"):
        groups: dict[str, dict[str, Any]] = {}
        for row in select(condition=condition):
            for family in [row.get("first_entry") or "no draw (target not called)"] + (["zero_dose"] if not row.get("faults") else []):
                cell = groups.setdefault(family, {}).setdefault(row["model"], {"n": 0, "successes": 0})
                cell["n"] += 1
                cell["successes"] += bool(row.get("success"))
        if groups:
            families[condition] = dict(sorted(groups.items()))

    paired: dict[str, dict[str, dict[str, Any]]] = {}
    for row in sorted(headline_rows, key=lambda item: (item["task"], _rep(item))):
        if row["condition"] not in CONDITIONS:
            continue
        key = f"{row['task']}#{row.get('rep')}"
        paired.setdefault(key, {}).setdefault(row["model"], {})[row["condition"]] = {
            "success": bool(row.get("success")), "outcome": row.get("outcome"),
            "first_entry": row.get("first_entry"), "target_tool": row.get("target_tool")}

    models_used: dict[str, dict[str, float]] = {}
    for row in rows:
        for name, usage in (row.get("model_usage") or {}).items():
            total = models_used.setdefault(name, {"runs": 0})
            total["runs"] += 1
            for field in USAGE_FIELDS:
                value = (usage or {}).get(field)
                if isinstance(value, (int, float)):
                    total[field] = total.get(field, 0) + value

    # Winnable subset: first drawn entry is not OP4/permanent (null = nothing drawn, zero dose, kept in).
    winnable: dict[str, Any] = {"rule": f"first_entry != {UNWINNABLE} (null first_entry counts as zero dose and is kept)",
                                "conditions": {}}
    for condition in WINNABLE_CONDITIONS:
        subset = [row for row in rows if row["condition"] == condition and row.get("first_entry") != UNWINNABLE]
        if not any(row["condition"] == condition for row in rows):
            continue
        winnable["conditions"][condition] = {
            model: {"headline": _small_cell([row for row in subset if row["model"] == model and is_headline(row)]),
                    "all": _small_cell([row for row in subset if row["model"] == model])} for model in models}

    shim_lift: dict[str, dict[str, Any]] = {}
    shim_lift_by_family: dict[str, dict[str, dict[str, Any]]] = {}
    for shim, base in SHIM_PAIRS:
        name = f"{shim} - {base}"
        for model in models:
            pairs = _pairs(rows, model, shim, base)
            if not pairs:
                continue
            shim_lift.setdefault(name, {})[model] = {
                "all": _lift(pairs), "headline": _lift([pair for pair in pairs if is_headline(pair[0])])}
            by_family: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
            for pair in pairs:
                family = pair[0].get("first_entry") or pair[1].get("first_entry") or "no draw"
                by_family.setdefault(family, []).append(pair)
            for family, group in sorted(by_family.items()):
                shim_lift_by_family.setdefault(name, {}).setdefault(family, {})[model] = _lift(group)

    cap_stats = []
    for model in models:
        for condition in ALL_CONDITIONS:
            group = select(rows, model=model, condition=condition)
            if group:
                cap_stats.append({"model": model, "condition": condition, "n": len(group),
                                  "capped": sum(row.get("outcome") == "timeout" for row in group),
                                  "run_cap": sorted({float(row.get("run_cap") or WALL_CLOCK_SECONDS) for row in group})})

    cap_rows = []
    chaos_by_key = {(row["task"], row["model"], _rep(row)): row for row in rows if row["condition"] == "chaos"}
    for row in sorted(select(rows, condition="chaos_cap3000"), key=lambda item: (item["model"], item["task"], _rep(item))):
        base = chaos_by_key.get((row["task"], row["model"], _rep(row)))
        if base:
            cap_rows.append({"task": row["task"], "model": row["model"], "rep": _rep(row),
                             "chaos_outcome": base.get("outcome"), "chaos_wall_time": base.get("wall_time"),
                             "cap_outcome": row.get("outcome"), "cap_wall_time": row.get("wall_time"),
                             "cap_run_cap": row.get("run_cap")})
    cap_by_model: dict[str, dict[str, Any]] = {}
    for item in cap_rows:
        cell = cap_by_model.setdefault(item["model"], {"n": 0, "chaos_successes": 0, "cap_successes": 0,
                                                       "chaos_capped": 0, "cap_capped": 0, "flipped_to_success": 0,
                                                       "flipped_to_failure": 0, "chaos_wall": 0.0, "cap_wall": 0.0})
        chaos_ok, cap_ok = item["chaos_outcome"] == "ok", item["cap_outcome"] == "ok"
        cell["n"] += 1
        cell["chaos_successes"] += chaos_ok
        cell["cap_successes"] += cap_ok
        cell["chaos_capped"] += item["chaos_outcome"] == "timeout"
        cell["cap_capped"] += item["cap_outcome"] == "timeout"
        cell["flipped_to_success"] += cap_ok and not chaos_ok
        cell["flipped_to_failure"] += chaos_ok and not cap_ok
        cell["chaos_wall"] += float(item["chaos_wall_time"] or 0)
        cell["cap_wall"] += float(item["cap_wall_time"] or 0)
    for cell in cap_by_model.values():
        cell["chaos_mean_wall_time"] = cell.pop("chaos_wall") / cell["n"]
        cell["cap_mean_wall_time"] = cell.pop("cap_wall") / cell["n"]

    extension_winnable: dict[str, Any] = {"label": SEED_SELECTED, "rule": winnable["rule"], "conditions": {}}
    for condition in WINNABLE_CONDITIONS:
        subset = [row for row in extension_rows if row["condition"] == condition and row.get("first_entry") != UNWINNABLE]
        if any(row["condition"] == condition for row in extension_rows):
            extension_winnable["conditions"][condition] = {
                model: _small_cell([row for row in subset if row["model"] == model]) for model in models}

    extension_reps: dict[str, list[int]] = {}
    for row in extension_rows:
        extension_reps.setdefault(row["task"], [])
        if _rep(row) not in extension_reps[row["task"]]:
            extension_reps[row["task"]].append(_rep(row))
    return {"n_runs": len(rows), "reps": reps, "conditions": conditions, "shim_conditions": shim_conditions,
            "tasks": tasks, "models": per_model, "coverage": coverage, "fault_families": families, "paired": paired,
            "models_used": models_used,
            "headline": {"reps": [1, HEADLINE_REPS], "conditions": conditions,
                         "n_runs": sum(row["condition"] in CONDITIONS for row in headline_rows),
                         "note": f"reps 1..{HEADLINE_REPS} (paper-weighted sample); models[].conditions, coverage, "
                                 "fault_families and paired use only these rows"},
            "extension": {"n_runs": len(extension_rows),
                          "conditions": sorted({row["condition"] for row in extension_rows}),
                          "reps": {task: sorted(values) for task, values in sorted(extension_reps.items())},
                          "note": "rep-file reps (bench/winnable_reps.json); excluded from the headline rates, "
                                  "included in winnable (all) and shim lift (all)"},
            "winnable": winnable, "shim_lift": shim_lift, "shim_lift_by_family": shim_lift_by_family,
            "cap_stats": cap_stats, "cap_sensitivity": {"rows": cap_rows, "by_model": cap_by_model},
            "faulted_only": {"reps": [1, HEADLINE_REPS], "rule": "faults > 0 (at least one fault fired)",
                             "conditions": faulted_only(headline_rows, models)},
            "between_model_mcnemar": {"reps": [1, HEADLINE_REPS], **between_model_mcnemar(headline_rows, models)},
            "shim_analysis": shim_analysis(headline_rows, models),
            "after_error": after_error_analysis(headline_rows, models),
            "extension_winnable": extension_winnable}


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _ci(cell: dict[str, Any]) -> str:
    return "n/a" if not cell.get("ci95") else f"{cell['ci95'][0]:.0%}–{cell['ci95'][1]:.0%}"


def _fmt_ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def summary_markdown(summary: dict[str, Any]) -> str:
    """Markdown tables for summary.md and the README results block."""
    lines = ["| Model | Condition | n | Success | 95% CI | Tool calls | Retries | Faults fired | Wall time | Timeouts | Built-in tool runs |",
             "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|"]
    for model in summary["models"]:
        for condition, cell in model["conditions"].items():
            lines.append(f"| {model['model']} | {condition} | {cell['n']} | {cell['successes']} ({_pct(cell['success_rate'])}) | "
                         f"{_ci(cell)} | {cell['mean_tool_calls']:.1f} | {cell['mean_retries']:.2f} | "
                         f"{cell['mean_faults_fired']:.2f} | {cell['mean_wall_time']:.0f}s | {cell['timeouts']} | "
                         f"{cell['builtin_tool_runs']} |")
    lines += ["", "| Model | Effort | Resilience (chaos ÷ clean) | Scoped resilience (chaos_scoped ÷ clean) | Models seen |",
              "|---|---|---:|---:|---|"]
    for model in summary["models"]:
        lines.append(f"| {model['model']} | {', '.join(model['effort'])} | {_fmt_ratio(model['resilience_ratio'])} | "
                     f"{_fmt_ratio(model['scoped_resilience_ratio'])} | {', '.join(model['models_seen']) or 'n/a'} |")
    conditions = summary["conditions"]
    lines += ["", "### Coverage (successes / runs per task)", "",
              "| Model | Task | " + " | ".join(conditions) + " |", "|---|---|" + "---:|" * len(conditions)]
    cells = {(item["model"], item["task"], item["condition"]): item for item in summary["coverage"]}
    for model in summary["models"]:
        for task in summary["tasks"]:
            values = []
            for condition in conditions:
                item = cells[(model["model"], task, condition)]
                values.append(f"{item['successes']}/{item['n']}" + (" ⚠" if item["incomplete"] else ""))
            lines.append(f"| {model['model']} | {task} | " + " | ".join(values) + " |")
    if any(item["incomplete"] for item in summary["coverage"]):
        lines += ["", f"⚠ = fewer than {summary['reps']} runs in this cell."]
    model_names = [model["model"] for model in summary["models"]]
    for condition, groups in summary["fault_families"].items():
        lines += ["", f"### {condition}: success by first drawn entry", "",
                  "| First entry | " + " | ".join(model_names) + " |", "|---|" + "---:|" * len(model_names)]
        for family, per_model in groups.items():
            values = [f"{per_model[name]['successes']}/{per_model[name]['n']}" if name in per_model else "-"
                      for name in model_names]
            label = "zero dose (no fault fired)" if family == "zero_dose" else family
            lines.append(f"| {label} | " + " | ".join(values) + " |")
    if summary["models_used"]:
        lines += ["", "### Models used (from Claude Code modelUsage)", "", "| Model id | Runs | Input tokens | Output tokens | Cache read | Cache write | Notional API cost (USD, not billed) |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for name, usage in sorted(summary["models_used"].items()):
            lines.append(f"| {name} | {usage.get('runs', 0)} | {usage.get('inputTokens', 0):,.0f} | "
                         f"{usage.get('outputTokens', 0):,.0f} | {usage.get('cacheReadInputTokens', 0):,.0f} | "
                         f"{usage.get('cacheCreationInputTokens', 0):,.0f} | {usage.get('costUSD', 0):.2f} |")
    return "\n".join(lines) + "\n"


def _ci_pair(cell: dict[str, Any]) -> str:
    return f"{cell['successes']}/{cell['n']} ({_pct(cell['success_rate'])}, {_ci(cell)})" if cell["n"] else "-"


def _p(value: float) -> str:
    return f"{value:.3f}" if value >= 0.001 else "<0.001"


def winnable_markdown(summary: dict[str, Any]) -> str:
    """Winnable subset: chaos / chaos_shim runs whose first drawn entry is not OP4/permanent."""
    winnable = summary.get("winnable") or {}
    if not winnable.get("conditions"):
        return ""
    lines = [f"Rule: {winnable['rule']}. Reps 1–{HEADLINE_REPS} only; extension reps are in their own table "
             f"({SEED_SELECTED}).", "", "| Model | Condition | Reps 1–10: success (95% CI) |", "|---|---|---|"]
    for model in summary["models"]:
        for condition, per_model in winnable["conditions"].items():
            cell = per_model.get(model["model"])
            if cell:
                lines.append(f"| {model['model']} | {condition} | {_ci_pair(cell['headline'])} |")
    return "\n".join(lines) + "\n"


def extension_markdown(summary: dict[str, Any]) -> str:
    """Winnable-rep extension and shim lift including extension reps; every label says seed-selected."""
    tag = f"({SEED_SELECTED})"
    lines = [f"Extension reps come from `bench/winnable_reps.json`: (task, rep) pairs chosen because their first draw is "
             f"not OP4/permanent. They are {SEED_SELECTED}, and never enter the reps 1–{HEADLINE_REPS} tables above.", ""]
    winnable = summary.get("winnable") or {}
    extension = (summary.get("extension_winnable") or {}).get("conditions") or {}
    if not extension:
        lines.append(f"No extension runs yet {tag}.")
    else:
        lines += [f"| Model | Condition | Extension reps only {tag}: success (95% CI) | "
                  f"All reps incl. extension {tag}: success (95% CI) |", "|---|---|---|---|"]
        for model in summary["models"]:
            for condition, per_model in extension.items():
                cell = per_model.get(model["model"])
                every = ((winnable.get("conditions") or {}).get(condition) or {}).get(model["model"])
                if cell:
                    lines.append(f"| {model['model']} | {condition} | {_ci_pair(cell)} | "
                                 f"{_ci_pair(every['all']) if every else '-'} |")
    lifts = {name: {model: scopes["all"] for model, scopes in per_model.items() if scopes["all"]["n_pairs"]}
             for name, per_model in (summary.get("shim_lift") or {}).items()}
    if extension and any(lifts.values()):
        lines += ["", f"Shim lift on all paired reps incl. extension {tag}; improved = base ✗ → shim ✓, worsened = "
                  "base ✓ → shim ✗; p = exact two-sided sign test.", "",
                  f"| Comparison | Model | Reps {tag} | Pairs | Base | Shim | Lift | Improved | Worsened | p |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for name, per_model in lifts.items():
            for model, lift in per_model.items():
                lines.append(f"| {name} | {model} | all incl. extension {tag} | {lift['n_pairs']} | "
                             f"{lift['base_successes']} | {lift['shim_successes']} | {lift['lift']:+.0%} | "
                             f"{lift['improved']} | {lift['worsened']} | {_p(lift['sign_test_p'])} |")
        for name, families in (summary.get("shim_lift_by_family") or {}).items():
            model_names = sorted({model for per_model in families.values() for model in per_model})
            lines += ["", f"#### {name}: lift by first drawn entry, all paired reps incl. extension {tag} "
                      "(base→shim successes / pairs)", "",
                      f"| First entry {tag} | " + " | ".join(model_names) + " |", "|---|" + "---:|" * len(model_names)]
            for family, per_model in families.items():
                values = [f"{per_model[m]['base_successes']}→{per_model[m]['shim_successes']}/{per_model[m]['n_pairs']}"
                          if m in per_model else "-" for m in model_names]
                lines.append(f"| {family} | " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def faulted_only_markdown(summary: dict[str, Any]) -> str:
    """Success among runs where at least one fault fired (reps 1–10), with Wilson CIs."""
    table = (summary.get("faulted_only") or {}).get("conditions") or {}
    if not table:
        return ""
    lines = [f"Reps 1–{HEADLINE_REPS}; runs with faults > 0. Wilson 95% CI.", "",
             "| Condition | Model | Faulted: success / n | 95% CI | No fault fired | of which no draw at all |",
             "|---|---|---:|---|---:|---:|"]
    for condition, per_model in table.items():
        for model in _model_order(list(per_model)):
            cell = per_model[model]
            lines.append(f"| {condition} | {model} | {cell['successes']}/{cell['n']} ({_pct(cell['success_rate'])}) | "
                         f"{_ci(cell)} | {cell['no_fault_fired']} | {cell['no_fault_no_draw']} |")
    return "\n".join(lines) + "\n"


def mcnemar_markdown(summary: dict[str, Any]) -> str:
    """Between-model exact McNemar per condition, all pairs and faulted-only."""
    block = summary.get("between_model_mcnemar") or {}
    if not block.get("conditions"):
        return ""
    lines = [f"Reps 1–{HEADLINE_REPS}, paired on (task, rep). b = A ✓ B ✗, c = A ✗ B ✓; p = exact two-sided McNemar. "
             "Bonferroni ×3: family = the 3 model pairs within one condition and scope. Bonferroni ×9: family = "
             "3 pairs × 3 conditions (clean, chaos, chaos_scoped) within one scope. Faulted-only: both runs had "
             "faults > 0.", "",
             "| Condition | Scope | A vs B | Pairs | A ✓ | B ✓ | b | c | p | Bonf ×3 | Bonf ×9 |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for condition, tests in block["conditions"].items():
        for scope in ("all", "faulted_only"):
            for item in tests:
                if item["scope"] != scope:
                    continue
                stats = ([_p(item["p"]), _p(item["p_bonferroni_3"]), _p(item["p_bonferroni_9"])] if item["n_pairs"]
                         else ["-"] * 3)
                lines.append(f"| {condition} | {scope.replace('_', '-')} | {item['model_a']} vs {item['model_b']} | "
                             f"{item['n_pairs']} | {item['a_successes']} | {item['b_successes']} | {item['b']} | "
                             f"{item['c']} | " + " | ".join(stats) + " |")
    return "\n".join(lines) + "\n"


def _shim_values(cell: dict[str, Any], bonferroni: bool) -> list[str]:
    """Pairs, no-shim ✓, shim ✓, b, c, p, [Bonf ×3,] median walls; "pending" while the shim arm is missing."""
    if cell["status"] == "pending":
        pending = ["pending"] * (6 if bonferroni else 5)
        return [f"pending (no-shim n = {cell['baseline_n']})", str(cell["baseline_successes"]), *pending]
    pairs = str(cell["n_pairs"]) + (f" of {cell['baseline_n']}" if cell["n_pairs"] < cell["baseline_n"] else "")
    values = [pairs, str(cell["base_successes"]), str(cell["shim_successes"]), str(cell["b"]), str(cell["c"]),
              _p(cell["p"])]
    if bonferroni:
        values.append(_p(cell["p_bonferroni_3"]))
    return values + [f"{cell['median_wall_base']:.0f}s", f"{cell['median_wall_shim']:.0f}s"]


def shim_analysis_markdown(summary: dict[str, Any]) -> str:
    """Pre-registered shim vs no-shim analysis: primary per comparison, then secondary slices."""
    primary, secondary = shim_primary_markdown(summary), shim_secondary_markdown(summary)
    return primary + ("\n" + secondary if secondary else "")


def shim_primary_markdown(summary: dict[str, Any]) -> str:
    """Shim vs no-shim per comparison and model on the pre-registered population."""
    analysis = summary.get("shim_analysis") or {}
    if not analysis.get("comparisons"):
        return ""
    lines = [f"Reps 1–{HEADLINE_REPS}, paired on (task, rep). b = shim ✓ no-shim ✗, c = shim ✗ no-shim ✓; p = exact "
             "two-sided McNemar; Bonferroni ×3 across models. **Primary (confirmatory): chaos_scoped_shim vs "
             "chaos_scoped, pairs whose no-shim run had faults > 0.** The other rows are secondary.", "",
             "| Comparison | Model | Population | Pairs | No-shim ✓ | Shim ✓ | b | c | p | Bonf ×3 | "
             "Median wall no-shim | Median wall shim |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for comparison in analysis["comparisons"]:
        name = f"{comparison['shim']} vs {comparison['base']}" + (" (primary)" if comparison["confirmatory"] else "")
        population = "faulted-only (no-shim)" if comparison["population"] != "all pairs" else "all pairs"
        for model, block in comparison["models"].items():
            lines.append(f"| {name} | {model} | {population} | " + " | ".join(_shim_values(block["primary"], True)) + " |")
    return "\n".join(lines) + "\n"


def shim_secondary_markdown(summary: dict[str, Any]) -> str:
    """Secondary (not confirmatory) shim slices: first entry, fallback-eligible target, OP4/permanent × target."""
    analysis = summary.get("shim_analysis") or {}
    secondary = [(comparison, model, block) for comparison in analysis.get("comparisons") or []
                 for model, block in comparison["models"].items() if block["slices"]]
    if not secondary:
        return ""
    lines = ["Secondary slices (not confirmatory). First entry and fallback-eligible target "
             f"({', '.join(analysis['fallback_eligible_targets'])}) are taken from the no-shim run, within the "
             "faulted-only population.", "",
             "| Comparison | Model | Slice | Pairs | No-shim ✓ | Shim ✓ | b | c | p | Median wall no-shim | "
             "Median wall shim |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for comparison, model, block in secondary:
        name = f"{comparison['shim']} vs {comparison['base']}"
        slices = block["slices"]
        labelled = [(f"first entry {family}", cell) for family, cell in slices.get("by_first_entry", {}).items()]
        labelled += [(f"target {label}", cell) for label, cell in slices.get("fallback_eligible_target", {}).items()]
        labelled += list(slices.get("op4_permanent_by_target", {}).items())
        labelled += [("both faulted", slices["both_faulted"]), ("all pairs", slices["all_pairs"])]
        for label, cell in labelled:
            lines.append(f"| {name} | {model} | {label} | " + " | ".join(_shim_values(cell, False)) + " |")
    return "\n".join(lines) + "\n"


def shim_markdown(summary: dict[str, Any]) -> str:
    """Shim conditions (reps 1–10) and the pre-registered shim vs no-shim analysis."""
    lines: list[str] = []
    rows = [(model["model"], condition, cell) for model in summary["models"]
            for condition, cell in (model.get("shim_conditions") or {}).items()]
    if rows:
        lines += ["| Model | Condition (reps 1–10) | n | Success | 95% CI | Tool calls | Wall time | Timeouts |",
                  "|---|---|---:|---:|---|---:|---:|---:|"]
        lines += [f"| {model} | {condition} | {cell['n']} | {cell['successes']} ({_pct(cell['success_rate'])}) | "
                  f"{_ci(cell)} | {cell['mean_tool_calls']:.1f} | {cell['mean_wall_time']:.0f}s | {cell['timeouts']} |"
                  for model, condition, cell in rows]
    analysis = shim_analysis_markdown(summary)
    if analysis:
        lines += (["", analysis.rstrip("\n")] if lines else [analysis.rstrip("\n")])
    return "\n".join(lines) + "\n" if lines else ""


def cap_markdown(summary: dict[str, Any]) -> str:
    """Runs that hit their wall-clock cap per model x condition, and the chaos_cap3000 sensitivity rerun."""
    if not summary.get("cap_stats"):
        return ""
    lines = ["| Model | Condition | Runs | Hit cap | Run cap (s) |", "|---|---|---:|---:|---|"]
    for item in summary["cap_stats"]:
        lines.append(f"| {item['model']} | {item['condition']} | {item['n']} | {item['capped']} | "
                     f"{', '.join(f'{cap:g}' for cap in item['run_cap'])} |")
    sensitivity = summary.get("cap_sensitivity") or {}
    if sensitivity.get("rows"):
        lines += ["", "Cap sensitivity: chaos_cap3000 (3000 s cap) vs the same (task, model, rep) in chaos (600 s cap).", "",
                  "| Model | Pairs | chaos ok | cap3000 ok | chaos hit cap | cap3000 hit cap | → success | → failure | "
                  "Mean wall chaos | Mean wall cap3000 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for model, cell in sensitivity["by_model"].items():
            lines.append(f"| {model} | {cell['n']} | {cell['chaos_successes']} | {cell['cap_successes']} | "
                         f"{cell['chaos_capped']} | {cell['cap_capped']} | {cell['flipped_to_success']} | "
                         f"{cell['flipped_to_failure']} | {cell['chaos_mean_wall_time']:.0f}s | "
                         f"{cell['cap_mean_wall_time']:.0f}s |")
        lines += ["", "| Task | Model | Rep | chaos outcome | chaos wall | cap3000 outcome | cap3000 wall |",
                  "|---|---|---:|---|---:|---|---:|"]
        for item in sensitivity["rows"]:
            lines.append(f"| {item['task']} | {item['model']} | {item['rep']} | {item['chaos_outcome']} | "
                         f"{float(item['chaos_wall_time'] or 0):.0f}s | {item['cap_outcome']} | "
                         f"{float(item['cap_wall_time'] or 0):.0f}s |")
    return "\n".join(lines) + "\n"


def paired_markdown(summary: dict[str, Any]) -> str:
    model_names = [model["model"] for model in summary["models"]]
    lines = ["| Task # rep | " + " | ".join(model_names) + " |", "|---|" + "---|" * len(model_names)]
    mark = {True: "✓", False: "✗"}
    for key, per_model in summary["paired"].items():
        values = []
        for name in model_names:
            cell = per_model.get(name, {})
            values.append(" ".join(f"{SHORT[condition]}{mark[cell[condition]['success']]}"
                                   for condition in summary["conditions"] if condition in cell) or "-")
        lines.append(f"| {key} | " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def write_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Write machine-readable and human-readable aggregate results from runs.jsonl rows."""
    summary = summarize(rows)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    headline, extension = summary["headline"], summary["extension"]
    text = ["# Arena summary", "", f"{summary['n_runs']} runs from `results/runs.jsonl`.", "",
            f"## Headline (reps 1–{HEADLINE_REPS}, paper-weighted; {headline['n_runs']} runs)", "",
            f"`headline` = reps 1–{HEADLINE_REPS}. `extension` = rep-file reps ({extension['n_runs']} runs), which "
            "never enter the headline rates.", "", summary_markdown(summary),
            "## Paired outcomes (c = clean, x = chaos, s = chaos_scoped)", "", paired_markdown(summary)]
    for title, block in ((f"Faulted-only success (reps 1–{HEADLINE_REPS})", faulted_only_markdown(summary)),
                         (f"Between-model McNemar (reps 1–{HEADLINE_REPS})", mcnemar_markdown(summary)),
                         ("Winnable subset", winnable_markdown(summary)),
                         ("Resilience shim: pre-registered analysis", shim_markdown(summary)),
                         ("After an error on the target (faulted one-tool pairs)", after_error_markdown(summary)),
                         (f"Extension: winnable reps ({SEED_SELECTED})", extension_markdown(summary)),
                         ("Run caps", cap_markdown(summary))):
        if block:
            text += [f"## {title}", "", block]
    (RESULTS / "summary.md").write_text("\n".join(text), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------------------------- driver

def _append(path: Path, row: dict[str, Any]) -> None:
    with _write_lock, path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")


def task_reps(tasks: list[dict[str, Any]], args: Any) -> dict[str, list[int]]:
    """Reps per task: --rep-file pairs, else --rep-range A-B, else 1..--reps."""
    if getattr(args, "rep_file", None):
        from mcp_fault_bench.winnable import load_rep_file
        pairs = load_rep_file(str(ROOT / args.rep_file) if not Path(args.rep_file).is_absolute() else args.rep_file)
        return {task["id"]: pairs.get(task["id"], []) for task in tasks}
    if getattr(args, "rep_range", None):
        first, _, last = str(args.rep_range).partition("-")
        reps = list(range(int(first), int(last or first) + 1))
    else:
        reps = list(range(1, int(args.reps) + 1))
    return {task["id"]: reps for task in tasks}


def plan_jobs(tasks: list[dict[str, Any]], models: list[str], conditions: list[str], rows: list[dict[str, Any]],
              args: Any, adapter: str = LEGACY_ADAPTER) -> list[tuple[dict[str, Any], str, str, int]]:
    """Missing (task, model, condition, rep) cells, ordered by rep; resume keyed on (task, model, condition, rep,
    effort, adapter)."""
    completed = {(row["task"], row["model"], row["condition"], row["rep"], row.get("effort"), row_adapter(row))
                 for row in rows}
    only = None
    if getattr(args, "only_file", None):
        path = Path(args.only_file) if Path(args.only_file).is_absolute() else ROOT / args.only_file
        only = {(item["task"], item["model"], int(item["rep"])) for item in json.loads(path.read_text(encoding="utf-8"))}
    reps = task_reps(tasks, args)
    cells = sorted({(rep, index) for index, task in enumerate(tasks) for rep in reps[task["id"]]})
    return [(tasks[index], model, condition, rep) for rep, index in cells for model in models for condition in conditions
            if (tasks[index]["id"], model, condition, rep, args.effort, adapter) not in completed
            and (only is None or (tasks[index]["id"], model, rep) in only)]


def result_paths(results_file: str | None) -> tuple[Path, Path, bool]:
    """(results file, harness-error file, write summary?) for --results-file; relative paths are under ROOT.

    Only the default results/runs.jsonl feeds results/summary.*; any other file gets <stem>.harness_errors.jsonl
    beside it. Run artifacts go to runs/ beside the results file (see run_arena).
    """
    default = RESULTS / "runs.jsonl"
    path = Path(results_file) if results_file else default
    path = path if path.is_absolute() else ROOT / path
    if path.resolve() == default.resolve():
        return default, RESULTS / "harness_errors.jsonl", True
    return path, path.parent / f"{path.stem}.harness_errors.jsonl", False


def run_arena(args: Any) -> int:
    """Run missing arena cells concurrently and append each result as it finishes."""
    tasks = yaml.safe_load((ROOT / args.task_file).read_text(encoding="utf-8"))["tasks"]
    if args.tasks:
        wanted = {task_id.strip() for task_id in args.tasks.split(",")}
        unknown = wanted - {task["id"] for task in tasks}
        if unknown:
            raise ValueError(f"Unknown task(s): {', '.join(sorted(unknown))}")
        tasks = [task for task in tasks if task["id"] in wanted]
    adapter = resolve_adapter(getattr(args, "adapter", None))
    models = ([model.strip() for model in args.models.split(",")] if getattr(args, "models", None)
              else adapter.default_models())
    if not models:
        raise ValueError(f"Adapter {adapter.name!r} has no default models; pass --models")
    conditions = [condition.strip() for condition in args.conditions.split(",")]
    allowed = allowed_models(adapter)
    invalid = set(models) - allowed if allowed is not None else set()
    if invalid:
        raise ValueError(f"Unsupported model(s) for adapter {adapter.name!r}: {', '.join(sorted(invalid))}")
    if set(conditions) - set(ALL_CONDITIONS):
        raise ValueError(f"Unknown condition(s): {', '.join(sorted(set(conditions) - set(ALL_CONDITIONS)))}")
    result_path, error_path, summarize_rows = result_paths(getattr(args, "results_file", None))
    runs_dir = result_path.parent / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    rows = load_runs(result_path)
    jobs = plan_jobs(tasks, models, conditions, rows, args, adapter.name)
    run_cap = float(getattr(args, "run_cap", None) or WALL_CLOCK_SECONDS)
    print(f"{len(jobs)} cell(s) to run with adapter {adapter.name}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = [executor.submit(run_one, task, model, condition, rep, args.seed, args.effort,
                                   RUN_CAPS.get(condition, run_cap), adapter=adapter, runs_dir=runs_dir)
                   for task, model, condition, rep in jobs]
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            if row["outcome"] == "harness_error":
                # The agent CLI exited before producing a result. Not an agent result: keep it out of
                # runs.jsonl so the next invocation re-queues the cell, and keep no artifacts.
                shutil.rmtree(ROOT / row["artifact_dir"], ignore_errors=True)
                _append(error_path, {key: row[key] for key in HARNESS_FIELDS})
                print(f"harness_error {row['id']} (re-queued on the next invocation)", flush=True)
                continue
            rows.append(row)
            _append(result_path, row)
            if summarize_rows:
                write_summary(rows)
            print(json.dumps({key: row[key] for key in ("id", "outcome", "success", "tool_calls", "faults",
                                                        "first_entry", "wall_time")}), flush=True)
    if rows and summarize_rows:
        write_summary(rows)
    return 0
