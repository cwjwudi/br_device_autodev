"""Auto-discover Automation Studio project metadata and initialize br-auto-dev.json."""

from __future__ import annotations

import difflib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from br_plc_toolchain.config.loader import PROJECT_CONFIG_NAME, load_project_config  # noqa: E402
from br_plc_toolchain.config.toolchains import list_toolchains  # noqa: E402


AS_VERSION_PI_RE = re.compile(r"<\?AutomationStudio\b[^?]*?\bVersion=\"([^\"]+)\"", re.IGNORECASE)
AS_WORKING_VERSION_PI_RE = re.compile(r"<\?AutomationStudio\b[^?]*?\bWorkingVersion=\"([^\"]+)\"", re.IGNORECASE)
VALID_TEMPLATES = {"arsim", "test_plc_whitelist", "test_plc_blacklist"}


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def locate_apj(project_path: str | Path, *, repo_root: Path = REPO_ROOT) -> Path:
    raw = str(project_path or "").strip()
    if not raw:
        raise ValueError("project_path is required to initialize project configuration.")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    candidate = candidate.resolve()

    if candidate.is_file():
        if candidate.suffix.lower() != ".apj":
            raise ValueError(f"Expected a .apj file or project directory, got: {candidate}")
        return candidate
    if not candidate.is_dir():
        raise FileNotFoundError(f"Project path does not exist: {candidate}")

    apj_files = sorted(candidate.glob("*.apj"))
    if not apj_files:
        raise FileNotFoundError(f"No .apj file found in directory: {candidate}")
    if len(apj_files) > 1:
        names = ", ".join(item.name for item in apj_files)
        raise ValueError(f"Multiple .apj files found in {candidate} ({names}); pass the exact .apj path.")
    return apj_files[0]


def detect_as_version(apj_path: Path) -> tuple[str | None, str | None]:
    """Return (version_string, family) where family is 'AS4', 'AS6', or None."""
    text = apj_path.read_text(encoding="utf-8-sig", errors="replace")
    match = AS_VERSION_PI_RE.search(text) or AS_WORKING_VERSION_PI_RE.search(text)
    version = match.group(1).strip() if match else None
    if not version:
        return None, None
    major = version.split(".", 1)[0]
    if major == "6":
        return version, "AS6"
    if major == "4":
        return version, "AS4"
    return version, None


def discover_physical_configs(project_dir: Path) -> list[dict[str, Any]]:
    """Parse Physical/Physical.pkg and inspect Hardware.hw for SimulationIPAddress."""
    physical_dir = project_dir / "Physical"
    pkg_path = physical_dir / "Physical.pkg"
    config_names: list[str] = []

    if pkg_path.is_file():
        try:
            root = ET.parse(pkg_path).getroot()
            for elem in root.iter():
                if _local_tag(elem.tag) == "Object":
                    obj_type = (elem.attrib.get("Type") or "").strip().lower()
                    name = (elem.text or "").strip()
                    if name and (obj_type == "configuration" or not obj_type):
                        config_names.append(name)
        except ET.ParseError:
            pass

    if not config_names and physical_dir.is_dir():
        for child in sorted(physical_dir.iterdir()):
            if child.is_dir() and (child / "Hardware.hw").is_file():
                config_names.append(child.name)

    configs: list[dict[str, Any]] = []
    for name in config_names:
        hw_path = physical_dir / name / "Hardware.hw"
        sim_ip: str | None = None
        if hw_path.is_file():
            try:
                hw_root = ET.parse(hw_path).getroot()
                for node in hw_root.iter():
                    if node.attrib.get("ID") == "SimulationIPAddress" and node.attrib.get("Value"):
                        sim_ip = str(node.attrib["Value"]).strip()
                        break
            except ET.ParseError:
                pass
        configs.append(
            {
                "name": name,
                "hardware_hw": str(hw_path) if hw_path.is_file() else None,
                "simulation_ip": sim_ip,
            }
        )
    return configs


def match_toolchain_for_family(
    family: str | None,
    *,
    explicit_toolchain: str | None = None,
    toolchains_path: str | Path | None = None,
) -> dict[str, Any]:
    listing = list_toolchains(registry_path=toolchains_path)
    toolchains = listing.get("toolchains") or []
    if explicit_toolchain:
        matched = next((item for item in toolchains if item["id"] == explicit_toolchain), None)
        if matched is None:
            choices = ", ".join(item["id"] for item in toolchains)
            raise ValueError(f"Unknown toolchain {explicit_toolchain!r}; available: {choices}")
        return {
            "id": matched["id"],
            "family": matched["family"],
            "available": matched["available"],
            "enabled": matched["enabled"],
            "reason": "explicit",
            "registry_path": listing["source_path"],
        }

    if family:
        family_items = [item for item in toolchains if item["family"] == family and item["enabled"]]
        available = [item for item in family_items if item["available"]]
        chosen = available[0] if available else (family_items[0] if family_items else None)
        if chosen is not None:
            return {
                "id": chosen["id"],
                "family": chosen["family"],
                "available": chosen["available"],
                "enabled": chosen["enabled"],
                "reason": f"matched_{family.lower()}",
                "registry_path": listing["source_path"],
            }

    default_id = listing.get("default_toolchain")
    fallback = next((item for item in toolchains if item["id"] == default_id), toolchains[0])
    return {
        "id": fallback["id"],
        "family": fallback["family"],
        "available": fallback["available"],
        "enabled": fallback["enabled"],
        "reason": "default_fallback",
        "registry_path": listing["source_path"],
    }


def _build_config_payload(
    *,
    apj_name: str,
    config_name: str,
    toolchain_id: str,
    template: str,
    target_name: str,
    ip: str,
) -> dict[str, Any]:
    if template == "arsim":
        return {
            "project_path": apj_name,
            "config": config_name,
            "toolchain": toolchain_id,
            "target": target_name,
            "targets": {
                target_name: {
                    "ip": ip,
                    "role": "arsim",
                }
            },
            "logger": {
                "enabled": True,
            },
            "pvi": {
                "enabled": True,
                "write_policy": "whitelist",
                "read_whitelist": [],
                "write_whitelist": [],
                "restore_writes": [],
                "validation_variables": [],
            },
        }
    if template == "test_plc_whitelist":
        return {
            "project_path": apj_name,
            "config": config_name,
            "toolchain": toolchain_id,
            "target": target_name,
            "targets": {
                target_name: {
                    "ip": ip,
                    "role": "dedicated_test_plc",
                }
            },
            "logger": {
                "enabled": True,
            },
            "pvi": {
                "enabled": True,
                "write_policy": "whitelist",
                "write_whitelist": [],
            },
        }
    return {
        "project_path": apj_name,
        "config": config_name,
        "toolchain": toolchain_id,
        "target": target_name,
        "targets": {
            target_name: {
                "ip": ip,
                "role": "dedicated_test_plc",
            }
        },
        "logger": {
            "enabled": True,
        },
        "pvi": {
            "enabled": True,
            "write_policy": "blacklist",
            "write_blacklist": ["Safety:*", "sys:*", "*physicalio*"],
        },
    }


def init_project_config(
    *,
    project_path: str | Path,
    template: str = "arsim",
    config: str | None = None,
    ip: str | None = None,
    target: str | None = None,
    toolchain: str | None = None,
    toolchains_path: str | Path | None = None,
    overwrite: bool = False,
    execute: bool = False,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    tmpl = str(template or "arsim").strip().lower()
    if tmpl not in VALID_TEMPLATES:
        raise ValueError(f"Unsupported template {template!r}; expected one of {sorted(VALID_TEMPLATES)}.")

    apj_path = locate_apj(project_path, repo_root=repo_root)
    project_dir = apj_path.parent
    as_version, family = detect_as_version(apj_path)
    configs = discover_physical_configs(project_dir)

    if config:
        selected_info = next((item for item in configs if item["name"] == config), None)
        if configs and selected_info is None:
            names = ", ".join(item["name"] for item in configs)
            raise ValueError(f"Config {config!r} was not found in Physical/Physical.pkg; available: {names}")
        selected_config = config
    else:
        if not configs:
            raise ValueError(f"No Automation Studio configurations were discovered under {project_dir / 'Physical'}")
        # Prefer a config that explicitly specifies SimulationIPAddress when template is arsim
        if tmpl == "arsim":
            selected_info = next((item for item in configs if item.get("simulation_ip")), configs[0])
        else:
            selected_info = configs[0]
        selected_config = selected_info["name"]

    matched_toolchain = match_toolchain_for_family(
        family,
        explicit_toolchain=toolchain,
        toolchains_path=toolchains_path,
    )

    if ip and str(ip).strip():
        resolved_ip = str(ip).strip()
    elif tmpl == "arsim":
        resolved_ip = (selected_info or {}).get("simulation_ip") or "127.0.0.1"
    else:
        resolved_ip = "192.0.2.10"

    resolved_target = (str(target).strip() if target else "") or ("arsim" if tmpl == "arsim" else "test_plc")
    payload = _build_config_payload(
        apj_name=apj_path.name,
        config_name=selected_config,
        toolchain_id=matched_toolchain["id"],
        template=tmpl,
        target_name=resolved_target,
        ip=resolved_ip,
    )

    config_file = project_dir / PROJECT_CONFIG_NAME
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    exists = config_file.is_file()
    diff_text = ""
    if exists:
        existing_text = config_file.read_text(encoding="utf-8-sig", errors="replace")
        diff_text = "".join(
            difflib.unified_diff(
                existing_text.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=f"{PROJECT_CONFIG_NAME} (existing)",
                tofile=f"{PROJECT_CONFIG_NAME} (recommended)",
            )
        )

    base_result: dict[str, Any] = {
        "ok": True,
        "executed": False,
        "written": False,
        "template": tmpl,
        "apj_path": str(apj_path),
        "config_path": str(config_file),
        "exists": exists,
        "as_version": as_version,
        "family": family,
        "matched_toolchain": matched_toolchain,
        "available_configs": configs,
        "selected_config": selected_config,
        "recommended_config": payload,
        "diff": diff_text,
    }

    if not execute:
        return base_result

    if exists and not overwrite:
        return {
            **base_result,
            "ok": False,
            "error_code": "CONFIG_ALREADY_EXISTS",
            "error": f"Refusing to overwrite existing {config_file}; pass overwrite=true to replace it.",
        }

    config_file.write_text(rendered, encoding="utf-8")
    # Validate generated config with canonical loader
    load_project_config(str(apj_path), repo_root=repo_root)
    return {
        **base_result,
        "ok": True,
        "executed": True,
        "written": True,
        "exists": True,
    }
