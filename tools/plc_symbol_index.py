#!/usr/bin/env python
"""Build and query a lightweight PLC variable catalog for Agent-directed access."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plc_access_policy import (
    access_policy,
    canonical_variable,
    matches_blocked_name,
    opcua_read_set,
    pvi_read_map,
    pvi_write_map,
)
from pvi_read import load_json_file


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = REPO_ROOT / "PrintDemo"
VAR_DECL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?);")


def is_task_variables_file(path: Path) -> bool:
    return path.name.lower() == "variables.var" and path.parent.name.lower() != "logical"


def module_from_variables_file(path: Path) -> str | None:
    if is_task_variables_file(path):
        return path.parent.name
    return None


def iter_var_blocks(text: str) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    current_kind: str | None = None
    current_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        upper = line.upper()
        if upper.startswith("VAR"):
            current_kind = upper
            current_lines = []
            continue
        if upper == "END_VAR" and current_kind is not None:
            blocks.append((current_kind, current_lines))
            current_kind = None
            current_lines = []
            continue
        if current_kind is not None:
            current_lines.append(raw_line)
    return blocks


def parse_variables_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    task = module_from_variables_file(path)
    variables: list[dict[str, Any]] = []
    for block_kind, lines in iter_var_blocks(text):
        is_constant = "CONSTANT" in block_kind
        for line in lines:
            stripped = line.split("//", 1)[0].strip()
            if not stripped or stripped.upper().startswith(("VAR", "END_VAR")):
                continue
            match = VAR_DECL_RE.match(stripped)
            if not match:
                continue
            name = match.group(1)
            type_expr = match.group(2).split(":=", 1)[0].strip()
            scope = "task" if task else "global"
            pvi = f"{task}:{name}" if task else name
            opcua = f"ns=5;s=::{task}:{name}" if task else f"ns=5;s=::AsGlobalPV:{name}"
            variables.append(
                {
                    "name": name,
                    "scope": scope,
                    "task": task,
                    "pvi": pvi,
                    "opcua": opcua,
                    "type": type_expr,
                    "constant": is_constant,
                    "source": str(path.relative_to(REPO_ROOT)),
                }
            )
    return variables


def build_catalog(config: dict[str, Any], targets_file: str, project_root: Path = DEFAULT_PROJECT_ROOT) -> dict[str, Any]:
    policy = access_policy(config)
    pvi_reads = pvi_read_map(config)
    pvi_writes = pvi_write_map(config)
    opcua_reads = opcua_read_set(config)
    variables: dict[str, dict[str, Any]] = {}

    logical_root = project_root / "Logical"
    for path in (logical_root.rglob("*.var") if logical_root.exists() else []):
        for item in parse_variables_file(path):
            key = item["pvi"]
            access = set()
            if item["pvi"] in pvi_reads or item["opcua"] in opcua_reads or policy["mode"] == "agent_directed":
                access.add("read")
            if item["pvi"] in pvi_writes or (policy["mode"] == "agent_directed" and not item["constant"]):
                access.add("write")
            if matches_blocked_name(item["pvi"], policy) or matches_blocked_name(item["opcua"], policy):
                access.discard("write")
                item["blocked_by_policy"] = True
            item["access"] = sorted(access)
            item["in_pvi_read_whitelist"] = item["pvi"] in pvi_reads
            item["in_pvi_write_whitelist"] = item["pvi"] in pvi_writes
            item["in_opcua_validation_nodes"] = item["opcua"] in opcua_reads
            variables[key] = item

    for variable, entry in pvi_reads.items():
        if variable not in variables:
            variables[variable] = {
                "name": variable.split(":", 1)[-1],
                "scope": "task" if ":" in variable else "global",
                "task": variable.split(":", 1)[0] if ":" in variable else None,
                "pvi": variable,
                "opcua": None,
                "type": entry.get("type"),
                "source": "tools target config",
                "access": ["read"],
                "in_pvi_read_whitelist": True,
                "in_pvi_write_whitelist": variable in pvi_writes,
                "in_opcua_validation_nodes": False,
            }

    for variable, entry in pvi_writes.items():
        item = variables.setdefault(
            variable,
            {
                "name": variable.split(":", 1)[-1],
                "scope": "task" if ":" in variable else "global",
                "task": variable.split(":", 1)[0] if ":" in variable else None,
                "pvi": variable,
                "opcua": None,
                "type": entry.get("type"),
                "source": "tools target config",
                "access": [],
            },
        )
        item["type"] = item.get("type") or entry.get("type")
        item["in_pvi_write_whitelist"] = True
        item["access"] = sorted(set(item.get("access") or []) | {"write"})

    return {
        "command": "ListVariables",
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "targets_file": str(Path(targets_file).resolve()),
        "access_policy": policy,
        "variables": sorted(variables.values(), key=lambda item: (str(item.get("task") or ""), str(item.get("name") or ""))),
    }


def filter_catalog(catalog: dict[str, Any], *, query: str | None, module: str | None, access: str | None) -> dict[str, Any]:
    terms = [term.lower() for term in re.split(r"\s+", query or "") if term.strip()]
    filtered = []
    for item in catalog.get("variables") or []:
        haystack = " ".join(str(item.get(key) or "") for key in ("name", "task", "pvi", "opcua", "type", "source")).lower()
        if terms and not all(term in haystack for term in terms):
            continue
        if module and str(item.get("task") or "").lower() != module.lower():
            continue
        if access and access not in set(item.get("access") or []):
            continue
        filtered.append(item)
    result = dict(catalog)
    result["command"] = "SearchVariables" if query or module or access else "ListVariables"
    result["query"] = query
    result["module"] = module
    result["access_filter"] = access
    result["variables"] = filtered
    result["count"] = len(filtered)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="List/search PLC variable catalog.")
    parser.add_argument("--targets-file", required=True)
    parser.add_argument("--query")
    parser.add_argument("--module")
    parser.add_argument("--access", choices=["read", "write"])
    parser.add_argument("--output-file")
    args = parser.parse_args()

    targets_path = Path(args.targets_file)
    if not targets_path.is_absolute():
        targets_path = REPO_ROOT / targets_path
    config = load_json_file(str(targets_path))
    catalog = build_catalog(config, str(targets_path))
    result = filter_catalog(catalog, query=args.query, module=args.module, access=args.access)

    if args.output_file:
        output = Path(args.output_file)
        if not output.is_absolute():
            output = REPO_ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        result["catalog_path"] = str(output)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
