"""Pure-Python read-only parser and static integrity checker for Automation Studio projects."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from br_plc_toolchain.config.loader import PROJECT_CONFIG_NAME, REPO_ROOT


AS_VERSION_PI_RE = re.compile(r'<\?AutomationStudio\b[^?]*?\bVersion="([^"]+)"', re.IGNORECASE)
AS_WORKING_VERSION_PI_RE = re.compile(
    r'<\?AutomationStudio\b[^?]*?\bWorkingVersion="([^"]+)"', re.IGNORECASE
)
SAFETY_MODULE_TYPE_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])(?:SafeLOGIC|SafeDESIGNER|Safety|X20SL\d|X20SLX|X20SI\d|X20SO\d|X20SC\d|X20SP\d|X20SR\d|X20SD\d|X67SI|X67SO|X67SC|X90SL)",
    re.IGNORECASE,
)


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _rel_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _locate_apj(project_path: str | Path, *, repo_root: Path = REPO_ROOT) -> Path:
    raw = str(project_path or "").strip()
    if not raw:
        raise ValueError("project_path is required to inspect an Automation Studio project.")
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
        raise ValueError(
            f"Multiple .apj files found in {candidate} ({names}); pass the exact .apj path."
        )
    return apj_files[0]


def _parse_xml_file(
    path: Path,
    *,
    project_dir: Path,
    issues: list[dict[str, Any]],
) -> tuple[ET.Element | None, str | None]:
    """Read and parse an XML file, recording encoding/BOM/parse issues without raising."""
    rel = _rel_path(path, project_dir)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        issues.append(
            {
                "severity": "error",
                "file": rel,
                "code": "FILE_READ_ERROR",
                "message": f"Failed to read XML file: {exc}",
            }
        )
        return None, None

    if raw.startswith(b"\xef\xbb\xbf\xef\xbb\xbf"):
        issues.append(
            {
                "severity": "warning",
                "file": rel,
                "code": "XML_BOM_ANOMALY",
                "message": "Duplicate UTF-8 BOM detected at start of XML file.",
            }
        )
    if b"\x00" in raw and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        issues.append(
            {
                "severity": "error",
                "file": rel,
                "code": "XML_ENCODING_ERROR",
                "message": "Unexpected NUL bytes found in XML file.",
            }
        )
        return None, None

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-16")
        except UnicodeDecodeError as exc:
            issues.append(
                {
                    "severity": "error",
                    "file": rel,
                    "code": "XML_ENCODING_ERROR",
                    "message": f"XML file is not valid UTF-8/UTF-16: {exc}",
                }
            )
            return None, None

    # Strip any extra leading BOM characters after double-BOM detection so parsing can proceed.
    cleaned = text.lstrip("\ufeff")
    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError as exc:
        issues.append(
            {
                "severity": "error",
                "file": rel,
                "code": "MALFORMED_XML",
                "message": f"XML parse error: {exc}",
            }
        )
        return None, cleaned
    return root, cleaned


def _detect_as_version(apj_text: str | None) -> tuple[str | None, str | None]:
    if not apj_text:
        return None, None
    match = AS_VERSION_PI_RE.search(apj_text) or AS_WORKING_VERSION_PI_RE.search(apj_text)
    version = match.group(1).strip() if match else None
    if not version:
        return None, None
    major = version.split(".", 1)[0]
    if major == "6":
        return version, "AS6"
    if major == "4":
        return version, "AS4"
    return version, None


def _default_config_from_br_auto_dev(project_dir: Path) -> str | None:
    for candidate in (project_dir / PROJECT_CONFIG_NAME, project_dir.parent / PROJECT_CONFIG_NAME):
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        cfg = data.get("config")
        if isinstance(cfg, str) and cfg.strip():
            return cfg.strip()
    return None


def _discover_configs(
    project_dir: Path, *, issues: list[dict[str, Any]]
) -> list[str]:
    physical_dir = project_dir / "Physical"
    pkg_path = physical_dir / "Physical.pkg"
    configs: list[str] = []

    if pkg_path.is_file():
        root, _ = _parse_xml_file(pkg_path, project_dir=project_dir, issues=issues)
        if root is not None:
            seen_lower: set[str] = set()
            for elem in root.iter():
                if _local_tag(elem.tag) != "Object":
                    continue
                obj_type = (elem.attrib.get("Type") or "").strip().lower()
                name = (elem.text or "").strip()
                if not name:
                    continue
                if name.lower() in seen_lower:
                    issues.append(
                        {
                            "severity": "error",
                            "file": _rel_path(pkg_path, project_dir),
                            "code": "DUPLICATE_PACKAGE_OBJECT",
                            "message": f"Duplicate object {name!r} in Physical.pkg.",
                        }
                    )
                seen_lower.add(name.lower())
                if obj_type == "configuration" or not obj_type:
                    configs.append(name)

    if not configs and physical_dir.is_dir():
        for child in sorted(physical_dir.iterdir()):
            if child.is_dir() and (
                (child / "Hardware.hw").is_file() or (child / "Config.pkg").is_file()
            ):
                configs.append(child.name)

    return configs


def _inspect_hardware_and_cpu(
    project_dir: Path,
    config_name: str,
    *,
    issues: list[dict[str, Any]],
) -> tuple[dict[str, Any], Path | None]:
    config_dir = project_dir / "Physical" / config_name
    config_pkg = config_dir / "Config.pkg"
    hw_path = config_dir / "Hardware.hw"

    cpu_dir_name: str | None = None
    safety_nodes: list[str] = []

    if config_pkg.is_file():
        cfg_root, _ = _parse_xml_file(config_pkg, project_dir=project_dir, issues=issues)
        if cfg_root is not None:
            for elem in cfg_root.iter():
                if _local_tag(elem.tag) != "Object":
                    continue
                obj_type = (elem.attrib.get("Type") or "").strip().lower()
                name = (elem.text or "").strip()
                if not name:
                    continue
                if obj_type == "cpu" and cpu_dir_name is None:
                    cpu_dir_name = name
                if obj_type == "package" and "safety" in name.lower():
                    safety_nodes.append(f"Config.pkg:{name}")

    if cpu_dir_name is None and config_dir.is_dir():
        for child in sorted(config_dir.iterdir()):
            if child.is_dir() and (child / "Cpu.pkg").is_file():
                cpu_dir_name = child.name
                break

    cpu_dir = (config_dir / cpu_dir_name) if cpu_dir_name else None
    cpu_pkg = (cpu_dir / "Cpu.pkg") if cpu_dir else None
    cpu_sw = (cpu_dir / "Cpu.sw") if cpu_dir else None

    cpu_type: str | None = cpu_dir_name
    ar_version: str | None = None
    safety_release: str | None = None
    online_connection: str | None = None

    if cpu_pkg and cpu_pkg.is_file():
        cpu_root, _ = _parse_xml_file(cpu_pkg, project_dir=project_dir, issues=issues)
        if cpu_root is not None:
            for elem in cpu_root.iter():
                tag = _local_tag(elem.tag)
                if tag == "Configuration" and elem.attrib.get("ModuleId"):
                    cpu_type = str(elem.attrib["ModuleId"]).strip()
                elif tag == "AutomationRuntime" and elem.attrib.get("Version"):
                    ar_version = str(elem.attrib["Version"]).strip()
                elif tag == "Safety":
                    rel_val = str(elem.attrib.get("SafetyRelease") or "").strip()
                    safety_release = rel_val or None
                    if rel_val and rel_val not in {"0", "0.0", "0.0.0"}:
                        safety_nodes.append(f"Cpu.pkg:SafetyRelease={rel_val}")
                elif tag == "OnlineConfiguration" and elem.attrib.get("ConnectionParameters"):
                    online_connection = str(elem.attrib["ConnectionParameters"]).strip()
                elif tag == "Object":
                    obj_type = (elem.attrib.get("Type") or "").strip().lower()
                    name = (elem.text or "").strip()
                    if obj_type == "package" and "safety" in name.lower():
                        safety_nodes.append(f"Cpu.pkg:{name}")

    sim_ip: str | None = None
    if hw_path.is_file():
        hw_root, _ = _parse_xml_file(hw_path, project_dir=project_dir, issues=issues)
        if hw_root is not None:
            for elem in hw_root.iter():
                tag = _local_tag(elem.tag)
                if tag == "Parameter" and elem.attrib.get("ID") == "SimulationIPAddress":
                    val = str(elem.attrib.get("Value") or "").strip()
                    if val:
                        sim_ip = val
                elif tag == "Module":
                    mod_name = str(elem.attrib.get("Name") or "").strip()
                    mod_type = str(elem.attrib.get("Type") or "").strip()
                    if mod_type and SAFETY_MODULE_TYPE_RE.search(mod_type):
                        safety_nodes.append(f"Hardware.hw:{mod_name or mod_type}({mod_type})")
                    elif mod_name and "safelogic" in mod_name.lower():
                        safety_nodes.append(f"Hardware.hw:{mod_name}")

    sim_ip_is_default = sim_ip is None
    effective_sim_ip = sim_ip or "127.0.0.1"

    hardware_summary = {
        "config": config_name,
        "cpu_directory": _rel_path(cpu_dir, project_dir) if cpu_dir and cpu_dir.is_dir() else None,
        "cpu_type": cpu_type,
        "ar_version": ar_version,
        "simulation_ip": effective_sim_ip,
        "simulation_ip_is_default": sim_ip_is_default,
        "online_connection": online_connection,
        "safety_release": safety_release,
        "has_safety_hardware": bool(safety_nodes),
        "safety_nodes": sorted(set(safety_nodes)),
        "hardware_hw": _rel_path(hw_path, project_dir) if hw_path.is_file() else None,
        "cpu_sw": _rel_path(cpu_sw, project_dir) if cpu_sw and cpu_sw.is_file() else None,
    }
    return hardware_summary, cpu_sw


def _resolve_reference_path(raw_ref: str, *, base_dir: Path, project_dir: Path) -> Path:
    normalized = raw_ref.replace("\\", "/").strip()
    if normalized.startswith("/"):
        return project_dir / normalized.lstrip("/")
    return base_dir / normalized


def _parse_prg_files(
    prg_path: Path,
    *,
    project_dir: Path,
    issues: list[dict[str, Any]],
    check_integrity: bool,
) -> list[str]:
    root, _ = _parse_xml_file(prg_path, project_dir=project_dir, issues=issues)
    if root is None:
        return []
    files: list[str] = []
    prg_dir = prg_path.parent
    rel_prg = _rel_path(prg_path, project_dir)
    for elem in root.iter():
        if _local_tag(elem.tag) != "File":
            continue
        name = (elem.text or "").strip()
        if not name:
            continue
        is_ref = (elem.attrib.get("Reference") or "").strip().lower() == "true"
        target = (
            _resolve_reference_path(name, base_dir=prg_dir, project_dir=project_dir)
            if is_ref
            else (prg_dir / name)
        )
        files.append(_rel_path(target, project_dir))
        if check_integrity and not target.exists():
            issues.append(
                {
                    "severity": "error",
                    "file": rel_prg,
                    "code": "MISSING_REFERENCED_FILE",
                    "message": f"Program file {name!r} referenced by {rel_prg} does not exist on disk.",
                }
            )
    return files


def _resolve_task_source(
    source: str,
    *,
    project_dir: Path,
) -> tuple[Path | None, Path | None]:
    """Resolve a Cpu.sw task Source like 'Source.AcpTrak.TrakAuto.prg' to (dir_path, prg_file)."""
    cleaned = source.strip()
    if not cleaned:
        return None, None
    logical_dir = project_dir / "Logical"
    stem = cleaned[:-4] if cleaned.lower().endswith(".prg") else cleaned
    parts = [part for part in stem.split(".") if part]
    if not parts:
        return None, None

    candidate_dir = logical_dir.joinpath(*parts)
    if candidate_dir.is_dir():
        for preferred in ("IEC.prg", "ANSIC.prg", "Binary.prg", "ST.prg"):
            prg = candidate_dir / preferred
            if prg.is_file():
                return candidate_dir, prg
        prgs = sorted(candidate_dir.glob("*.prg"))
        return candidate_dir, (prgs[0] if prgs else None)

    direct_file = logical_dir.joinpath(*parts[:-1], f"{parts[-1]}.prg") if len(parts) > 1 else logical_dir / f"{parts[0]}.prg"
    if direct_file.is_file():
        return direct_file.parent, direct_file
    return None, None


def _parse_cpu_sw(
    cpu_sw: Path | None,
    *,
    project_dir: Path,
    include_files: bool,
    check_integrity: bool,
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if cpu_sw is None or not cpu_sw.is_file():
        return [], []
    root, _ = _parse_xml_file(cpu_sw, project_dir=project_dir, issues=issues)
    if root is None:
        return [], []

    rel_sw = _rel_path(cpu_sw, project_dir)
    task_classes: list[dict[str, Any]] = []
    all_tasks: list[dict[str, Any]] = []

    for tc_elem in root.iter():
        if _local_tag(tc_elem.tag) != "TaskClass":
            continue
        tc_name = str(tc_elem.attrib.get("Name") or "").strip()
        tc_tasks: list[dict[str, Any]] = []
        for child in list(tc_elem):
            tag = _local_tag(child.tag)
            if tag not in {"Task", "TaskObject"}:
                continue
            name = str(child.attrib.get("Name") or "").strip()
            source = str(child.attrib.get("Source") or "").strip()
            memory = str(child.attrib.get("Memory") or "").strip() or None
            language = str(child.attrib.get("Language") or "").strip() or None
            debugging = str(child.attrib.get("Debugging") or "").strip().lower() == "true"
            disabled = str(child.attrib.get("Disabled") or "").strip().lower() == "true"

            source_dir, prg_file = _resolve_task_source(source, project_dir=project_dir)
            source_exists = source_dir is not None
            if check_integrity and source and not source_exists:
                issues.append(
                    {
                        "severity": "error",
                        "file": rel_sw,
                        "code": "BROKEN_TASK_SOURCE",
                        "message": f"Task {name!r} in {tc_name or 'TaskClass'} references missing Logical source {source!r}.",
                    }
                )

            task_entry: dict[str, Any] = {
                "name": name,
                "task_class": tc_name,
                "source": source,
                "memory": memory,
                "language": language,
                "debugging": debugging,
                "disabled": disabled,
                "enabled": not disabled,
                "source_exists": source_exists,
                "source_dir": _rel_path(source_dir, project_dir) if source_dir else None,
                "program_file": _rel_path(prg_file, project_dir) if prg_file else None,
            }
            if include_files:
                if prg_file and prg_file.is_file():
                    task_entry["files"] = _parse_prg_files(
                        prg_file,
                        project_dir=project_dir,
                        issues=[],  # Integrity check walks Logical once to avoid duplicate issues.
                        check_integrity=False,
                    )
                else:
                    task_entry["files"] = []
            tc_tasks.append(task_entry)
            all_tasks.append(task_entry)

        task_classes.append(
            {
                "name": tc_name,
                "task_count": len(tc_tasks),
                "enabled_count": sum(1 for item in tc_tasks if item["enabled"]),
                "tasks": tc_tasks,
            }
        )
    return task_classes, all_tasks


def _collect_global_declarations(project_dir: Path) -> dict[str, Any]:
    logical_dir = project_dir / "Logical"
    global_var = logical_dir / "Global.var"
    global_typ = logical_dir / "Global.typ"
    package_declarations: list[dict[str, Any]] = []

    if logical_dir.is_dir():
        for child in sorted(logical_dir.iterdir()):
            if not child.is_dir() or child.name.lower() == "libraries":
                continue
            vars_files = sorted(_rel_path(p, project_dir) for p in child.glob("*.var"))
            typs_files = sorted(_rel_path(p, project_dir) for p in child.glob("*.typ"))
            if vars_files or typs_files:
                package_declarations.append(
                    {
                        "package": child.name,
                        "var_files": vars_files,
                        "typ_files": typs_files,
                    }
                )

    return {
        "global_var": _rel_path(global_var, project_dir) if global_var.is_file() else None,
        "global_typ": _rel_path(global_typ, project_dir) if global_typ.is_file() else None,
        "top_level_packages": package_declarations,
    }


def _check_logical_integrity(project_dir: Path, *, issues: list[dict[str, Any]]) -> None:
    """Walk Logical/Package.pkg and *.prg files for dangling references and duplicates."""
    logical_dir = project_dir / "Logical"
    if not logical_dir.is_dir():
        return

    visited_pkgs: set[Path] = set()

    def walk_package(pkg_path: Path, *, skip_libraries_subtree: bool = False) -> None:
        resolved = pkg_path.resolve()
        if resolved in visited_pkgs:
            return
        visited_pkgs.add(resolved)

        root, _ = _parse_xml_file(pkg_path, project_dir=project_dir, issues=issues)
        if root is None:
            return

        pkg_dir = pkg_path.parent
        rel_pkg = _rel_path(pkg_path, project_dir)
        seen_names: set[str] = set()

        for elem in root.iter():
            if _local_tag(elem.tag) != "Object":
                continue
            name = (elem.text or "").strip()
            if not name:
                continue
            obj_type = (elem.attrib.get("Type") or "").strip().lower()
            is_ref = (elem.attrib.get("Reference") or "").strip().lower() == "true"

            key = name.lower()
            if key in seen_names:
                issues.append(
                    {
                        "severity": "error",
                        "file": rel_pkg,
                        "code": "DUPLICATE_PACKAGE_OBJECT",
                        "message": f"Duplicate object {name!r} declared in {rel_pkg}.",
                    }
                )
            seen_names.add(key)

            target = (
                _resolve_reference_path(name, base_dir=pkg_dir, project_dir=project_dir)
                if is_ref
                else (pkg_dir / name)
            )
            if not target.exists():
                issues.append(
                    {
                        "severity": "error",
                        "file": rel_pkg,
                        "code": "MISSING_REFERENCED_FILE",
                        "message": f"Object {name!r} (Type={elem.attrib.get('Type') or 'unknown'}) referenced in {rel_pkg} does not exist on disk.",
                    }
                )
                continue

            if is_ref:
                continue
            if obj_type == "package" and target.is_dir():
                if skip_libraries_subtree and target.name.lower() == "libraries":
                    continue
                child_pkg = target / "Package.pkg"
                if child_pkg.is_file():
                    walk_package(child_pkg)
            elif obj_type == "program" and target.is_dir():
                for prg_file in sorted(target.glob("*.prg")):
                    _parse_prg_files(
                        prg_file,
                        project_dir=project_dir,
                        issues=issues,
                        check_integrity=True,
                    )

    root_pkg = logical_dir / "Package.pkg"
    if root_pkg.is_file():
        walk_package(root_pkg, skip_libraries_subtree=True)


def inspect_project(
    project_path: str | Path,
    *,
    config: str | None = None,
    include_files: bool = False,
    check_integrity: bool = True,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Inspect an Automation Studio project's topology and run optional static integrity checks."""
    apj_path = _locate_apj(project_path, repo_root=repo_root)
    project_dir = apj_path.parent
    issues: list[dict[str, Any]] = []

    _, apj_text = _parse_xml_file(apj_path, project_dir=project_dir, issues=issues)
    as_version, family = _detect_as_version(apj_text)
    available_configs = _discover_configs(project_dir, issues=issues)

    selected_config: str | None = None
    if config and str(config).strip():
        requested = str(config).strip()
        if available_configs and requested not in available_configs:
            names = ", ".join(available_configs)
            raise ValueError(
                f"Config {requested!r} was not found in Physical/Physical.pkg; available: {names}"
            )
        selected_config = requested
    else:
        default_cfg = _default_config_from_br_auto_dev(project_dir)
        if default_cfg and (not available_configs or default_cfg in available_configs):
            selected_config = default_cfg
        elif available_configs:
            selected_config = available_configs[0]

    hardware_summary: dict[str, Any] = {}
    cpu_sw: Path | None = None
    if selected_config:
        hardware_summary, cpu_sw = _inspect_hardware_and_cpu(
            project_dir, selected_config, issues=issues
        )

    task_classes, all_tasks = _parse_cpu_sw(
        cpu_sw,
        project_dir=project_dir,
        include_files=bool(include_files),
        check_integrity=bool(check_integrity),
        issues=issues,
    )
    globals_index = _collect_global_declarations(project_dir)

    if check_integrity:
        _check_logical_integrity(project_dir, issues=issues)

    # Deduplicate issues while preserving order.
    deduped_issues: list[dict[str, Any]] = []
    seen_issue_keys: set[tuple[str, str, str, str]] = set()
    for item in issues:
        key = (item["severity"], item["file"], item["code"], item["message"])
        if key not in seen_issue_keys:
            seen_issue_keys.add(key)
            deduped_issues.append(item)

    error_count = sum(1 for item in deduped_issues if item["severity"] == "error")
    warning_count = sum(1 for item in deduped_issues if item["severity"] == "warning")

    return {
        "ok": True,
        "project": {
            "apj_path": str(apj_path),
            "project_dir": str(project_dir),
            "as_version": as_version,
            "family": family,
            "selected_config": selected_config,
            "available_configs": available_configs,
        },
        "hardware": hardware_summary,
        "task_summary": {
            "total_tasks": len(all_tasks),
            "enabled_tasks": sum(1 for item in all_tasks if item["enabled"]),
            "disabled_tasks": sum(1 for item in all_tasks if item["disabled"]),
        },
        "task_classes": task_classes,
        "global_declarations": globals_index,
        "integrity": {
            "checked": bool(check_integrity),
            "ok": error_count == 0,
            "error_count": error_count,
            "warning_count": warning_count,
            "issues": deduped_issues,
        },
    }
