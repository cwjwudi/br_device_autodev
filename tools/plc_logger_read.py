#!/usr/bin/env python
"""Read B&R PLC/AR logger modules through PVITransfer Logger commands."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "tools" / ".generated" / "logger"
DEFAULT_ALLOWED_MODULES = [
    {"type": "System", "name": "$arlogsys"},
    {"type": "User", "name": "$arlogusr"},
    {"type": "Connectivity", "name": "$arlogconn"},
]
DEFAULT_BLOCKED_MODULES = [{"type": "Safety", "name": "$safety"}]
ALLOWED_FORMATS = {".html", ".csvx", ".arl", ".logpkg"}


def load_json_file(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def module_key(logger_type: str, logger_name: str) -> tuple[str, str]:
    return (logger_type.strip().lower(), logger_name.strip().lower())


def module_display(module: dict[str, Any]) -> str:
    return f"{module.get('type')} / {module.get('name')}"


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.replace("$", ""))
    return cleaned.strip("._") or "logger"


def normalize_format(value: str | None, default_format: str) -> str:
    fmt = (value or default_format or ".html").strip().lower()
    if fmt and not fmt.startswith("."):
        fmt = "." + fmt
    if fmt not in ALLOWED_FORMATS:
        raise ValueError(f"Unsupported logger output format '{fmt}'. Allowed formats: {sorted(ALLOWED_FORMATS)}.")
    return fmt


def resolve_output_path(output_path: str | None, target: str, logger_type: str, logger_name: str, fmt: str) -> Path:
    stem = "_".join(
        [
            utc_stamp(),
            safe_filename_part(target),
            safe_filename_part(logger_type),
            safe_filename_part(logger_name),
        ]
    )

    if output_path:
        candidate = Path(output_path)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        candidate = candidate.resolve()
        if candidate.suffix:
            if candidate.suffix.lower() != fmt:
                raise ValueError(f"OutputPath suffix '{candidate.suffix}' does not match requested format '{fmt}'.")
            resolved = candidate
        else:
            resolved = candidate / f"{stem}{fmt}"
    else:
        resolved = (DEFAULT_OUTPUT_DIR / f"{stem}{fmt}").resolve()

    if not is_relative_to(resolved, REPO_ROOT):
        raise ValueError(f"Output path must stay inside the repository: {resolved}")
    return resolved


def validate_request(
    *,
    config: dict[str, Any],
    target: str,
    logger_type: str,
    logger_name: str,
    fmt: str,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    target_config = (config.get("targets") or {}).get(target)
    if not target_config:
        return {}, [f"Target '{target}' was not found in targets configuration."]

    logger_config = config.get("logger") or {}
    if logger_config.get("enabled") is False:
        errors.append("Logger reading is disabled in logger.enabled.")
    if str(target_config.get("role", "")).lower() == "production":
        errors.append(f"Refusing to read logger from production target '{target}'.")

    allowed_modules = logger_config.get("allowed_modules") or DEFAULT_ALLOWED_MODULES
    blocked_modules = logger_config.get("blocked_modules") or DEFAULT_BLOCKED_MODULES
    requested = module_key(logger_type, logger_name)
    allowed = {module_key(str(item.get("type", "")), str(item.get("name", ""))) for item in allowed_modules}
    blocked = {module_key(str(item.get("type", "")), str(item.get("name", ""))) for item in blocked_modules}

    if requested in blocked or "safety" in requested[0] or "safety" in requested[1]:
        blocked_text = ", ".join(module_display(item) for item in blocked_modules)
        errors.append(f"Logger module '{logger_type} / {logger_name}' is blocked. Blocked modules: {blocked_text}.")
    if requested not in allowed:
        allowed_text = ", ".join(module_display(item) for item in allowed_modules)
        errors.append(f"Logger module '{logger_type} / {logger_name}' is not in logger.allowed_modules. Allowed modules: {allowed_text}.")
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


def summarize_lines(lines: list[str]) -> str | None:
    interesting = [
        line.strip()
        for line in lines
        if re.search(r"\b(error|failed|not found|timeout|refus|denied)\b", line, re.IGNORECASE)
    ]
    if interesting:
        return " | ".join(interesting[-5:])
    tail = [line.strip() for line in lines[-5:] if line.strip()]
    return " | ".join(tail) if tail else None


def parse_csvx_summary(path: Path, limit: int) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "entries": [],
        "severity_counts": {},
        "latest_timestamp": None,
    }

    text = path.read_text(encoding="utf-8-sig", errors="replace")
    stripped = text.lstrip()
    rows: list[dict[str, Any]] = []
    if stripped.startswith("<"):
        root = ET.fromstring(text)
        for element in root.iter():
            if len(element) == 0 and element.attrib:
                rows.append(dict(element.attrib))
            elif len(element) > 0:
                values = {child.tag.split("}", 1)[-1]: (child.text or "") for child in element}
                if values:
                    rows.append(values)
    else:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        reader = csv.DictReader(text.splitlines(), dialect=dialect)
        rows = [dict(row) for row in reader]

    severity_counts: Counter[str] = Counter()
    latest_timestamp: str | None = None
    entries: list[dict[str, Any]] = []
    time_keys = ("Time", "Timestamp", "DateTime", "Date/Time", "time", "timestamp")
    severity_keys = ("Severity", "Level", "Type", "ErrorLevel", "severity", "level")
    message_keys = ("Message", "Text", "Description", "Event", "message", "text")

    for row in rows:
        severity = next((str(row.get(key)) for key in severity_keys if row.get(key)), "unknown")
        timestamp = next((str(row.get(key)) for key in time_keys if row.get(key)), None)
        message = next((str(row.get(key)) for key in message_keys if row.get(key)), None)
        severity_counts[severity] += 1
        if timestamp and (latest_timestamp is None or timestamp > latest_timestamp):
            latest_timestamp = timestamp
        if len(entries) < limit:
            entries.append(
                {
                    "timestamp": timestamp,
                    "severity": severity,
                    "message": message,
                }
            )

    summary["entries"] = entries
    summary["severity_counts"] = dict(severity_counts)
    summary["latest_timestamp"] = latest_timestamp
    summary["total_entries"] = len(rows)
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    config_path = (REPO_ROOT / args.targets_file).resolve() if not Path(args.targets_file).is_absolute() else Path(args.targets_file).resolve()
    config = load_json_file(config_path)
    logger_config = config.get("logger") or {}
    fmt = normalize_format(args.format, str(logger_config.get("default_format") or ".html"))
    output_path = resolve_output_path(args.output_path, args.target, args.logger_type, args.logger_name, fmt)
    target_config, validation_errors = validate_request(
        config=config,
        target=args.target,
        logger_type=args.logger_type,
        logger_name=args.logger_name,
        fmt=fmt,
    )

    report: dict[str, Any] = {
        "command": "ReadLogger",
        "ok": False,
        "target": args.target,
        "target_ip": target_config.get("ip") if target_config else None,
        "target_role": target_config.get("role") if target_config else None,
        "logger_type": args.logger_type,
        "logger_name": args.logger_name,
        "format": fmt,
        "output_path": str(output_path),
        "log_path": None,
        "error_summary": None,
    }

    if validation_errors:
        report["validation_errors"] = validation_errors
        report["error_summary"] = " | ".join(validation_errors)
        return report

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pil_path = output_path.with_suffix(output_path.suffix + ".pil")
    log_path = output_path.with_suffix(output_path.suffix + ".pvitransfer.log")
    report["pil_path"] = str(pil_path)
    report["log_path"] = str(log_path)

    wrapper_path = (REPO_ROOT / "tools" / "invoke_pvitransfer_silent.ps1").resolve()
    pvi_transfer_path = Path(args.pvi_transfer_path or (config.get("automation_studio") or {}).get("pvi_transfer_exe") or "").resolve()
    if not pvi_transfer_path.exists():
        report["error_summary"] = f"PVITransfer.exe was not found: {pvi_transfer_path}"
        return report

    write_logger_pil(pil_path, str(target_config["ip"]), args.logger_type, args.logger_name, fmt, output_path)
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper_path),
            "-PilPath",
            str(pil_path),
            "-LogPath",
            str(log_path),
            "-PviTransferPath",
            str(pvi_transfer_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=args.timeout_seconds,
        check=False,
    )

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    log_lines: list[str] = []
    if log_path.exists():
        log_lines = log_path.read_text(encoding="mbcs", errors="replace").splitlines()
    all_lines = lines or log_lines
    output_exists = output_path.exists() and output_path.stat().st_size > 0
    logger_success = any("Logger" in line and "SUCCESSFUL" in line for line in all_lines)
    report["process_exit_code"] = completed.returncode
    report["output_exists"] = output_exists
    report["output_size_bytes"] = output_path.stat().st_size if output_path.exists() else 0
    report["output_tail"] = all_lines[-20:]
    report["stderr"] = completed.stderr.strip() or None
    report["ok"] = bool(completed.returncode == 0 and output_exists and (logger_success or not all_lines))

    if not report["ok"]:
        report["error_summary"] = summarize_lines(all_lines) or completed.stderr.strip() or "PVITransfer Logger command failed."

    if report["ok"] and fmt == ".csvx":
        try:
            report["summary"] = parse_csvx_summary(output_path, args.summary_limit)
        except Exception as exc:
            report["summary_parse_error"] = repr(exc)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a whitelisted B&R PLC/AR logger module through PVITransfer.")
    parser.add_argument("--target", required=True, help="Target name from tools/plc_targets.local.json.")
    parser.add_argument("--targets-file", required=True, help="Toolchain target configuration JSON.")
    parser.add_argument("--logger-type", default="System", help="Logger module type, for example System.")
    parser.add_argument("--logger-name", default="$arlogsys", help="Logger module name, for example $arlogsys.")
    parser.add_argument("--format", default=None, help="Output format: .html, .csvx, .arl, or .logpkg.")
    parser.add_argument("--output-path", help="Output file or directory. Must stay inside the repository.")
    parser.add_argument("--pvi-transfer-path", help="Optional PVITransfer.exe path. Defaults to automation_studio.pvi_transfer_exe.")
    parser.add_argument("--timeout-seconds", type=int, default=120, help="Maximum seconds to wait for PVITransfer.")
    parser.add_argument("--summary-limit", type=int, default=20, help="Maximum parsed .csvx entries to include in JSON.")
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
