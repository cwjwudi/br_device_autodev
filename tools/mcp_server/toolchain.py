from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PLC_TOOLCHAIN = REPO_ROOT / "tools" / "plc_toolchain.ps1"
GENERATED_DIR = REPO_ROOT / "tools" / ".generated"
DEFAULT_PROJECT_PATH = "PrintDemo\\Huitong_FrontEval.apj"
DEFAULT_CONFIG = "x1685"
DEFAULT_TARGETS_PATH = "tools\\plc_targets.local.json"


class ToolchainError(RuntimeError):
    def __init__(self, message: str, *, stdout: str = "", stderr: str = "", exit_code: int | None = None):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


def write_json_argument_file(prefix: str, payload: Any) -> str:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / f"{prefix}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def run_plc_toolchain(
    command: str,
    *,
    target: str = "arsim",
    project_path: str = DEFAULT_PROJECT_PATH,
    config: str = DEFAULT_CONFIG,
    targets_path: str = DEFAULT_TARGETS_PATH,
    package_path: str | None = None,
    transfer_pil_path: str | None = None,
    writes_path: str | None = None,
    suite_path: str | None = None,
    case_name: str | None = None,
    logger_type: str | None = None,
    logger_name: str | None = None,
    logger_format: str | None = None,
    output_path: str | None = None,
    pvi_variables: list[str] | None = None,
    opcua_node_ids: list[str] | None = None,
    build_ruc_package: bool = False,
    execute: bool = False,
    settle_ms: int | None = None,
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
    if writes_path:
        args.extend(["-WritesPath", writes_path])
    if suite_path:
        args.extend(["-SuitePath", suite_path])
    if case_name:
        args.extend(["-CaseName", case_name])
    if logger_type:
        args.extend(["-LoggerType", logger_type])
    if logger_name:
        args.extend(["-LoggerName", logger_name])
    if logger_format:
        args.extend(["-Format", logger_format])
    if output_path:
        args.extend(["-OutputPath", output_path])
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
    if settle_ms is not None:
        args.extend(["-SettleMs", str(settle_ms)])

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
    if command == "ReadLogger":
        if data.get("ok"):
            return f"read {data.get('logger_type')} / {data.get('logger_name')} logger to {data.get('format')}"
        return str(data.get("error_summary") or "logger read failed")
    if command == "WritePvi":
        writes = data.get("writes") or []
        ok_count = sum(1 for item in writes if item.get("ok"))
        if not data.get("executed"):
            return "write blocked: execute=true is required"
        return f"wrote {ok_count}/{len(writes)} PVI variables"
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
    if command == "RunVerificationSuite":
        method = data.get("method") or "unknown"
        return f"verification {'OK' if data.get('ok') else 'FAILED'} via {method}"
    if command == "RunIoTestCase":
        cases = data.get("cases") or []
        name = cases[0].get("name") if cases else data.get("case_name")
        return f"IO test case {name or ''} {'OK' if data.get('ok') else 'FAILED'}".strip()
    if command == "RunTestSuite":
        return f"IO suite {'OK' if data.get('ok') else 'FAILED'}: {data.get('cases_passed', 0)}/{data.get('cases_total', 0)} passed"
    if command == "ResetTestHarness":
        reset = data.get("reset") or data
        return f"test harness reset {'OK' if reset.get('ok') else 'FAILED'}"
    if command == "RunArsimClosedLoop":
        download = data.get("download") or {}
        if download.get("executed"):
            return f"ARsim closed loop {'OK' if data.get('ok') else 'FAILED'}"
        return "ARsim build/check completed; execute not set, no download performed"
    if command == "GetTargetConfig":
        target_config = data.get("target_config") or {}
        return f"{target_config.get('ip')} / {target_config.get('role')}"
    if command == "ListTargets":
        targets = data.get("targets") or []
        return f"{len(targets)} target(s) configured"
    return str(data.get("summary") or command)


def collect_logs(data: dict[str, Any]) -> list[str]:
    logs: list[str] = []
    for key in ("log_path", "pil_path", "output_path", "nodes_file", "variables_file", "writes_file", "suite_path", "report_path"):
        value = data.get(key)
        if value:
            if key == "output_path" and data.get("output_exists") is not True:
                continue
            logs.append(str(value))

    for nested_key in (
        "probe",
        "package",
        "safety_check",
        "build",
        "start_arsim",
        "target_probe",
        "download_check",
        "download",
        "verification",
        "opcua",
        "pvi",
        "reset",
        "suite_reset",
        "final_reset",
    ):
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
    if tool == "plc_read_logger" and data.get("ok"):
        return ["Open the generated logger report path for detailed diagnostics."]
    if tool == "plc_read_logger" and not data.get("ok"):
        return ["Check target reachability, logger.allowed_modules, and the PVITransfer log path."]
    if tool == "plc_write_pvi" and not data.get("ok"):
        return ["Do not retry writes until execute=true, target role, and pvi.write_whitelist have been checked."]
    if tool in ("plc_run_io_test_case", "plc_run_test_suite") and data.get("ok"):
        return ["Review the generated IO test report for writes, readback, checks, and restore results."]
    if tool in ("plc_run_io_test_case", "plc_run_test_suite") and not data.get("ok"):
        return ["Review the generated IO test report and confirm restore/reset completed before retrying."]
    if tool == "plc_reset_test_harness" and not data.get("ok"):
        return ["Check PVI connectivity and pvi.restore_writes before running IO tests."]
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
    if tool == "plc_run_arsim_closed_loop" and data.get("ok"):
        download = data.get("download") or {}
        if download.get("executed"):
            return ["Review the generated report path for build, download, and verification details."]
        return ["Re-run with execute=true if you want to download after reviewing the safety check."]
    if tool == "plc_run_verification_suite" and not data.get("ok"):
        return ["Review OPC UA and PVI results in the generated report."]
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


def plc_read_logger(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "test_plc")
    logger_type = str(arguments.get("logger_type") or "System")
    logger_name = str(arguments.get("logger_name") or "$arlogsys")
    logger_format = str(arguments.get("format") or ".html")
    output_path = arguments.get("output_path")
    if output_path is not None and not isinstance(output_path, str):
        raise ValueError("output_path must be a string.")
    data = run_plc_toolchain(
        "ReadLogger",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        logger_type=logger_type,
        logger_name=logger_name,
        logger_format=logger_format,
        output_path=output_path,
        timeout_seconds=int(arguments.get("timeout_seconds") or 150),
    )
    return wrap_result("plc_read_logger", "ReadLogger", data, target)


def plc_write_pvi(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    writes = arguments.get("writes")
    if not isinstance(writes, list) or not writes:
        raise ValueError("writes must be a non-empty array of {variable, value} objects.")
    writes_path = write_json_argument_file(f"mcp_write_pvi_{target}", writes)
    execute = arguments.get("execute") is True
    data = run_plc_toolchain(
        "WritePvi",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        writes_path=writes_path,
        execute=execute,
        timeout_seconds=int(arguments.get("timeout_seconds") or 90),
    )
    return wrap_result("plc_write_pvi", "WritePvi", data, target)


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


def plc_run_arsim_closed_loop(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    execute = arguments.get("execute") is True
    data = run_plc_toolchain(
        "RunArsimClosedLoop",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        execute=execute,
        timeout_seconds=int(arguments.get("timeout_seconds") or 600),
    )
    return wrap_result("plc_run_arsim_closed_loop", "RunArsimClosedLoop", data, target)


def plc_run_verification_suite(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    data = run_plc_toolchain(
        "RunVerificationSuite",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        timeout_seconds=int(arguments.get("timeout_seconds") or 120),
    )
    return wrap_result("plc_run_verification_suite", "RunVerificationSuite", data, target)


def plc_run_io_test_case(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "test_plc")
    case_name = arguments.get("case_name")
    if not case_name:
        raise ValueError("case_name is required.")
    execute = arguments.get("execute") is True
    data = run_plc_toolchain(
        "RunIoTestCase",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        suite_path=str(arguments.get("suite_path") or "tests\\plc\\lqr_io_tests.json"),
        case_name=str(case_name),
        execute=execute,
        settle_ms=int(arguments.get("settle_ms") or 100),
        timeout_seconds=int(arguments.get("timeout_seconds") or 180),
    )
    return wrap_result("plc_run_io_test_case", "RunIoTestCase", data, target)


def plc_run_test_suite(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "test_plc")
    execute = arguments.get("execute") is True
    data = run_plc_toolchain(
        "RunTestSuite",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        suite_path=str(arguments.get("suite_path") or "tests\\plc\\lqr_io_tests.json"),
        execute=execute,
        settle_ms=int(arguments.get("settle_ms") or 100),
        timeout_seconds=int(arguments.get("timeout_seconds") or 600),
    )
    return wrap_result("plc_run_test_suite", "RunTestSuite", data, target)


def plc_reset_test_harness(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "test_plc")
    execute = arguments.get("execute") is True
    data = run_plc_toolchain(
        "ResetTestHarness",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        suite_path=str(arguments.get("suite_path") or "tests\\plc\\lqr_io_tests.json"),
        execute=execute,
        timeout_seconds=int(arguments.get("timeout_seconds") or 120),
    )
    return wrap_result("plc_reset_test_harness", "ResetTestHarness", data, target)


def plc_get_target_config(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    data = run_plc_toolchain(
        "GetTargetConfig",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        timeout_seconds=int(arguments.get("timeout_seconds") or 30),
    )
    return wrap_result("plc_get_target_config", "GetTargetConfig", data, target)


def plc_list_targets(arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "arsim")
    data = run_plc_toolchain(
        "ListTargets",
        target=target,
        project_path=str(arguments.get("project_path") or DEFAULT_PROJECT_PATH),
        config=str(arguments.get("config") or DEFAULT_CONFIG),
        targets_path=str(arguments.get("targets_path") or DEFAULT_TARGETS_PATH),
        timeout_seconds=int(arguments.get("timeout_seconds") or 30),
    )
    return wrap_result("plc_list_targets", "ListTargets", data, target)


TOOLS = {
    "plc_build_project": plc_build_project,
    "plc_start_arsim": plc_start_arsim,
    "plc_probe_target": plc_probe_target,
    "plc_describe_ruc_package": plc_describe_ruc_package,
    "plc_check_download": plc_check_download,
    "plc_download_ruc": plc_download_ruc,
    "plc_verify_opcua": plc_verify_opcua,
    "plc_read_pvi": plc_read_pvi,
    "plc_read_logger": plc_read_logger,
    "plc_write_pvi": plc_write_pvi,
    "plc_run_arsim_closed_loop": plc_run_arsim_closed_loop,
    "plc_run_verification_suite": plc_run_verification_suite,
    "plc_run_io_test_case": plc_run_io_test_case,
    "plc_run_test_suite": plc_run_test_suite,
    "plc_reset_test_harness": plc_reset_test_harness,
    "plc_get_target_config": plc_get_target_config,
    "plc_list_targets": plc_list_targets,
}
