"""Command line entry point for the MCP Fault Bench tools (`python -m mcp_fault_bench`, alias `python -m chaosmonkey`)."""

from __future__ import annotations

import argparse
import json
import sys

from .proxy import run_proxy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp-fault-bench")
    commands = parser.add_subparsers(dest="command", required=True)

    proxy = commands.add_parser("proxy", help="wrap an MCP stdio server")
    proxy.add_argument("--schedule")
    proxy.add_argument("--log")
    proxy.add_argument("--seed", help="override the schedule seed (any string)")
    proxy.add_argument("--target", help="profile_draw only: restrict the drawn entry to this tool")
    proxy.add_argument("--shim", help="enable the resilience shim with this config (e.g. profiles/shim.yaml)")
    proxy.add_argument("command_line", nargs=argparse.REMAINDER)

    convert = commands.add_parser("convert-paper-profile", help="convert the included calibrated paper profile")
    convert.add_argument("--input", default="third_party/mcp-injector/fault_mode_1.json")
    convert.add_argument("--output", default="profiles/paper_opp.yaml")
    convert.add_argument("--scoped-output", default="profiles/paper_opp_scoped.yaml")

    winnable = commands.add_parser("winnable-reps", help="pick extension reps whose first draw is not excluded")
    winnable.add_argument("--schedule", default="profiles/paper_opp.yaml")
    winnable.add_argument("--seed", default="42")
    winnable.add_argument("--start", type=int, default=11)
    winnable.add_argument("--per-task", type=int, default=4)
    winnable.add_argument("--tasks", help="comma-separated task ids (default: all in --task-file)")
    winnable.add_argument("--task-file", default="bench/tasks.yaml")
    winnable.add_argument("--exclude", action="append", help="first-draw label to skip (repeatable; default OP4/permanent)")
    winnable.add_argument("--output", default="bench/winnable_reps.json")

    arena = commands.add_parser("arena", help="run the benchmark arena with an agent adapter (default: Claude Code)")
    arena.add_argument("--adapter", help="agent adapter from the registry (default: $MCP_FAULT_BENCH_ADAPTER, "
                                         "else claude-code)")
    arena.add_argument("--task-file", default="bench/tasks.yaml")
    arena.add_argument("--tasks", help="comma-separated task ids (default: all)")
    arena.add_argument("--models", help="comma-separated model ids (default: the adapter's models; claude-code: "
                                        "claude-opus-5-5,claude-sonnet-5-5,claude-haiku-5-5)")
    arena.add_argument("--conditions", default="clean,chaos,chaos_scoped")
    arena.add_argument("--reps", type=int, default=10)
    arena.add_argument("--rep-range", help="run reps A-B instead of 1..--reps, e.g. 1-10")
    arena.add_argument("--rep-file", help="run exactly the (task, rep) pairs in this file (bench/winnable_reps.json)")
    arena.add_argument("--only-file", help="JSON list of {task, model, rep}: run only these (e.g. the cap rerun)")
    arena.add_argument("--run-cap", type=float, default=600, help="per-run wall clock in seconds (chaos_cap3000: 3000)")
    arena.add_argument("--parallel", type=int, default=6)
    arena.add_argument("--seed", default="42")
    arena.add_argument("--effort", default="medium")
    arena.add_argument("--results-file", default="results/runs.jsonl",
                       help="resume from and append to this file (run artifacts go to runs/ beside it); "
                            "only the default updates results/summary.*")

    commands.add_parser("summarize", help="rewrite results/summary.* from results/runs.jsonl")

    serve = commands.add_parser("serve", help="serve the local scoreboard and replay")
    serve.add_argument("--port", type=int, default=8787)
    return parser


def main() -> int:
    """Parse command line arguments and dispatch to the requested operation."""
    parser = _parser()
    arguments = parser.parse_args()
    if arguments.command == "proxy":
        command = arguments.command_line
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error("proxy requires an upstream command after --")
        return run_proxy(command, arguments.schedule, arguments.log, arguments.seed, arguments.target, arguments.shim)
    if arguments.command == "convert-paper-profile":
        from .profile import convert
        convert(arguments.input, arguments.output, arguments.scoped_output)
        return 0
    if arguments.command == "winnable-reps":
        from .winnable import write_winnable_reps
        tasks = [task.strip() for task in arguments.tasks.split(",")] if arguments.tasks else None
        document = write_winnable_reps(arguments.schedule, arguments.seed, arguments.start, arguments.per_task,
                                       arguments.exclude or ["OP4/permanent"], arguments.task_file, tasks,
                                       arguments.output)
        print(json.dumps(document, indent=2))
        print(f"wrote {arguments.output}", file=sys.stderr)
        return 0
    if arguments.command == "arena":
        from bench.arena import resolve_adapter, run_arena
        try:
            resolve_adapter(arguments.adapter)
        except ValueError as error:
            parser.error(str(error))
        return run_arena(arguments)
    if arguments.command == "summarize":
        from bench.arena import RESULTS, load_runs, write_summary
        write_summary(load_runs(RESULTS / "runs.jsonl"))
        return 0
    if arguments.command == "serve":
        from web.server import serve
        serve(arguments.port)
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
