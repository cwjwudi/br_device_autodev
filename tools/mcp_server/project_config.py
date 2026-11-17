"""Discover a project's configuration without relying on the server's cwd."""

from __future__ import annotations

import json
import ipaddress
from pathlib import Path
from typing import Any

NAME = "br-auto-dev.json"


def load_project_config(project: str, repo_root: Path) -> tuple[dict[str, Any], Path | None]:
    if not project:
        return {}, None
    selected = Path(project)
    if not selected.is_absolute():
        selected = repo_root / selected
    selected = selected.resolve()
    is_directory = selected.is_dir()
    directory = selected if is_directory else selected.parent
    candidates = [directory / NAME]
    if not is_directory:
        candidates.append(directory.parent / NAME)
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
    policy = data.get("access_policy")
    if not isinstance(policy, dict) or policy.get("mode") not in {"whitelist", "catalog_policy", "agent_directed"}:
        raise ValueError(f"Project configuration {path} requires a valid access_policy.mode")
    pvi = data.get("pvi", {})
    if not isinstance(pvi, dict) or pvi.get("write_policy", "whitelist") not in ("whitelist", "blacklist"):
        raise ValueError(f"Project configuration {path} requires a valid pvi.write_policy")
    for key in ("write_whitelist", "write_blacklist"):
        if key in pvi and not isinstance(pvi[key], list):
            raise ValueError(f"Project configuration {path} requires {key} to be an array")
    data["project_path"] = str(project_path)
    return data, path
