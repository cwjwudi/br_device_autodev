from __future__ import annotations

import json
import sys
import traceback
import uuid
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
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
from toolchain import (
    TOOLS,
    ToolchainError,
    cancel_operation,
    close_runtime_pvi_service,
    reset_operation_id,
    set_operation_id,
)
from validation import validate_json_schema
from version import SERVER_RUNTIME, __version__


SERVER_INFO = {"name": "br-plc-toolchain", "version": __version__, **SERVER_RUNTIME}
PROTOCOL_VERSION = "2024-11-05"
TOOL_DEFINITIONS_BY_NAME = {definition["name"]: definition for definition in TOOL_DEFINITIONS}
AUDIT_DIR = DEFAULT_AUDIT_DIR
LOCK_DIR = DEFAULT_LOCK_DIR
ERROR_LOG = Path(__file__).resolve().parents[2] / "var" / "reports" / "mcp_server_errors.log"
RATE_LIMIT_WINDOW_SECONDS = 60.0
MAX_TARGET_CHANGES_PER_WINDOW = 10
_RATE_LIMIT_LOCK = threading.RLock()
_TARGET_CHANGE_TIMES: dict[str, list[float]] = {}


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
        "protocolVersion": requested_version if requested_version == PROTOCOL_VERSION else PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": SERVER_INFO,
    }


def write_exception_log(operation_id: str, exc: BaseException) -> str | None:
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open("a", encoding="utf-8") as stream:
            stream.write(
                f"[{datetime.now(UTC).isoformat()}] operation_id={operation_id}\n"
                f"{traceback.format_exc()}\n"
            )
        return str(ERROR_LOG)
    except Exception:
        return None


def classify_exception(exc: BaseException) -> tuple[str, bool, str, list[str]]:
    message = str(exc)
    error_code = getattr(exc, "error_code", None)
    if error_code:
        return (
            str(error_code),
            bool(getattr(exc, "retryable", False)),
            "trace" if str(error_code).startswith("TRACE_") else "pvi",
            ["Inspect the trace status or stop the active trace before retrying."],
        )
    if message.startswith("PVI_SESSION_FINGERPRINT_MISMATCH"):
        return "PVI_SESSION_FINGERPRINT_MISMATCH", False, "policy", ["Open a new test session after confirming the target identity."]
    if message.startswith("PVI_OPERATION_TIMEOUT") or message.startswith("PVI_WORKER_DIRTY"):
        return "PVI_OPERATION_TIMEOUT", False, "pvi", ["Treat the target state as unknown and reconnect before retrying."]
    if "PVI_CONNECTION_UNAVAILABLE" in message or "Pvi-Error 12004" in message or "Pvi-Error 12059" in message:
        return "PVI_CONNECTION_UNAVAILABLE", True, "pvi", [
            "Check whether PVI Manager is running and licensed; the unlicensed trial expires after two hours and then requires a PVI Manager restart.",
            "After restarting PVI Manager, retry the read-only discovery so the MCP server creates a fresh PVI object hierarchy.",
        ]
    if message.startswith("INVALID_TARGET_NAME"):
        return "INVALID_TARGET_NAME", False, "validation", ["Use only letters, digits, dot, underscore, and hyphen in target names."]
    if isinstance(exc, PermissionError):
        return "POLICY_DENIED", False, "policy", ["Review the target role, access policy, execute flag, and active test session."]
    if isinstance(exc, (ValueError, KeyError, FileNotFoundError)):
        return "CONFIGURATION_ERROR", False, "configuration", ["Fix the selected environment, project, config, or target configuration."]
    if isinstance(exc, TimeoutError):
        return "TOOLCHAIN_TIMEOUT", True, "execution", ["Re-probe the target before retrying a read-only operation."]
    return "INTERNAL_ERROR", False, "handler", ["Inspect the server error log before retrying."]


def check_target_change_rate_limit(lock_keys: list[str], *, now: float | None = None) -> tuple[bool, int]:
    """Bound repeated state-changing requests per target in this MCP process."""
    if not lock_keys:
        return True, 0
    import time

    current = now if now is not None else time.monotonic()
    retry_after = 0
    with _RATE_LIMIT_LOCK:
        for key in lock_keys:
            recent = [item for item in _TARGET_CHANGE_TIMES.get(key, []) if current - item < RATE_LIMIT_WINDOW_SECONDS]
            _TARGET_CHANGE_TIMES[key] = recent
            if len(recent) >= MAX_TARGET_CHANGES_PER_WINDOW:
                retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (current - recent[0])))
                return False, retry_after
        for key in lock_keys:
            _TARGET_CHANGE_TIMES.setdefault(key, []).append(current)
    return True, retry_after


def handle_tools_call(params: dict[str, Any], operation_id: str | None = None) -> dict[str, Any]:
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
    operation_id = operation_id or uuid.uuid4().hex
    if validation_errors:
        payload = {
            "ok": False,
            "tool": name,
            "error": "Tool argument validation failed.",
            "error_code": "CONFIGURATION_ERROR",
            "retryable": False,
            "stage": "validation",
            "target": arguments.get("target") if isinstance(arguments, dict) else None,
            "remediation": ["Fix the reported tool arguments before retrying."],
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
    if TOOL_RISK_LEVELS.get(tool_name) == "target_change":
        allowed, retry_after = check_target_change_rate_limit(lock_keys)
        if not allowed:
            payload = {
                "ok": False,
                "tool": tool_name,
                "error": "Target-change rate limit exceeded.",
                "error_code": "RATE_LIMITED",
                "retryable": True,
                "stage": "policy",
                "target": arguments.get("target"),
                "details": {"lock_keys": lock_keys, "retry_after_seconds": retry_after},
                "remediation": ["Wait for the rate-limit window or review repeated state-changing calls."],
                "attempt_id": operation_id,
            }
            return text_result(payload, is_error=True)
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
    operation_token = set_operation_id(operation_id)
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
            "error_code": "LOCK_CONFLICT",
            "retryable": True,
            "stage": "lock",
            "command": tool_name,
            "details": {"lock_keys": lock_keys},
            "remediation": ["Wait for the active operation to finish; do not bypass the lock."],
            "attempt_id": operation_id,
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
            "error_code": exc.error_code,
            "retryable": exc.retryable,
            "stage": exc.stage,
            "target": exc.target,
            "command": exc.command,
            "details": exc.details,
            "remediation": exc.remediation,
            "attempt_id": exc.attempt_id,
            "exit_code": exc.exit_code,
            "cleanup": exc.cleanup,
        }
        if exc.process_id is not None:
            error_payload["process_id"] = exc.process_id
        if exc.stdout:
            error_payload["stdout_tail"] = exc.stdout[-4000:]
        if exc.stderr:
            error_payload["stderr_tail"] = exc.stderr[-4000:]
    except Exception as exc:
        traceback_path = write_exception_log(operation_id, exc)
        error_code, retryable, stage, remediation = classify_exception(exc)
        error_payload = {
            "ok": False,
            "tool": name,
            "error": str(exc),
            "error_code": error_code,
            "retryable": retryable,
            "stage": stage,
            "attempt_id": operation_id,
            "target": arguments.get("target") or arguments.get("environment"),
            "command": tool_name,
            "details": {},
            "remediation": remediation,
        }
        if traceback_path:
            error_payload["error_log"] = traceback_path
    finally:
        reset_operation_id(operation_token)

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


def handle_request(message: dict[str, Any], operation_id: str | None = None) -> dict[str, Any] | None:
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
        return make_response(request_id, handle_tools_call(params, operation_id=operation_id))

    return make_error(request_id, -32601, f"Method not found: {method}")


def run() -> None:
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mcp-tool")
    active: dict[Any, tuple[Future[dict[str, Any] | None], str]] = {}
    active_lock = threading.RLock()
    output_lock = threading.Lock()

    def write_response(response: dict[str, Any] | None) -> None:
        if response is None:
            return
        with output_lock:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def complete(request_id: Any, future: Future[dict[str, Any] | None]) -> None:
        try:
            write_response(future.result())
        except Exception as exc:
            write_response(make_error(request_id, -32603, f"Internal MCP execution error: {exc}"))
        finally:
            with active_lock:
                active.pop(request_id, None)

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                response = make_error(None, -32700, f"Parse error: {exc}")
            else:
                method = message.get("method")
                request_id = message.get("id")
                if method == "$/cancelRequest":
                    cancelled_id = (message.get("params") or {}).get("requestId")
                    with active_lock:
                        active_item = active.get(cancelled_id)
                    if active_item:
                        future, operation_id = active_item
                        cancel_operation(operation_id)
                        future.cancel()
                    continue
                if method == "tools/call" and request_id is not None:
                    operation_id = uuid.uuid4().hex
                    future = executor.submit(handle_request, message, operation_id)
                    with active_lock:
                        active[request_id] = (future, operation_id)
                    future.add_done_callback(lambda done, rid=request_id: complete(rid, done))
                    continue
                response = handle_request(message)

            write_response(response)
    finally:
        executor.shutdown(wait=True, cancel_futures=False)
        close_runtime_pvi_service()


if __name__ == "__main__":
    run()
