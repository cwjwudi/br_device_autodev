from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from schemas import TOOL_DEFINITIONS
from toolchain import TOOLS, ToolchainError


SERVER_INFO = {"name": "br-plc-toolchain", "version": "0.1.0"}
PROTOCOL_VERSION = "2024-11-05"


def make_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def text_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        "structuredContent": payload,
        "isError": is_error,
    }


def handle_initialize(params: dict[str, Any]) -> dict[str, Any]:
    requested_version = params.get("protocolVersion")
    return {
        "protocolVersion": requested_version or PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": SERVER_INFO,
    }


def handle_tools_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return text_result(
            {
                "ok": False,
                "tool": name,
                "error": "Tool arguments must be an object.",
            },
            is_error=True,
        )

    tool = TOOLS.get(str(name))
    if tool is None:
        return text_result(
            {
                "ok": False,
                "tool": name,
                "error": f"Unknown tool: {name}",
            },
            is_error=True,
        )

    try:
        result = tool(arguments)
        return text_result(result, is_error=False)
    except ToolchainError as exc:
        return text_result(
            {
                "ok": False,
                "tool": name,
                "error": str(exc),
                "exit_code": exc.exit_code,
                "stdout": exc.stdout,
                "stderr": exc.stderr,
            },
            is_error=True,
        )
    except Exception as exc:
        return text_result(
            {
                "ok": False,
                "tool": name,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
            is_error=True,
        )


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if request_id is None:
        return None

    if method == "initialize":
        return make_response(request_id, handle_initialize(params))
    if method == "tools/list":
        return make_response(request_id, {"tools": TOOL_DEFINITIONS})
    if method == "tools/call":
        return make_response(request_id, handle_tools_call(params))

    return make_error(request_id, -32601, f"Method not found: {method}")


def run() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = make_error(None, -32700, f"Parse error: {exc}")
        else:
            response = handle_request(message)

        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run()
