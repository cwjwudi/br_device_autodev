#!/usr/bin/env python
"""Read B&R PLC/AR logger modules directly through PVITransfer Logger."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "var" / "logger"
ALLOWED_FORMATS = {".html", ".csvx", ".arl", ".logpkg"}
DEFAULT_FORMAT = ".csvx"
DEFAULT_DIAGNOSTIC_MODULES: list[tuple[str, str]] = [
    ("System", "$arlogsys"),
    ("User", "$arlogusr"),
    ("Motion", "$motion"),
    ("Fieldbus", "$fieldbus"),
]
SEVERITY_RANKS: dict[str, int] = {
    "info": 1,
    "information": 1,
    "success": 1,
    "notice": 1,
    "0": 1,
    "1": 1,
    "warning": 2,
    "warn": 2,
    "2": 2,
    "error": 3,
    "fatal": 3,
    "critical": 3,
    "3": 3,
}
SUCCESS_MARKER_RE = re.compile(r"PROCESS FINISHED \(SUCCESS\)|Transfer .* SUCCESSFUL", re.IGNORECASE)
FAILURE_MARKER_RE = re.compile(r"PROCESS FINISHED \((?:FAILURE|ERROR)\)|Transfer .* (?:FAILED|ERROR)", re.IGNORECASE)


def load_json_file(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:21]


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.replace("$", ""))
    return cleaned.strip("._") or "logger"


def normalize_format(value: str | None, default_format: str = DEFAULT_FORMAT) -> str:
    fmt = (value or default_format or DEFAULT_FORMAT).strip().lower()
    if fmt and not fmt.startswith("."):
        fmt = "." + fmt
    if fmt not in ALLOWED_FORMATS:
        raise ValueError(f"Unsupported logger output format '{fmt}'. Allowed formats: {sorted(ALLOWED_FORMATS)}.")
    return fmt


def resolve_output_path(
    output_path: str | None,
    target: str,
    logger_type: str,
    logger_name: str,
    fmt: str,
    *,
    repo_root: Path = REPO_ROOT,
    default_output_dir: Path | None = None,
) -> Path:
    stem = "_".join(
        [
            utc_stamp(),
            safe_filename_part(target),
            safe_filename_part(logger_type),
            safe_filename_part(logger_name),
        ]
    )
    base_dir = default_output_dir or (repo_root / "var" / "logger")

    if output_path:
        candidate = Path(output_path)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        candidate = candidate.resolve()
        if candidate.suffix:
            if candidate.suffix.lower() != fmt:
                raise ValueError(f"OutputPath suffix '{candidate.suffix}' does not match requested format '{fmt}'.")
            resolved = candidate
        else:
            resolved = candidate / f"{stem}{fmt}"
    else:
        resolved = (base_dir / f"{stem}{fmt}").resolve()

    if not is_relative_to(resolved, repo_root.resolve()):
        raise ValueError(f"Output path must stay inside the repository: {resolved}")
    return resolved


def is_logger_enabled(config: dict[str, Any]) -> bool:
    """Return True when project configuration explicitly permits logger download."""
    allow_logger = config.get("allow_logger")
    logger_config = config.get("logger")
    enabled = logger_config.get("enabled") if isinstance(logger_config, dict) else None
    if allow_logger is False or enabled is False:
        return False
    return allow_logger is True or enabled is True


def _lookup_target(config: dict[str, Any], target: str) -> dict[str, Any] | None:
    targets = config.get("targets") or {}
    if not isinstance(targets, dict):
        return None
    found = targets.get(target)
    if isinstance(found, dict):
        return found
    lowered = target.casefold()
    for name, item in targets.items():
        if isinstance(name, str) and name.casefold() == lowered and isinstance(item, dict):
            return item
    return None


def validate_request(
    *,
    config: dict[str, Any] | None,
    target: str,
    logger_type: str,
    logger_name: str,
    fmt: str,
    target_ip: str | None = None,
    target_role: str | None = None,
    require_config_opt_in: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    target_config: dict[str, Any] = {}

    if config is not None:
        found = _lookup_target(config, target)
        if not found:
            if target_ip:
                target_config = {"ip": target_ip, "role": target_role or "unregistered"}
            else:
                return {}, [f"Target '{target}' was not found in targets configuration."]
        else:
            target_config = dict(found)
        if require_config_opt_in and not is_logger_enabled(config):
            errors.append(
                "Logger download is not enabled in project configuration. "
                "Set logger.enabled = true (or allow_logger = true) to allow downloading logger modules."
            )
    else:
        if not target_ip:
            return {}, [f"Target '{target}' could not be resolved; provide project_path, targets_path, or ip."]
        target_config = {"ip": target_ip, "role": target_role or "unregistered"}

    if "safety" in logger_type.strip().lower() or "safety" in logger_name.strip().lower():
        errors.append(f"Logger module '{logger_type} / {logger_name}' is blocked by immutable safety policy.")

    for label, value in (
        ("target_ip", str(target_config.get("ip") or "")),
        ("logger_type", logger_type),
        ("logger_name", logger_name),
    ):
        if not value or any(ch in value for ch in ('"', "\r", "\n")):
            errors.append(f"Invalid {label} value for PVITransfer PIL generation.")

    if fmt not in ALLOWED_FORMATS:
        errors.append(f"Logger format '{fmt}' is not allowed.")

    return target_config, errors


def write_logger_pil(pil_path: Path, ip: str, logger_type: str, logger_name: str, fmt: str, output_path: Path) -> None:
    lines = [
        f'Connection "/IF=tcpip", "/IP={ip} /COMT=2500 /AM=* /PT=11169", "WT=30"',
        f'Logger "{logger_type}", "{logger_name}", "{fmt}", "{output_path}", "en"',
    ]
    pil_path.parent.mkdir(parents=True, exist_ok=True)
    with pil_path.open("w", encoding="ascii", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")


def _terminate_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def _read_log_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    for _ in range(5):
        try:
            raw = path.read_bytes()
            text = raw.decode("mbcs", errors="replace") if os.name == "nt" else raw.decode("utf-8", errors="replace")
            return text.splitlines()
        except OSError:
            time.sleep(0.05)
    return []


def execute_pvitransfer_silent(
    *,
    pvi_transfer_path: Path,
    pil_path: Path,
    log_path: Path,
    timeout_seconds: int = 120,
    grace_seconds: float = 2.0,
) -> tuple[int | None, list[str], bool]:
    """Run PVITransfer.exe directly in silent mode without intermediate PowerShell hops."""
    log_path.unlink(missing_ok=True)
    args = [str(pvi_transfer_path), "-silent", f"-{pil_path}", f"-{log_path}"]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        args,
        cwd=pil_path.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    start = time.monotonic()
    deadline = start + max(1, timeout_seconds)
    # Wait for normal process exit before inspecting log_path to avoid file-lock contention with PVITransfer.
    normal_wait = min(10.0, max(1.0, timeout_seconds * 0.5))
    try:
        returncode = process.wait(timeout=normal_wait)
        return returncode, _read_log_lines(log_path), False
    except subprocess.TimeoutExpired:
        pass

    success_seen_at: float | None = None
    completion: str | None = None
    timed_out = False

    while process.poll() is None:
        lines = _read_log_lines(log_path)
        if lines:
            log_text = "\n".join(lines)
            if SUCCESS_MARKER_RE.search(log_text):
                if success_seen_at is None:
                    success_seen_at = time.monotonic()
                completion = "success"
            elif FAILURE_MARKER_RE.search(log_text):
                completion = "failure"

        now = time.monotonic()
        if completion == "failure":
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process.pid)
            break
        if completion == "success" and success_seen_at is not None and (now - success_seen_at) >= grace_seconds:
            _terminate_process_tree(process.pid)
            break
        if now >= deadline:
            timed_out = True
            _terminate_process_tree(process.pid)
            break
        time.sleep(min(0.5, max(0.01, deadline - now)))

    try:
        returncode = process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process.pid)
        returncode = process.poll()

    final_lines = _read_log_lines(log_path)
    return returncode, final_lines, timed_out


def summarize_lines(lines: list[str]) -> str | None:
    interesting = [
        line.strip()
        for line in lines
        if re.search(r"\b(error|failed|not found|timeout|refus|denied|aborted)\b", line, re.IGNORECASE)
    ]
    if interesting:
        return " | ".join(interesting[-5:])
    tail = [line.strip() for line in lines[-5:] if line.strip()]
    return " | ".join(tail) if tail else None


def _split_csvx_row(line: str, delimiter: str = ";") -> list[str]:
    """Split a B&R .csvx row, preserving inner unescaped quotes inside quoted fields."""
    fields: list[str] = []
    n = len(line)
    i = 0
    while i <= n:
        if i == n:
            if line.endswith(delimiter):
                fields.append("")
            break
        if line[i] == '"':
            end = i + 1
            while end < n:
                if line[end] == '"' and (end + 1 == n or line[end + 1] == delimiter):
                    break
                end += 1
            if end < n:
                fields.append(line[i + 1 : end])
                i = end + 1
                if i < n and line[i] == delimiter:
                    i += 1
                    if i == n:
                        fields.append("")
                        break
            else:
                fields.append(line[i + 1 :])
                break
        else:
            sep = line.find(delimiter, i)
            if sep == -1:
                fields.append(line[i:])
                break
            fields.append(line[i:sep])
            i = sep + 1
            if i == n:
                fields.append("")
                break
    return fields


def _parse_csvx_rows(text: str) -> list[dict[str, Any]]:
    stripped = text.lstrip()
    if not stripped:
        return []
    if stripped.startswith("<"):
        root = ET.fromstring(text)
        xml_rows: list[dict[str, Any]] = []
        for element in root.iter():
            if len(element) == 0 and element.attrib:
                xml_rows.append(dict(element.attrib))
            elif len(element) > 0:
                values = {child.tag.split("}", 1)[-1]: (child.text or "") for child in element}
                if values:
                    xml_rows.append(values)
        return xml_rows

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    header_idx = 0
    # B&R PVITransfer .csvx starts with a metadata line like: Origin="..." formatVersion="1" ...
    if lines[0].lstrip().startswith("Origin=") and len(lines) > 1:
        for idx in range(1, min(len(lines), 6)):
            if ";" in lines[idx] or "," in lines[idx]:
                header_idx = idx
                break

    header_line = lines[header_idx]
    if ";" in header_line:
        headers = _split_csvx_row(header_line, ";")
        rows: list[dict[str, Any]] = []
        for line in lines[header_idx + 1 :]:
            values = _split_csvx_row(line, ";")
            row = {
                headers[idx]: (values[idx] if idx < len(values) else "")
                for idx in range(len(headers))
                if headers[idx]
            }
            if row:
                rows.append(row)
        return rows

    sample = "\n".join(lines[header_idx : header_idx + 10])[:4096]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    reader = csv.DictReader(lines[header_idx:], dialect=dialect)
    return [dict(row) for row in reader]


def parse_csvx_summary(
    path: Path,
    limit: int = 20,
    *,
    severity: str | None = None,
    order: str = "newest",
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = _parse_csvx_rows(text)

    severity_counts: Counter[str] = Counter()
    latest_timestamp: str | None = None
    parsed_entries: list[dict[str, Any]] = []

    time_keys = ("Time", "Timestamp", "DateTime", "Date/Time", "time", "timestamp")
    severity_keys = ("Severity", "Level", "Type", "ErrorLevel", "severity", "level")
    message_keys = ("ASCII Data", "Message", "Text", "Description", "Event", "message", "text")
    record_id_keys = ("RecordID", "RecordId", "record_id")
    code_keys = ("ID", "Code", "ErrorCode", "code", "id")
    origin_keys = ("Entered by", "Origin", "TaskName", "entered_by", "origin")

    severity_filters = (
        {item.strip().lower() for item in severity.split(",") if item.strip()}
        if severity
        else set()
    )

    for row in rows:
        sev = next((str(row.get(key)) for key in severity_keys if row.get(key)), "unknown")
        timestamp = next((str(row.get(key)) for key in time_keys if row.get(key)), None)
        message = next((str(row.get(key)) for key in message_keys if row.get(key)), None)
        record_id = next((str(row.get(key)) for key in record_id_keys if row.get(key)), None)
        code = next((str(row.get(key)) for key in code_keys if row.get(key)), None)
        entered_by = next((str(row.get(key)) for key in origin_keys if row.get(key)), None)

        severity_counts[sev] += 1
        if timestamp and (latest_timestamp is None or timestamp > latest_timestamp):
            latest_timestamp = timestamp

        if severity_filters and sev.lower() not in severity_filters:
            continue

        entry: dict[str, Any] = {
            "timestamp": timestamp,
            "severity": sev,
            "message": message,
        }
        if record_id is not None:
            entry["record_id"] = record_id
        if code is not None:
            entry["code"] = code
        if entered_by is not None:
            entry["entered_by"] = entered_by
        parsed_entries.append(entry)

    bounded_limit = max(1, int(limit))
    if order == "oldest":
        selected_entries = parsed_entries[:bounded_limit]
    else:
        selected_entries = list(reversed(parsed_entries[-bounded_limit:]))

    return {
        "entries": selected_entries,
        "severity_counts": dict(severity_counts),
        "latest_timestamp": latest_timestamp,
        "total_entries": len(rows),
        "filtered_entries": len(parsed_entries),
        "order": order,
    }


def read_logger(
    *,
    target: str,
    logger_type: str = "System",
    logger_name: str = "$arlogsys",
    fmt: str | None = None,
    output_path: str | None = None,
    pvi_transfer_path: str | Path,
    config: dict[str, Any] | None = None,
    targets_file: str | Path | None = None,
    target_ip: str | None = None,
    target_role: str | None = None,
    require_config_opt_in: bool = True,
    timeout_seconds: int = 120,
    summary_limit: int = 20,
    severity: str | None = None,
    order: str = "newest",
    keep_temp_files: bool = True,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    loaded_config = config
    if loaded_config is None and targets_file:
        config_path = Path(targets_file)
        if not config_path.is_absolute():
            config_path = repo_root / config_path
        loaded_config = load_json_file(config_path.resolve())

    logger_config = (loaded_config or {}).get("logger") or {}
    resolved_fmt = normalize_format(
        fmt,
        str(logger_config.get("default_format") or DEFAULT_FORMAT),
    )
    resolved_output = resolve_output_path(
        output_path,
        target,
        logger_type,
        logger_name,
        resolved_fmt,
        repo_root=repo_root,
    )
    target_config, validation_errors = validate_request(
        config=loaded_config,
        target=target,
        logger_type=logger_type,
        logger_name=logger_name,
        fmt=resolved_fmt,
        target_ip=target_ip,
        target_role=target_role,
        require_config_opt_in=require_config_opt_in,
    )

    report: dict[str, Any] = {
        "command": "ReadLogger",
        "ok": False,
        "target": target,
        "target_ip": target_config.get("ip") if target_config else None,
        "target_role": target_config.get("role") if target_config else None,
        "logger_type": logger_type,
        "logger_name": logger_name,
        "format": resolved_fmt,
        "output_path": str(resolved_output),
        "log_path": None,
        "error_summary": None,
    }

    if validation_errors:
        report["validation_errors"] = validation_errors
        report["error_summary"] = " | ".join(validation_errors)
        return report

    transfer_exe = Path(pvi_transfer_path).resolve()
    if not transfer_exe.exists():
        report["error_summary"] = f"PVITransfer.exe was not found: {transfer_exe}"
        return report

    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    pil_path = resolved_output.with_suffix(resolved_output.suffix + ".pil")
    log_path = resolved_output.with_suffix(resolved_output.suffix + ".pvitransfer.log")
    report["pil_path"] = str(pil_path)
    report["log_path"] = str(log_path)

    write_logger_pil(
        pil_path,
        str(target_config["ip"]),
        logger_type,
        logger_name,
        resolved_fmt,
        resolved_output,
    )

    returncode, log_lines, timed_out = execute_pvitransfer_silent(
        pvi_transfer_path=transfer_exe,
        pil_path=pil_path,
        log_path=log_path,
        timeout_seconds=timeout_seconds,
    )

    output_exists = resolved_output.exists() and resolved_output.stat().st_size > 0
    logger_success = any("Logger" in line and "SUCCESSFUL" in line for line in log_lines)
    report["process_exit_code"] = returncode
    report["timed_out"] = timed_out
    report["output_exists"] = output_exists
    report["output_size_bytes"] = resolved_output.stat().st_size if resolved_output.exists() else 0
    report["output_tail"] = log_lines[-20:]
    report["ok"] = bool(
        not timed_out
        and output_exists
        and (returncode == 0 or logger_success)
        and (logger_success or not log_lines)
    )

    if not report["ok"]:
        if timed_out:
            report["error_summary"] = f"PVITransfer Logger timed out after {timeout_seconds}s."
        else:
            report["error_summary"] = summarize_lines(log_lines) or "PVITransfer Logger command failed."

    if report["ok"] and resolved_fmt == ".csvx":
        try:
            report["summary"] = parse_csvx_summary(
                resolved_output,
                summary_limit,
                severity=severity,
                order=order,
            )
        except Exception as exc:
            report["summary_parse_error"] = repr(exc)

    if report["ok"] and not keep_temp_files:
        pil_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        report["pil_path"] = None
        report["log_path"] = None

    return report


def _normalize_severity_rank(value: str | None) -> int:
    if not value:
        return 1
    return SEVERITY_RANKS.get(value.strip().lower(), 1)


def _parse_logger_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    # Try ISO-8601 first
    iso_candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M:%S.%f",
        "%d.%m.%Y %H:%M:%S",
        "%Y/%m/%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _normalize_module_specs(
    modules: list[Any] | None,
) -> list[tuple[str, str]]:
    if not modules:
        return list(DEFAULT_DIAGNOSTIC_MODULES)
    result: list[tuple[str, str]] = []
    for item in modules:
        if isinstance(item, dict):
            ltype = str(item.get("logger_type") or item.get("type") or "Named").strip()
            lname = str(item.get("logger_name") or item.get("name") or "").strip()
            if lname:
                result.append((ltype, lname))
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            result.append((str(item[0]).strip(), str(item[1]).strip()))
        elif isinstance(item, str) and item.strip():
            raw = item.strip()
            if ":" in raw:
                ltype, lname = raw.split(":", 1)
                result.append((ltype.strip(), lname.strip()))
            elif "/" in raw:
                ltype, lname = raw.split("/", 1)
                result.append((ltype.strip(), lname.strip()))
            else:
                default_type = next((t for t, n in DEFAULT_DIAGNOSTIC_MODULES if n.casefold() == raw.casefold()), "Named")
                result.append((default_type, raw))
    return result


def _extract_compact_entries(path: Path, module_label: str) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = _parse_csvx_rows(text)

    time_keys = ("Time", "Timestamp", "DateTime", "Date/Time", "time", "timestamp")
    severity_keys = ("Severity", "Level", "Type", "ErrorLevel", "severity", "level")
    event_id_keys = ("Event ID", "EventId", "event_id", "ID", "Code", "ErrorCode", "code", "id")
    object_id_keys = ("Object ID", "ObjectId", "object_id", "Entered by", "Origin", "TaskName", "entered_by", "origin")
    desc_keys = ("Description", "ASCII Data", "Message", "Text", "Event", "description", "message", "text")

    entries: list[dict[str, Any]] = []
    for row in rows:
        timestamp = next((str(row.get(k)) for k in time_keys if row.get(k)), None)
        severity = next((str(row.get(k)) for k in severity_keys if row.get(k)), "unknown")
        event_id = next((str(row.get(k)) for k in event_id_keys if row.get(k)), None)
        object_id = next((str(row.get(k)) for k in object_id_keys if row.get(k)), None)
        description = next((str(row.get(k)) for k in desc_keys if row.get(k)), None)
        entries.append(
            {
                "timestamp": timestamp,
                "module": module_label,
                "severity": severity,
                "event_id": event_id,
                "object_id": object_id,
                "description": description,
            }
        )
    return entries


def diagnose_loggers(
    *,
    target: str,
    pvi_transfer_path: str | Path,
    modules: list[Any] | None = None,
    min_severity: str = "warning",
    since_minutes: float | None = None,
    max_entries: int = 50,
    output_path: str | None = None,
    config: dict[str, Any] | None = None,
    targets_file: str | Path | None = None,
    target_ip: str | None = None,
    target_role: str | None = None,
    require_config_opt_in: bool = True,
    timeout_seconds: int = 120,
    keep_temp_files: bool = False,
    repo_root: Path = REPO_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pull multiple logger modules and merge compact filtered events in reverse chronological order."""
    min_sev = str(min_severity or "warning").strip().lower()
    if min_sev not in {"info", "warning", "error"}:
        raise ValueError(f"Unsupported min_severity {min_severity!r}; expected 'info', 'warning', or 'error'.")
    min_rank = _normalize_severity_rank(min_sev)
    bounded_max = max(1, min(int(max_entries or 50), 200))

    specs = _normalize_module_specs(modules)
    if not specs:
        raise ValueError("At least one logger module must be specified.")

    loaded_config = config
    if loaded_config is None and targets_file:
        config_path = Path(targets_file)
        if not config_path.is_absolute():
            config_path = repo_root / config_path
        loaded_config = load_json_file(config_path.resolve())

    if loaded_config is not None and require_config_opt_in and not is_logger_enabled(loaded_config):
        return {
            "command": "ReadLoggerAggregate",
            "mode": "aggregate",
            "ok": False,
            "target": target,
            "error_code": "POLICY_DENIED",
            "error_summary": (
                "Logger download is not enabled in project configuration. "
                "Set logger.enabled = true (or allow_logger = true) to allow downloading logger modules."
            ),
            "modules": [],
            "blocked_modules": [],
            "entries": [],
        }

    started = time.monotonic()
    deadline = started + max(5, int(timeout_seconds))
    reference_now = now or datetime.now(timezone.utc)
    cutoff_dt = (
        datetime.fromtimestamp(reference_now.timestamp() - float(since_minutes) * 60.0, tz=timezone.utc)
        if since_minutes is not None
        else None
    )

    module_results: list[dict[str, Any]] = []
    blocked_modules: list[dict[str, Any]] = []
    csvx_paths: dict[str, str] = {}
    all_entries: list[dict[str, Any]] = []
    total_before_filter = 0

    for idx, (logger_type, logger_name) in enumerate(specs):
        module_label = f"{logger_type}/{logger_name}"
        if "safety" in logger_type.lower() or "safety" in logger_name.lower():
            blocked_info = {
                "logger_type": logger_type,
                "logger_name": logger_name,
                "module": module_label,
                "status": "blocked_safety",
                "error_code": "SAFETY_LOGGER_BLOCKED",
                "error_summary": f"Logger module '{logger_type} / {logger_name}' is blocked by immutable safety policy.",
            }
            blocked_modules.append(blocked_info)
            module_results.append(blocked_info)
            continue

        remaining = deadline - time.monotonic()
        if remaining <= 1.0:
            module_results.append(
                {
                    "logger_type": logger_type,
                    "logger_name": logger_name,
                    "module": module_label,
                    "status": "skipped_timeout",
                    "error_summary": "Total aggregate logger time budget exhausted.",
                }
            )
            continue

        remaining_count = max(1, len(specs) - idx)
        per_module_timeout = max(5, int(min(remaining, max(15.0, remaining / remaining_count))))
        single = read_logger(
            target=target,
            logger_type=logger_type,
            logger_name=logger_name,
            fmt=".csvx",
            output_path=output_path,
            pvi_transfer_path=pvi_transfer_path,
            config=loaded_config,
            targets_file=targets_file,
            target_ip=target_ip,
            target_role=target_role,
            require_config_opt_in=require_config_opt_in,
            timeout_seconds=per_module_timeout,
            summary_limit=1,
            keep_temp_files=keep_temp_files,
            repo_root=repo_root,
        )

        if not single.get("ok"):
            module_results.append(
                {
                    "logger_type": logger_type,
                    "logger_name": logger_name,
                    "module": module_label,
                    "status": "missing_or_empty",
                    "output_path": single.get("output_path"),
                    "error_summary": single.get("error_summary"),
                }
            )
            continue

        out_file = Path(str(single["output_path"]))
        csvx_paths[module_label] = str(out_file)
        try:
            parsed = _extract_compact_entries(out_file, module_label)
        except Exception as exc:
            module_results.append(
                {
                    "logger_type": logger_type,
                    "logger_name": logger_name,
                    "module": module_label,
                    "status": "parse_error",
                    "output_path": str(out_file),
                    "error_summary": repr(exc),
                }
            )
            continue

        total_before_filter += len(parsed)
        matched_in_module = 0
        for entry in parsed:
            if _normalize_severity_rank(entry.get("severity")) < min_rank:
                continue
            if cutoff_dt is not None:
                entry_dt = _parse_logger_timestamp(entry.get("timestamp"))
                if entry_dt is None or entry_dt < cutoff_dt:
                    continue
            all_entries.append(entry)
            matched_in_module += 1

        module_results.append(
            {
                "logger_type": logger_type,
                "logger_name": logger_name,
                "module": module_label,
                "status": "ok" if parsed else "missing_or_empty",
                "output_path": str(out_file),
                "total_entries": len(parsed),
                "filtered_entries": matched_in_module,
            }
        )

    def _sort_key(entry: dict[str, Any]) -> tuple[int, float, str]:
        dt = _parse_logger_timestamp(entry.get("timestamp"))
        if dt is not None:
            return (1, dt.timestamp(), str(entry.get("timestamp") or ""))
        return (0, 0.0, str(entry.get("timestamp") or ""))

    all_entries.sort(key=_sort_key, reverse=True)
    selected = all_entries[:bounded_max]

    succeeded_count = sum(1 for item in module_results if item["status"] == "ok")
    if succeeded_count == 0 and blocked_modules:
        ok = False
        error_code = "SAFETY_LOGGER_BLOCKED"
        error_summary = blocked_modules[0]["error_summary"]
    elif succeeded_count == 0:
        ok = False
        error_code = "LOGGER_AGGREGATE_EMPTY"
        error_summary = "No requested logger modules could be retrieved."
    else:
        ok = True
        error_code = None
        error_summary = None

    return {
        "command": "ReadLoggerAggregate",
        "mode": "aggregate",
        "ok": ok,
        "target": target,
        "min_severity": min_sev,
        "since_minutes": since_minutes,
        "max_entries": bounded_max,
        "total_entries_before_filter": total_before_filter,
        "total_entries_after_filter": len(all_entries),
        "returned_entries": len(selected),
        "entries": selected,
        "modules": module_results,
        "blocked_modules": blocked_modules,
        "csvx_paths": csvx_paths,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        **({"error_code": error_code} if error_code else {}),
        **({"error_summary": error_summary} if error_summary else {}),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    config_path = (
        (REPO_ROOT / args.targets_file).resolve()
        if not Path(args.targets_file).is_absolute()
        else Path(args.targets_file).resolve()
    )
    config = load_json_file(config_path)
    pvi_transfer = args.pvi_transfer_path or (config.get("pvi") or {}).get("transfer_exe") or ""
    if not pvi_transfer:
        raise ValueError("PVITransfer.exe path is required via --pvi-transfer-path.")
    return read_logger(
        target=args.target,
        logger_type=args.logger_type,
        logger_name=args.logger_name,
        fmt=args.format,
        output_path=args.output_path,
        pvi_transfer_path=pvi_transfer,
        config=config,
        targets_file=config_path,
        timeout_seconds=args.timeout_seconds,
        summary_limit=args.summary_limit,
        severity=args.severity,
        order=args.order,
        keep_temp_files=args.keep_temp_files,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a B&R PLC/AR logger module directly through PVITransfer.")
    parser.add_argument("--target", required=True, help="Target name from the selected target configuration.")
    parser.add_argument("--targets-file", required=True, help="Toolchain target configuration JSON.")
    parser.add_argument("--logger-type", default="System", help="Logger module type, for example System, User, Named.")
    parser.add_argument("--logger-name", default="$arlogsys", help="Logger module name, for example $arlogsys, $arlogusr, $motion.")
    parser.add_argument("--format", default=None, help="Output format: .csvx (default), .html, .arl, or .logpkg.")
    parser.add_argument("--output-path", help="Output file or directory. Must stay inside the repository.")
    parser.add_argument("--pvi-transfer-path", required=True, help="Path to PVITransfer.exe.")
    parser.add_argument("--timeout-seconds", type=int, default=120, help="Maximum seconds to wait for PVITransfer.")
    parser.add_argument("--summary-limit", type=int, default=20, help="Maximum parsed .csvx entries to include in JSON.")
    parser.add_argument("--severity", default=None, help="Optional comma-separated severity filter for .csvx summary.")
    parser.add_argument("--order", choices=["newest", "oldest"], default="newest", help="Summary entry order for .csvx.")
    parser.add_argument("--keep-temp-files", action="store_true", help="Keep .pil and .pvitransfer.log after success.")
    args = parser.parse_args()

    report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "command": "ReadLogger",
                    "ok": False,
                    "target": None,
                    "logger_type": None,
                    "logger_name": None,
                    "format": None,
                    "output_path": None,
                    "log_path": None,
                    "error_summary": repr(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)
