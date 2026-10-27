"""Claude Code (`claude -p ... --output-format stream-json`) as the arena agent: the round-1 adapter."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from bench.adapters import AgentAdapter, register_adapter

MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
CLAUDE_ENV = {"MCP_TOOL_TIMEOUT": "60000", "MCP_TIMEOUT": "20000"}
STREAM_EVENTS = ("system", "assistant", "user", "result")


def claude_bin() -> str:
    """Claude Code binary: $CLAUDE_BIN, then ~/.local/bin/claude, then PATH."""
    configured = os.getenv("CLAUDE_BIN")
    if configured:
        return configured
    local = Path.home() / ".local" / "bin" / "claude"
    return str(local) if local.exists() else (shutil.which("claude") or "claude")


def claude_command(prompt: str, model: str, effort: str, mcp_config: Path, servers: list[str]) -> list[str]:
    # --tools "" removes every built-in tool; dontAsk denies anything not pre-approved by --allowedTools,
    # so the run never waits on a permission prompt. This CLI version has no --max-turns flag.
    return [claude_bin(), "-p", prompt, "--model", model, "--effort", effort,
            "--output-format", "stream-json", "--verbose",
            "--mcp-config", str(mcp_config), "--strict-mcp-config",
            "--tools", "", "--allowedTools", *[f"mcp__{name}" for name in servers],
            "--permission-mode", "dontAsk", "--disable-slash-commands",
            "--setting-sources", "", "--no-session-persistence"]


def _short_tool(name: str) -> str:
    """mcp__inventory__get_price -> get_price."""
    return name.split("__", 2)[2] if name.startswith("mcp__") and name.count("__") >= 2 else name


def parse_stream(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract init, tool calls (in order, with error flags) and the final result from stream-json."""
    init: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    calls: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    position = 0  # stream order of tool_use / tool_result blocks, so "issued after an error came back" is decidable
    for event in events:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            init = event
        elif kind == "result":
            result = event
        elif kind in ("assistant", "user"):
            content = (event.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                position += 1
                if block.get("type") == "tool_use":
                    call = {"id": block.get("id"), "name": block.get("name", ""),
                            "tool": _short_tool(block.get("name", "")), "is_error": None,
                            "args": json.dumps(block.get("input"), sort_keys=True), "issued_at": position,
                            "result_at": None}
                    calls.append(call)
                    by_id[str(block.get("id"))] = call
                elif block.get("type") == "tool_result" and str(block.get("tool_use_id")) in by_id:
                    by_id[str(block.get("tool_use_id"))]["is_error"] = bool(block.get("is_error"))
                    by_id[str(block.get("tool_use_id"))]["result_at"] = position
    return {"init": init, "result": result, "calls": calls}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _event_type(line: str) -> str | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    return event.get("type") if isinstance(event, dict) else None


def keep_stream_events(path: Path) -> None:
    """Store only the stream events the scorer uses (init, messages, tool results, final result)."""
    if path.exists():
        kept = [line for line in path.read_text(encoding="utf-8").splitlines()
                if _event_type(line) in STREAM_EVENTS]
        path.write_text("".join(line + "\n" for line in kept), encoding="utf-8")


@register_adapter
class ClaudeCodeAdapter(AgentAdapter):
    name = "claude-code"
    artifact_name = "claude.jsonl"
    env = CLAUDE_ENV

    def command(self, prompt: str, model: str, effort: str, mcp_config_path: Path, servers: list[str]) -> list[str]:
        return claude_command(prompt, model, effort, mcp_config_path, servers)

    def parse(self, artifact_dir: Path) -> dict[str, Any]:
        return parse_stream(read_jsonl(Path(artifact_dir) / self.artifact_name))

    def finalize(self, artifact_dir: Path) -> None:
        keep_stream_events(Path(artifact_dir) / self.artifact_name)

    def allowed_models(self) -> set[str]:
        return set(MODELS)

    def default_models(self) -> list[str]:
        return list(MODELS)
