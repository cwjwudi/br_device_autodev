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
DEFAULT_PROJECT_ROOT = REPO_ROOT
VAR_DECL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?);")
GENERATED_DECL_RE = re.compile(
    r"^\s*(?P<storage>_BUR_LOCAL|_LOCAL|_GLOBAL|_GLOBAL_CONST)\s+"
    r"(?P<type>.+?)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<array>\[[^\]]+\])?\s*;"
)
C_TO_IEC_TYPES = {
    "plcbit": "BOOL",
    "signed char": "SINT",
    "unsigned char": "USINT",
    "signed short": "INT",
    "unsigned short": "UINT",
    "signed long": "DINT",
    "unsigned long": "UDINT",
    "float": "REAL",
    "double": "LREAL",
}


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
                    "source": relative_path(path),
                }
            )
    return variables


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def generated_iec_type(c_type: str, array_suffix: str | None) -> str:
    normalized = " ".join(c_type.strip().split())
    if normalized.startswith("struct "):
        result = normalized.removeprefix("struct ").strip()
    else:
        result = C_TO_IEC_TYPES.get(normalized, normalized)
    if array_suffix:
        result += array_suffix
    return result


def parse_generated_header(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    source_match = re.search(r"iecfile.*?(Logical/[^\\\"]+\.var)", text)
    scope_match = re.search(r"scope.*?(local|global)", text, flags=re.IGNORECASE)
    if not source_match or not scope_match:
        return []

    source = source_match.group(1)
    generated_scope = scope_match.group(1).lower()
    scope = "task" if generated_scope == "local" else "global"
    task = Path(source).parent.name if scope == "task" else None
    variables: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = GENERATED_DECL_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        pvi = f"{task}:{name}" if task else name
        opcua = f"ns=5;s=::{task}:{name}" if task else f"ns=5;s=::AsGlobalPV:{name}"
        variables.append(
            {
                "name": name,
                "scope": scope,
                "task": task,
                "pvi": pvi,
                "opcua": opcua,
                "type": generated_iec_type(match.group("type"), match.group("array")),
                "constant": match.group("storage") == "_GLOBAL_CONST",
                "source": source,
                "artifact_source": relative_path(path),
                "catalog_source": "automation_studio_generated_header",
                "confidence": "high",
                "generated_from": [relative_path(path), source],
            }
        )
    return variables


def build_artifact_variables(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    include_root = project_root / "Temp" / "Includes"
    symbol_map = project_root / "Temp" / "Objects" / "Symbols.map"
    headers = sorted(include_root.rglob("*var.h")) if include_root.exists() else []
    source_files = sorted((project_root / "Logical").rglob("*.var")) if (project_root / "Logical").exists() else []
    warnings: list[str] = []

    if not headers:
        return [], {
            "catalog_source": "source_scan",
            "confidence": "low",
            "generated_from": [],
            "warnings": [
                "Automation Studio generated variable headers were not found; catalog fell back to source scanning."
            ],
        }

    newest_header = max(path.stat().st_mtime for path in headers)
    newer_sources = [path for path in source_files if path.stat().st_mtime > newest_header + 1.0]
    if newer_sources:
        return [], {
            "catalog_source": "source_scan",
            "confidence": "low",
            "generated_from": [relative_path(path) for path in headers],
            "warnings": [
                "Automation Studio generated headers are older than one or more .var sources; catalog fell back to source scanning.",
                *[
                    f"Source is newer than build artifacts: {relative_path(path)}"
                    for path in newer_sources[:10]
                ],
            ],
        }

    variables: list[dict[str, Any]] = []
    used_headers: list[Path] = []
    for header in headers:
        parsed = parse_generated_header(header)
        if parsed:
            variables.extend(parsed)
            used_headers.append(header)
    if not variables:
        return [], {
            "catalog_source": "source_scan",
            "confidence": "low",
            "generated_from": [relative_path(path) for path in headers],
            "warnings": [
                "Automation Studio headers were present but contained no supported variable declarations; catalog fell back to source scanning."
            ],
        }

    confidence = "high" if symbol_map.exists() else "medium"
    if not symbol_map.exists():
        warnings.append(
            "Symbols.map was not found; generated headers were used with medium catalog confidence."
        )
        for item in variables:
            item["confidence"] = "medium"
    generated_from = [relative_path(path) for path in used_headers]
    if symbol_map.exists():
        generated_from.append(relative_path(symbol_map))
    return variables, {
        "catalog_source": "automation_studio_build_artifacts",
        "confidence": confidence,
        "generated_from": generated_from,
        "warnings": warnings,
    }


def build_catalog(config: dict[str, Any], targets_file: str, project_root: Path = DEFAULT_PROJECT_ROOT) -> dict[str, Any]:
    policy = access_policy(config)
    pvi_reads = pvi_read_map(config)
    pvi_writes = pvi_write_map(config)
    opcua_reads = opcua_read_set(config)
    variables: dict[str, dict[str, Any]] = {}

    source_items, provenance = build_artifact_variables(project_root)
    if not source_items:
        logical_root = project_root / "Logical"
        source_paths = sorted(logical_root.rglob("*.var")) if logical_root.exists() else []
        for path in source_paths:
            for item in parse_variables_file(path):
                item["catalog_source"] = "source_scan"
                item["confidence"] = "low"
                item["generated_from"] = [relative_path(path)]
                source_items.append(item)
        provenance["generated_from"] = list(
            dict.fromkeys(
                [*(provenance.get("generated_from") or []), *[relative_path(path) for path in source_paths]]
            )
        )
        if not source_items:
            provenance.setdefault("warnings", []).append(
                "No PLC variables were discovered in build artifacts or source .var files."
            )

    for item in source_items:
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
                "catalog_source": "target_config",
                "confidence": "configured",
                "generated_from": [str(Path(targets_file).resolve())],
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
                "catalog_source": "target_config",
                "confidence": "configured",
                "generated_from": [str(Path(targets_file).resolve())],
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
        "catalog_source": provenance["catalog_source"],
        "confidence": provenance["confidence"],
        "generated_from": provenance["generated_from"],
        "warnings": provenance["warnings"],
        "variables": sorted(variables.values(), key=lambda item: (str(item.get("task") or ""), str(item.get("name") or ""))),
    }


def filter_catalog(
    catalog: dict[str, Any],
    *,
    query: str | None,
    module: str | None,
    access: str | None,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
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
    matched_count = len(filtered)
    safe_offset = max(0, offset)
    page = filtered[safe_offset:] if limit is None else filtered[safe_offset : safe_offset + max(1, limit)]
    result = dict(catalog)
    result["command"] = "SearchVariables" if query or module or access else "ListVariables"
    result["query"] = query
    result["module"] = module
    result["access_filter"] = access
    result["variables"] = page
    result["count"] = len(page)
    result["matched_count"] = matched_count
    result["total_count"] = len(catalog.get("variables") or [])
    result["offset"] = safe_offset
    result["limit"] = limit
    result["truncated"] = safe_offset + len(page) < matched_count
    result["next_offset"] = safe_offset + len(page) if result["truncated"] else None
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="List/search PLC variable catalog.")
    parser.add_argument("--targets-file", required=True)
    parser.add_argument("--query")
    parser.add_argument("--module")
    parser.add_argument("--access", choices=["read", "write"])
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-file")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    args = parser.parse_args()

    targets_path = Path(args.targets_file)
    if not targets_path.is_absolute():
        targets_path = REPO_ROOT / targets_path
    project_root = Path(args.project_root)
    if not project_root.is_absolute():
        project_root = REPO_ROOT / project_root
    config = load_json_file(str(targets_path))
    catalog = build_catalog(config, str(targets_path), project_root=project_root)
    result = filter_catalog(
        catalog,
        query=args.query,
        module=args.module,
        access=args.access,
        offset=args.offset,
        limit=args.limit,
    )

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
