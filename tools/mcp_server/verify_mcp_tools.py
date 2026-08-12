#!/usr/bin/env python3
"""Verify MCP tool registration and basic invocation for both toolchain servers."""

from __future__ import annotations

import importlib.util
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLC_SERVER = ROOT / "tools" / "mcp_server" / "server.py"
MAPPVIEW_SERVER = ROOT.parent / "mappview-ai-kb" / "mcp-server" / "server.py"
MAPPVIEW_KB = ROOT.parent / "mappview-ai-kb" / "mcp-server" / "kb.py"


def call_plc_rpc(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    completed = subprocess.run(
        [sys.executable, str(PLC_SERVER)],
        input=json.dumps(payload) + "\n",
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0 and not completed.stdout.strip():
        raise RuntimeError(f"PLC MCP server failed: {completed.stderr.strip()}")
    line = completed.stdout.strip().splitlines()[-1]
    return json.loads(line)


def parse_plc_tool_result(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result") or {}
    text = result.get("content", [{}])[0].get("text", "{}")
    return json.loads(text)


def verify_plc_server(
    *,
    environment: str | None = None,
    execute: bool = False,
    project_path: str | None = None,
    config: str | None = None,
    targets_path: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    init = call_plc_rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    if "result" not in init:
        raise RuntimeError(f"initialize failed: {init}")

    tools_resp = call_plc_rpc("tools/list", {}, request_id=2)
    tool_names = [item["name"] for item in tools_resp["result"]["tools"]]
    rows.append({"server": "br-plc-toolchain", "check": "tools/list", "status": "ok", "detail": f"{len(tool_names)} tools"})

    if not environment:
        gate_response = call_plc_rpc(
            "tools/call",
            {"name": "plc_start_arsim", "arguments": {"target": "arsim", "execute": False}},
            request_id=3,
        )
        gate_payload = parse_plc_tool_result(gate_response)
        gate_ok = (gate_payload.get("ok") is False and "execute=true" in json.dumps(gate_payload, ensure_ascii=False))
        rows.append(
            {
                "server": "br-plc-toolchain",
                "check": "confirmation gate",
                "status": "ok" if gate_ok else "fail",
                "detail": "State-changing ARsim start remains blocked without execute=true.",
            }
        )
        rows.append(
            {
                "server": "br-plc-toolchain",
                "check": "external PLC smoke tests",
                "status": "skipped",
                "detail": "Pass --environment to run environment-dependent checks.",
            }
        )
        rows.append(
            {
                "server": "br-plc-toolchain",
                "check": "target-change smoke tests",
                "status": "skipped",
                "detail": "Pass --environment and --execute to run state-changing checks.",
            }
        )
        return rows

    def scoped(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = {"environment": environment}
        if project_path:
            result["project_path"] = project_path
        if config:
            result["config"] = config
        if targets_path:
            result["targets_path"] = targets_path
        result.update(arguments or {})
        return result

    read_only_calls: dict[str, dict[str, Any]] = {
        "plc_list_targets": scoped(),
        "plc_list_environments": {},
        "plc_get_target_config": scoped(),
        "plc_list_variables": scoped(),
        "plc_search_variables": scoped({"query": "LQR", "module": "LQR"}),
        "plc_describe_ruc_package": scoped(),
        "plc_check_download": scoped(),
        "plc_probe_target": scoped({"timeout_seconds": 30}),
        "plc_verify_opcua": scoped({"timeout_seconds": 30}),
        "plc_read_pvi": scoped({"timeout_seconds": 30}),
        "plc_read_logger": scoped({"timeout_seconds": 30}),
        "plc_run_verification_suite": scoped({"timeout_seconds": 60}),
    }

    gated_calls: dict[str, dict[str, Any]] = {
        "plc_download_ruc": scoped({"execute": False}),
        "plc_write_pvi": scoped({
            "execute": False,
            "writes": [{"variable": "LQR:bLqrEnable", "value": True}],
        }),
        "plc_reset_test_harness": scoped({"execute": False}),
        "plc_run_io_test_case": scoped({
            "execute": False,
            "case_name": "zero_state_zero_output",
        }),
        "plc_run_test_suite": scoped({"execute": False}),
        "plc_run_arsim_closed_loop": scoped({"execute": False}),
    }

    heavy_calls: dict[str, dict[str, Any]] = {}
    if execute:
        heavy_calls = {
            "plc_build_project": scoped({"build_ruc_package": False, "timeout_seconds": 600}),
            "plc_start_arsim": scoped({"execute": True, "timeout_seconds": 30}),
        }

    request_id = 3
    for name in tool_names:
        if name in read_only_calls:
            args = read_only_calls[name]
        elif name in gated_calls:
            args = gated_calls[name]
        elif name in heavy_calls:
            args = heavy_calls[name]
        else:
            rows.append({"server": "br-plc-toolchain", "tool": name, "status": "skipped", "detail": "no smoke-test mapping"})
            continue

        response = call_plc_rpc("tools/call", {"name": name, "arguments": args}, request_id=request_id)
        request_id += 1
        payload = parse_plc_tool_result(response)
        ok = bool(payload.get("ok"))
        if name in gated_calls and not args.get("execute"):
            ok = ok or "execute" in json.dumps(payload, ensure_ascii=False).lower() or payload.get("executed") is False
        rows.append(
            {
                "server": "br-plc-toolchain",
                "tool": name,
                "status": "ok" if ok else "fail",
                "detail": payload.get("summary") or payload.get("error") or str(payload)[:200],
            }
        )

    missing = [name for name in tool_names if not any(row.get("tool") == name for row in rows)]
    for name in missing:
        rows.append({"server": "br-plc-toolchain", "tool": name, "status": "missing", "detail": "not exercised"})

    return rows


def verify_mappview_tools() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    spec = importlib.util.spec_from_file_location("kb", MAPPVIEW_KB)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import knowledge base module: {MAPPVIEW_KB}")
    kb_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kb_mod)
    kb = kb_mod.KnowledgeBase()

    checks = [
        ("list_widgets", lambda: kb.list_widgets()),
        ("list_widgets(chart)", lambda: kb.list_widgets(category="chart")),
        ("get_widget", lambda: kb.get_widget("Paper")),
        ("search_properties", lambda: kb.search_properties("transform", bindable_only=True, limit=5)),
        ("get_datatype", lambda: kb.get_datatype("Boolean")),
        ("get_enum", lambda: kb.get_enum("ImageAlign")),
        ("list_categories", lambda: kb.list_categories()),
    ]
    for name, fn in checks:
        try:
            result = fn()
            ok = bool(result)
            rows.append({"server": "mappview-widgets", "tool": name, "status": "ok" if ok else "fail", "detail": f"items={len(result) if hasattr(result, '__len__') else 1}"})
        except Exception as exc:
            rows.append({"server": "mappview-widgets", "tool": name, "status": "fail", "detail": str(exc)})

    completed = subprocess.run(
        [sys.executable, "-c", "import mcp.server.fastmcp"],
        capture_output=True,
        text=True,
        check=False,
    )
    rows.append(
        {
            "server": "mappview-widgets",
            "check": "fastmcp import",
            "status": "ok" if completed.returncode == 0 else "fail",
            "detail": completed.stderr.strip() or "mcp package available",
        }
    )

    if completed.returncode == 0:
        rows.append(
            {
                "server": "mappview-widgets",
                "check": "server.py import",
                "status": "ok" if MAPPVIEW_SERVER.exists() else "fail",
                "detail": str(MAPPVIEW_SERVER),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify MCP server contracts and optional PLC smoke tests.")
    parser.add_argument("--environment", help="Configured environment for external PLC smoke tests.")
    parser.add_argument("--project-path", help="Optional project path override for a configured environment.")
    parser.add_argument("--config", help="Optional Automation Studio configuration override.")
    parser.add_argument("--targets-path", help="Optional target configuration override.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Allow state-changing smoke tests; requires --environment.",
    )
    parser.add_argument("--plc-only", action="store_true", help="Skip the mappview server checks.")
    parser.add_argument("--report-path", help="Optional JSON report path; defaults to var/reports/mcp_tools_verification.json.")
    args = parser.parse_args(argv)
    if args.execute and not args.environment:
        parser.error("--execute requires --environment")

    print("Verifying MCP servers...\n")
    rows = verify_plc_server(
        environment=args.environment,
        execute=args.execute,
        project_path=args.project_path,
        config=args.config,
        targets_path=args.targets_path,
    )
    if not args.plc_only:
        rows += verify_mappview_tools()

    ok_count = sum(1 for row in rows if row.get("status") == "ok")
    fail_count = sum(1 for row in rows if row.get("status") == "fail")
    skip_count = sum(1 for row in rows if row.get("status") == "skipped")

    for row in rows:
        label = row.get("tool") or row.get("check") or "?"
        print(f"[{row['status'].upper():7}] {row['server']} :: {label} :: {row.get('detail', '')}")

    print(f"\nSummary: ok={ok_count}, fail={fail_count}, skipped={skip_count}")
    report_path = Path(args.report_path) if args.report_path else ROOT / "var" / "reports" / "mcp_tools_verification.json"
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
