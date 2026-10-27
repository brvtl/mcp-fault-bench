"""Simple persistent key/value notes MCP server used by the arena."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _state_path() -> Path | None:
    path = os.getenv("CHAOS_STATE_FILE")
    return Path(path) if path else None


def _load_notes() -> dict[str, str]:
    path = _state_path()
    return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}


NOTES = _load_notes()
TOOLS = [
    {"name": "put_note", "description": "Store a note under a key", "inputSchema": {
        "type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}, "required": ["key", "value"]}},
    {"name": "get_note", "description": "Read a note", "inputSchema": {
        "type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}},
    {"name": "list_notes", "description": "List note keys", "inputSchema": {
        "type": "object", "properties": {}, "required": []}},
    {"name": "search_notes", "description": "Search note text", "inputSchema": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
]


def save_notes() -> None:
    """Write current notes to the arena state file when configured."""
    path = _state_path()
    if path:
        path.write_text(json.dumps(NOTES, indent=2), encoding="utf-8")


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Run a notes operation and return its structured value."""
    if name == "put_note":
        NOTES[arguments["key"]] = arguments["value"]
        save_notes()
        return {"stored": True, "key": arguments["key"]}
    if name == "get_note":
        return {"key": arguments["key"], "value": NOTES.get(arguments["key"])}
    if name == "list_notes":
        return list(NOTES)
    if name == "search_notes":
        query = arguments["query"].lower()
        return {key: value for key, value in NOTES.items() if query in value.lower()}
    raise KeyError(name)


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Return a JSON-RPC response for a request, or None for notifications."""
    method, request_id = message.get("method"), message.get("id")
    params = message.get("params", {})
    if method == "initialize":
        requested = params.get("protocolVersion")
        result = {"protocolVersion": requested if requested == "2025-06-18" else "2025-06-18",
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "notes", "version": "1.0"}}
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
