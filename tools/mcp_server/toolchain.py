from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PLC_TOOLCHAIN = REPO_ROOT / "tools" / "plc_toolchain.ps1"
DEFAULT_PROJECT_PATH = "PrintDemo\\Huitong_FrontEval.apj"
DEFAULT_CONFIG = "Config1"
DEFAULT_TARGETS_PATH = "tools\\plc_targets.local.json"


class ToolchainError(RuntimeError):
    def __init__(self, message: str, *, stdout: str = "", stderr: str = "", exit_code: int | None = None):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


def run_plc_toolchain(
    command: str,
    *,
    target: str = "arsim",
    project_path: str = DEFAULT_PROJECT_PATH,
    config: str = DEFAULT_CONFIG,
    targets_path: str = DEFAULT_TARGETS_PATH,
    package_path: str | None = None,
    transfer_pil_path: str | None = None,
    pvi_variables: list[str] | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PLC_TOOLCHAIN),
        "-Command",
        command,
        "-Target",
        target,
        "-ProjectPath",
        project_path,
        "-Config",
        config,
        "-TargetsPath",
        targets_path,
    ]
    if package_path:
        args.extend(["-PackagePath", package_path])
    if transfer_pil_path:
        args.extend(["-TransferPilPath", transfer_pil_path])
    if pvi_variables:
        args.extend(["-PviVariable", ",".join(pvi_variables)])

    completed = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if not stdout:
        raise ToolchainError(
            "PLC toolchain returned no JSON output.",
            stdout=stdout,
            stderr=stderr,
            exit_code=completed.returncode,
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ToolchainError(
            f"PLC toolchain returned invalid JSON: {exc}",
            stdout=stdout,
            stderr=stderr,
            exit_code=completed.returncode,
        ) from exc

    if stderr:
        data.setdefault("stderr", stderr)
    data.setdefault("process_exit_code", completed.returncode)
    return data


def summarize(command: str, data: dict[str, Any]) -> str:
    if command == "Probe":
        return " / ".join(
            str(v)
            for v in [data.get("cpu_type"), data.get("ar_version"), data.get("plc_status")]
            if v
        )
    if command == "CheckDownload":
        if data.get("ok"):
            package = data.get("package") or {}
            probe = data.get("probe") or {}
            return f"download allowed: package {package.get('cpu_type')} -> target {probe.get('cpu_type')}"
        reasons = data.get("reasons") or []
        return "; ".join(str(r) for r in reasons) or "download check failed"
    if command == "ReadPvi":
        variables = data.get("variables") or []
        ok_count = sum(1 for item in variables if item.get("ok"))
        return f"read {ok_count}/{len(variables)} PVI variables"
    return str(data.get("summary") or command)


def collect_logs(data: dict[str, Any]) -> list[str]:
    logs: list[str] = []
    for key in ("log_path", "pil_path", "nodes_file", "variables_file"):
        value = data.get(key)
        if value:
            logs.append(str(value))

    for nested_key in ("probe", "package", "safety_check"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            logs.extend(collect_logs(nested))

    seen: set[str] = set()
    unique: list[str] = []
    for item in logs:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def collect_warnings(data: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    raw = data.get("warnings")
    if isinstance(raw, list):
        warnings.extend(str(item) for item in raw)
    elif raw:
        warnings.append(str(raw))

    reasons = data.get("reasons")
    if data.get("ok") is False and isinstance(reasons, list):
        warnings.extend(str(item) for item in reasons)

    error = data.get("error")
    if data.get("ok") is False and error:
        warnings.append(str(error))
    return warnings


def next_actions(tool: str, data: dict[str, Any]) -> list[str]:
    if tool == "plc_probe_target" and data.get("ok"):
        return ["Run plc_check_download before any download."]
    if tool == "plc_check_download" and data.get("ok"):
        return ["A download may be attempted only with an explicit execute=true download tool."]
    if tool == "plc_check_download" and not data.get("ok"):
        return ["Do not download. Fix the reported package/target mismatch first."]
    if tool == "plc_read_pvi" and not data.get("ok"):
        return ["Check PVI Manager, target reachability, and variable whitelist names."]
    return []


def wrap_result(tool: str, command: str, data: dict[str, Any], target: str) -> dict[str, Any]:
    return {
        "ok": bool(data.get("ok")),
        "tool": tool,
        "target": target,
        "summary": summarize(command, data),
        "data": data,
        "logs": collect_logs(data),
        "warnings": collect_warnings(data),
        "next_actions": next_actions(tool, data),
    }


def plc_probe_target(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    data = run_plc_toolchain(
        "Probe",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        timeout_seconds=int(arguments.get("timeout_seconds") or 60),
    )
    return wrap_result("plc_probe_target", "Probe", data, target)


def plc_read_pvi(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    pvi_variables = arguments.get("pvi_variables")
    if pvi_variables is not None and not isinstance(pvi_variables, list):
        raise ValueError("pvi_variables must be an array of strings.")
    data = run_plc_toolchain(
        "ReadPvi",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        pvi_variables=[str(item) for item in pvi_variables] if pvi_variables else None,
        timeout_seconds=int(arguments.get("timeout_seconds") or 60),
    )
    return wrap_result("plc_read_pvi", "ReadPvi", data, target)


def plc_check_download(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    data = run_plc_toolchain(
        "CheckDownload",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        package_path=arguments.get("package_path"),
        transfer_pil_path=arguments.get("transfer_pil_path"),
        timeout_seconds=int(arguments.get("timeout_seconds") or 90),
    )
    return wrap_result("plc_check_download", "CheckDownload", data, target)


TOOLS = {
    "plc_probe_target": plc_probe_target,
    "plc_read_pvi": plc_read_pvi,
    "plc_check_download": plc_check_download,
}
