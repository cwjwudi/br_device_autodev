"""Persist the caller's download identity and recover evidence without network I/O."""

from __future__ import annotations

from contextlib import closing
from contextvars import ContextVar
from datetime import UTC, datetime
import hashlib
import json
import os
import re
import sqlite3
import time
from typing import Any

import download
from download_job import owner_alive, remaining_processes


REQUEST_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
EXECUTION: ContextVar[tuple[dict[str, Any], list[str], list[str]] | None] = ContextVar("download_scope", default=None)


def valid_request_id(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(REQUEST_ID_PATTERN, value) is not None


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _connect(*, readonly: bool = False):
    path = download.DOWNLOAD_ROOT / "operations.sqlite3"
    if readonly and not path.is_file():
        return None
    if readonly:
        db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=0.1)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=0.1)
    db.row_factory = sqlite3.Row
    return db


def claim(request_id: str, operation_id: str, arguments: dict[str, Any]):
    fingerprint = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode("utf-8")).hexdigest()
    with closing(_connect()) as db, db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, operation_id TEXT UNIQUE NOT NULL,
                accepted_at TEXT NOT NULL, owner_pid INTEGER NOT NULL, lease_until REAL NOT NULL,
                target_key TEXT, protected INTEGER NOT NULL DEFAULT 0, scope TEXT, result TEXT,
                finished_at TEXT
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS downloads_target ON downloads(target_key) WHERE protected = 1")
        inserted = db.execute(
            """INSERT OR IGNORE INTO downloads
               (request_id, fingerprint, operation_id, accepted_at, owner_pid, lease_until)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (request_id, fingerprint, operation_id, timestamp(), os.getpid(), time.time() + 60),
        ).rowcount
        row = db.execute("SELECT * FROM downloads WHERE request_id = ?", (request_id,)).fetchone()
    return inserted == 1, row["fingerprint"] == fingerprint, row


def _may_launch(row) -> bool:
    return row["result"] is None and time.time() < row["lease_until"] and owner_alive(row["owner_pid"]) is not False


def _protected(db, keys: list[str]):
    for key in keys:
        for row in db.execute("SELECT * FROM downloads WHERE target_key = ? AND protected = 1", (key,)):
            if _may_launch(row) or remaining_processes(row["operation_id"]) != 0:
                return row
    return None


def protected(keys: list[str]):
    if not keys:
        return None
    db = _connect(readonly=True)
    if db is None:
        return None
    with closing(db):
        return _protected(db, keys)


class DownloadProtected(RuntimeError):
    def __init__(self, request_id: str):
        super().__init__(f"Previous download {request_id} still protects the target.")
        self.request_id = request_id


def bind(operation_id: str, timeout: int, deadline: float) -> None:
    execution = EXECUTION.get()
    if execution is None:
        return
    context, keys, audit = execution
    scope = {
        key: context.get(key) for key in ("target", "target_ip", "target_role", "project_path", "config")
    }
    scope.update({"effective_timeout_seconds": timeout, "audit": audit})
    target_key = next(key for key in keys if key.startswith("target:"))
    with closing(_connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        holder = _protected(db, [target_key])
        if holder is not None:
            raise DownloadProtected(holder["request_id"])
        updated = db.execute(
            "UPDATE downloads SET target_key = ?, protected = 1, scope = ?, lease_until = ? WHERE operation_id = ?",
            (target_key, json.dumps(scope), time.time() + max(0, deadline - time.monotonic()), operation_id),
        ).rowcount
        if updated != 1:
            raise RuntimeError("The download identity was not persisted; no process was started.")


def _fields(value, *keys):
    return {key: value[key] for key in keys if isinstance(value, dict) and key in value}


def _probe(value):
    return _fields(value, "ok", "ip", "cpu_type", "ar_version", "plc_status", "log_path", "error", "error_code")


def _safety(value):
    return {
        **_fields(value, "ok", "decision", "reasons", "error_codes", "safety_bypassed", "target_ip"),
        "package": _fields((value or {}).get("package"), "package_path", "configuration_id", "config_version"),
        "probe": _probe((value or {}).get("probe")),
    } if isinstance(value, dict) else None


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", {})
    return {
        **_fields(payload, "ok", "tool", "command", "target", "error", "error_code", "retryable", "stage",
                  "attempt_id", "summary", "remediation", "next_actions", "audit", "audit_error",
                  "logs", "blocking_request_id", "validation_errors"),
        "data": {
            **_fields(data, "download_state", "download_ok", "stage", "effective_timeout_seconds",
                      "transfer_log_state", "transfer_log_error", "transfer_dispatched", "error", "error_code",
                      "deployment_state", "executed", "process_id", "process_exit_code", "processes_ended",
                      "cleanup", "log_path", "pil_path", "next_action"),
            "safety_check": _safety(data.get("safety_check")),
            "probe_after": _probe(data.get("probe_after")),
            "application_readiness": _fields(data.get("application_readiness"), "ok", "error_code"),
        },
    }


def finish(operation_id: str, payload: dict[str, Any]) -> None:
    result = _compact(payload)
    with closing(_connect()) as db, db:
        row = db.execute("SELECT * FROM downloads WHERE operation_id = ?", (operation_id,)).fetchone()
        data = result["data"]
        if not data.get("download_state"):
            data["download_state"] = "unknown" if row["scope"] else "not_started"
        if not row["scope"]:
            data.update({"executed": False, "processes_ended": True})
        db.execute(
            "UPDATE downloads SET result = ?, protected = ?, finished_at = ? WHERE operation_id = ?",
            (json.dumps(result), bool(row["scope"] and data.get("processes_ended") is not True), timestamp(), operation_id),
        )


def find(request_id: str):
    db = _connect(readonly=True)
    if db is None:
        return None
    with closing(db):
        return db.execute("SELECT * FROM downloads WHERE request_id = ?", (request_id,)).fetchone()


def status(request_id: str, row) -> dict[str, Any]:
    if row is None:
        return {
            "ok": False, "request_id": request_id, "download_state": "unknown", "stage": "lookup",
            "error_code": "DOWNLOAD_RESULT_NOT_FOUND", "error": "No download record was found. Transfer cannot be ruled out.",
            "next_action": "Check the original client, audit and transfer evidence before any new download.",
        }
    scope = json.loads(row["scope"]) if row["scope"] else {}
    result = json.loads(row["result"]) if row["result"] else None
    operation_id = row["operation_id"]
    facts = download.evidence(operation_id, scope["target"]) if scope else None
    running = _may_launch(row)
    remaining = remaining_processes(operation_id) if row["protected"] else 0
    if running:
        state = "in_progress"
        phase = "queued" if not facts else (
            "post_download" if facts["transfer_log_state"] == "success" else
            "transfer" if facts["transfer_dispatched"] else "safety_check"
        )
        action = "Query this request_id again after the download finishes."
    elif remaining != 0:
        state = "unknown"
        phase = "cleanup"
        action = "Wait for confirmed process exit and query this request_id again. Stop automatic downloads."
    elif result and result["data"]["download_state"] != "unknown" and (facts or {}).get("transfer_log_state") != "conflicting":
        state = result["data"]["download_state"]
        phase = "complete"
        action = result["data"].get("next_action") or next(iter(result.get("next_actions", [])), None) or (
            "Resolve the reported cause and pass plc_check_download before retrying with a new request_id."
        )
    else:
        phase = "recovered"
        data = result["data"].copy() if result else {}
        safety = (facts or {}).get("safety_check") or {}
        if facts and (facts["transfer_dispatched"] or facts["transfer_log_state"] != "missing" or safety.get("ok") is False):
            download.conclude(data, facts, processes_ended=True)
            data["safety_check"] = _safety(data.get("safety_check"))
        state = data.get("download_state", "unknown")
        if state == "unknown":
            data.setdefault("error_code", "TRANSFER_STATE_UNKNOWN")
            data.setdefault("error", "Persisted evidence does not establish the transfer result.")
        action = data.get("next_action") or "Inspect the operation log and probe the target before any new download."
        result = {
            **(result or {}),
            "data": {**data, "download_state": state, "processes_ended": True},
        }
    return {
        "ok": True, "request_id": request_id, "operation_id": operation_id,
        "accepted_at": row["accepted_at"], "finished_at": row["finished_at"], **scope,
        "download_state": state, "stage": phase, "remaining_processes": remaining,
        "target_protected": running or remaining != 0,
        "next_action": action, "result": result,
        "transfer_evidence": _fields(facts, "log_path", "transfer_log_state", "transfer_log_error", "transfer_dispatched"),
        "audit": (result or {}).get("audit") or scope.get("audit", []),
        "evidence_scope": "Audit records server activity. Transfer logs describe transfer only. Check target probe and application readiness separately.",
    }


def plc_get_download_result(arguments: dict[str, Any]) -> dict[str, Any]:
    request_id = arguments["request_id"]
    try:
        return status(request_id, find(request_id))
    except (OSError, sqlite3.Error) as exc:
        return {
            "ok": False, "request_id": request_id, "download_state": "unknown",
            "error_code": "DOWNLOAD_RECORD_UNAVAILABLE", "error": str(exc),
            "next_action": "Retry this lookup. Stop automatic downloads while the result is unknown.",
        }
