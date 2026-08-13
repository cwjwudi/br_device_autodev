from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from locks import resolve_scope_context
from version import SERVER_RUNTIME


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = REPO_ROOT / "var" / "audit"
SENSITIVE_KEY_PARTS = ("password", "secret", "token", "credential")
AUDIT_RETENTION_DAYS = 30
AUDIT_MAX_BYTES = 100 * 1024 * 1024
TRUSTED_PVI_ROLES = {"arsim", "dedicated_test_plc"}
PVI_ACCESS_TOOLS = {
    "plc_read_pvi",
    "plc_read_pvi_batch",
    "plc_write_pvi",
    "plc_discover_runtime_target",
    "plc_list_runtime_tasks",
    "plc_list_runtime_variables",
    "plc_get_runtime_variable_info",
    "plc_read_runtime_variable",
    "plc_write_runtime_variable",
    "plc_start_pvi_trace",
    "plc_get_pvi_trace_status",
    "plc_read_pvi_trace",
    "plc_stop_pvi_trace",
    "plc_run_io_test_case",
    "plc_run_test_suite",
    "plc_reset_test_harness",
}


def _safe_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(part in lowered for part in SENSITIVE_KEY_PARTS):
        return "<redacted>"
    if key == "writes" and isinstance(value, list):
        variables = [
            str(item.get("variable"))
            for item in value
            if isinstance(item, dict) and item.get("variable")
        ]
        return {"count": len(value), "variables": variables}
    if key == "value":
        return "<redacted>"
    if isinstance(value, dict):
        return {str(name): _safe_value(str(name), item) for name, item in value.items()}
    if isinstance(value, list):
        return [_safe_value(key, item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def summarize_request(arguments: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _safe_value(str(key), value) for key, value in arguments.items()}


def summarize_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    report_path = data.get("report_path") or result.get("report_path")
    summary = {
        "ok": bool(result.get("ok")),
        "summary": result.get("summary"),
        "target": result.get("target"),
        "report_path": report_path,
        "logs": [str(item) for item in (result.get("logs") or [])],
        "warnings": [str(item) for item in (result.get("warnings") or [])],
    }
    writes = data.get("writes") or result.get("writes")
    if isinstance(writes, list):
        summary["writes"] = [
            {
                "variable": item.get("variable") or item.get("name"),
                "ok": bool(item.get("ok")),
                "before": item.get("before"),
                "requested": item.get("requested_value", item.get("requested")),
                "readback": item.get("readback"),
                "warning": item.get("warning"),
                "error": item.get("error"),
            }
            for item in writes
            if isinstance(item, dict)
        ]
    for name in ("download_ok", "safety_bypassed", "deployment_state", "stage"):
        value = data.get(name, result.get(name))
        if value is not None:
            summary[name] = value
    return summary


def pvi_access_mode(tool: str, target_role: Any) -> str | None:
    if tool not in PVI_ACCESS_TOOLS:
        return None
    role = str(target_role or "unknown").lower()
    if role in TRUSTED_PVI_ROLES:
        return "trusted_role_unrestricted"
    if role == "production":
        return "production_conservative"
    return "restricted_or_unknown_role"


def prune_audit(directory: Path = AUDIT_DIR) -> None:
    """Keep generated audit state bounded without touching non-audit files."""
    if not directory.exists():
        return
    now = datetime.now(timezone.utc).timestamp()
    files = [path for path in directory.glob("*/*.json") if path.is_file()]
    total_bytes = sum(path.stat().st_size for path in files)
    cutoff = now - AUDIT_RETENTION_DAYS * 86400
    for path in sorted(files, key=lambda item: item.stat().st_mtime):
        remove = path.stat().st_mtime < cutoff or total_bytes > AUDIT_MAX_BYTES
        if not remove:
            continue
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        total_bytes = max(0, total_bytes - size)
    for day_dir in directory.iterdir():
        if day_dir.is_dir() and not any(day_dir.iterdir()):
            day_dir.rmdir()


def write_audit_event(
    *,
    tool: str,
    status: str,
    arguments: dict[str, Any],
    operation_id: str,
    lock_keys: list[str],
    result: dict[str, Any] | None = None,
    error: str | None = None,
    directory: Path = AUDIT_DIR,
) -> str:
    now = datetime.now(timezone.utc)
    context = resolve_scope_context(arguments)
    payload = {
        "schema_version": 2,
        "event_id": uuid.uuid4().hex,
        "operation_id": operation_id,
        "timestamp": now.isoformat(),
        "tool": tool,
        "status": status,
        "target": context["target"],
        "target_role": context["target_role"],
        "environment": context["environment"],
        "project_path": context["project_path"],
        "config": context["config"],
        "targets_path": context["targets_path"],
        "lock_keys": lock_keys,
        "request_summary": summarize_request(arguments),
        "result_summary": summarize_result(result),
        "error": error,
        "process_id": os.getpid(),
        "server_runtime": dict(SERVER_RUNTIME),
    }
    access_mode = pvi_access_mode(tool, context["target_role"])
    if access_mode is not None:
        payload["pvi_access_mode"] = access_mode
    day_dir = directory / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{now.strftime('%H%M%S_%f')}_{tool}_{status}_{payload['event_id'][:8]}.json"
    path = day_dir / filename
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    prune_audit(directory)
    return str(path)
