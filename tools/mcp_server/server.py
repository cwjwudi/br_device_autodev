from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import traceback
import uuid
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audit import AUDIT_DIR as DEFAULT_AUDIT_DIR, write_audit_event
import download
import download_recovery
from locks import (
    CRITICAL_TOOLS,
    LOCK_DIR as DEFAULT_LOCK_DIR,
    LockConflict,
    acquire_locks,
    lock_keys_for_tool,
    resolve_scope_context,
)
from schemas import EXPLICIT_TARGET_RISK_LEVELS, TOOL_DEFINITIONS, TOOL_RISK_LEVELS
from toolchain import (
    TOOLS,
    ToolchainError,
    cancel_operation,
    close_catalog_watcher,
    close_runtime_pvi_service,
    reset_operation_id,
    set_operation_id,
    start_catalog_watcher,
)
from validation import validate_json_schema
from version import SERVER_RUNTIME, __version__
from tool_visibility import load_disabled_tools, visible_definitions


SERVER_INFO = {"name": "br-plc-toolchain", "version": __version__, **SERVER_RUNTIME}
PROTOCOL_VERSION = "2024-11-05"
TOOL_DEFINITIONS_BY_NAME = {definition["name"]: definition for definition in TOOL_DEFINITIONS}
DISABLED_TOOLS = load_disabled_tools()
AUDIT_DIR = DEFAULT_AUDIT_DIR
LOCK_DIR = DEFAULT_LOCK_DIR
ERROR_LOG = Path(__file__).resolve().parents[2] / "var" / "reports" / "mcp_server_errors.log"
STDIO_LOG = ERROR_LOG.with_name("download_stdio.jsonl")
RATE_LIMIT_WINDOW_SECONDS = 60.0
MAX_TARGET_CHANGES_PER_WINDOW = 10
MAX_CONCURRENT_DOWNLOADS = 8
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
    if message.startswith("CONFIRMATION_REQUIRED"):
        return "CONFIRMATION_REQUIRED", False, "policy", ["Pass execute=true to confirm the state-changing action."]
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


def handle_tools_call(params: dict[str, Any], operation_id: str | None = None, *, download_busy: bool = False) -> dict[str, Any]:
    arguments = params.get("arguments")
    if params.get("name") != "plc_download_ruc" or not isinstance(arguments, dict):
        return _handle_tools_call(params, operation_id)
    operation_id = operation_id or uuid.uuid4().hex
    request_id = arguments.get("request_id", operation_id)
    if not download_recovery.valid_request_id(request_id):
        return _handle_tools_call(params, operation_id)

    def journal_error(code: str, message: str) -> dict[str, Any]:
        return text_result({
            "ok": False, "tool": "plc_download_ruc", "request_id": request_id,
            "attempt_id": operation_id, "error_code": code, "error": message,
            "stage": "recovery", "retryable": False,
            "next_actions": ["Query plc_get_download_result with the same request_id before any new download."],
        }, is_error=True)

    try:
        inserted, matches, row = download_recovery.claim(request_id, operation_id, arguments)
    except (OSError, sqlite3.Error) as exc:
        return journal_error("DOWNLOAD_RECORD_UNAVAILABLE", f"The download request could not be recorded: {exc}")
    if not matches:
        return journal_error("DOWNLOAD_REQUEST_ID_CONFLICT", "This request_id is already bound to different arguments.")
    if not inserted:
        try:
            recovered = download_recovery.status(request_id, row)
        except (OSError, sqlite3.Error) as exc:
            return journal_error("DOWNLOAD_RECORD_UNAVAILABLE", str(exc))
        result = recovered.get("result") or {}
        return text_result({
            **result, "ok": bool(result.get("ok")) and recovered["download_state"] in {"transfer_succeeded", "not_started"},
            "request_id": request_id, "attempt_id": recovered["operation_id"],
            "replayed": True, "recovery": recovered,
            "next_actions": [recovered["next_action"]],
        })

    if download_busy:
        response = text_result({
            "ok": False, "tool": "plc_download_ruc", "stage": "admission", "retryable": True,
            "error_code": "DOWNLOAD_SERVER_BUSY", "error": "All download workers are in use. No transfer was started.",
        }, is_error=True)
    else:
        response = _handle_tools_call({**params, "arguments": {**arguments, "request_id": request_id}}, operation_id)
    payload = response["structuredContent"]
    payload.update({"request_id": request_id, "attempt_id": operation_id})
    data = payload.get("data") or {}
    try:
        if not data.get("download_state"):
            row = download_recovery.find(request_id)
            bound = bool(row and row["scope"])
            payload["download_state"] = "unknown" if bound else "not_started"
            if not bound and payload.get("error_code") != "DOWNLOAD_TARGET_PROTECTED":
                payload["next_actions"] = ["Resolve the reported cause and pass plc_check_download before a bounded retry with a new request_id."]
        download_recovery.finish(operation_id, payload)
    except (OSError, sqlite3.Error) as exc:
        payload["recovery_error"] = str(exc)
    return text_result(payload, is_error=response["isError"])


def _handle_tools_call(params: dict[str, Any], operation_id: str | None = None) -> dict[str, Any]:
    name = params.get("name")
    if str(name) in DISABLED_TOOLS:
        return text_result(
            {
                "ok": False,
                "tool": name,
                "error": f"Tool is disabled by config/mcp/tool_filter.json: {name}",
                "error_code": "TOOL_DISABLED",
                "retryable": False,
                "stage": "validation",
                "remediation": [
                    "Use an enabled alternative listed in README.md, or re-enable the tool in config/mcp/tool_filter.json."
                ],
            },
            is_error=True,
        )
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
    skip_explicit_target = (
        str(name) == "plc_manage_arsim"
        and isinstance(arguments, dict)
        and (
            str(arguments.get("action") or "").lower() in {"list", "clean"}
            or bool(str(arguments.get("run_id") or "").strip())
        )
    )
    if risk_level in EXPLICIT_TARGET_RISK_LEVELS and not has_explicit_target and not skip_explicit_target:
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
    try:
        lock_keys = lock_keys_for_tool(tool_name, arguments)
        if tool_name in {"plc_init_project_config", "plc_manage_arsim"}:
            try:
                context = resolve_scope_context(arguments)
            except (ValueError, OSError):
                context = {"target": arguments.get("target"), "project_path": arguments.get("project_path")}
        else:
            context = resolve_scope_context(arguments)
    except (ValueError, OSError) as exc:
        return text_result({"ok": False, "tool": tool_name, "error": str(exc),
                            "error_code": "CONFIGURATION_ERROR", "stage": "configuration"}, is_error=True)
    is_readonly_manage = tool_name == "plc_manage_arsim" and str(arguments.get("action") or "").lower() == "list"
    if TOOL_RISK_LEVELS.get(tool_name) == "target_change" and not is_readonly_manage:
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
    execution_token = download_recovery.EXECUTION.set(
        (context, lock_keys, audit_paths) if tool_name == "plc_download_ruc" else None
    )
    try:
        with acquire_locks(
            lock_keys,
            directory=LOCK_DIR,
            metadata={
                "tool": tool_name, "operation_id": operation_id,
                **({"managed_download": True, "request_id": arguments["request_id"]} if tool_name == "plc_download_ruc" else {}),
            },
        ):
            holder = download_recovery.protected([key for key in lock_keys if key.startswith("target:")])
            if holder is not None:
                raise download_recovery.DownloadProtected(holder["request_id"])
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
    except download_recovery.DownloadProtected as exc:
        final_status = "blocked"
        error_payload = {
            "ok": False, "tool": name, "error": str(exc), "error_code": "DOWNLOAD_TARGET_PROTECTED",
            "stage": "lock", "retryable": False, "blocking_request_id": exc.request_id,
            "next_actions": ["Query plc_get_download_result with blocking_request_id and wait for process exit."],
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
        download_recovery.EXECUTION.reset(execution_token)
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


def handle_request(message: dict[str, Any], operation_id: str | None = None,
                   received_at: float | None = None, cancelled: threading.Event | None = None,
                   download_busy: bool = False) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if request_id is None:
        return None

    if method == "initialize":
        return make_response(request_id, handle_initialize(params))
    if method == "tools/list":
        return make_response(request_id, {"tools": visible_definitions(DISABLED_TOOLS)})
    if method == "tools/call":
        time_token = download.RECEIVED_AT.set(received_at)
        cancel_token = download.CANCELLED.set(cancelled)
        try:
            return make_response(request_id, handle_tools_call(params, operation_id=operation_id, download_busy=download_busy))
        finally:
            download.CANCELLED.reset(cancel_token)
            download.RECEIVED_AT.reset(time_token)

    return make_error(request_id, -32601, f"Method not found: {method}")


def run() -> None:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    start_catalog_watcher()
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mcp-tool")
    downloads = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS, thread_name_prefix="mcp-download")
    download_slots = threading.BoundedSemaphore(MAX_CONCURRENT_DOWNLOADS)
    active: dict[Any, tuple[Future[dict[str, Any] | None], str, threading.Event | None]] = {}
    active_lock = threading.RLock()
    output_lock = threading.Lock()

    def trace(stage: str, request_id: Any, operation_id: str, **fields: Any) -> None:
        try:
            STDIO_LOG.parent.mkdir(parents=True, exist_ok=True)
            with STDIO_LOG.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "stage": stage, "request_id": request_id, "operation_id": operation_id,
                    "timestamp": datetime.now(UTC).isoformat(), "server_pid": os.getpid(), **fields,
                }) + "\n")
        except OSError:
            pass

    def write_response(response: dict[str, Any] | None, operation_id: str | None = None) -> None:
        if response is None:
            return
        request_id = response.get("id")
        line = json.dumps(response, ensure_ascii=False) + "\n"
        if operation_id:
            trace("response_serialized", request_id, operation_id, bytes=len(line.encode("utf-8")))
        with output_lock:
            sys.stdout.write(line)
            if operation_id:
                trace("stdout_written", request_id, operation_id)
            sys.stdout.flush()
        if operation_id:
            trace("stdout_flushed", request_id, operation_id)

    def complete(request_id: Any, future: Future[dict[str, Any] | None],
                 operation_id: str | None, download_slot: bool) -> None:
        try:
            write_response(future.result(), operation_id)
        except OSError as exc:
            if operation_id:
                trace("stdout_failed", request_id, operation_id, error=str(exc))
        except Exception as exc:
            write_response(make_error(request_id, -32603, f"Internal MCP execution error: {exc}"), operation_id)
        finally:
            with active_lock:
                active.pop(request_id, None)
            if download_slot:
                download_slots.release()

    try:
        for line in sys.stdin:
            received_at = time.monotonic()
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
                if method in {"$/cancelRequest", "notifications/cancelled"}:
                    cancelled_id = (message.get("params") or {}).get("requestId")
                    with active_lock:
                        active_item = active.get(cancelled_id)
                    if active_item:
                        future, operation_id, cancelled = active_item
                        if cancelled is not None:
                            cancelled.set()
                        else:
                            cancel_operation(operation_id)
                            future.cancel()
                    continue
                if method == "tools/call" and request_id is not None:
                    operation_id = uuid.uuid4().hex
                    tool_name = (message.get("params") or {}).get("name")
                    cancelled = threading.Event() if tool_name == "plc_download_ruc" else None
                    traced = operation_id if tool_name in {"plc_download_ruc", "plc_get_download_result"} else None
                    if traced:
                        arguments = (message.get("params") or {}).get("arguments")
                        client_request_id = arguments.get("request_id") if isinstance(arguments, dict) else None
                        trace("request_received", request_id, traced,
                              client_request_id=client_request_id if download_recovery.valid_request_id(client_request_id) else None)
                    if tool_name == "plc_get_download_result":
                        write_response(handle_request(message, operation_id, received_at), operation_id)
                        continue
                    is_download = cancelled is not None
                    if is_download and not download_slots.acquire(blocking=False):
                        write_response(handle_request(message, operation_id, received_at, download_busy=True), operation_id)
                        continue
                    worker_pool = downloads if is_download else executor
                    future = worker_pool.submit(handle_request, message, operation_id, received_at, cancelled)
                    with active_lock:
                        active[request_id] = (future, operation_id, cancelled)
                    future.add_done_callback(lambda done, rid=request_id, oid=traced, slot=is_download: complete(rid, done, oid, slot))
                    continue
                response = handle_request(message)

            write_response(response)
    finally:
        downloads.shutdown(wait=True, cancel_futures=False)
        executor.shutdown(wait=True, cancel_futures=False)
        close_catalog_watcher()
        close_runtime_pvi_service()


if __name__ == "__main__":
    run()
