from __future__ import annotations

import json
import sys
import traceback
import uuid
from typing import Any

from audit import AUDIT_DIR as DEFAULT_AUDIT_DIR, write_audit_event
from locks import (
    CRITICAL_TOOLS,
    LOCK_DIR as DEFAULT_LOCK_DIR,
    LockConflict,
    acquire_locks,
    lock_keys_for_tool,
)
from schemas import EXPLICIT_TARGET_RISK_LEVELS, TOOL_DEFINITIONS, TOOL_RISK_LEVELS
from toolchain import TOOLS, ToolchainError
from validation import validate_json_schema
from version import __version__


SERVER_INFO = {"name": "br-plc-toolchain", "version": __version__}
PROTOCOL_VERSION = "2024-11-05"
TOOL_DEFINITIONS_BY_NAME = {definition["name"]: definition for definition in TOOL_DEFINITIONS}
AUDIT_DIR = DEFAULT_AUDIT_DIR
LOCK_DIR = DEFAULT_LOCK_DIR


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
    tool = TOOLS.get(str(name))
    definition = TOOL_DEFINITIONS_BY_NAME.get(str(name))
    if tool is None or definition is None:
        return text_result(
            {
                "ok": False,
                "tool": name,
                "error": f"Unknown tool: {name}",
            },
            is_error=True,
        )

    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    validation_errors = validate_json_schema(arguments, definition["inputSchema"])
    risk_level = TOOL_RISK_LEVELS[str(name)]
    has_explicit_target = isinstance(arguments, dict) and any(
        isinstance(arguments.get(key), str) and bool(arguments[key].strip())
        for key in ("target", "environment")
    )
    if risk_level in EXPLICIT_TARGET_RISK_LEVELS and not has_explicit_target:
        validation_errors.append(
            {
                "path": "$.target",
                "keyword": "explicitTarget",
                "message": (
                    "Target-changing tools require an explicit non-empty target or environment."
                ),
            }
        )
    operation_id = uuid.uuid4().hex
    if validation_errors:
        payload = {
            "ok": False,
            "tool": name,
            "error": "Tool argument validation failed.",
            "validation_errors": validation_errors,
        }
        if str(name) in CRITICAL_TOOLS:
            audit_arguments = arguments if isinstance(arguments, dict) else {}
            try:
                audit_path = write_audit_event(
                    tool=str(name),
                    status="rejected",
                    arguments=audit_arguments,
                    operation_id=operation_id,
                    lock_keys=[],
                    error=payload["error"],
                    directory=AUDIT_DIR,
                )
                payload["audit"] = [audit_path]
            except Exception as exc:
                payload["audit_error"] = str(exc)
        return text_result(payload, is_error=True)

    assert isinstance(arguments, dict)
    tool_name = str(name)
    lock_keys = lock_keys_for_tool(tool_name, arguments)
    audit_paths: list[str] = []
    if tool_name in CRITICAL_TOOLS:
        try:
            audit_paths.append(
                write_audit_event(
                    tool=tool_name,
                    status="started",
                    arguments=arguments,
                    operation_id=operation_id,
                    lock_keys=lock_keys,
                    directory=AUDIT_DIR,
                )
            )
        except Exception as exc:
            return text_result(
                {
                    "ok": False,
                    "tool": name,
                    "error": f"Audit initialization failed; action was not executed: {exc}",
                },
                is_error=True,
            )

    result: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None
    final_status = "failed"
    try:
        with acquire_locks(
            lock_keys,
            directory=LOCK_DIR,
            metadata={"tool": tool_name, "operation_id": operation_id},
        ):
            result = tool(arguments)
        final_status = "succeeded" if result.get("ok") else "failed"
    except LockConflict as exc:
        final_status = "blocked"
        error_payload = {
            "ok": False,
            "tool": name,
            "error": str(exc),
            "lock_conflict": {
                "key": exc.key,
                "path": str(exc.path),
                "holder": exc.holder,
            },
        }
    except ToolchainError as exc:
        error_payload = {
            "ok": False,
            "tool": name,
            "error": str(exc),
            "exit_code": exc.exit_code,
            "stdout": exc.stdout,
            "stderr": exc.stderr,
        }
    except Exception as exc:
        error_payload = {
            "ok": False,
            "tool": name,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }

    payload = result if result is not None else error_payload
    assert payload is not None
    if tool_name in CRITICAL_TOOLS:
        try:
            audit_paths.append(
                write_audit_event(
                    tool=tool_name,
                    status=final_status,
                    arguments=arguments,
                    operation_id=operation_id,
                    lock_keys=lock_keys,
                    result=result,
                    error=error_payload.get("error") if error_payload else None,
                    directory=AUDIT_DIR,
                )
            )
        except Exception as exc:
            payload["audit_error"] = str(exc)
    if audit_paths:
        payload["audit"] = audit_paths
    return text_result(payload, is_error=error_payload is not None)


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
