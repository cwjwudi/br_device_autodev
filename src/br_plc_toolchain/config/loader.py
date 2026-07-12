"""Structured configuration loader with safe behavior when no policy file exists."""

from __future__ import annotations

import copy
import ipaddress
import json
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_ROOT = REPO_ROOT / "config"
PROFILE_ROOT = CONFIG_ROOT / "profiles"
LOCAL_ROOT = CONFIG_ROOT / "local"
ENVIRONMENTS_PATH = CONFIG_ROOT / "environments" / "environments.json"

IMMUTABLE_SAFETY_BASELINE: dict[str, Any] = {
    "deny_production_write": True,
    "deny_production_download": True,
    "deny_safety_write": True,
    "deny_physical_io_write": True,
    "deny_system_write": True,
    "require_execute_for_write": True,
    "require_readback": True,
    "blocked_name_patterns": [
        "*safety*",
        "*safeio*",
        "*physicalio*",
        "*iomap*",
        "*system*",
        "sys:*",
    ],
}


class ConfigError(ValueError):
    """Raised for invalid or unsafe configuration operations."""


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_json_config(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = REPO_ROOT / resolved
    if not resolved.is_file():
        raise ConfigError(f"Configuration file was not found: {resolved}")
    data = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ConfigError(f"Configuration root must be an object: {resolved}")
    return data


def load_profile(name: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
        raise ConfigError(f"Invalid profile name: {name!r}")
    profile = load_json_config(PROFILE_ROOT / f"{name}.json")
    baseline = load_json_config(CONFIG_ROOT / "defaults" / "base.json")
    merged = _deep_merge(baseline, profile)
    # The hard baseline is returned separately and cannot be weakened by JSON.
    merged["immutable_safety"] = copy.deepcopy(IMMUTABLE_SAFETY_BASELINE)
    merged["profile"] = name
    return merged


def load_environment_map() -> dict[str, Any]:
    return load_json_config(ENVIRONMENTS_PATH)


def _is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError as exc:
        raise ConfigError(f"Invalid target IP address: {ip}") from exc


def create_ephemeral_target_config(
    *,
    ip: str,
    name: str | None = None,
    declared_role: str | None = None,
) -> dict[str, Any]:
    """Create a non-persistent safe target config from user intent and IP.

    Missing policy never means unrestricted writes. Unknown physical targets use
    readonly discovery. Loopback is treated as ARsim. A physical target only gets
    office-test behavior after the caller explicitly declares it a dedicated test PLC.
    """
    loopback = _is_loopback(ip)
    role = (declared_role or "").strip().lower()
    if loopback:
        profile_name = "arsim-development"
        target_role = "arsim"
    elif role in {"dedicated_test_plc", "test", "office_test"}:
        profile_name = "office-test"
        target_role = "dedicated_test_plc"
    elif role == "production":
        profile_name = "production-locked"
        target_role = "production"
    else:
        profile_name = "readonly-discovery"
        target_role = "unregistered"

    config = load_profile(profile_name)
    target_name = name or ("arsim" if loopback else f"discovered-{ip.replace('.', '-')}")
    config["target"] = {
        "name": target_name,
        "ip": ip,
        "role": target_role,
        "persistent": False,
        "source": "generated_ephemeral",
    }
    return config


def save_local_target(config: dict[str, Any], *, filename: str, overwrite: bool = False) -> Path:
    """Persist an explicitly confirmed discovered target under ignored config/local."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*\.json", filename):
        raise ConfigError("Local target filename must be a simple lowercase .json filename")
    target = config.get("target") or {}
    if target.get("source") != "generated_ephemeral":
        raise ConfigError("Only generated ephemeral target configurations can be saved here")
    path = LOCAL_ROOT / filename
    if path.exists() and not overwrite:
        raise ConfigError(f"Refusing to overwrite existing local target config: {path}")
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    persisted = copy.deepcopy(config)
    persisted["target"]["persistent"] = True
    persisted["target"]["source"] = "local_saved"
    path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

