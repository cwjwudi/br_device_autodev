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


def is_production_target(target_config: dict[str, Any]) -> bool:
    return str(target_config.get("role") or "").lower() == "production"


def invalid_arsim_target(target_config: dict[str, Any]) -> bool:
    if str(target_config.get("role") or "").lower() != "arsim":
        return False
    try:
        return not ipaddress.ip_address(target_config.get("ip", "")).is_loopback
    except ValueError:
        return True


def matches_blocked_name(name: str) -> bool:
    lowered = name.lower()
    for pattern in DEFAULT_BLOCKED_NAME_PATTERNS:
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
    errors: list[str] = []
    if "access_policy" in config:
        errors.append("Removed access_policy must be reviewed and removed before OPC UA reads.")
    if is_production_target(target_config):
        errors.append("Refusing dynamic OPC UA reads on a production target.")
    if str(target_config.get("role") or "").lower() not in DEFAULT_ALLOWED_TARGET_ROLES:
        errors.append(f"Target role '{target_config.get('role')}' is not allowed for OPC UA reads.")

    allowed = opcua_read_set(config)
    for node_id in node_ids:
        node = str(node_id)
        if matches_blocked_name(node):
            errors.append(f"OPC UA node '{node}' matches a blocked name pattern.")
            continue
        if node in allowed:
            continue
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
    else:
        raise ValueError(f"Unsupported access policy operation: {operation}")

    return {
        "ok": not errors,
        "operation": operation,
        "errors": errors,
        "blocked_reason": errors[0] if errors else None,
        "target": target_name,
        "target_role": str(target_config.get("role") or ""),
        "requested_items": normalized_items,
        "explicit": bool(explicit),
        "execute": bool(execute),
    }
