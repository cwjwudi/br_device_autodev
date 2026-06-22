from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


PACKAGE_NS = "http://br-automation.co.at/AS/Package"
LIBRARY_NS = "http://br-automation.co.at/AS/Library"
BLOCKED_LIBRARY_FRAGMENTS = ("safety", "safeio")
VERSION_DIRECTORY_RE = re.compile(r"^v(?P<version>\d+(?:\.\d+)*)$", re.IGNORECASE)
IEC_COMMENT_RE = re.compile(r"\(\*.*?\*\)", re.DOTALL)
IEC_FUNCTION_RE = re.compile(
    r"\b(?P<kind>FUNCTION_BLOCK|FUNCTION)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
IEC_DECLARATION_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:(?!=)")
HEADER_DEFINE_RE = re.compile(r"^\s*#\s*define\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
HEADER_CALLABLE_RE = re.compile(
    r"\b(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*;",
    re.MULTILINE,
)
HEADER_TYPEDEF_RE = re.compile(
    r"\btypedef\b[^;{}]*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;",
    re.MULTILINE,
)


class LibraryManagerError(RuntimeError):
    pass


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def resolve_path(value: str | Path, base: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LibraryManagerError(f"Could not read JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LibraryManagerError(f"JSON file must contain an object: {path}")
    return payload


def unique_existing_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.resolve()
        key = os.path.normcase(str(resolved))
        if key in seen or not resolved.is_dir():
            continue
        seen.add(key)
        result.append(resolved)
    return result


def discover_library_roots(
    repo_root: Path,
    targets_file: Path,
    explicit_roots: Iterable[Path] = (),
) -> list[Path]:
    if not path_within(targets_file, repo_root):
        raise LibraryManagerError(f"targets file must stay inside repository root: {targets_file}")
    explicit = list(explicit_roots)
    if explicit:
        return unique_existing_paths(resolve_path(path, repo_root) for path in explicit)

    config = read_json(targets_file)
    automation_studio = config.get("automation_studio") or {}
    candidates: list[Path] = []

    configured_roots = automation_studio.get("library_roots") or []
    if isinstance(configured_roots, list):
        candidates.extend(resolve_path(str(path), repo_root) for path in configured_roots)

    build_exe = automation_studio.get("build_exe")
    bin_dir = automation_studio.get("bin_dir")
    install_roots: list[Path] = []
    if build_exe:
        install_roots.append(resolve_path(str(build_exe), repo_root).parent.parent)
    if bin_dir:
        install_roots.append(resolve_path(str(bin_dir), repo_root).parent)

    for install_root in install_roots:
        candidates.extend(
            [
                install_root / "AS" / "Library_2",
                install_root / "AS" / "TechnologyPackages",
            ]
        )

    configured_candidates = unique_existing_paths(candidates)
    if configured_candidates:
        return configured_candidates

    for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
        program_files = os.environ.get(env_name)
        if not program_files:
            continue
        install_root = Path(program_files) / "BRAutomation" / "AS6"
        candidates.extend(
            [
                install_root / "AS" / "Library_2",
                install_root / "AS" / "TechnologyPackages",
            ]
        )

    return unique_existing_paths(candidates)


def find_library_manifests(root: Path) -> list[Path]:
    manifests: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for filename in filenames:
            if filename.lower() == "binary.lby":
                manifests.append((Path(directory) / filename).resolve())
    return sorted(manifests, key=lambda path: os.path.normcase(str(path)))


def parse_iec_symbols(path: Path) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    text = IEC_COMMENT_RE.sub("", text)
    suffix = path.suffix.lower()
    symbols: dict[str, str] = {}

    if suffix == ".fun":
        for match in IEC_FUNCTION_RE.finditer(text):
            kind = "function_block" if match.group("kind").upper() == "FUNCTION_BLOCK" else "function"
            symbols.setdefault(match.group("name"), kind)
    elif suffix == ".typ":
        struct_depth = 0
        in_type = False
        for line in text.splitlines():
            upper = line.strip().upper()
            if upper == "TYPE":
                in_type = True
                continue
            if upper == "END_TYPE":
                in_type = False
                continue
            if not in_type:
                continue
            if upper.startswith("END_STRUCT"):
                struct_depth = max(0, struct_depth - 1)
                continue
            if struct_depth == 0:
                match = IEC_DECLARATION_RE.match(line)
                if match:
                    symbols.setdefault(match.group("name"), "type")
            if re.search(r"\bSTRUCT\b", upper) and not upper.startswith("END_STRUCT"):
                struct_depth += 1
    elif suffix == ".var":
        for line in text.splitlines():
            match = IEC_DECLARATION_RE.match(line)
            if match:
                symbols.setdefault(match.group("name"), "constant_or_variable")

    return [{"name": name, "kind": kind} for name, kind in symbols.items()]


def parse_header_symbols(path: Path) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    symbols: dict[str, str] = {}
    for match in HEADER_DEFINE_RE.finditer(text):
        symbols.setdefault(match.group("name"), "macro")
    for match in HEADER_TYPEDEF_RE.finditer(text):
        symbols.setdefault(match.group("name"), "type")
    for match in HEADER_CALLABLE_RE.finditer(text):
        name = match.group("name")
        if name not in {"if", "for", "while", "switch", "sizeof"}:
            symbols.setdefault(name, "function")
    return [{"name": name, "kind": kind} for name, kind in symbols.items()]


def library_file_entries(root: ET.Element) -> list[str]:
    entries: list[str] = []
    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "File" and element.text and element.text.strip():
            entries.append(element.text.strip())
        elif tag == "Object" and element.get("Type", "").lower() == "file" and element.text:
            entries.append(element.text.strip())
    return entries


def technology_package_details(path: Path) -> tuple[str | None, str | None]:
    parts = path.parts
    lowered = [part.lower() for part in parts]
    try:
        index = lowered.index("technologypackages")
    except ValueError:
        return None, None
    if len(parts) <= index + 2:
        return None, None
    return parts[index + 1], parts[index + 2]


def parse_library_manifest(path: Path, source_root: Path, *, include_symbols: bool) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise LibraryManagerError(f"Could not parse library manifest {path}: {exc}") from exc

    version_match = VERSION_DIRECTORY_RE.match(path.parent.name)
    library_name = path.parent.parent.name if version_match else path.parent.name
    version = root.get("Version") or (version_match.group("version") if version_match else None)
    technology_package, technology_package_version = technology_package_details(path)
    files = library_file_entries(root)
    missing_files = [name for name in files if not (path.parent / name).is_file()]

    dependencies: list[dict[str, str | None]] = []
    for element in root.iter():
        if local_name(element.tag) != "Dependency":
            continue
        name = element.get("ObjectName")
        if name:
            dependencies.append(
                {
                    "name": name,
                    "from_version": element.get("FromVersion"),
                    "to_version": element.get("ToVersion"),
                }
            )

    symbols: dict[str, str] = {}
    if include_symbols:
        for relative_name in files:
            source_file = path.parent / relative_name
            for symbol in parse_iec_symbols(source_file):
                symbols.setdefault(symbol["name"], symbol["kind"])
        sg4 = path.parent / "SG4"
        if sg4.is_dir():
            for header in sg4.rglob("*.h"):
                for symbol in parse_header_symbols(header):
                    symbols.setdefault(symbol["name"], symbol["kind"])

    return {
        "name": library_name,
        "version": version,
        "description": root.get("Description") or "",
        "language": (root.get("SubType") or "binary").lower(),
        "source_path": str(path.parent.resolve()),
        "manifest_path": str(path.resolve()),
        "source_root": str(source_root.resolve()),
        "technology_package": technology_package,
        "technology_package_version": technology_package_version,
        "dependencies": dependencies,
        "files": files,
        "missing_files": missing_files,
        "symbols": [{"name": name, "kind": kind} for name, kind in sorted(symbols.items(), key=lambda item: item[0].lower())],
    }


def build_catalog(
    library_roots: Iterable[Path],
    *,
    include_symbols: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    libraries: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for source_root in library_roots:
        for manifest in find_library_manifests(source_root):
            key = os.path.normcase(str(manifest))
            if key in seen:
                continue
            seen.add(key)
            try:
                libraries.append(parse_library_manifest(manifest, source_root, include_symbols=include_symbols))
            except LibraryManagerError as exc:
                warnings.append(str(exc))
    libraries.sort(
        key=lambda item: (
            item["name"].lower(),
            version_key(item.get("version")),
            os.path.normcase(item["source_path"]),
        )
    )
    return libraries, warnings


def version_key(version: str | None) -> tuple[int, ...]:
    if not version:
        return ()
    numbers = [int(part) for part in re.findall(r"\d+", version)]
    while numbers and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def version_in_range(version: str | None, minimum: str | None, maximum: str | None) -> bool:
    if not minimum and not maximum:
        return True
    if not version:
        return False
    value = version_key(version)
    if minimum and value < version_key(minimum):
        return False
    if maximum and value > version_key(maximum):
        return False
    return True


def read_project_technology_packages(project_path: Path) -> dict[str, str]:
    try:
        root = ET.parse(project_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise LibraryManagerError(f"Could not parse Automation Studio project {project_path}: {exc}") from exc
    packages: dict[str, str] = {}
    for container in root.iter():
        if local_name(container.tag) != "TechnologyPackages":
            continue
        for element in container:
            if element.get("Version"):
                packages[local_name(element.tag).lower()] = str(element.get("Version"))
    return packages


def project_library_paths(project_path: Path) -> tuple[Path, Path]:
    libraries_dir = project_path.parent / "Logical" / "Libraries"
    package_path = libraries_dir / "Package.pkg"
    if not package_path.is_file():
        raise LibraryManagerError(f"Automation Studio library package was not found: {package_path}")
    return libraries_dir.resolve(), package_path.resolve()


def read_project_libraries(project_path: Path) -> dict[str, dict[str, Any]]:
    libraries_dir, package_path = project_library_paths(project_path)
    try:
        root = ET.parse(package_path).getroot()
    except ET.ParseError as exc:
        raise LibraryManagerError(f"Could not parse Automation Studio package {package_path}: {exc}") from exc

    result: dict[str, dict[str, Any]] = {}
    for element in root.iter():
        if local_name(element.tag) != "Object" or element.get("Type", "").lower() != "library":
            continue
        name = (element.text or "").strip()
        if not name:
            continue
        item: dict[str, Any] = {
            "name": name,
            "version": None,
            "path": str((libraries_dir / name).resolve()),
            "present": (libraries_dir / name).is_dir(),
        }
        directory = libraries_dir / name
        if directory.is_dir():
            manifests = [path for path in directory.iterdir() if path.is_file() and path.name.lower() == "binary.lby"]
            if manifests:
                try:
                    manifest_root = ET.parse(manifests[0]).getroot()
                    item["version"] = manifest_root.get("Version")
                except ET.ParseError:
                    pass
        result[name.lower()] = item
    return result


def candidate_public(candidate: dict[str, Any], *, include_symbols: bool = False) -> dict[str, Any]:
    result = {key: value for key, value in candidate.items() if key != "symbols"}
    if include_symbols:
        result["symbols"] = candidate.get("symbols") or []
    return result


def candidate_compatibility(candidate: dict[str, Any], project_packages: dict[str, str]) -> tuple[bool, str | None]:
    package = candidate.get("technology_package")
    package_version = candidate.get("technology_package_version")
    if not package:
        return True, None
    package_key = str(package).lower()
    aliases = [package_key]
    if package_key == "mappservices":
        aliases.append("mapp")
    project_version = next((project_packages[key] for key in aliases if key in project_packages), None)
    if project_version is None:
        return False, f"requires Technology Package {package} {package_version or candidate.get('version') or ''}".strip()
    if package_version and version_key(project_version) != version_key(str(package_version)):
        return False, f"project uses Technology Package {package} {project_version}, candidate requires {package_version}"
    return True, None


def blocked_library(name: str) -> bool:
    lowered = name.lower()
    return any(fragment in lowered for fragment in BLOCKED_LIBRARY_FRAGMENTS)


def choose_candidate(
    name: str,
    version: str | None,
    catalog: list[dict[str, Any]],
    project_packages: dict[str, str],
    minimum: str | None = None,
    maximum: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    candidates = [item for item in catalog if item["name"].lower() == name.lower()]
    if version:
        candidates = [
            item
            for item in candidates
            if version_key(item.get("version")) == version_key(version)
            or version_key(item.get("technology_package_version")) == version_key(version)
        ]
    candidates = [item for item in candidates if version_in_range(item.get("version"), minimum, maximum)]

    reasons: list[str] = []
    compatible: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("missing_files"):
            reasons.append(f"{candidate['name']} has missing interface files: {', '.join(candidate['missing_files'])}")
            continue
        ok, reason = candidate_compatibility(candidate, project_packages)
        if ok:
            compatible.append(candidate)
        elif reason:
            reasons.append(reason)

    if len(compatible) == 1:
        return compatible[0], candidates, reasons
    if not candidates:
        reasons.append(f"library {name!r} was not found in trusted Automation Studio roots")
    elif not compatible and not reasons:
        reasons.append(f"no compatible version of library {name!r} was found")
    elif len(compatible) > 1:
        versions = sorted({item.get("version") or "unversioned" for item in compatible})
        reasons.append(f"multiple compatible candidates found for {name!r}: {', '.join(versions)}")
    return None, candidates, reasons


def plan_library_add(
    repo_root: Path,
    project_path: Path,
    targets_file: Path,
    library_name: str,
    version: str | None = None,
    explicit_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    if blocked_library(library_name):
        return {
            "command": "PlanLibraryAdd",
            "ok": False,
            "requested_library": library_name,
            "errors": [f"automatic addition of Safety-related library {library_name!r} is blocked"],
        }
    if not path_within(project_path, repo_root):
        return {
            "command": "PlanLibraryAdd",
            "ok": False,
            "requested_library": library_name,
            "errors": [f"project must stay inside repository root: {project_path}"],
        }

    roots = discover_library_roots(repo_root, targets_file, explicit_roots)
    if not roots:
        return {
            "command": "PlanLibraryAdd",
            "ok": False,
            "requested_library": library_name,
            "library_roots": [],
            "errors": ["no trusted Automation Studio library roots were found"],
        }

    catalog, catalog_warnings = build_catalog(roots)
    project_packages = read_project_technology_packages(project_path)
    installed = read_project_libraries(project_path)
    additions: list[dict[str, Any]] = []
    errors: list[str] = []
    visiting: set[str] = set()
    selected_names: set[str] = set()

    def visit(name: str, requested_version: str | None, minimum: str | None, maximum: str | None) -> None:
        key = name.lower()
        if key in visiting:
            errors.append(f"cyclic library dependency detected at {name}")
            return
        existing = installed.get(key)
        if existing and existing.get("present"):
            if requested_version and version_key(existing.get("version")) != version_key(requested_version):
                errors.append(
                    f"installed library {existing['name']} version {existing.get('version') or 'unversioned'} "
                    f"does not match requested version {requested_version}"
                )
                return
            if not version_in_range(existing.get("version"), minimum, maximum):
                errors.append(
                    f"installed library {existing['name']} version {existing.get('version') or 'unversioned'} "
                    f"does not satisfy dependency range {minimum or '*'}..{maximum or '*'}"
                )
            return
        if key in selected_names:
            return
        if blocked_library(name):
            errors.append(f"automatic addition of Safety-related dependency {name!r} is blocked")
            return

        selected, candidates, reasons = choose_candidate(
            name,
            requested_version,
            catalog,
            project_packages,
            minimum,
            maximum,
        )
        if selected is None:
            errors.extend(reasons)
            if candidates:
                errors.append(
                    f"candidate details for {name}: "
                    + ", ".join(
                        f"{item.get('version') or 'unversioned'} at {item['source_path']}" for item in candidates
                    )
                )
            return

        visiting.add(key)
        for dependency in selected.get("dependencies") or []:
            visit(
                str(dependency["name"]),
                None,
                dependency.get("from_version"),
                dependency.get("to_version"),
            )
        visiting.remove(key)
        if errors:
            return
        selected_names.add(key)
        additions.append(candidate_public(selected))

    visit(library_name, version, None, None)
    return {
        "command": "PlanLibraryAdd",
        "ok": not errors,
        "project_path": str(project_path),
        "requested_library": library_name,
        "requested_version": version,
        "library_roots": [str(path) for path in roots],
        "installed_libraries": [item["name"] for item in installed.values()],
        "libraries_to_add": additions if not errors else [],
        "warnings": catalog_warnings,
        "errors": errors,
    }


def find_library_for_symbol(
    repo_root: Path,
    project_path: Path,
    targets_file: Path,
    symbol: str,
    explicit_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    roots = discover_library_roots(repo_root, targets_file, explicit_roots)
    catalog, warnings = build_catalog(roots, include_symbols=True)
    installed = read_project_libraries(project_path)
    project_packages = read_project_technology_packages(project_path)
    matches: list[dict[str, Any]] = []
    for candidate in catalog:
        matching_symbols = [item for item in candidate.get("symbols") or [] if item["name"].lower() == symbol.lower()]
        if not matching_symbols:
            continue
        compatible, reason = candidate_compatibility(candidate, project_packages)
        public = candidate_public(candidate)
        public["matched_symbols"] = matching_symbols
        public["already_in_project"] = candidate["name"].lower() in installed
        public["compatible"] = compatible
        if reason:
            public["compatibility_reason"] = reason
        matches.append(public)
    matches.sort(
        key=lambda item: (
            not item["already_in_project"],
            not item["compatible"],
            item["name"].lower(),
            version_key(item.get("version")),
        )
    )
    return {
        "command": "FindLibraryForSymbol",
        "ok": bool(matches),
        "symbol": symbol,
        "project_path": str(project_path),
        "library_roots": [str(path) for path in roots],
        "matches": matches,
        "warnings": warnings,
        "errors": [] if matches else [f"symbol {symbol!r} was not found in trusted Automation Studio libraries"],
    }


def package_with_added_libraries(package_path: Path, additions: list[dict[str, Any]]) -> bytes:
    original = package_path.read_text(encoding="utf-8-sig")
    newline = "\r\n" if "\r\n" in original else "\n"
    processing_instruction = re.search(r"<\?AutomationStudio\s+[^?]+\?>", original)
    root = ET.fromstring(original)
    objects = next((element for element in root if local_name(element.tag) == "Objects"), None)
    if objects is None:
        objects = ET.SubElement(root, f"{{{PACKAGE_NS}}}Objects")

    existing = {
        (element.text or "").strip().lower()
        for element in objects
        if local_name(element.tag) == "Object" and element.get("Type", "").lower() == "library"
    }
    for library in additions:
        if library["name"].lower() in existing:
            continue
        attributes = {"Type": "Library", "Language": library.get("language") or "binary"}
        if library.get("description"):
            attributes["Description"] = str(library["description"])
        element = ET.SubElement(objects, f"{{{PACKAGE_NS}}}Object", attributes)
        element.text = str(library["name"])
        existing.add(library["name"].lower())

    ET.register_namespace("", PACKAGE_NS)
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    prefix = ['<?xml version="1.0" encoding="utf-8"?>']
    if processing_instruction:
        prefix.append(processing_instruction.group(0))
    return (newline.join(prefix + [body, ""])).encode("utf-8")


def atomic_write(path: Path, content: bytes) -> None:
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_bytes(content)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*"), key=lambda value: str(value.relative_to(path)).lower()):
        if not item.is_file():
            continue
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def acquire_project_lock(libraries_dir: Path, token: str) -> Path:
    lock_path = libraries_dir / ".as_library_manager.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        owner = lock_path.read_text(encoding="utf-8", errors="replace").strip() if lock_path.is_file() else "unknown"
        raise LibraryManagerError(f"another library transaction holds {lock_path} ({owner})") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()} transaction={token}\n".encode("ascii"))
    finally:
        os.close(descriptor)
    return lock_path


def release_project_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def add_project_library(
    repo_root: Path,
    project_path: Path,
    targets_file: Path,
    library_name: str,
    version: str | None,
    execute: bool,
    explicit_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    plan = plan_library_add(
        repo_root,
        project_path,
        targets_file,
        library_name,
        version,
        explicit_roots,
    )
    result = dict(plan)
    result["command"] = "AddProjectLibrary"
    result["executed"] = False
    if not plan.get("ok"):
        return result
    additions = plan.get("libraries_to_add") or []
    if not additions:
        result["already_satisfied"] = True
        return result
    if not execute:
        result["ok"] = False
        result["errors"] = ["execute=true is required to modify the Automation Studio project"]
        return result

    transaction_id = uuid.uuid4().hex
    libraries_dir, package_path = project_library_paths(project_path)
    try:
        lock_path = acquire_project_lock(libraries_dir, transaction_id)
    except LibraryManagerError as exc:
        result["ok"] = False
        result["errors"] = [str(exc)]
        return result

    try:
        locked_plan = plan_library_add(
            repo_root,
            project_path,
            targets_file,
            library_name,
            version,
            explicit_roots,
        )
    except Exception:
        release_project_lock(lock_path)
        raise
    if not locked_plan.get("ok") or not locked_plan.get("libraries_to_add"):
        release_project_lock(lock_path)
        locked_result = dict(locked_plan)
        locked_result["command"] = "AddProjectLibrary"
        locked_result["executed"] = False
        if locked_plan.get("ok"):
            locked_result["already_satisfied"] = True
        return locked_result
    additions = locked_plan["libraries_to_add"]
    result.update(locked_plan)
    result["command"] = "AddProjectLibrary"
    result["executed"] = False

    transaction_dir = repo_root / "tools" / ".generated" / "library_transactions" / transaction_id
    stage_dir = transaction_dir / "stage"
    backup_path = transaction_dir / "Package.pkg.before"

    added_dirs: list[Path] = []
    try:
        transaction_dir.mkdir(parents=True, exist_ok=False)
        stage_dir.mkdir()
        shutil.copy2(package_path, backup_path)
        for library in additions:
            source = Path(library["source_path"])
            destination = libraries_dir / str(library["name"])
            if destination.exists():
                raise LibraryManagerError(f"destination already exists: {destination}")
            staged = stage_dir / str(library["name"])
            shutil.copytree(source, staged)

        for library in additions:
            staged = stage_dir / str(library["name"])
            destination = libraries_dir / str(library["name"])
            shutil.move(str(staged), str(destination))
            added_dirs.append(destination)

        atomic_write(package_path, package_with_added_libraries(package_path, additions))
        manifest = {
            "transaction_id": transaction_id,
            "project_path": str(project_path),
            "package_path": str(package_path),
            "package_backup": str(backup_path),
            "added_libraries": [
                {
                    "name": path.name,
                    "path": str(path),
                    "digest": tree_digest(path),
                }
                for path in added_dirs
            ],
            "rolled_back": False,
        }
        (transaction_dir / "transaction.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        rollback_errors: list[str] = []
        for path in reversed(added_dirs):
            if path.exists():
                try:
                    shutil.rmtree(path)
                except OSError as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
        if backup_path.is_file():
            try:
                shutil.copy2(backup_path, package_path)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        result["ok"] = False
        result["errors"] = [f"library transaction failed; rollback was attempted: {exc}"]
        if rollback_errors:
            result["errors"].append("rollback cleanup errors: " + "; ".join(rollback_errors))
        result["transaction_id"] = transaction_id
        result["transaction_path"] = str(transaction_dir)
        release_project_lock(lock_path)
        return result

    release_project_lock(lock_path)
    result.update(
        {
            "ok": True,
            "executed": True,
            "transaction_id": transaction_id,
            "transaction_path": str(transaction_dir),
            "added_libraries": [path.name for path in added_dirs],
            "package_path": str(package_path),
        }
    )
    return result


def rollback_transaction(repo_root: Path, transaction_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        return {"command": "RollbackLibraryAdd", "ok": False, "errors": ["invalid transaction id"]}
    transaction_dir = (repo_root / "tools" / ".generated" / "library_transactions" / transaction_id).resolve()
    if not path_within(transaction_dir, repo_root):
        return {"command": "RollbackLibraryAdd", "ok": False, "errors": ["transaction path escaped repository root"]}
    manifest_path = transaction_dir / "transaction.json"
    if not manifest_path.is_file():
        return {"command": "RollbackLibraryAdd", "ok": False, "errors": [f"transaction was not found: {transaction_id}"]}
    manifest = read_json(manifest_path)
    if manifest.get("rolled_back"):
        return {"command": "RollbackLibraryAdd", "ok": True, "transaction_id": transaction_id, "already_rolled_back": True}

    package_path = Path(str(manifest["package_path"])).resolve()
    backup_path = Path(str(manifest["package_backup"])).resolve()
    added_libraries = manifest.get("added_libraries") or []
    errors: list[str] = []
    for item in added_libraries:
        path = Path(str(item["path"])).resolve()
        if not path_within(path, repo_root):
            errors.append(f"refusing to remove path outside repository: {path}")
        elif path.is_dir() and tree_digest(path) != item.get("digest"):
            errors.append(f"library changed after transaction; refusing automatic rollback: {path}")
    if errors:
        return {"command": "RollbackLibraryAdd", "ok": False, "transaction_id": transaction_id, "errors": errors}

    for item in reversed(added_libraries):
        path = Path(str(item["path"])).resolve()
        if path.exists():
            shutil.rmtree(path)
    atomic_write(package_path, backup_path.read_bytes())
    manifest["rolled_back"] = True
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "command": "RollbackLibraryAdd",
        "ok": True,
        "transaction_id": transaction_id,
        "removed_libraries": [str(item["name"]) for item in added_libraries],
        "package_path": str(package_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Index and safely add Automation Studio libraries.")
    parser.add_argument("command", choices=("find", "plan", "add", "rollback"))
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--project-path", default="PrintDemo\\Huitong_FrontEval.apj")
    parser.add_argument("--targets-file", default="tools\\plc_targets.local.json")
    parser.add_argument("--library-root", action="append", default=[])
    parser.add_argument("--symbol")
    parser.add_argument("--library")
    parser.add_argument("--version")
    parser.add_argument("--transaction-id")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    project_path = resolve_path(args.project_path, repo_root)
    targets_file = resolve_path(args.targets_file, repo_root)
    explicit_roots = [resolve_path(path, repo_root) for path in args.library_root]
    try:
        if args.command == "find":
            if not args.symbol:
                raise LibraryManagerError("--symbol is required for find")
            result = find_library_for_symbol(repo_root, project_path, targets_file, args.symbol, explicit_roots)
        elif args.command == "plan":
            if not args.library:
                raise LibraryManagerError("--library is required for plan")
            result = plan_library_add(repo_root, project_path, targets_file, args.library, args.version, explicit_roots)
        elif args.command == "add":
            if not args.library:
                raise LibraryManagerError("--library is required for add")
            result = add_project_library(
                repo_root,
                project_path,
                targets_file,
                args.library,
                args.version,
                args.execute,
                explicit_roots,
            )
        else:
            if not args.transaction_id:
                raise LibraryManagerError("--transaction-id is required for rollback")
            result = rollback_transaction(repo_root, args.transaction_id)
    except LibraryManagerError as exc:
        result = {"command": args.command, "ok": False, "errors": [str(exc)]}
    except Exception as exc:
        result = {"command": args.command, "ok": False, "errors": [f"unexpected library manager error: {exc}"]}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
