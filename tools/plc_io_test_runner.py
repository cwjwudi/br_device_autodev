#!/usr/bin/env python
"""Run PLC input/output tests through access-policy-gated PVI writes and reads."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from plc_access_policy import canonical_variable, pvi_read_map, validate_pvi_read
from pvi_read import load_json_file, read_variables
from pvi_write import load_target_config, validate_writes, write_variables


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = REPO_ROOT / "tools" / ".generated" / "reports"
FAILURE_STAGES = ("validation", "write", "read", "assert", "restore")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def add_failure(
    report: dict[str, Any],
    stage: str,
    message: str,
    *,
    details: Any | None = None,
) -> None:
    if stage not in FAILURE_STAGES:
        raise ValueError(f"Unsupported failure stage: {stage}")
    failure: dict[str, Any] = {"stage": stage, "message": message}
    if details is not None:
        failure["details"] = details
    report.setdefault("failures", []).append(failure)
    stages = report.setdefault("failure_stages", [])
    if stage not in stages:
        stages.append(stage)
    if report.get("failure_stage") is None or stage == "restore":
        report["failure_stage"] = stage


def reset_record(
    args: argparse.Namespace,
    config: dict[str, Any],
    *,
    phase: str,
    scope: str,
) -> dict[str, Any]:
    result = reset_harness(args, config)
    return {
        "stage": "restore",
        "phase": phase,
        "scope": scope,
        "ok": bool(result.get("ok")),
        "timestamp": iso_now(),
        "result": result,
    }


def pvi_args(args: argparse.Namespace) -> SimpleNamespace:
    config, _ = load_target_config(args.targets_file, args.target)
    pvi_config = config.get("pvi") or {}
    return SimpleNamespace(
        target=args.target,
        targets_file=args.targets_file,
        execute=args.execute,
        pvi_dll_dir=args.pvi_dll_dir or pvi_config.get("pvi_dll_dir"),
        port=args.port,
        cpu_name=args.cpu_name or args.target,
        manager_timeout=args.manager_timeout,
        communication_timeout_ms=args.communication_timeout_ms,
        connect_wait_ms=args.connect_wait_ms,
        variable_wait_ms=args.variable_wait_ms,
        write_wait_ms=args.write_wait_ms,
        ip=None,
    )


def read_args(args: argparse.Namespace) -> SimpleNamespace:
    config, target_config = load_target_config(args.targets_file, args.target)
    pvi_config = config.get("pvi") or {}
    return SimpleNamespace(
        ip=target_config["ip"],
        port=args.port,
        pvi_dll_dir=args.pvi_dll_dir or pvi_config.get("pvi_dll_dir"),
        cpu_name=args.cpu_name or args.target,
        manager_timeout=args.manager_timeout,
        communication_timeout_ms=args.communication_timeout_ms,
        connect_wait_ms=args.connect_wait_ms,
        variable_wait_ms=args.variable_wait_ms,
    )


def load_suite(path: str) -> dict[str, Any]:
    suite = load_json_file(path)
    if isinstance(suite, list):
        return {"name": Path(path).stem, "cases": suite}
    if not isinstance(suite, dict):
        raise TypeError("Test suite must be a JSON object or array.")
    suite.setdefault("name", Path(path).stem)
    suite.setdefault("cases", [])
    if not isinstance(suite["cases"], list):
        raise TypeError("Test suite 'cases' must be an array.")
    return suite


def validate_suite_structure(suite: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cases = suite.get("cases")
    if not isinstance(cases, list):
        return ["Test suite 'cases' must be an array."]
    if not cases:
        errors.append("Test suite must contain at least one case.")

    seen_names: set[str] = set()
    for index, case in enumerate(cases):
        label = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{label} must be an object.")
            continue
        name = case.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{label}.name must be a non-empty string.")
        elif name in seen_names:
            errors.append(f"Duplicate test case name: {name}")
        else:
            seen_names.add(name)

        settle_ms = case.get("settle_ms")
        if settle_ms is not None and (
            not isinstance(settle_ms, int) or isinstance(settle_ms, bool) or settle_ms < 0
        ):
            errors.append(f"{label}.settle_ms must be a non-negative integer.")

        writes = case.get("writes", [])
        if not isinstance(writes, list):
            errors.append(f"{label}.writes must be an array.")
        else:
            for write_index, item in enumerate(writes):
                if not isinstance(item, dict):
                    errors.append(f"{label}.writes[{write_index}] must be an object.")
                    continue
                if not item.get("variable") and not item.get("name"):
                    errors.append(
                        f"{label}.writes[{write_index}] must declare variable."
                    )
                if "value" not in item:
                    errors.append(f"{label}.writes[{write_index}] must declare value.")

        checks = case.get("checks", [])
        if not isinstance(checks, list):
            errors.append(f"{label}.checks must be an array.")
        else:
            for check_index, item in enumerate(checks):
                if not isinstance(item, dict) or not item.get("variable"):
                    errors.append(
                        f"{label}.checks[{check_index}] must be an object with variable."
                    )
    return errors


def read_whitelist(config: dict[str, Any]) -> set[str]:
    return set(pvi_read_map(config))


def base_check_variable(variable: str, allowed: set[str]) -> str | None:
    matches = [item for item in allowed if variable == item or variable.startswith(item + ".") or variable.startswith(item + "[")]
    if not matches:
        return None
    return max(matches, key=len)


def validate_case_access(config: dict[str, Any], target_config: dict[str, Any], case: dict[str, Any], execute: bool) -> list[str]:
    errors: list[str] = []
    writes = as_list(case.get("writes"))
    normalized_writes = []
    for item in writes:
        if not isinstance(item, dict):
            errors.append(f"Case '{case.get('name')}' has a non-object write item: {item!r}")
            continue
        variable = item.get("variable") or item.get("name")
        if not variable:
            errors.append(f"Case '{case.get('name')}' has a write item without variable.")
            continue
        normalized_writes.append({"variable": canonical_variable(variable), "value": item.get("value")})
    errors.extend(
        validate_writes(
            config=config,
            target_config=target_config,
            targets_file=str(config.get("_targets_file") or ""),
            writes=normalized_writes,
            execute=execute,
        )
    )

    read_variables_to_check = []
    for variable in as_list(case.get("readback")):
        key = canonical_variable(variable)
        read_variables_to_check.append(key)
    for check in as_list(case.get("checks")):
        variable = str(check.get("variable", ""))
        if not variable:
            errors.append(f"Case '{case.get('name')}' has a check without variable.")
            continue
        key = canonical_variable(variable)
        base = key.split("[", 1)[0].split(".", 1)[0]
        read_variables_to_check.append(base)
    errors.extend(
        validate_pvi_read(
            config=config,
            target_config=target_config,
            targets_file=str(config.get("_targets_file") or ""),
            variables=read_variables_to_check,
            explicit=True,
        )
    )
    return errors


def extract_value(value: Any, remainder: str, base_name: str) -> Any:
    current = value
    rest = remainder
    while rest:
        if rest.startswith("["):
            match = re.match(r"^\[(\d+)\](.*)$", rest)
            if not match:
                raise KeyError(rest)
            current = current[int(match.group(1))]
            rest = match.group(2)
            continue
        if rest.startswith("."):
            rest = rest[1:]
            match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)(.*)$", rest)
            if not match:
                raise KeyError(rest)
            field = match.group(1)
            if isinstance(current, dict):
                if field in current:
                    current = current[field]
                elif f".{field}" in current:
                    current = current[f".{field}"]
                elif f"{base_name}.{field}" in current:
                    current = current[f"{base_name}.{field}"]
                else:
                    raise KeyError(field)
            else:
                raise KeyError(field)
            rest = match.group(2)
            continue
        raise KeyError(rest)
    return current


def readback_map(read_report: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for item in read_report.get("variables") or []:
        if not item.get("ok"):
            continue
        if item.get("scope") == "task":
            key = f"{item.get('task')}:{item.get('name')}"
        else:
            key = str(item.get("name"))
        values[key] = item.get("value")
    return values


def actual_for_variable(values: dict[str, Any], variable: str) -> Any:
    key = canonical_variable(variable)
    candidates = [item for item in values if key == item or key.startswith(item + ".") or key.startswith(item + "[")]
    if not candidates:
        raise KeyError(variable)
    base = max(candidates, key=len)
    base_name = base.split(":", 1)[-1]
    return extract_value(values[base], key[len(base) :], base_name)


def compare_check(values: dict[str, Any], check: dict[str, Any]) -> dict[str, Any]:
    variable = str(check["variable"])
    expected = check.get("expected")
    tolerance = check.get("tolerance")
    comparison = str(check.get("comparison") or "equals")
    result: dict[str, Any] = {
        "variable": variable,
        "expected": expected,
        "tolerance": tolerance,
        "comparison": comparison,
        "ok": False,
    }
    try:
        actual = actual_for_variable(values, variable)
        result["actual"] = actual
        if comparison in ("equals", "eq"):
            if isinstance(expected, (int, float)) and isinstance(actual, (int, float)) and tolerance is not None:
                result["ok"] = math.isclose(float(actual), float(expected), abs_tol=float(tolerance), rel_tol=0.0)
            else:
                result["ok"] = actual == expected
        elif comparison == "approx":
            result["ok"] = math.isclose(float(actual), float(expected), abs_tol=float(tolerance or 0.0), rel_tol=0.0)
        elif comparison == "abs_le":
            result["ok"] = abs(float(actual)) <= float(expected)
        elif comparison == "le":
            result["ok"] = float(actual) <= float(expected)
        elif comparison == "ge":
            result["ok"] = float(actual) >= float(expected)
        else:
            result["error"] = f"Unsupported comparison: {comparison}"
    except Exception as exc:
        result["error"] = repr(exc)
    return result


def run_writes(args: argparse.Namespace, writes: list[dict[str, Any]]) -> dict[str, Any]:
    return write_variables(pvi_args(args), writes)


def run_reads(args: argparse.Namespace, variables: list[Any]) -> dict[str, Any]:
    return read_variables(read_args(args), variables)


def reset_harness(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    restore_writes = as_list((config.get("pvi") or {}).get("restore_writes"))
    if not restore_writes:
        return {
            "command": "ResetTestHarness",
            "ok": False,
            "executed": False,
            "error": "No pvi.restore_writes entries are configured.",
        }
    try:
        report = run_writes(args, restore_writes)
    except Exception as exc:
        report = {
            "ok": False,
            "executed": bool(args.execute),
            "error": f"Reset/restore raised an exception: {exc}",
        }
    report["command"] = "ResetTestHarness"
    return report


def run_case(args: argparse.Namespace, config: dict[str, Any], target_config: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    case_name = str(case.get("name") or "unnamed")
    case_report: dict[str, Any] = {
        "name": case_name,
        "ok": False,
        "started_at": iso_now(),
        "settle_ms": int(case.get("settle_ms", args.settle_ms)),
        "failure_stage": None,
        "failure_stages": [],
        "failures": [],
        "reset_records": [],
    }

    validation_errors = validate_case_access(config, target_config, case, args.execute)
    if validation_errors:
        case_report["validation_errors"] = validation_errors
        add_failure(
            case_report,
            "validation",
            "Test case validation failed.",
            details=validation_errors,
        )
        restore = reset_record(
            args, config, phase="after_validation_failure", scope=case_name
        )
        case_report["reset_records"].append(restore)
        case_report["restore"] = restore["result"]
        if not restore["ok"]:
            add_failure(case_report, "restore", "Restore after validation failure failed.")
        case_report["finished_at"] = iso_now()
        return case_report

    try:
        pre_reset = reset_record(args, config, phase="before_case", scope=case_name)
        case_report["reset_records"].append(pre_reset)
        case_report["pre_reset"] = pre_reset["result"]
        if not pre_reset["ok"]:
            case_report["error"] = "Pre-test reset failed."
            add_failure(case_report, "restore", case_report["error"])
            return case_report

        writes = as_list(case.get("writes"))
        try:
            case_report["writes"] = run_writes(args, writes)
        except Exception as exc:
            case_report["writes"] = {"ok": False, "error": str(exc)}
        if not case_report["writes"].get("ok"):
            case_report["error"] = "PVI write failed."
            add_failure(
                case_report,
                "write",
                case_report["error"],
                details=case_report["writes"].get("error"),
            )
            return case_report

        if case_report["settle_ms"] > 0:
            time.sleep(case_report["settle_ms"] / 1000.0)

        readback = as_list(case.get("readback"))
        if not readback:
            readback = list(read_whitelist(config))
        try:
            case_report["readback"] = run_reads(args, readback)
        except Exception as exc:
            case_report["readback"] = {"ok": False, "error": str(exc), "variables": []}
        if not case_report["readback"].get("ok"):
            add_failure(
                case_report,
                "read",
                "PVI readback failed.",
                details=case_report["readback"].get("error"),
            )
        values = readback_map(case_report["readback"])
        case_report["checks"] = [compare_check(values, check) for check in as_list(case.get("checks"))]
        failed_checks = [item for item in case_report["checks"] if not item.get("ok")]
        if failed_checks:
            add_failure(
                case_report,
                "assert",
                f"{len(failed_checks)} assertion(s) failed.",
                details=failed_checks,
            )
        case_report["ok"] = (
            bool(case_report["readback"].get("ok")) and not failed_checks
        )
    finally:
        restore = reset_record(args, config, phase="after_case", scope=case_name)
        case_report["reset_records"].append(restore)
        case_report["restore"] = restore["result"]
        case_report["finished_at"] = iso_now()
        if not restore["ok"]:
            case_report["ok"] = False
            case_report["restore_error"] = "Post-test restore/reset failed."
            add_failure(case_report, "restore", case_report["restore_error"])

    return case_report


def save_report(args: argparse.Namespace, report: dict[str, Any], name: str) -> dict[str, Any]:
    report_dir = Path(args.report_dir) if args.report_dir else DEFAULT_REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "io_test"
    path = report_dir / f"{utc_stamp()}_{safe_name}.json"
    report["report_path"] = str(path)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    config, target_config = load_target_config(args.targets_file, args.target)
    config["_targets_file"] = args.targets_file
    suite = load_suite(args.suite) if not args.reset_only else {"name": "reset_test_harness", "cases": []}

    report: dict[str, Any] = {
        "command": "ResetTestHarness" if args.reset_only else ("RunIoTestCase" if args.case_name else "RunTestSuite"),
        "ok": False,
        "target": args.target,
        "target_ip": target_config.get("ip"),
        "target_role": target_config.get("role"),
        "suite": suite.get("name"),
        "suite_path": str(Path(args.suite).resolve()) if args.suite else None,
        "generated_at": iso_now(),
        "execute": bool(args.execute),
        "failure_stage": None,
        "failure_stages": [],
        "failures": [],
        "reset_records": [],
    }

    if args.reset_only:
        reset = reset_record(
            args, config, phase="manual_reset", scope="test_harness"
        )
        report["reset_records"].append(reset)
        report["reset"] = reset["result"]
        report["ok"] = reset["ok"]
        if not reset["ok"]:
            add_failure(report, "restore", "Manual test harness reset failed.")
        return save_report(args, report, f"reset_test_harness_{args.target}")

    fixture = suite.get("fixture")
    if not isinstance(fixture, dict):
        fixture = {
            "name": suite.get("name"),
            "mode": "direct_variable_access",
            "dedicated": False,
            "reset_strategy": "pvi.restore_writes",
        }
        report.setdefault("warnings", []).append(
            "Suite has no explicit fixture metadata; treating it as legacy direct variable access."
        )
    report["fixture"] = fixture
    if fixture.get("dedicated") is not True:
        report.setdefault("warnings", []).append(
            "Suite fixture is not a dedicated TestHarness interface; migrate business variables behind a controlled harness when practical."
        )

    suite_validation_errors = validate_suite_structure(suite)
    if suite_validation_errors:
        report["validation_errors"] = suite_validation_errors
        add_failure(
            report,
            "validation",
            "Test suite structure validation failed.",
            details=suite_validation_errors,
        )
        return save_report(args, report, f"io_test_{suite.get('name')}")

    cases = list(suite.get("cases") or [])
    if args.case_name:
        cases = [case for case in cases if case.get("name") == args.case_name]
        if not cases:
            report["error"] = f"Test case '{args.case_name}' was not found."
            add_failure(report, "validation", report["error"])
            return save_report(args, report, f"io_test_{suite.get('name')}")

    if str(target_config.get("role", "")).lower() == "production":
        report["error"] = "Refusing to run IO tests on a production target."
        add_failure(report, "validation", report["error"])
        return save_report(args, report, f"io_test_{suite.get('name')}")

    suite_reset = reset_record(args, config, phase="before_suite", scope=str(suite.get("name")))
    report["reset_records"].append(suite_reset)
    report["suite_reset"] = suite_reset["result"]
    if suite_reset["ok"]:
        report["cases"] = [
            run_case(args, config, target_config, case) for case in cases
        ]
    else:
        report["cases"] = []
        add_failure(report, "restore", "Pre-suite reset failed; cases were not executed.")

    final_reset = reset_record(args, config, phase="after_suite", scope=str(suite.get("name")))
    report["reset_records"].append(final_reset)
    report["final_reset"] = final_reset["result"]
    if not final_reset["ok"]:
        add_failure(report, "restore", "Final suite restore/reset failed.")

    for case_report in report["cases"]:
        report["reset_records"].extend(case_report.get("reset_records") or [])
        for failure in case_report.get("failures") or []:
            stage = failure.get("stage")
            if stage in FAILURE_STAGES and stage not in report["failure_stages"]:
                report["failure_stages"].append(stage)
        if case_report.get("failure_stage") == "restore":
            report["failure_stage"] = "restore"
        elif report["failure_stage"] is None and case_report.get("failure_stage"):
            report["failure_stage"] = case_report["failure_stage"]

    report["cases_total"] = len(cases)
    report["cases_executed"] = len(report["cases"])
    report["cases_skipped"] = report["cases_total"] - report["cases_executed"]
    report["cases_passed"] = sum(1 for case in report["cases"] if case.get("ok"))
    report["cases_failed"] = report["cases_total"] - report["cases_passed"]
    report["ok"] = (
        suite_reset["ok"]
        and final_reset["ok"]
        and report["cases_failed"] == 0
    )
    return save_report(args, report, f"io_test_{suite.get('name')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PLC IO test cases through PVI.")
    parser.add_argument("--target", required=True, help="Target name from the selected target configuration.")
    parser.add_argument("--targets-file", required=True, help="Toolchain target configuration JSON.")
    parser.add_argument("--suite", default="tests/plc/lqr_io_tests.json", help="PLC test suite JSON file.")
    parser.add_argument("--case-name", help="Run only one case from the suite.")
    parser.add_argument("--reset-only", action="store_true", help="Only run pvi.restore_writes.")
    parser.add_argument("--execute", action="store_true", help="Required to perform writes.")
    parser.add_argument("--report-dir", help="Directory for JSON reports.")
    parser.add_argument("--settle-ms", type=int, default=100, help="Default wait after writes.")
    parser.add_argument("--port", type=int, default=11169, help="ANSL TCP port.")
    parser.add_argument("--pvi-dll-dir", help="Directory containing PviCom64.dll.")
    parser.add_argument("--cpu-name", default="plc", help="Local PVI object name for the CPU.")
    parser.add_argument("--manager-timeout", type=int, default=5, help="PVI manager timeout in seconds.")
    parser.add_argument("--communication-timeout-ms", type=int, default=2500, help="PLC communication timeout.")
    parser.add_argument("--connect-wait-ms", type=int, default=1000, help="Initial wait after creating PVI objects.")
    parser.add_argument("--variable-wait-ms", type=int, default=50, help="Wait after creating each variable object.")
    parser.add_argument("--write-wait-ms", type=int, default=50, help="Wait after each write before readback.")
    args = parser.parse_args()

    try:
        report = run(args)
    except Exception as exc:
        report = {
            "command": "ResetTestHarness"
            if args.reset_only
            else ("RunIoTestCase" if args.case_name else "RunTestSuite"),
            "ok": False,
            "target": args.target,
            "suite_path": str(Path(args.suite).resolve()) if args.suite else None,
            "generated_at": iso_now(),
            "execute": bool(args.execute),
            "failure_stage": "validation",
            "failure_stages": ["validation"],
            "failures": [
                {
                    "stage": "validation",
                    "message": "Test request could not be loaded or validated.",
                    "details": repr(exc),
                }
            ],
            "reset_records": [],
            "error": repr(exc),
        }
        report = save_report(args, report, "io_test_validation_failure")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
