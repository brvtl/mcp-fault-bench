"""Agent adapter registry, the Claude Code adapter, adapter-tagged rows and legacy rows (fakes only, no agent runs)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench import adapters, arena
from bench.adapters import AgentAdapter, ClaudeCodeAdapter, available_adapters, get_adapter, register_adapter

ROOT = Path(__file__).resolve().parents[1]


class FakeAdapter(AgentAdapter):
    name = "fake-agent"
    artifact_name = "fake.jsonl"
    env = {"FAKE_AGENT": "1"}

    def command(self, prompt, model, effort, mcp_config_path, servers):
        # Writes one line to stdout (the artifact) and exits; no agent, no network.
        return [sys.executable, "-c", "import json; print(json.dumps({'answer': 'FINAL: 56.55'}))"]

    def parse(self, artifact_dir):
        lines = (Path(artifact_dir) / self.artifact_name).read_text().splitlines()
        answer = json.loads(lines[0])["answer"] if lines else ""
        return {"init": {"model": "fake-1", "tools": ["mcp__inventory__get_price"],
                         "mcp_servers": [{"name": "inventory", "status": "connected"}]},
                "result": {"result": answer, "is_error": False, "num_turns": 1, "modelUsage": {"fake-1": {}}},
                "calls": [{"id": "c1", "name": "mcp__inventory__get_price", "tool": "get_price", "is_error": False,
                           "args": "{}", "issued_at": 1, "result_at": 2}]}

    def allowed_models(self):
        return {"fake-1"}


@pytest.fixture
def fake_adapter(monkeypatch):
    monkeypatch.setattr(adapters, "_REGISTRY", dict(adapters._REGISTRY))
    register_adapter(FakeAdapter)
    return get_adapter("fake-agent")


def _task():
    return {"id": "price_total", "servers": ["inventory"], "grade": {"type": "answer_number", "value": 56.55}}


def test_registry_lookup_and_default():
    adapter = get_adapter("claude-code")
    assert isinstance(adapter, ClaudeCodeAdapter) and adapter.artifact_name == "claude.jsonl"
    assert get_adapter() is adapter and arena.resolve_adapter() is adapter
    assert "claude-code" in available_adapters()
    assert adapter.default_models() == list(arena.DEFAULT_MODELS)
    assert arena.allowed_models() == set(arena.DEFAULT_MODELS)


def test_registering_an_adapter(fake_adapter):
    assert isinstance(fake_adapter, FakeAdapter)
    assert available_adapters() == sorted(["claude-code", "fake-agent"])
    assert arena.allowed_models(fake_adapter) == {"fake-1"}


def test_unknown_adapter_lists_available(monkeypatch):
    with pytest.raises(ValueError, match="Unknown adapter 'nope'; available adapters: claude-code"):
        get_adapter("nope")
    monkeypatch.setenv(arena.ADAPTER_ENV, "nope")
    with pytest.raises(ValueError, match="available adapters"):
        arena.resolve_adapter()
    assert arena.resolve_adapter("claude-code").name == "claude-code"  # --adapter beats the environment
    result = subprocess.run([sys.executable, "-m", "mcp_fault_bench", "arena", "--adapter", "nope"], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 2 and "available adapters: claude-code" in result.stderr


def test_claude_code_command_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_BIN", "/opt/claude")
    config = tmp_path / "mcp.json"
    previous = ["/opt/claude", "-p", "do it", "--model", "claude-haiku-5-5", "--effort", "medium",
                "--output-format", "stream-json", "--verbose",
                "--mcp-config", str(config), "--strict-mcp-config",
                "--tools", "", "--allowedTools", "mcp__notes", "mcp__inventory",
                "--permission-mode", "dontAsk", "--disable-slash-commands",
                "--setting-sources", "", "--no-session-persistence"]
    adapter = get_adapter("claude-code")
    assert adapter.command("do it", "claude-haiku-5-5", "medium", config, ["notes", "inventory"]) == previous
    assert arena.claude_command("do it", "claude-haiku-5-5", "medium", config, ["notes", "inventory"]) == previous
    assert dict(adapter.env) == {"MCP_TOOL_TIMEOUT": "60000", "MCP_TIMEOUT": "20000"} == arena.CLAUDE_ENV


def test_claude_code_parse_reads_the_stored_stream(tmp_path):
    events = [{"type": "system", "subtype": "init", "model": "m"},
              {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": "mcp__a__b",
                                                             "input": {}}]}},
              {"type": "result", "result": "FINAL: 1"}]
    (tmp_path / "claude.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    assert get_adapter("claude-code").parse(tmp_path) == arena.parse_stream(events)


def test_score_run_tags_rows_with_the_adapter(tmp_path, monkeypatch, fake_adapter):
    monkeypatch.setattr(arena, "ROOT", tmp_path)
    run = tmp_path / "run-1"
    run.mkdir()
    (run / "fake.jsonl").write_text(json.dumps({"answer": "FINAL: 56.55"}) + "\n")
    row = arena.score_run(_task(), "fake-1", "clean", 1, "42:price_total:1", None, "medium", run,
                          {"inventory": str(run / "inventory.json")}, 1.0, False, 600, fake_adapter)
    assert row["adapter"] == "fake-agent" and row["model"] == "fake-1"
    assert row["outcome"] == "ok" and row["success"] and row["tool_calls"] == 1
    legacy = tmp_path / "run-2"
    legacy.mkdir()
    (legacy / "claude.jsonl").write_text("")
    assert arena.score_run(_task(), "m", "clean", 1, "s", None, "medium", legacy, {}, 1.0, False)["adapter"] \
        == "claude-code"


def test_run_one_uses_the_adapter_command_env_and_artifact(tmp_path, monkeypatch, fake_adapter):
    monkeypatch.setattr(arena, "ROOT", tmp_path)
    monkeypatch.setattr(arena, "RUNS", tmp_path / "results" / "runs")
    row = arena.run_one({**_task(), "prompt": "add prices"}, "fake-1", "clean", 1, "42", "medium", 30,
                        adapter=fake_adapter)
    assert row["adapter"] == "fake-agent" and row["success"]
    artifact = tmp_path / row["artifact_dir"]
    assert (artifact / "fake.jsonl").exists() and not (artifact / "claude.jsonl").exists()


def test_run_arena_passes_the_adapter_and_resumes_per_adapter(tmp_path, monkeypatch, fake_adapter):
    results = tmp_path / "results"
    results.mkdir()
    (tmp_path / "bench").mkdir()
    (tmp_path / "bench" / "tasks.yaml").write_text(json.dumps({"tasks": [{"id": "price_total"}]}))
    monkeypatch.setattr(arena, "ROOT", tmp_path)
    monkeypatch.setattr(arena, "RESULTS", results)
    monkeypatch.setattr(arena, "RUNS", results / "runs")
    # A legacy row (no adapter field) for the same cell must not count as done for another adapter.
    legacy = {"id": "r1", "task": "price_total", "model": "fake-1", "condition": "clean", "rep": 1, "effort": "medium"}
    round_file = results / "round2.jsonl"
    round_file.write_text(json.dumps(legacy) + "\n")
    seen = []

    def fake_run_one(task, model, condition, rep, seed, effort, run_cap, adapter=None):
        seen.append((adapter.name, model, rep))
        return {**legacy, "id": f"r{rep}", "rep": rep, "adapter": adapter.name, "outcome": "ok", "success": True,
                "tool_calls": 1, "faults": 0, "first_entry": None, "wall_time": 1.0, "artifact_dir": "x"}

    monkeypatch.setattr(arena, "run_one", fake_run_one)
    args = SimpleNamespace(task_file="bench/tasks.yaml", tasks=None, models=None, conditions="clean", reps=1,
                           rep_range=None, rep_file=None, only_file=None, run_cap=600, parallel=1, seed="42",
                           effort="medium", results_file="results/round2.jsonl", adapter="fake-agent")
    assert arena.run_arena(args) == 0
    assert seen == [("fake-agent", "fake-1", 1)]
    stored = [json.loads(line) for line in round_file.read_text().splitlines()]
    assert "adapter" not in stored[0] and stored[1]["adapter"] == "fake-agent"
    seen.clear()
    assert arena.run_arena(args) == 0 and seen == []  # resumed: the fake-agent row now exists
    with pytest.raises(ValueError, match="Unsupported model"):
        arena.run_arena(SimpleNamespace(**{**vars(args), "models": "claude-opus-5-5"}))


def test_legacy_rows_load_as_claude_code(tmp_path):
    path = tmp_path / "runs.jsonl"
    text = json.dumps({"id": "a", "model": "claude-opus-5-5"}) + "\n" + \
        json.dumps({"id": "b", "model": "x", "adapter": "other"}) + "\n"
    path.write_text(text)
    assert [row["adapter"] for row in arena.load_runs(path)] == ["claude-code", "other"]
    assert path.read_text() == text  # tagging happens in memory only
    shipped = arena.load_runs(ROOT / "results" / "runs.jsonl")
    assert shipped and {row["adapter"] for row in shipped} == {"claude-code"}
