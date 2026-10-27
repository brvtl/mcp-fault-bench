"""The former package name `chaosmonkey` stays importable and runnable as an alias of `mcp_fault_bench`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chaosmonkey_submodules_are_the_new_modules():
    import chaosmonkey.proxy
    import mcp_fault_bench.proxy
    import mcp_fault_bench.shim
    import mcp_fault_bench.winnable
    from chaosmonkey.proxy import first_draw
    from chaosmonkey.shim import load_shim_config
    from chaosmonkey.winnable import load_rep_file

    assert chaosmonkey.proxy is mcp_fault_bench.proxy
    assert first_draw is mcp_fault_bench.proxy.first_draw
    assert load_shim_config is mcp_fault_bench.shim.load_shim_config
    assert load_rep_file is mcp_fault_bench.winnable.load_rep_file


def test_both_module_names_run_the_same_cli():
    outputs = []
    for module in ("mcp_fault_bench", "chaosmonkey"):
        result = subprocess.run([sys.executable, "-m", module, "--help"], cwd=ROOT, capture_output=True, text=True,
                                check=True)
        outputs.append(result.stdout)
        assert "proxy" in result.stdout and "arena" in result.stdout
    assert outputs[0] == outputs[1]


def test_console_scripts_point_at_a_callable_main():
    import tomllib

    from mcp_fault_bench.__main__ import main

    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts == {"mcp-fault-bench": "mcp_fault_bench.__main__:main", "chaosmonkey": "mcp_fault_bench.__main__:main"}
    assert callable(main)
