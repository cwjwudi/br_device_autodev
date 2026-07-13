"""Global Automation Studio/PVI toolchain registry."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .loader import CONFIG_ROOT, ConfigError, REPO_ROOT, load_json_config


DEFAULT_TOOLCHAINS_PATH = CONFIG_ROOT / "toolchains" / "toolchains.json"
LOCAL_TOOLCHAINS_PATH = CONFIG_ROOT / "local" / "toolchains.json"
SUPPORTED_FAMILIES = {"AS4", "AS6"}


@dataclass(frozen=True)
class ResolvedToolchain:
    id: str
    family: str
    version: str
    enabled: bool
    build_exe: Path
    bin_dir: Path
    install_root: Path
    library_roots: tuple[Path, ...]
    pvi_family: str
    pvi_transfer_exe: Path
    pvi_dll_dir: Path | None
    source_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family": self.family,
            "version": self.version,
            "enabled": self.enabled,
            "automation_studio": {
                "install_root": str(self.install_root),
                "bin_dir": str(self.bin_dir),
                "build_exe": str(self.build_exe),
                "library_roots": [str(path) for path in self.library_roots],
            },
            "pvi": {
                "family": self.pvi_family,
                "transfer_exe": str(self.pvi_transfer_exe),
                "dll_dir": str(self.pvi_dll_dir) if self.pvi_dll_dir else None,
            },
            "source_path": str(self.source_path),
        }


def _resolve_path(value: Any, *, source: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Toolchain path is missing in {source}")
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def load_toolchain_registry(path: str | Path | None = None) -> tuple[dict[str, Any], Path]:
    if path is None:
        selected = LOCAL_TOOLCHAINS_PATH if LOCAL_TOOLCHAINS_PATH.is_file() else DEFAULT_TOOLCHAINS_PATH
    else:
        selected = Path(path)
        if not selected.is_absolute():
            selected = REPO_ROOT / selected
        if selected.resolve() == DEFAULT_TOOLCHAINS_PATH.resolve() and LOCAL_TOOLCHAINS_PATH.is_file():
            selected = LOCAL_TOOLCHAINS_PATH
    selected = selected.resolve()
    registry = load_json_config(selected)
    if registry.get("schema_version") != 1:
        raise ConfigError(f"Unsupported toolchain registry schema in {selected}")
    if not isinstance(registry.get("toolchains"), dict) or not registry["toolchains"]:
        raise ConfigError(f"Toolchain registry has no toolchains: {selected}")
    return registry, selected


def resolve_toolchain(
    toolchain_id: str | None = None, *, registry_path: str | Path | None = None
) -> ResolvedToolchain:
    registry, source = load_toolchain_registry(registry_path)
    selected = toolchain_id or registry.get("default_toolchain")
    if not isinstance(selected, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", selected):
        raise ConfigError(f"Invalid or missing toolchain id: {selected!r}")
    raw = registry["toolchains"].get(selected)
    if not isinstance(raw, dict):
        choices = ", ".join(sorted(registry["toolchains"]))
        raise ConfigError(f"Unknown toolchain {selected!r}; available: {choices}")
    family = str(raw.get("family") or "").upper()
    if family not in SUPPORTED_FAMILIES:
        raise ConfigError(f"Toolchain {selected!r} has unsupported family {family!r}")
    automation = raw.get("automation_studio") or {}
    pvi = raw.get("pvi") or {}
    library_values = automation.get("library_roots") or []
    if not isinstance(library_values, list):
        raise ConfigError(f"Toolchain {selected!r} library_roots must be an array")
    return ResolvedToolchain(
        id=selected,
        family=family,
        version=str(raw.get("version") or "unknown"),
        enabled=raw.get("enabled") is not False,
        build_exe=_resolve_path(automation.get("build_exe"), source=source),
        bin_dir=_resolve_path(automation.get("bin_dir"), source=source),
        install_root=_resolve_path(automation.get("install_root"), source=source),
        library_roots=tuple(_resolve_path(item, source=source) for item in library_values),
        pvi_family=str(pvi.get("family") or "unknown").upper(),
        pvi_transfer_exe=_resolve_path(pvi.get("transfer_exe"), source=source),
        pvi_dll_dir=_resolve_path(pvi["dll_dir"], source=source) if pvi.get("dll_dir") else None,
        source_path=source,
    )


def list_toolchains(*, registry_path: str | Path | None = None) -> dict[str, Any]:
    registry, source = load_toolchain_registry(registry_path)
    items = []
    for toolchain_id in sorted(registry["toolchains"]):
        resolved = resolve_toolchain(toolchain_id, registry_path=source)
        item = resolved.to_dict()
        item["available"] = bool(
            resolved.enabled
            and resolved.build_exe.is_file()
            and resolved.pvi_transfer_exe.is_file()
        )
        items.append(item)
    return {
        "ok": True,
        "source_path": str(source),
        "default_toolchain": registry.get("default_toolchain"),
        "toolchains": items,
    }


def merge_toolchain_into_legacy_config(
    config: dict[str, Any], toolchain: ResolvedToolchain
) -> dict[str, Any]:
    """Temporary adapter for legacy CLI modules while paths move out of target files."""
    merged = copy.deepcopy(config)
    merged["automation_studio"] = {
        "version": toolchain.version,
        "family": toolchain.family,
        "bin_dir": str(toolchain.bin_dir),
        "build_exe": str(toolchain.build_exe),
        "library_roots": [str(path) for path in toolchain.library_roots],
        "pvi_transfer_exe": str(toolchain.pvi_transfer_exe),
    }
    merged.setdefault("pvi", {})["pvi_dll_dir"] = (
        str(toolchain.pvi_dll_dir) if toolchain.pvi_dll_dir else None
    )
    return merged
