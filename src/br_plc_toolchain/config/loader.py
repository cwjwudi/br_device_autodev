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
LOCAL_ROOT = CONFIG_ROOT / "local"

IMMUTABLE_SAFETY_BASELINE: dict[str, Any] = {
    "deny_production_write": True,
    "deny_production_download": True,
    "require_execute_for_write": True,
    "require_readback": True,
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
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a non-persistent safe target config from user intent and IP.

    Missing policy never means unrestricted writes. Unknown physical targets use
    readonly discovery. Loopback is treated as ARsim. A physical target only gets
    office-test behavior after the caller explicitly declares it a dedicated test PLC.
    """
    loopback = _is_loopback(ip)
    role = (declared_role or "").strip().lower()
    if role == "production":
        profile_name = "production-locked"
        target_role = "production"
    elif role in {"dedicated_test_plc", "test", "office_test"}:
        profile_name = "office-test"
        target_role = "dedicated_test_plc"
    elif loopback and role in {"", "arsim"}:
        profile_name = "arsim-development"
        target_role = "arsim"
    else:
        profile_name = "readonly-discovery"
        target_role = "unregistered"

    config = _deep_merge(load_json_config(CONFIG_ROOT / "defaults" / "base.json"), project_config or {})
    config["immutable_safety"] = copy.deepcopy(IMMUTABLE_SAFETY_BASELINE)
    config["profile"] = profile_name
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


PROJECT_CONFIG_NAME = "br-auto-dev.json"


def load_project_config(
    project: str, repo_root: Path | None = None
) -> tuple[dict[str, Any], Path | None]:
    """Load and validate a project's br-auto-dev.json from a .apj or directory."""
    if not project:
        return {}, None
    root = repo_root or REPO_ROOT
    selected = Path(project)
    if not selected.is_absolute():
        selected = root / selected
    selected = selected.resolve()
    is_directory = selected.is_dir()
    directory = selected if is_directory else selected.parent
    candidates = [directory / PROJECT_CONFIG_NAME]
    if not is_directory:
        candidates.append(directory.parent / PROJECT_CONFIG_NAME)
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        if is_directory:
            raise ValueError(f"Project configuration not found in {directory}")
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid project configuration {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Project configuration must be an object: {path}")
    for key in ("project_path", "config", "toolchain", "target"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"Project configuration {path} requires a non-empty {key}")
    project_path = Path(data["project_path"])
    if not project_path.is_absolute():
        project_path = path.parent / project_path
    project_path = project_path.resolve()
    if project_path.suffix.lower() != ".apj" or not project_path.is_file():
        raise ValueError(f"Project configuration {path} references a missing .apj: {project_path}")
    if not is_directory and project_path != selected:
        raise ValueError(f"Project configuration {path} references a different project: {project_path}")
    targets = data.get("targets")
    if not isinstance(targets, dict) or not isinstance(targets.get(data["target"]), dict):
        raise ValueError(f"Project configuration {path} must define its selected target")
    for name, target in targets.items():
        if not isinstance(target, dict) or target.get("role") not in {"arsim", "dedicated_test_plc", "production"}:
            raise ValueError(f"Invalid role for target {name!r} in {path}")
        if "allow_auto_download" in target and not isinstance(target["allow_auto_download"], bool):
            raise ValueError(f"allow_auto_download for target {name!r} must be a boolean")
        try:
            ip = ipaddress.ip_address(target.get("ip", ""))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid IP for target {name!r} in {path}") from exc
        if target["role"] == "arsim" and not ip.is_loopback:
            raise ValueError(f"ARsim target {name!r} must use a loopback IP")
    if "access_policy" in data:
        raise ValueError(f"Project configuration {path} contains removed access_policy; review and remove it")
    pvi = data.get("pvi", {})
    if not isinstance(pvi, dict) or pvi.get("write_policy", "whitelist") not in ("whitelist", "blacklist"):
        raise ValueError(f"Project configuration {path} requires a valid pvi.write_policy")
    for key in ("write_whitelist", "write_blacklist"):
        if key in pvi and not isinstance(pvi[key], list):
            raise ValueError(f"Project configuration {path} requires {key} to be an array")
    data["project_path"] = str(project_path)
    return data, path

