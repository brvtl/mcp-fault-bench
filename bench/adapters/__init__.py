"""Agent adapters: how the arena launches one agent run and reads back what the agent did.

The arena owns everything that stays fixed across rounds (tasks, fault profiles, seeds, the proxy, grading). An
adapter owns the agent side: the command line for one headless run, the environment it needs, the name of the file
its stdout is stored in, and a parser that turns that file into the normalized structure the scorer reads::

    {"init":   {"model": str, "tools": [...], "mcp_servers": [{"name": str, "status": "connected"}, ...]},
     "result": {"result": str, "is_error": bool, "num_turns": int, "duration_ms": int,
                "total_cost_usd": float | None, "usage": dict | None, "modelUsage": {model: {...}}} | None,
     "calls":  [{"id", "name", "tool", "is_error", "args", "issued_at", "result_at"}, ...]}

MCP tool calls must be named ``mcp__<server>__<tool>`` in ``name`` (the Claude Code convention the scorer uses
to tell MCP calls from built-in tools). ``init`` is empty and ``result`` is None when the agent exited before starting or finishing (scored as a harness
error). ``calls`` are the agent's tool calls in order; ``tool`` is the bare MCP tool name, ``args`` the JSON-encoded
arguments, ``issued_at`` / ``result_at`` positions in the agent's event order. Register a new adapter with
``register_adapter`` and select it with ``arena --adapter <name>``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

LEGACY_ADAPTER = "claude-code"  # result rows written before adapters existed have no "adapter" field


class AgentAdapter:
    """Base class for an agent harness. Subclasses set ``name`` and implement ``command`` and ``parse``."""

    name: str = ""
    artifact_name: str = "agent.jsonl"  # the agent's stdout, stored in the run's artifact directory
    env: Mapping[str, str] = {}  # extra environment for the agent process

    def command(self, prompt: str, model: str, effort: str, mcp_config_path: Path, servers: list[str]) -> list[str]:
        """argv for one headless run: answer ``prompt`` with ``model`` using only the MCP servers in the config."""
        raise NotImplementedError

    def parse(self, artifact_dir: Path) -> dict[str, Any]:
        """Normalized {init, result, calls} from the stored artifact (see the module docstring)."""
        raise NotImplementedError

    def finalize(self, artifact_dir: Path) -> None:
        """Trim the stored artifact after the run (before path scrubbing). Default: keep it as is."""

    def allowed_models(self) -> set[str] | None:
        """Model ids this adapter accepts; None accepts any id."""
        return None

    def default_models(self) -> list[str]:
        """Models run when ``--models`` is not given."""
        return sorted(self.allowed_models() or [])


_REGISTRY: dict[str, AgentAdapter] = {}


def register_adapter(adapter: AgentAdapter | type[AgentAdapter]) -> AgentAdapter | type[AgentAdapter]:
    """Register an adapter instance or class (usable as a class decorator) under its ``name``."""
    instance = adapter() if isinstance(adapter, type) else adapter
    if not instance.name:
        raise ValueError("adapter has no name")
    _REGISTRY[instance.name] = instance
    return adapter


def available_adapters() -> list[str]:
    return sorted(_REGISTRY)


def get_adapter(name: str | None = None) -> AgentAdapter:
    """The registered adapter called ``name`` (default: the legacy Claude Code adapter)."""
    name = name or LEGACY_ADAPTER
    if name not in _REGISTRY:
        raise ValueError(f"Unknown adapter {name!r}; available adapters: {', '.join(available_adapters())}")
    return _REGISTRY[name]


def row_adapter(row: Mapping[str, Any]) -> str:
    """Adapter name of a result row; rows written before adapters existed are Claude Code runs."""
    return row.get("adapter") or LEGACY_ADAPTER


from bench.adapters.claude_code import ClaudeCodeAdapter  # noqa: E402  (registers "claude-code")

__all__ = ["AgentAdapter", "ClaudeCodeAdapter", "LEGACY_ADAPTER", "available_adapters", "get_adapter",
           "register_adapter", "row_adapter"]
