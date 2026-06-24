from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from locks import resolve_scope_context


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = REPO_ROOT / "tools" / ".generated" / "audit"
SENSITIVE_KEY_PARTS = ("password", "secret", "token", "credential")


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
    return {
        "ok": bool(result.get("ok")),
        "summary": result.get("summary"),
        "target": result.get("target"),
        "report_path": report_path,
        "logs": [str(item) for item in (result.get("logs") or [])],
        "warnings": [str(item) for item in (result.get("warnings") or [])],
    }


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
        "schema_version": 1,
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
    }
    day_dir = directory / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{now.strftime('%H%M%S_%f')}_{tool}_{status}_{payload['event_id'][:8]}.json"
    path = day_dir / filename
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return str(path)
