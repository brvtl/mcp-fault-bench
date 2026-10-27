"""Minimal stdio MCP server for shim tests: prices, a slow tool, and an order tool with a visible side effect."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

ORDERS: list[dict] = []
write_lock = threading.Lock()


def call(name: str, arguments: dict) -> dict:
    if name in ("get_price", "get_price_v2"):
        return {"sku": arguments.get("sku", "SKU-1"), "price": 4.37}
    if name == "slow":
        time.sleep(float(arguments.get("seconds", 1.0)))
        return {"slept": float(arguments.get("seconds", 1.0))}
    if name == "place_order":
        order = {"sku": arguments["sku"], "quantity": int(arguments["quantity"])}
        ORDERS.append(order)
        state = os.getenv("CHAOS_STATE_FILE")
        if state:
            Path(state).write_text(json.dumps({"orders": ORDERS}), encoding="utf-8")
        return order
    if name == "list_orders":
        return {"orders": ORDERS}
    raise KeyError(name)


def respond(message: dict) -> None:
    method, request_id, params = message.get("method"), message.get("id"), message.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
    elif method == "tools/call":
        try:
            value = call(params["name"], params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
        except Exception as error:
            result = {"content": [{"type": "text", "text": f"Error: {error}"}], "isError": True}
    else:
        result = {}
    if request_id is not None:
        with write_lock:
            print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)


def main() -> None:
    for line in sys.stdin:
        message = json.loads(line)
        # Calls run concurrently so a slow call does not block the next one.
        threading.Thread(target=respond, args=(message,), daemon=True).start()


if __name__ == "__main__":
    main()
