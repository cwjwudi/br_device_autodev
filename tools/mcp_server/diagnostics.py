from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from br_plc_toolchain.config import ConfigError, resolve_toolchain  # noqa: E402
REPORTS_DIR = REPO_ROOT / "var" / "reports"
GENERATED_DIR = REPO_ROOT / "var"
MAX_REPORT_BYTES = 10 * 1024 * 1024


def repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def project_candidates() -> list[Path]:
    excluded = {".git", ".pytest_cache", "var", "Temp", "tools"}
    candidates = {
        path.resolve()
        for path in REPO_ROOT.rglob("*.apj")
        if path.is_file() and not any(part in excluded for part in path.parts)
    }
    return sorted(candidates)


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    ok: bool,
    message: str,
    *,
    severity: str = "error",
    path: Path | None = None,
) -> None:
    item: dict[str, Any] = {
        "name": name,
        "ok": bool(ok),
        "severity": severity,
        "message": message,
    }
    if path is not None:
        item["path"] = str(path)
    checks.append(item)


def load_targets(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "Targets configuration must be a JSON object."
    return value, None


def validate_environment(options: dict[str, str]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    targets_path = repo_path(options["targets_path"]).resolve()
    project_raw = str(options.get("project_path") or "").strip()
    project_path = repo_path(project_raw).resolve() if project_raw else None
    config_name = options["config"]
    target_name = options["target"]
    toolchain = None
    try:
        toolchain = resolve_toolchain(
            options.get("toolchain") or None,
            registry_path=options.get("toolchains_path") or None,
        )
        add_check(
            checks,
            "toolchain",
            toolchain.enabled,
            f"Toolchain '{toolchain.id}' resolves to {toolchain.family} {toolchain.version}."
            if toolchain.enabled
            else f"Toolchain '{toolchain.id}' is disabled.",
            path=toolchain.source_path,
        )
    except ConfigError as exc:
        add_check(checks, "toolchain", False, str(exc))

    targets, targets_error = load_targets(targets_path)
    add_check(
        checks,
        "targets_config",
        targets is not None,
        "Targets configuration loaded." if targets is not None else f"Targets configuration failed: {targets_error}",
        path=targets_path,
    )

    target_config: dict[str, Any] | None = None
    if targets is not None:
        candidate = (targets.get("targets") or {}).get(target_name)
        target_config = candidate if isinstance(candidate, dict) else None
    add_check(
        checks,
        "target",
        target_config is not None,
        f"Target '{target_name}' is configured."
        if target_config is not None
        else f"Target '{target_name}' is missing from the targets configuration.",
    )

    candidates = project_candidates()
    project_ok = bool(project_path and project_path.is_file() and project_path.suffix.lower() == ".apj")
    if project_path is None:
        if len(candidates) == 1:
            project_message = "Project path is required; one .apj candidate was found and was not selected automatically."
        elif candidates:
            project_message = f"Project path is required; {len(candidates)} .apj candidates were found."
        else:
            project_message = "Project path is required and no .apj candidate was found."
    else:
        project_message = (
            "Automation Studio project exists."
            if project_ok
            else "Automation Studio project file is missing or is not an .apj file."
        )
    add_check(
        checks,
        "project",
        project_ok,
        project_message,
        path=project_path,
    )

    project_as_family = None
    project_as_version = None
    if project_ok and project_path is not None:
        head = project_path.read_text(encoding="utf-8-sig", errors="replace")[:4096]
        match = re.search(r'<\?AutomationStudio\s+Version="([^"]+)"', head)
        if match:
            project_as_version = match.group(1)
            major = project_as_version.split(".", 1)[0]
            project_as_family = f"AS{major}" if major.isdigit() else None
    if toolchain and project_as_family:
        compatible = project_as_family == toolchain.family
        add_check(
            checks,
            "project_toolchain_compatibility",
            compatible,
            f"Project declares {project_as_version}; selected toolchain is {toolchain.family} {toolchain.version}."
            if compatible
            else f"Project declares {project_as_version} ({project_as_family}) but selected toolchain is {toolchain.family} {toolchain.version}.",
        )
    elif project_ok:
        add_check(
            checks,
            "project_toolchain_compatibility",
            True,
            "Project Automation Studio version declaration was not found; family compatibility was not asserted.",
            severity="warning",
        )

    physical_dir = project_path.parent / "Physical" / config_name if project_path else None
    hardware_file = physical_dir / "Hardware.hw" if physical_dir else None
    config_ok = bool(config_name and physical_dir and physical_dir.is_dir() and hardware_file and hardware_file.is_file())
    config_message = (
        f"Automation Studio config '{config_name}' exists."
        if config_ok
        else "Configuration name is required."
        if not config_name
        else f"Automation Studio config '{config_name}' or Hardware.hw is missing."
    )
    add_check(
        checks,
        "configuration",
        config_ok,
        config_message,
        path=physical_dir,
    )

    role = str((target_config or {}).get("role") or "")
    add_check(
        checks,
        "target_role",
        bool(role),
        f"Target role is '{role}'." if role else "Target role is missing.",
    )
    if role.lower() == "production":
        add_check(
            checks,
            "production_guard",
            True,
            "Production target detected; automatic state-changing operations remain blocked.",
            severity="warning",
        )

    errors = [item["message"] for item in checks if not item["ok"] and item["severity"] == "error"]
    warnings = [item["message"] for item in checks if item["severity"] == "warning"]
    error_codes: list[str] = []
    if not project_ok or not config_ok:
        error_codes.append("PROJECT_CONFIG_REQUIRED")
    if not error_codes and (toolchain is None or not toolchain.enabled):
        error_codes.append("TOOLCHAIN_NOT_CONFIGURED")
    return {
        "command": "ValidateEnvironment",
        "ok": not errors,
        "environment": options.get("environment"),
        "target": target_name,
        "target_role": role or None,
        "project_path": str(project_path) if project_path else None,
        "project_candidates": [str(path) for path in candidates],
        "config": config_name,
        "targets_path": str(targets_path),
        "toolchain": toolchain.to_dict() if toolchain else None,
        "project_as_family": project_as_family,
        "project_as_version": project_as_version,
        "checks": checks,
        "errors": errors,
        "error_codes": error_codes,
        "warnings": warnings,
    }


def run_doctor(options: dict[str, str]) -> dict[str, Any]:
    environment_result = validate_environment(options)
    checks = list(environment_result["checks"])
    targets, _ = load_targets(Path(environment_result["targets_path"]))
    toolchain_data = environment_result.get("toolchain") or {}
    automation = toolchain_data.get("automation_studio") or {}
    pvi = toolchain_data.get("pvi") or {}

    add_check(
        checks,
        "python",
        Path(sys.executable).is_file(),
        f"Python {sys.version.split()[0]} is available.",
        path=Path(sys.executable),
    )
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    add_check(
        checks,
        "powershell",
        bool(powershell),
        "PowerShell is available." if powershell else "PowerShell was not found on PATH.",
        path=Path(powershell) if powershell else None,
    )

    for key, label, raw_path in (
        ("build_exe", "Automation Studio build executable", automation.get("build_exe")),
        ("pvi_transfer_exe", "PVITransfer executable", pvi.get("transfer_exe")),
    ):
        path = Path(str(raw_path)) if raw_path else None
        ok = bool(path and path.is_file())
        add_check(
            checks,
            key,
            ok,
            f"{label} exists." if ok else f"{label} is missing or not configured.",
            path=path,
        )

    expected_dll = pvi.get("expected_dll")
    dll_path = Path(str(expected_dll)) if expected_dll else None
    add_check(
        checks,
        "pvi_dll",
        bool(dll_path and dll_path.is_file()),
        "PVI communication DLL exists."
        if dll_path and dll_path.is_file()
        else "PVI communication DLL is missing or pvi.dll_dir points to the wrong directory.",
        path=dll_path,
    )

    pvi_available = importlib.util.find_spec("pvi") is not None
    add_check(
        checks,
        "pvi_python",
        pvi_available,
        "Python PVI module is importable."
        if pvi_available
        else "Python PVI module 'pvi' is not installed in this interpreter.",
    )

    target_config = ((targets or {}).get("targets") or {}).get(options["target"])
    if isinstance(target_config, dict) and str(target_config.get("role") or "").lower() == "arsim":
        loader_raw = target_config.get("arsim_loader_exe")
        loader_value = str(loader_raw or "").strip()
        loader = repo_path(loader_value).resolve() if loader_value and not loader_value.startswith("<") else None
        add_check(
            checks,
            "arsim_loader",
            bool(loader and loader.is_file()),
            "ARsim loader exists."
            if loader and loader.is_file()
            else "ARsim target is selected but arsim_loader_exe is missing or invalid.",
            path=loader,
        )

    generated_ok = False
    generated_error: str | None = None
    try:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix="doctor_", suffix=".tmp", dir=GENERATED_DIR)
        os.close(descriptor)
        Path(temporary).unlink()
        generated_ok = True
    except Exception as exc:
        generated_error = str(exc)
    add_check(
        checks,
        "generated_write",
        generated_ok,
        "Generated output directory is writable."
        if generated_ok
        else f"Generated output directory is not writable: {generated_error}",
        path=GENERATED_DIR,
    )

    errors = [item["message"] for item in checks if not item["ok"] and item["severity"] == "error"]
    error_codes = list(environment_result.get("error_codes") or [])
    if any(item["name"] == "arsim_loader" and not item["ok"] for item in checks):
        error_codes.append("ARSIM_LOADER_REQUIRED")
    if not error_codes and errors:
        error_codes.append("TOOLCHAIN_NOT_CONFIGURED")
    warnings = [item["message"] for item in checks if item["severity"] == "warning"]
    return {
        "command": "Doctor",
        "ok": not errors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": options.get("environment"),
        "target": options["target"],
        "checks": checks,
        "errors": errors,
        "error_codes": sorted(set(error_codes)),
        "warnings": warnings,
    }


def report_kind(name: str, payload: dict[str, Any]) -> str:
    command = str(payload.get("command") or "").lower()
    lowered = name.lower()
    if "io_test" in lowered or command in {"runtestsuite", "runiotestcase"}:
        return "io_test"
    if "verification" in lowered or command == "runverificationsuite":
        return "verification"
    if "closed_loop" in lowered or command == "runarsimclosedloop":
        return "closed_loop"
    if "reset" in lowered or command == "resettestharness":
        return "reset"
    if "build" in lowered or command == "build":
        return "build"
    return "other"


def compact_report(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    return {
        "name": path.name,
        "report_path": str(path),
        "kind": report_kind(path.name, payload),
        "size_bytes": path.stat().st_size,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "command": payload.get("command"),
        "ok": payload.get("ok"),
        "target": payload.get("target"),
        "suite": payload.get("suite"),
        "generated_at": payload.get("generated_at"),
        "summary": payload.get("summary"),
        "failure_stage": payload.get("failure_stage"),
        "cases_total": payload.get("cases_total", len(cases) if cases else None),
        "cases_passed": payload.get("cases_passed"),
        "cases_failed": payload.get("cases_failed"),
    }


def string_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def list_reports(
    *,
    limit: int = 20,
    kind: str = "all",
    status: str = "all",
    reports_dir: Path = REPORTS_DIR,
) -> dict[str, Any]:
    warnings: list[str] = []
    reports: list[dict[str, Any]] = []
    if reports_dir.exists():
        paths = sorted(
            reports_dir.rglob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
        )
        for path in paths:
            if path.stat().st_size > MAX_REPORT_BYTES:
                warnings.append(f"Skipped oversized report: {path.name}")
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                warnings.append(f"Skipped unreadable report {path.name}: {exc}")
                continue
            if not isinstance(payload, dict):
                warnings.append(f"Skipped non-object report: {path.name}")
                continue
            summary = compact_report(path, payload)
            if kind != "all" and summary["kind"] != kind:
                continue
            if status == "passed" and summary["ok"] is not True:
                continue
            if status == "failed" and summary["ok"] is not False:
                continue
            reports.append(summary)
            if len(reports) >= limit:
                break
    return {
        "command": "ListReports",
        "ok": True,
        "reports_dir": str(reports_dir.resolve()),
        "count": len(reports),
        "reports": reports,
        "warnings": warnings,
    }


def resolve_report_path(raw_path: str, reports_dir: Path = REPORTS_DIR) -> Path:
    root = reports_dir.resolve()
    supplied = Path(raw_path)
    if supplied.is_absolute():
        candidate = supplied.resolve()
    elif supplied.parts[:2] == ("var", "reports"):
        candidate = (REPO_ROOT / supplied).resolve()
    else:
        candidate = (root / supplied).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Report path must stay inside var/reports.") from exc
    if candidate.suffix.lower() != ".json":
        raise ValueError("Report path must reference a JSON file.")
    if not candidate.is_file():
        raise FileNotFoundError(f"Report was not found: {candidate}")
    if candidate.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("Report is too large for summary reading.")
    return candidate


def read_report_summary(raw_path: str, reports_dir: Path = REPORTS_DIR) -> dict[str, Any]:
    path = resolve_report_path(raw_path, reports_dir)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Report JSON must contain an object.")
    summary = compact_report(path, payload)
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    summary["failure_stages"] = payload.get("failure_stages") or []
    summary["errors"] = string_items(payload.get("errors"))
    summary["warnings"] = string_items(payload.get("warnings"))
    summary["case_results"] = [
        {
            "name": case.get("name"),
            "ok": case.get("ok"),
            "failure_stage": case.get("failure_stage"),
            "failure_stages": case.get("failure_stages") or [],
            "checks_total": len(case.get("checks") or []),
            "checks_failed": sum(
                1
                for check in (case.get("checks") or [])
                if not isinstance(check, dict) or check.get("ok") is not True
            ),
        }
        for case in cases
        if isinstance(case, dict)
    ]
    logs = []
    for key in ("log_path", "output_path", "catalog_path"):
        if payload.get(key):
            logs.append(str(payload[key]))
    summary["logs"] = logs
    return {
        "command": "ReadReportSummary",
        "ok": True,
        "report_path": str(path),
        "summary": summary,
        "warnings": summary["warnings"],
    }
