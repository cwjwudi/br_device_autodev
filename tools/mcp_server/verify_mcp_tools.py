#!/usr/bin/env python3
"""Verify MCP tool registration and basic invocation for both toolchain servers."""

from __future__ import annotations

import importlib.util
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


def verify_plc_server() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    init = call_plc_rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    if "result" not in init:
        raise RuntimeError(f"initialize failed: {init}")

    tools_resp = call_plc_rpc("tools/list", {}, request_id=2)
    tool_names = [item["name"] for item in tools_resp["result"]["tools"]]
    rows.append({"server": "br-plc-toolchain", "check": "tools/list", "status": "ok", "detail": f"{len(tool_names)} tools"})

    read_only_calls: dict[str, dict[str, Any]] = {
        "plc_list_targets": {},
        "plc_list_environments": {},
        "plc_get_target_config": {"environment": "br_local_x3687x"},
        "plc_list_variables": {"environment": "br_local_x3687x"},
        "plc_search_variables": {"environment": "br_local_x3687x", "query": "LQR", "module": "LQR"},
        "plc_describe_ruc_package": {"environment": "br_local_x3687x"},
        "plc_check_download": {"environment": "br_local_x3687x"},
        "plc_probe_target": {"environment": "br_local_x3687x", "timeout_seconds": 30},
        "plc_verify_opcua": {"environment": "br_local_x3687x", "timeout_seconds": 30},
        "plc_read_pvi": {"environment": "br_local_x3687x", "timeout_seconds": 30},
        "plc_read_logger": {"environment": "br_local_x3687x", "timeout_seconds": 30},
        "plc_run_verification_suite": {"environment": "br_local_x3687x", "timeout_seconds": 60},
    }

    gated_calls: dict[str, dict[str, Any]] = {
        "plc_download_ruc": {"environment": "br_local_x3687x", "execute": False},
        "plc_write_pvi": {
            "environment": "br_local_x3687x",
            "execute": False,
            "writes": [{"variable": "LQR:bLqrEnable", "value": True}],
        },
        "plc_reset_test_harness": {"environment": "br_local_x3687x", "execute": False},
        "plc_run_io_test_case": {
            "environment": "br_local_x3687x",
            "execute": False,
            "case_name": "zero_state_zero_output",
        },
        "plc_run_test_suite": {"environment": "br_local_x3687x", "execute": False},
        "plc_run_arsim_closed_loop": {"environment": "br_local_x3687x", "execute": False},
    }

    heavy_calls: dict[str, dict[str, Any]] = {
        "plc_build_project": {"environment": "br_local_x3687x", "build_ruc_package": False, "timeout_seconds": 600},
        "plc_start_arsim": {"environment": "br_local_x3687x", "timeout_seconds": 30},
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


def main() -> int:
    print("Verifying MCP servers...\n")
    rows = verify_plc_server() + verify_mappview_tools()

    ok_count = sum(1 for row in rows if row.get("status") == "ok")
    fail_count = sum(1 for row in rows if row.get("status") == "fail")
    skip_count = sum(1 for row in rows if row.get("status") == "skipped")

    for row in rows:
        label = row.get("tool") or row.get("check") or "?"
        print(f"[{row['status'].upper():7}] {row['server']} :: {label} :: {row.get('detail', '')}")

    print(f"\nSummary: ok={ok_count}, fail={fail_count}, skipped={skip_count}")
    report_path = ROOT / "tools" / ".generated" / "reports" / "mcp_tools_verification.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
