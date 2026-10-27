"""Backward-compatible alias for :mod:`mcp_fault_bench` (the package's former name).

``import chaosmonkey.proxy`` and ``from chaosmonkey.proxy import first_draw`` resolve to the same module objects as
``mcp_fault_bench.proxy``; pre-registration documents, rep-file rules and stored run artifacts use the old name.
"""

from __future__ import annotations

import importlib
import sys

import mcp_fault_bench

SUBMODULES = ("profile", "proxy", "shim", "winnable")

for _name in SUBMODULES:
    _module = importlib.import_module(f"mcp_fault_bench.{_name}")
    sys.modules[f"{__name__}.{_name}"] = _module
    globals()[_name] = _module
