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
    opcua_node_ids: list[str] | None = None,
    build_ruc_package: bool = False,
    execute: bool = False,
    start_wait_seconds: int | None = None,
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
    if opcua_node_ids:
        for nid in opcua_node_ids:
            args.extend(["-OpcUaNodeId", nid])
    if build_ruc_package:
        args.append("-BuildRucPackage")
    if execute:
        args.append("-Execute")
    if start_wait_seconds is not None:
        args.extend(["-StartWaitSeconds", str(start_wait_seconds)])

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
    if command == "Build":
        errors = data.get("parsed_errors")
        warnings = data.get("parsed_warnings")
        if errors is not None:
            return f"{errors} error(s), {warnings} warning(s)"
        return str(data.get("summary") or "build completed")
    if command == "StartArsim":
        if data.get("started_new_process"):
            return f"started new ARsim (pid={data.get('process_id')})"
        return f"reused existing ARsim (pid={data.get('process_id')})"
    if command == "DescribePackage":
        parts = []
        for k in ("cpu_type", "ar_version", "runtime_type", "config_version"):
            v = data.get(k)
            if v:
                parts.append(str(v))
        return " / ".join(parts) if parts else "package described"
    if command == "Download":
        if data.get("executed"):
            return f"download {'OK' if data.get('download_ok') else 'FAILED'}"
        reasons = data.get("safety_check", {}).get("reasons") or data.get("reasons") or []
        if reasons:
            return f"blocked: {'; '.join(str(r) for r in reasons)}"
        return "execute not set — dry run"
    if command == "VerifyOpcUa":
        results = data.get("results") or []
        ok_count = sum(1 for item in results if item.get("ok"))
        return f"read {ok_count}/{len(results)} OPC UA nodes"
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
    if tool == "plc_build_project" and data.get("ok"):
        return ["Run plc_describe_ruc_package to inspect the built RUC package, then plc_check_download."]
    if tool == "plc_build_project" and not data.get("ok"):
        return ["Review the build error lines and fix the project before rebuilding."]
    if tool == "plc_start_arsim" and data.get("ok"):
        return ["Run plc_probe_target to verify the ARsim is ready."]
    if tool == "plc_describe_ruc_package" and data.get("ok"):
        return ["Run plc_check_download to verify compatibility before downloading."]
    if tool == "plc_download_ruc" and data.get("ok"):
        return ["Run plc_verify_opcua or plc_read_pvi to confirm the download was successful."]
    if tool == "plc_download_ruc" and not data.get("ok"):
        safety = data.get("safety_check") or {}
        if safety.get("ok") is False:
            return ["Fix the reported safety check issues before retrying the download."]
        return ["Check the download log and target connectivity, then retry."]
    if tool == "plc_verify_opcua" and not data.get("ok"):
        return ["Check OPC UA server status on the target, node IDs, and network connectivity. Try plc_read_pvi as a fallback."]
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


def plc_build_project(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    build_ruc = bool(arguments.get("build_ruc_package") or False)
    data = run_plc_toolchain(
        "Build",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        build_ruc_package=build_ruc,
        timeout_seconds=int(arguments.get("timeout_seconds") or 300),
    )
    return wrap_result("plc_build_project", "Build", data, target)


def plc_start_arsim(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    data = run_plc_toolchain(
        "StartArsim",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        start_wait_seconds=int(arguments.get("start_wait_seconds") or 3),
        timeout_seconds=int(arguments.get("timeout_seconds") or 30),
    )
    return wrap_result("plc_start_arsim", "StartArsim", data, target)


def plc_describe_ruc_package(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    data = run_plc_toolchain(
        "DescribePackage",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        package_path=arguments.get("package_path"),
        timeout_seconds=int(arguments.get("timeout_seconds") or 30),
    )
    return wrap_result("plc_describe_ruc_package", "DescribePackage", data, target)


def plc_download_ruc(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    execute = arguments.get("execute") is True
    data = run_plc_toolchain(
        "Download",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        package_path=arguments.get("package_path"),
        transfer_pil_path=arguments.get("transfer_pil_path"),
        execute=execute,
        timeout_seconds=int(arguments.get("timeout_seconds") or 180),
    )
    return wrap_result("plc_download_ruc", "Download", data, target)


def plc_verify_opcua(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    opcua_node_ids = arguments.get("opcua_node_ids")
    if opcua_node_ids is not None and not isinstance(opcua_node_ids, list):
        raise ValueError("opcua_node_ids must be an array of strings.")
    data = run_plc_toolchain(
        "VerifyOpcUa",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        opcua_node_ids=[str(item) for item in opcua_node_ids] if opcua_node_ids else None,
        timeout_seconds=int(arguments.get("timeout_seconds") or 60),
    )
    return wrap_result("plc_verify_opcua", "VerifyOpcUa", data, target)


TOOLS = {
    "plc_build_project": plc_build_project,
    "plc_start_arsim": plc_start_arsim,
    "plc_probe_target": plc_probe_target,
    "plc_describe_ruc_package": plc_describe_ruc_package,
    "plc_check_download": plc_check_download,
    "plc_download_ruc": plc_download_ruc,
    "plc_verify_opcua": plc_verify_opcua,
    "plc_read_pvi": plc_read_pvi,
}
