"""Deterministic in-memory inventory MCP server used by the arena."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# sku: (name, category, price, stock). Fixed, deliberately irregular values the agent cannot guess.
CATALOG = {
    "SKU-731": ("Amber tea", "tea", 4.37, 8),
    "SKU-405": ("Birch chai", "tea", 5.83, 3),
    "SKU-118": ("Juniper oolong", "tea", 3.94, 0),
    "SKU-562": ("Smoke lapsang", "tea", 4.12, 11),
    "SKU-284": ("Cedar coffee", "coffee", 8.46, 0),
    "SKU-639": ("Ridge espresso", "coffee", 7.19, 6),
    "SKU-857": ("Harbor drip", "coffee", 6.73, 9),
    "SKU-302": ("Ember roast", "coffee", 6.41, 0),
    "SKU-916": ("Quartz cocoa", "cocoa", 3.17, 14),
    "SKU-473": ("Velvet cacao", "cocoa", 4.86, 4),
    "SKU-725": ("Dune cocoa nibs", "cocoa", 5.29, 0),
    "SKU-208": ("Moss matcha", "matcha", 9.62, 7),
    "SKU-994": ("Kiln matcha", "matcha", 11.38, 1),
    "SKU-547": ("Fern hojicha", "matcha", 8.07, 5),
}
PRODUCTS = {sku: row[0] for sku, row in CATALOG.items()}
CATEGORIES = {sku: row[1] for sku, row in CATALOG.items()}
PRICES = {sku: row[2] for sku, row in CATALOG.items()}
STOCK = {sku: row[3] for sku, row in CATALOG.items()}
ORDERS: list[dict[str, Any]] = []


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": properties, "required": required}}


TOOLS = [
    _tool("search_products", "List products in a category (tea, coffee, cocoa, matcha): SKUs and names",
          {"category": {"type": "string"}}, ["category"]),
    _tool("get_product", "Get product name and category by SKU", {"sku": {"type": "string"}}, ["sku"]),
    _tool("get_price", "Get exact item price by SKU", {"sku": {"type": "string"}}, ["sku"]),
    _tool("get_price_v2", "Alternate price endpoint by SKU", {"sku": {"type": "string"}}, ["sku"]),
    _tool("get_stock", "Get stock count by SKU", {"sku": {"type": "string"}}, ["sku"]),
    _tool("place_order", "Place an order", {"sku": {"type": "string"}, "quantity": {"type": "integer"}}, ["sku", "quantity"]),
    _tool("list_orders", "List placed orders", {}, []),
]


def save_state() -> None:
    """Persist mutable inventory state when the arena configured a path."""
    path = os.getenv("CHAOS_STATE_FILE")
    if path:
        Path(path).write_text(json.dumps({"orders": ORDERS, "stock": STOCK}, indent=2), encoding="utf-8")


def _sku(arguments: dict[str, Any]) -> str:
    sku = str(arguments.get("sku", "")).strip().upper()
    if sku not in CATALOG:
        raise ValueError(f"unknown sku: {arguments.get('sku')}")
    return sku


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Execute one inventory operation and return its structured value."""
    if name == "search_products":
        category = str(arguments["category"]).strip().lower()
        return [{"sku": sku, "name": PRODUCTS[sku]} for sku in CATALOG if CATEGORIES[sku] == category]
    if name == "get_product":
        sku = _sku(arguments)
        return {"sku": sku, "name": PRODUCTS[sku], "category": CATEGORIES[sku]}
    if name in ("get_price", "get_price_v2"):
        sku = _sku(arguments)
        return {"sku": sku, "price": PRICES[sku]}
    if name == "get_stock":
        sku = _sku(arguments)
        return {"sku": sku, "stock": STOCK[sku]}
    if name == "place_order":
        sku, quantity = _sku(arguments), int(arguments["quantity"])
        if quantity < 1:
            raise ValueError("quantity must be positive")
        if STOCK[sku] < quantity:
            raise ValueError("insufficient stock")
        order = {"sku": sku, "quantity": quantity}
        ORDERS.append(order)
        STOCK[sku] -= quantity
        save_state()
        return order
    if name == "list_orders":
        return ORDERS
    raise KeyError(name)


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Return a JSON-RPC response for a request, or None for notifications."""
    method, request_id = message.get("method"), message.get("id")
    params = message.get("params", {})
    if method == "initialize":
        requested = params.get("protocolVersion")
        result = {"protocolVersion": requested if requested == "2025-06-18" else "2025-06-18",
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "inventory", "version": "1.0"}}
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        if params.get("name") not in {tool["name"] for tool in TOOLS}:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32602, "message": f"unknown tool: {params.get('name')}"}}
        try:
            value = call_tool(params["name"], params.get("arguments", {}))
            result = {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
        except Exception as error:  # tool execution errors are reported in the result, per MCP
            result = {"content": [{"type": "text", "text": f"Error: {error}"}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": "method not found"}}
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> None:
    """Serve newline-delimited JSON-RPC until stdin closes."""
    for line in sys.stdin:
        try:
            response = handle_message(json.loads(line))
            if response is not None:
                print(json.dumps(response), flush=True)
        except (json.JSONDecodeError, TypeError):
            continue


if __name__ == "__main__":
    main()
