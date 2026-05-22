#!/usr/bin/env python
"""Read B&R PLC variables via PVI using hilch/Pvi.py."""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from typing import Any


def load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def parse_variable_spec(spec: Any) -> dict[str, Any]:
    if isinstance(spec, dict):
        item = dict(spec)
        raw_name = item.get("name") or item.get("variable") or item.get("node_id")
        if not raw_name:
            raise ValueError(f"Variable spec is missing 'name': {spec!r}")
        parsed = parse_variable_spec(str(raw_name))
        parsed.update({k: v for k, v in item.items() if v is not None})
        parsed["name"] = item.get("name") or parsed["name"]
        if item.get("task"):
            parsed["scope"] = "task"
            parsed["task"] = item["task"]
        return parsed

    text = str(spec).strip()
    if not text:
        raise ValueError("Empty variable spec")

    if ";s=" in text and text.lower().startswith("ns="):
        text = text.split(";s=", 1)[1]

    if text.startswith("::"):
        namespace, _, name = text[2:].partition(":")
        if namespace == "AsGlobalPV":
            return {"scope": "global", "name": name, "raw": str(spec)}
        if namespace and name:
            return {"scope": "task", "task": namespace, "name": name, "raw": str(spec)}

    if text.lower().startswith("task:"):
        _, task, name = text.split(":", 2)
        return {"scope": "task", "task": task, "name": name, "raw": str(spec)}

    if ":" in text:
        task, name = text.split(":", 1)
        if task and name and "." not in task:
            return {"scope": "task", "task": task, "name": name, "raw": str(spec)}

    return {"scope": "global", "name": text, "raw": str(spec)}


def normalize_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.rstrip(b"\x00").decode("utf-8", errors="replace")
    if isinstance(value, str) and value.startswith("b'"):
        try:
            decoded = ast.literal_eval(value)
            if isinstance(decoded, bytes):
                return normalize_value(decoded)
        except (SyntaxError, ValueError):
            pass
    if isinstance(value, (list, tuple)):
        return [normalize_value(v) for v in value]
    return value


def read_variables(args: argparse.Namespace, specs: list[Any]) -> dict[str, Any]:
    if args.pvi_dll_dir:
        os.environ["PVIPY_PVIDLLPATH"] = args.pvi_dll_dir

    from pvi import Connection, Cpu, Device, Line, PviError, Task, Variable

    connection = None
    results: list[dict[str, Any]] = []
    try:
        connection = Connection(timeout=args.manager_timeout)
        line = Line(connection.root, "LNANSL", CD="LNANSL")
        device = Device(line, "TCP", CD="/IF=TcpIp")
        cpu_cd = f"/IP={args.ip} /COMT={args.communication_timeout_ms} /PT={args.port}"
        cpu = Cpu(device, args.cpu_name, CD=cpu_cd)
        connection.sleep(args.connect_wait_ms)

        tasks: dict[str, Any] = {}
        for raw_spec in specs:
            result: dict[str, Any] = {"ok": False}
            try:
                spec = parse_variable_spec(raw_spec)
                result.update(
                    {
                        "scope": spec.get("scope", "global"),
                        "task": spec.get("task"),
                        "name": spec["name"],
                        "raw": spec.get("raw", raw_spec),
                    }
                )

                parent = cpu
                if result["scope"] == "task":
                    task_name = str(result["task"])
                    if task_name not in tasks:
                        tasks[task_name] = Task(cpu, task_name)
                    parent = tasks[task_name]

                variable = Variable(parent, spec["name"], RF=0)
                connection.sleep(args.variable_wait_ms)
                result["pvi_path"] = variable.name
                result["status"] = variable.status
                result["attributes"] = variable.attributes
                result["data_type"] = variable.dataType
                result["value"] = normalize_value(variable.value)
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
        "command": "ReadPvi",
        "ok": all(r.get("ok") for r in results) if results else False,
        "ip": args.ip,
        "port": args.port,
        "variables": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read B&R PLC variables via PVI.")
    parser.add_argument("--ip", required=True, help="PLC or ARsim IP address.")
    parser.add_argument("--port", type=int, default=11169, help="ANSL TCP port.")
    parser.add_argument("--variable", action="append", default=[], help="Variable spec. May be repeated.")
    parser.add_argument("--variables-file", help="JSON file containing variable specs.")
    parser.add_argument("--pvi-dll-dir", help="Directory containing PviCom64.dll.")
    parser.add_argument("--cpu-name", default="plc", help="Local PVI object name for the CPU.")
    parser.add_argument("--manager-timeout", type=int, default=5, help="PVI manager timeout in seconds.")
    parser.add_argument("--communication-timeout-ms", type=int, default=2500, help="PLC communication timeout.")
    parser.add_argument("--connect-wait-ms", type=int, default=1000, help="Initial wait after creating PVI objects.")
    parser.add_argument("--variable-wait-ms", type=int, default=50, help="Wait after creating each variable object.")
    args = parser.parse_args()

    specs: list[Any] = list(args.variable)
    if args.variables_file:
        file_specs = load_json_file(args.variables_file)
        if not isinstance(file_specs, list):
            raise TypeError("--variables-file must contain a JSON array.")
        specs.extend(file_specs)

    if not specs:
        raise ValueError("No PVI variables requested.")

    report = read_variables(args, specs)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"command": "ReadPvi", "ok": False, "error": repr(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)
