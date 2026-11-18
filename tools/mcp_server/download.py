"""Deadline, process supervision and evidence for one RUC download."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from download_job import DownloadJob, deadline_ticks


REPO_ROOT = Path(__file__).resolve().parents[2]
DOWNLOAD_ROOT = REPO_ROOT / "var" / "downloads"
DOWNLOAD_DEFAULTS = REPO_ROOT / "config" / "defaults" / "base.json"
RECEIVED_AT: ContextVar[float | None] = ContextVar("download_received_at", default=None)
CANCELLED: ContextVar[threading.Event | None] = ContextVar("download_cancelled", default=None)
CLEANUP_RESERVE = 0.5


def download_timeout(project: dict[str, Any], requested: int | None) -> int:
    from br_plc_toolchain.config.loader import load_json_config

    def configured(data: Any, path: str) -> int:
        value = data.get("timeout_seconds") if isinstance(data, dict) else None
        if type(value) is not int or not 1 <= value <= 60:
            raise ValueError(f"{path} download.timeout_seconds must be an integer from 1 to 60.")
        return value

    maximum = configured(load_json_config(DOWNLOAD_DEFAULTS).get("download"), str(DOWNLOAD_DEFAULTS))
    project_maximum = configured(project["download"], "Project") if "download" in project else maximum
    if requested is not None and (type(requested) is not int or requested < 1):
        raise ValueError("Download timeout_seconds must be a positive integer.")
    return min(maximum, project_maximum, requested if requested is not None else maximum)


def read_transfer_log(path: Path) -> tuple[str, str | None]:
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, os.fstat(stream.fileno()).st_size - 65536))
            lines = stream.read(65536).decode("utf-8", errors="replace")
    except FileNotFoundError:
        return "missing", None
    except OSError as exc:
        return "unreadable", str(exc)
    success = re.search(r"(?m)\bTransfer [^\r\n]+ SUCCESSFUL\b", lines)
    failure = re.search(r"(?m)\bTransfer [^\r\n]+ (?:FAILED|ERROR)\b|PROCESS FINISHED \((?:FAILURE|ERROR)\)", lines)
    if success and failure:
        return "conflicting", None
    if success:
        return "success", None
    if failure:
        return "failure", None
    return "incomplete", None


def evidence(operation_id: str, target: str) -> dict[str, Any]:
    directory = DOWNLOAD_ROOT / operation_id
    log_path = directory / f"pvi_download_{target}.log"
    log_state, log_error = read_transfer_log(log_path)
    try:
        safety = json.loads((directory / "safety.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        safety = None
    return {
        "log_path": str(log_path),
        "transfer_log_state": log_state,
        "transfer_log_error": log_error,
        "safety_check": safety,
        "transfer_dispatched": (directory / "transfer-started").is_file(),
    }


def conclude(data: dict[str, Any], facts: dict[str, Any], *, processes_ended: bool) -> dict[str, Any]:
    for key, value in facts.items():
        if data.get(key) is None and value is not None:
            data[key] = value
    log_state = facts["transfer_log_state"]
    dispatched = facts["transfer_dispatched"]
    code = data.get("error_code")
    if not processes_ended or log_state == "conflicting" or (log_state == "failure" and data.get("download_ok") is True):
        state = "unknown"
    elif log_state == "success" or data.get("download_ok") is True:
        state = "transfer_succeeded"
    elif log_state == "failure":
        state = "transfer_failed"
    elif not dispatched and log_state == "missing":
        state = "not_started"
    else:
        state = "unknown"
    data["download_state"] = state
    safety = data.get("safety_check") or {}
    if state == "transfer_succeeded":
        data["download_ok"] = True
        if not (data.get("probe_after") or {}).get("ok"):
            data["deployment_state"] = "transfer_completed"
            if data.get("ok"):
                data["stage"] = "TransferCompleted"
            else:
                data["error_code"] = code or "POST_DOWNLOAD_PROBE_UNCONFIRMED"
                data.setdefault("error", "Transfer succeeded; the post-download probe did not confirm target reachability.")
        data["retryable"] = False
        data["next_action"] = "Confirm target reachability and application readiness; do not download again."
    elif state in {"not_started", "transfer_failed"}:
        if state == "not_started":
            data["executed"] = False
        if not data.get("ok"):
            data["error_code"] = code or "DOWNLOAD_SAFETY_FAILED"
            data["error"] = data.get("error") or "; ".join(safety.get("reasons") or []) or "PVITransfer reported failure. Inspect the transfer log."
        data["retryable"] = not data.get("ok")
        data["next_action"] = "Resolve the reported cause and pass plc_check_download before a bounded retry with a new request_id."
    else:
        data["ok"] = False
        data["download_ok"] = None
        data["deployment_state"] = "unknown"
        data["error_code"] = code if code and code != "TRANSFER_FAILED" else (
            "DOWNLOAD_LOG_UNAVAILABLE" if log_state == "unreadable" else "TRANSFER_STATE_UNKNOWN"
        )
        data["error"] = data.get("error") or "Available evidence does not establish the transfer result."
        data["retryable"] = False
        data["next_action"] = "Stop automatic downloads. Query the same request_id and inspect transfer logs and target state."
    return data


def supervise(args: list[str], target: str, operation_id: str, deadline: float) -> dict[str, Any]:
    stop_at = deadline - CLEANUP_RESERVE
    process = job = None
    stdout = stderr = ""
    data: dict[str, Any] = {}
    ended = True
    cleanup_attempted = False
    cleanup_error = None
    cancelled = CANCELLED.get()
    try:
        if cancelled and cancelled.is_set():
            raise InterruptedError("The client cancelled the download.")
        if time.monotonic() >= stop_at:
            raise subprocess.TimeoutExpired(args, 0)
        job = DownloadJob(operation_id)
        process = subprocess.Popen(
            [*args, "-ManagedDownload"], cwd=REPO_ROOT, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # The script cannot begin any target work before it has entered the job.
        job.attach(process)
        remaining = stop_at - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(args, 0)
        process.stdin.write(f"{deadline_ticks(remaining)}\n")
        process.stdin.close()
        process.stdin = None
        while True:
            if cancelled and cancelled.is_set():
                raise InterruptedError("The client cancelled the download.")
            remaining = stop_at - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args, 0)
            try:
                stdout, stderr = process.communicate(timeout=min(remaining, 0.2))
                break
            except subprocess.TimeoutExpired:
                continue
        data = json.loads(stdout.lstrip("\ufeff"))
        if not isinstance(data, dict):
            raise ValueError("The download wrapper response was not a JSON object.")
    except subprocess.TimeoutExpired:
        data = {"ok": False, "error_code": "DOWNLOAD_TIMEOUT", "error": "The shared download deadline expired."}
    except InterruptedError as exc:
        data = {"ok": False, "error_code": "OPERATION_CANCELLED", "error": str(exc)}
    except OSError as exc:
        data = {"ok": False, "error_code": "DOWNLOAD_PROCESS_ERROR", "error": str(exc)}
    except ValueError as exc:
        data = {"ok": False, "error_code": "DOWNLOAD_WRAPPER_ERROR", "error": str(exc), "stdout_tail": stdout[-2000:]}
    finally:
        if job:
            try:
                if process and process.stdin is not None:
                    process.stdin.close()  # An unassigned wrapper receives EOF and cannot start.
                if job.active():
                    cleanup_attempted = True
                    job.terminate()
                cleanup_until = max(time.monotonic(), deadline - 0.1)
                while job.active() and time.monotonic() < cleanup_until:
                    time.sleep(min(0.02, max(0, cleanup_until - time.monotonic())))
                ended = job.active() == 0
            except OSError as exc:
                ended, cleanup_error = False, str(exc)
            finally:
                job.close()
    data.update({
        "command": "Download", "target": target, "attempt_id": operation_id,
        "process_id": process.pid if process else None,
        "process_exit_code": process.poll() if process else None,
        "processes_ended": ended,
        "cleanup": {"attempted": cleanup_attempted, "succeeded": ended, "error": cleanup_error},
    })
    if stderr:
        data.setdefault("stderr", stderr[-4000:])
    return conclude(data, evidence(operation_id, target), processes_ended=ended)
