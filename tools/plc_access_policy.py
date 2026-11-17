#!/usr/bin/env python
"""Shared PLC variable access policy helpers."""

from __future__ import annotations

import fnmatch
import ipaddress
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from br_plc_toolchain.policy.runtime import pvi_write_error
from pvi_read import parse_variable_spec


POLICY_MODES = {"whitelist", "catalog_policy", "agent_directed"}
DEFAULT_BLOCKED_NAME_PATTERNS = [
    "*safety*",
    "*safeio*",
    "*physicalio*",
    "*iomap*",
    "*system*",
    "sys:*",
]
DEFAULT_ALLOWED_TARGET_ROLES = ["arsim", "dedicated_test_plc"]


def canonical_variable(spec: Any) -> str:
    parsed = parse_variable_spec(spec)
    if parsed.get("scope") == "task":
        return f"{parsed.get('task')}:{parsed['name']}"
    return str(parsed["name"])


def access_policy(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("access_policy") or {}
    mode = str(raw.get("mode") or "whitelist")
    if mode not in POLICY_MODES:
        mode = "whitelist"
    return {
        "mode": mode,
        "allow_dynamic_pvi_read": bool(raw.get("allow_dynamic_pvi_read", mode in ("catalog_policy", "agent_directed"))),
        "allow_dynamic_pvi_write": bool(raw.get("allow_dynamic_pvi_write", mode in ("catalog_policy", "agent_directed"))),
        "allow_dynamic_opcua_read": bool(raw.get("allow_dynamic_opcua_read", mode in ("catalog_policy", "agent_directed"))),
        "allow_dynamic_opcua_write": bool(raw.get("allow_dynamic_opcua_write", False)),
        "allowed_target_roles": list(raw.get("allowed_target_roles") or DEFAULT_ALLOWED_TARGET_ROLES),
        "blocked_name_patterns": list(raw.get("blocked_name_patterns") or DEFAULT_BLOCKED_NAME_PATTERNS),
    }


def target_role_allowed(policy: dict[str, Any], target_config: dict[str, Any]) -> bool:
    role = str(target_config.get("role") or "").lower()
    return role in {str(item).lower() for item in policy.get("allowed_target_roles", [])}


def is_production_target(target_config: dict[str, Any]) -> bool:
    return str(target_config.get("role") or "").lower() == "production"


def invalid_arsim_target(target_config: dict[str, Any]) -> bool:
    if str(target_config.get("role") or "").lower() != "arsim":
        return False
    try:
        return not ipaddress.ip_address(target_config.get("ip", "")).is_loopback
    except ValueError:
        return True


def matches_blocked_name(name: str, policy: dict[str, Any]) -> bool:
    lowered = name.lower()
    for pattern in policy.get("blocked_name_patterns") or DEFAULT_BLOCKED_NAME_PATTERNS:
        if fnmatch.fnmatch(lowered, str(pattern).lower()):
            return True
    return False


def entries_to_map(entries: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, dict):
            variable = canonical_variable(entry)
            result[variable] = dict(entry)
        else:
            variable = canonical_variable(entry)
            result[variable] = {"variable": variable}
    return result


def pvi_read_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pvi = config.get("pvi") or {}
    return entries_to_map(list(pvi.get("read_whitelist") or pvi.get("validation_variables") or []))


def pvi_write_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return entries_to_map(list((config.get("pvi") or {}).get("write_whitelist") or []))


def opcua_read_set(config: dict[str, Any]) -> set[str]:
    return {str(item) for item in ((config.get("opcua") or {}).get("validation_node_ids") or [])}


def catalog_path(config: dict[str, Any], targets_file: str) -> Path:
    raw = (config.get("access_policy") or {}).get("catalog_path") or "var/catalogs/plc_symbol_catalog.json"
    path = Path(str(raw))
    if path.is_absolute():
        return path
    if Path(targets_file).name == "br-auto-dev.json" and (config.get("access_policy") or {}).get("catalog_path"):
        return Path(targets_file).resolve().parent / path
    return Path(targets_file).resolve().parents[1] / path


def load_catalog(config: dict[str, Any], targets_file: str) -> dict[str, Any]:
    path = catalog_path(config, targets_file)
    if not path.exists():
        return {"variables": []}
    import json

    return json.loads(path.read_text(encoding="utf-8-sig"))


def catalog_variable_map(config: dict[str, Any], targets_file: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    catalog = load_catalog(config, targets_file)
    for item in catalog.get("variables") or []:
        if not isinstance(item, dict):
            continue
        keys = []
        if item.get("pvi"):
            keys.append(str(item["pvi"]))
        if item.get("scope") == "task" and item.get("task") and item.get("name"):
            keys.append(f"{item['task']}:{item['name']}")
        elif item.get("name"):
            keys.append(str(item["name"]))
        for key in keys:
            result[key] = item
    return result


def base_variable(variable: str) -> str:
    for token in ("[", "."):
        if token in variable:
            variable = variable.split(token, 1)[0]
    return variable


def covered_by_map(variable: str, allowed: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    matches = [
        key
        for key in allowed
        if variable == key or variable.startswith(key + ".") or variable.startswith(key + "[")
    ]
    if not matches:
        return None
    return allowed[max(matches, key=len)]


def validate_pvi_read(
    *,
    config: dict[str, Any],
    target_config: dict[str, Any],
    targets_file: str,
    variables: list[str],
    explicit: bool,
) -> list[str]:
    errors: list[str] = []
    if (config.get("pvi") or {}).get("enabled") is False:
        errors.append("PVI is disabled in pvi.enabled.")
    if invalid_arsim_target(target_config):
        errors.append("ARsim target must use a loopback IP.")
    return errors


def validate_pvi_write(
    *,
    config: dict[str, Any],
    target_config: dict[str, Any],
    targets_file: str,
    variables: list[str],
    execute: bool,
) -> list[str]:
    errors: list[str] = []
    if (config.get("pvi") or {}).get("enabled") is False:
        errors.append("PVI is disabled in pvi.enabled.")
    if invalid_arsim_target(target_config):
        errors.append("ARsim target must use a loopback IP.")
    for variable in variables:
        key = canonical_variable(variable)
        error = pvi_write_error(config, str(target_config.get("role") or "").lower(), key,
                                execute=execute, writable=True)
        if error:
            errors.append(f"Variable '{key}': {error}")
    return errors


def validate_opcua_read(
    *,
    config: dict[str, Any],
    target_config: dict[str, Any],
    node_ids: list[str],
    explicit: bool,
) -> list[str]:
    policy = access_policy(config)
    errors: list[str] = []
    if is_production_target(target_config):
        errors.append("Refusing dynamic OPC UA reads on a production target.")
    if not target_role_allowed(policy, target_config):
        errors.append(f"Target role '{target_config.get('role')}' is not allowed by access_policy.allowed_target_roles.")

    allowed = opcua_read_set(config)
    for node_id in node_ids:
        node = str(node_id)
        if matches_blocked_name(node, policy):
            errors.append(f"OPC UA node '{node}' matches access_policy.blocked_name_patterns.")
            continue
        if node in allowed:
            continue
        if policy["mode"] in ("catalog_policy", "agent_directed"):
            if not explicit or not policy["allow_dynamic_opcua_read"]:
                errors.append(f"Dynamic OPC UA read is disabled for node '{node}'.")
        else:
            errors.append(f"OPC UA node '{node}' is not in opcua.validation_node_ids.")
    return errors


def evaluate_access_request(
    *,
    operation: str,
    config: dict[str, Any],
    target_name: str,
    target_config: dict[str, Any],
    targets_file: str,
    requested_items: list[Any],
    explicit: bool = False,
    execute: bool = False,
) -> dict[str, Any]:
    policy = access_policy(config)
    if operation == "pvi_read":
        normalized_items = [canonical_variable(item) for item in requested_items]
        errors = validate_pvi_read(
            config=config,
            target_config=target_config,
            targets_file=targets_file,
            variables=requested_items,
            explicit=explicit,
        )
    elif operation == "pvi_write":
        normalized_items = [canonical_variable(item) for item in requested_items]
        errors = validate_pvi_write(
            config=config,
            target_config=target_config,
            targets_file=targets_file,
            variables=requested_items,
            execute=execute,
        )
    elif operation == "opcua_read":
        if not all(isinstance(item, str) for item in requested_items):
            raise ValueError("OPC UA requested items must be strings.")
        normalized_items = [str(item) for item in requested_items]
        errors = validate_opcua_read(
            config=config,
            target_config=target_config,
            node_ids=requested_items,
            explicit=explicit,
        )
    elif operation == "describe":
        normalized_items = []
        errors = []
    else:
        raise ValueError(f"Unsupported access policy operation: {operation}")

    return {
        "ok": not errors,
        "operation": operation,
        "errors": errors,
        "blocked_reason": errors[0] if errors else None,
        "policy_mode": policy["mode"],
        "policy": policy,
        "target": target_name,
        "target_role": str(target_config.get("role") or ""),
        "requested_items": normalized_items,
        "explicit": bool(explicit),
        "execute": bool(execute),
    }
