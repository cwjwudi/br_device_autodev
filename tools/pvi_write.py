#!/usr/bin/env python
"""Write B&R PLC variables via PVI with access-policy gates."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from plc_access_policy import canonical_variable, pvi_write_map, validate_pvi_write
from pvi_read import load_json_file, normalize_value, parse_variable_spec


def load_target_config(targets_file: str, target: str) -> tuple[dict[str, Any], dict[str, Any]]:
    config = load_json_file(targets_file)
    targets = config.get("targets") or {}
    target_config = targets.get(target)
    if not target_config:
        raise ValueError(f"Target '{target}' was not found in {targets_file}.")
    return config, target_config


def normalize_write_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"Write item must be an object: {item!r}")
    variable = item.get("variable") or item.get("name")
    if not variable:
        raise ValueError(f"Write item is missing 'variable': {item!r}")
    if "value" not in item:
        raise ValueError(f"Write item for '{variable}' is missing 'value'.")
    parsed = parse_variable_spec(variable)
    return {
        "variable": canonical_variable(variable),
        "raw": variable,
        "scope": parsed.get("scope", "global"),
        "task": parsed.get("task"),
        "name": parsed["name"],
        "value": item["value"],
    }


def coerce_scalar(value: Any, declared_type: str | None) -> Any:
    dtype = (declared_type or "").upper()
    if dtype.startswith("BOOL"):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if dtype.startswith(("REAL", "LREAL")):
        return float(value)
    if dtype.startswith(("USINT", "UINT", "UDINT", "ULINT", "SINT", "INT", "DINT", "LINT")):
        return int(value)
    return value


def coerce_value(value: Any, declared_type: str | None) -> Any:
    if isinstance(value, list):
        return [coerce_scalar(item, declared_type) for item in value]
    return coerce_scalar(value, declared_type)


def validate_writes(
    *,
    config: dict[str, Any],
    target_config: dict[str, Any],
    targets_file: str,
    writes: list[dict[str, Any]],
    execute: bool,
) -> list[str]:
    return validate_pvi_write(
        config=config,
        target_config=target_config,
        targets_file=targets_file,
        variables=[item["variable"] for item in writes],
        execute=execute,
    )


def write_variables(args: argparse.Namespace, writes: list[dict[str, Any]]) -> dict[str, Any]:
    config, target_config = load_target_config(args.targets_file, args.target)
    normalized_writes = [normalize_write_item(item) for item in writes]
    validation_errors = validate_writes(
        config=config,
        target_config=target_config,
        targets_file=args.targets_file,
        writes=normalized_writes,
        execute=args.execute,
    )
    if validation_errors:
        return {
            "command": "WritePvi",
            "ok": False,
            "executed": False,
            "target": args.target,
            "target_ip": target_config.get("ip"),
            "target_role": target_config.get("role"),
            "errors": validation_errors,
            "writes": normalized_writes,
        }

    if args.pvi_dll_dir:
        os.environ["PVIPY_PVIDLLPATH"] = args.pvi_dll_dir
    elif (config.get("pvi") or {}).get("pvi_dll_dir"):
        os.environ["PVIPY_PVIDLLPATH"] = str((config.get("pvi") or {})["pvi_dll_dir"])

    from pvi import Connection, Cpu, Device, Line, PviError, Task, Variable

    allowed = pvi_write_map(config)
    connection = None
    results: list[dict[str, Any]] = []
    try:
        connection = Connection(timeout=args.manager_timeout)
        line = Line(connection.root, "LNANSL", CD="LNANSL")
        device = Device(line, "TCP", CD="/IF=TcpIp")
        cpu_cd = f"/IP={target_config['ip']} /COMT={args.communication_timeout_ms} /PT={args.port}"
        cpu = Cpu(device, args.cpu_name or args.target, CD=cpu_cd)
        connection.sleep(args.connect_wait_ms)

        tasks: dict[str, Any] = {}
        for item in normalized_writes:
            result: dict[str, Any] = {
                "ok": False,
                "variable": item["variable"],
                "scope": item["scope"],
                "task": item.get("task"),
                "name": item["name"],
                "requested_value": item["value"],
            }
            try:
                parent = cpu
                if item["scope"] == "task":
                    task_name = str(item["task"])
                    if task_name not in tasks:
                        tasks[task_name] = Task(cpu, task_name)
                    parent = tasks[task_name]

                variable = Variable(parent, item["name"], RF=0)
                connection.sleep(args.variable_wait_ms)
                result["data_type"] = variable.dataType
                result["before"] = normalize_value(variable.value)
                declared_type = (allowed.get(item["variable"]) or {}).get("type")
                variable.value = coerce_value(item["value"], declared_type)
                connection.sleep(args.write_wait_ms)
                result["readback"] = normalize_value(variable.value)
                result["status"] = variable.status
                result["ok"] = True
            except PviError as exc:
                result["error"] = str(exc)
            except Exception as exc:
                result["error"] = repr(exc)
            results.append(result)
    finally:
        if connection is not None:
            try:
                connection.stop()
            except Exception:
                pass

    return {
        "command": "WritePvi",
        "ok": all(item.get("ok") for item in results) if results else False,
        "executed": True,
        "target": args.target,
        "target_ip": target_config.get("ip"),
        "target_role": target_config.get("role"),
        "writes": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Write whitelisted B&R PLC test variables via PVI.")
    parser.add_argument("--target", required=True, help="Target name from tools/plc_targets.local.json.")
    parser.add_argument("--targets-file", required=True, help="Toolchain target configuration JSON.")
    parser.add_argument("--writes-file", required=True, help="JSON file containing write objects.")
    parser.add_argument("--execute", action="store_true", help="Required to perform writes.")
    parser.add_argument("--port", type=int, default=11169, help="ANSL TCP port.")
    parser.add_argument("--pvi-dll-dir", help="Directory containing PviCom64.dll.")
    parser.add_argument("--cpu-name", default="plc", help="Local PVI object name for the CPU.")
    parser.add_argument("--manager-timeout", type=int, default=5, help="PVI manager timeout in seconds.")
    parser.add_argument("--communication-timeout-ms", type=int, default=2500, help="PLC communication timeout.")
    parser.add_argument("--connect-wait-ms", type=int, default=1000, help="Initial wait after creating PVI objects.")
    parser.add_argument("--variable-wait-ms", type=int, default=50, help="Wait after creating each variable object.")
    parser.add_argument("--write-wait-ms", type=int, default=50, help="Wait after each write before readback.")
    args = parser.parse_args()

    writes = load_json_file(args.writes_file)
    if isinstance(writes, dict):
        writes = [writes]
    if not isinstance(writes, list):
        raise TypeError("--writes-file must contain a JSON array or object.")

    report = write_variables(args, writes)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"command": "WritePvi", "ok": False, "executed": False, "error": repr(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)
