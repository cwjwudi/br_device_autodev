"""Persistent registry and safe lifecycle management for codex-arsim instances."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "var" / "arsim" / "instances.json"
_REGISTRY_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _norm_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(value)))


def _is_subpath(child: str | Path, parent: str | Path) -> bool:
    try:
        child_norm = Path(_norm_path(child))
        parent_norm = Path(_norm_path(parent))
        child_norm.relative_to(parent_norm)
        return True
    except ValueError:
        return False


def is_codex_arsim_run_dir(path: str | Path) -> bool:
    """Return True iff path is a direct child of a 'codex-arsim' directory."""
    candidate = Path(os.path.abspath(str(path)))
    if candidate.is_symlink():
        return False
    return candidate.parent.name.casefold() == "codex-arsim" and bool(candidate.name)


def get_process_executable_path(pid: int) -> str | None:
    """Return the full executable path for a live process, or None if not running."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name != "nt":
        proc_exe = Path(f"/proc/{pid}/exe")
        try:
            return str(proc_exe.resolve()) if proc_exe.exists() else None
        except OSError:
            return None

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
    open_process.restype = ctypes.wintypes.HANDLE

    query_name = kernel32.QueryFullProcessImageNameW
    query_name.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.LPWSTR,
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    query_name.restype = ctypes.wintypes.BOOL

    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD)]
    get_exit_code.restype = ctypes.wintypes.BOOL

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.wintypes.HANDLE]
    close_handle.restype = ctypes.wintypes.BOOL

    handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        STILL_ACTIVE = 259
        exit_code = ctypes.wintypes.DWORD(0)
        if get_exit_code(handle, ctypes.byref(exit_code)) and exit_code.value != STILL_ACTIVE:
            return None
        size = ctypes.wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not query_name(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value or None
    finally:
        close_handle(handle)


def list_processes_under_directory(directory: str | Path) -> list[dict[str, Any]]:
    """Return running processes whose ExecutablePath is inside directory."""
    if os.name != "nt":
        return []
    target_dir = _norm_path(directory)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    enum_processes = psapi.EnumProcesses
    enum_processes.argtypes = [
        ctypes.POINTER(ctypes.wintypes.DWORD),
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    enum_processes.restype = ctypes.wintypes.BOOL

    count = 4096
    arr = (ctypes.wintypes.DWORD * count)()
    cb_needed = ctypes.wintypes.DWORD(0)
    if not enum_processes(arr, ctypes.sizeof(arr), ctypes.byref(cb_needed)):
        return []
    num_pids = cb_needed.value // ctypes.sizeof(ctypes.wintypes.DWORD)
    matched: list[dict[str, Any]] = []
    for idx in range(num_pids):
        pid = int(arr[idx])
        if pid <= 0:
            continue
        exe = get_process_executable_path(pid)
        if exe and _is_subpath(exe, target_dir):
            matched.append({"pid": pid, "executable": exe})
    return matched


def _load_registry_unlocked(registry_path: Path) -> dict[str, Any]:
    if not registry_path.is_file():
        return {"schema_version": 1, "instances": []}
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "instances": []}
    if not isinstance(data, dict) or not isinstance(data.get("instances"), list):
        return {"schema_version": 1, "instances": []}
    return data


def _save_registry_unlocked(registry_path: Path, data: dict[str, Any]) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = registry_path.with_name(f".{registry_path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp_path, registry_path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        tmp_path.unlink(missing_ok=True)


def load_instances(registry_path: Path = DEFAULT_REGISTRY_PATH) -> list[dict[str, Any]]:
    with _REGISTRY_LOCK:
        return list(_load_registry_unlocked(registry_path)["instances"])


def upsert_instance(record: dict[str, Any], registry_path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    run_id = str(record.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("Instance record requires a non-empty run_id")
    normalized = dict(record)
    normalized["run_id"] = run_id
    normalized.setdefault("created_at", _utc_now())
    normalized.setdefault("status", "running")
    with _REGISTRY_LOCK:
        data = _load_registry_unlocked(registry_path)
        instances = [item for item in data["instances"] if item.get("run_id") != run_id]
        instances.append(normalized)
        data["instances"] = instances
        _save_registry_unlocked(registry_path, data)
    return normalized


def remove_instances(run_ids: set[str], registry_path: Path = DEFAULT_REGISTRY_PATH) -> int:
    if not run_ids:
        return 0
    with _REGISTRY_LOCK:
        data = _load_registry_unlocked(registry_path)
        before = len(data["instances"])
        data["instances"] = [item for item in data["instances"] if item.get("run_id") not in run_ids]
        removed = before - len(data["instances"])
        if removed:
            _save_registry_unlocked(registry_path, data)
        return removed


def _matches_filters(
    record: dict[str, Any],
    *,
    project_path: str | None = None,
    target: str | None = None,
    run_id: str | None = None,
    ip: str | None = None,
) -> bool:
    if run_id and str(record.get("run_id") or "") != run_id:
        return False
    if target and str(record.get("target") or "").casefold() != target.casefold():
        return False
    if ip and str(record.get("ip") or "") != ip:
        return False
    if project_path:
        wanted = _norm_path(project_path)
        rec_proj = record.get("project_path")
        if not rec_proj:
            return False
        rec_norm = _norm_path(rec_proj)
        if rec_norm != wanted:
            # Allow passing project directory instead of .apj file
            if not _is_subpath(rec_norm, wanted):
                return False
    return True


def inspect_instance_processes(record: dict[str, Any]) -> dict[str, Any]:
    """Verify PIDs and executable ownership for one registered ARsim instance."""
    runtime_dir = str(record.get("runtime_directory") or "")
    owned_pids: list[int] = []
    mismatched: list[dict[str, Any]] = []
    checked_pids: set[int] = set()

    for key in ("runtime_pid", "loader_pid"):
        pid = record.get(key)
        if not isinstance(pid, int) or pid <= 0 or pid in checked_pids:
            continue
        checked_pids.add(pid)
        exe = get_process_executable_path(pid)
        if exe is None:
            continue
        if runtime_dir and _is_subpath(exe, runtime_dir):
            owned_pids.append(pid)
        else:
            mismatched.append({"field": key, "pid": pid, "executable": exe})

    if runtime_dir:
        for proc in list_processes_under_directory(runtime_dir):
            pid = int(proc["pid"])
            if pid not in owned_pids:
                owned_pids.append(pid)

    return {
        "owned_pids": owned_pids,
        "mismatched": mismatched,
        "running": bool(owned_pids),
    }


def list_arsim_instances(
    *,
    project_path: str | None = None,
    target: str | None = None,
    run_id: str | None = None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    records = load_instances(registry_path)
    items: list[dict[str, Any]] = []
    for record in records:
        if not _matches_filters(record, project_path=project_path, target=target, run_id=run_id):
            continue
        proc_state = inspect_instance_processes(record)
        enriched = dict(record)
        if proc_state["mismatched"] and not proc_state["running"]:
            enriched["live_status"] = "ownership_mismatch"
        elif proc_state["running"]:
            enriched["live_status"] = "running"
        else:
            enriched["live_status"] = "stopped"
        enriched["live_owned_pids"] = proc_state["owned_pids"]
        enriched["run_directory_exists"] = bool(
            record.get("run_directory") and Path(str(record["run_directory"])).exists()
        )
        items.append(enriched)
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {
        "ok": True,
        "action": "list",
        "registry_path": str(registry_path),
        "count": len(items),
        "instances": items,
    }


def _find_target_instance(
    *,
    project_path: str | None = None,
    target: str | None = None,
    run_id: str | None = None,
    ip: str | None = None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    records = load_instances(registry_path)
    matches = [
        rec
        for rec in records
        if _matches_filters(rec, project_path=project_path, target=target, run_id=run_id, ip=ip)
    ]
    matches.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    if not matches:
        return None, []
    if run_id:
        return matches[0], matches
    # Prefer a currently running instance if multiple historical entries exist
    running_matches = [rec for rec in matches if inspect_instance_processes(rec)["running"]]
    if len(running_matches) == 1:
        return running_matches[0], running_matches
    if len(running_matches) > 1:
        return None, running_matches
    return matches[0], matches


def _port_11169_conflicts(sample: dict[str, Any]) -> list[dict[str, Any]]:
    if not sample.get("ok"):
        return []
    slots = sample.get("slots") or []
    if not slots:
        return []
    conflicts = slots[0].get("conflicts") or []
    return [item for item in conflicts if item.get("port") == 11169]


def stop_arsim_instance(
    *,
    project_path: str | None = None,
    target: str | None = None,
    run_id: str | None = None,
    ip: str | None = None,
    execute: bool = False,
    occupancy: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    terminate_fn: Callable[[int], dict[str, Any]] | None = None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    if not execute:
        return {
            "ok": False,
            "action": "stop",
            "error_code": "CONFIRMATION_REQUIRED",
            "error": "Stopping an ARsim instance requires execute=true.",
        }
    record, candidates = _find_target_instance(
        project_path=project_path,
        target=target,
        run_id=run_id,
        ip=ip,
        registry_path=registry_path,
    )
    if record is None:
        if len(candidates) > 1:
            return {
                "ok": False,
                "action": "stop",
                "error_code": "ARSIM_INSTANCE_AMBIGUOUS",
                "error": "Multiple running ARsim instances match the filter; specify run_id.",
                "candidates": [item.get("run_id") for item in candidates],
            }
        return {
            "ok": False,
            "action": "stop",
            "error_code": "ARSIM_INSTANCE_NOT_FOUND",
            "error": "No registered ARsim instance matched the requested run_id/target.",
        }

    runtime_dir = str(record.get("runtime_directory") or "")
    if not runtime_dir:
        return {
            "ok": False,
            "action": "stop",
            "error_code": "ARSIM_OWNERSHIP_MISMATCH",
            "error": "Instance record is missing runtime_directory; refusing to terminate processes.",
            "run_id": record.get("run_id"),
        }

    proc_state = inspect_instance_processes(record)
    if proc_state["mismatched"]:
        return {
            "ok": False,
            "action": "stop",
            "error_code": "ARSIM_OWNERSHIP_MISMATCH",
            "error": "Process executable path does not belong to the registered ARsim runtime_directory; refusing to terminate.",
            "run_id": record.get("run_id"),
            "expected_runtime_directory": runtime_dir,
            "mismatched_processes": proc_state["mismatched"],
        }

    if terminate_fn is None:
        from toolchain import terminate_process_tree

        terminate_fn = terminate_process_tree

    terminated: list[dict[str, Any]] = []
    for pid in proc_state["owned_pids"]:
        res = terminate_fn(pid)
        terminated.append({"pid": pid, "result": res})

    instance_ip = str(record.get("ip") or "")
    occupancy_sample: dict[str, Any] | None = None
    port_released = True
    if occupancy is not None and instance_ip:
        deadline = time.monotonic() + min(max(timeout_seconds, 2), 10)
        while True:
            occupancy_sample = occupancy({"addresses": [instance_ip], "timeout_seconds": min(timeout_seconds, 10)})
            conflicts = _port_11169_conflicts(occupancy_sample)
            port_released = len(conflicts) == 0
            if port_released or time.monotonic() >= deadline:
                break
            time.sleep(0.3)

    updated = dict(record)
    updated["status"] = "stopped" if port_released else "stop_incomplete"
    updated["stopped_at"] = _utc_now()
    upsert_instance(updated, registry_path=registry_path)

    return {
        "ok": port_released,
        "action": "stop",
        "run_id": record.get("run_id"),
        "target": record.get("target"),
        "ip": instance_ip,
        "runtime_directory": runtime_dir,
        "terminated_pids": [item["pid"] for item in terminated],
        "termination_details": terminated,
        "port_11169_released": port_released,
        "occupancy": occupancy_sample,
        **({} if port_released else {"error_code": "ARSIM_PORT_STILL_OCCUPIED", "error": f"Port 11169 on {instance_ip} is still occupied after stop."}),
    }


def restart_arsim_instance(
    *,
    project_path: str | None = None,
    target: str | None = None,
    run_id: str | None = None,
    execute: bool = False,
    occupancy: Callable[[dict[str, Any]], dict[str, Any]],
    terminate_fn: Callable[[int], dict[str, Any]] | None = None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    if not execute:
        return {
            "ok": False,
            "action": "restart",
            "error_code": "CONFIRMATION_REQUIRED",
            "error": "Restarting an ARsim instance requires execute=true.",
        }
    record, candidates = _find_target_instance(
        project_path=project_path,
        target=target,
        run_id=run_id,
        registry_path=registry_path,
    )
    if record is None:
        if len(candidates) > 1:
            return {
                "ok": False,
                "action": "restart",
                "error_code": "ARSIM_INSTANCE_AMBIGUOUS",
                "error": "Multiple running ARsim instances match the filter; specify run_id.",
                "candidates": [item.get("run_id") for item in candidates],
            }
        return {
            "ok": False,
            "action": "restart",
            "error_code": "ARSIM_INSTANCE_NOT_FOUND",
            "error": "No registered ARsim instance matched the requested run_id/target.",
        }

    stop_result = stop_arsim_instance(
        run_id=str(record["run_id"]),
        execute=True,
        occupancy=occupancy,
        terminate_fn=terminate_fn,
        registry_path=registry_path,
        timeout_seconds=timeout_seconds,
    )
    if not stop_result.get("ok"):
        return {**stop_result, "action": "restart"}

    runtime = Path(str(record["runtime_directory"]))
    loader = Path(str(record.get("loader_exe") or (runtime / "ar000loader.exe")))
    if not loader.is_file() or not _is_subpath(loader, runtime):
        return {
            "ok": False,
            "action": "restart",
            "error_code": "ARSIM_LOADER_MISSING",
            "error": f"ARsim loader executable not found inside runtime directory: {loader}",
            "run_id": record["run_id"],
        }

    ip = str(record["ip"])
    before = occupancy({"addresses": [ip], "timeout_seconds": min(timeout_seconds, 15)})
    if not before.get("ok") or before["slots"][0]["state"] != "free":
        return {
            "ok": False,
            "action": "restart",
            "error_code": "ARSIM_IP_OCCUPIED",
            "error": f"Address {ip} is occupied before restart.",
            "run_id": record["run_id"],
            "occupancy": before,
        }

    if terminate_fn is None:
        from toolchain import terminate_process_tree

        terminate_fn = terminate_process_tree

    loader_process = subprocess.Popen(
        [str(loader), "-s", f"-simulationIP={ip}"],
        cwd=runtime,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + min(max(timeout_seconds, 5), 30)
    while time.monotonic() < deadline:
        addresses = [ip] if ip == "127.0.0.1" else [ip, "127.0.0.1"]
        sample = occupancy({"addresses": addresses, "timeout_seconds": min(timeout_seconds, 10)})
        conflicts = sample["slots"][0]["conflicts"] if sample.get("ok") else []
        owned = [
            item
            for item in conflicts
            if item.get("port") == 11169
            and item.get("path")
            and _is_subpath(item["path"], runtime)
        ]
        if owned:
            updated = dict(record)
            updated.update(
                {
                    "loader_pid": loader_process.pid,
                    "runtime_pid": owned[0]["pid"],
                    "status": "running",
                    "restarted_at": _utc_now(),
                }
            )
            run_dir = Path(str(record["run_directory"]))
            if run_dir.is_dir():
                (run_dir / "instance.json").write_text(json.dumps(updated, indent=2), encoding="utf-8")
            upsert_instance(updated, registry_path=registry_path)
            return {
                "ok": True,
                "action": "restart",
                "stage": "runtime_listening",
                "stop_result": stop_result,
                **updated,
            }
        if sample.get("ok") and len(sample["slots"]) > 1:
            wrong = [
                item
                for item in sample["slots"][1]["conflicts"]
                if item.get("path") and _is_subpath(item["path"], runtime)
            ]
            if wrong:
                return {
                    "ok": False,
                    "action": "restart",
                    "error_code": "ARSIM_WRONG_IP",
                    "conflicts": wrong,
                    "run_id": record["run_id"],
                    "loader_pid": loader_process.pid,
                    "cleanup": terminate_fn(loader_process.pid),
                }
        time.sleep(0.5)

    return {
        "ok": False,
        "action": "restart",
        "error_code": "ARSIM_START_TIMEOUT",
        "run_id": record["run_id"],
        "loader_pid": loader_process.pid,
        "cleanup": terminate_fn(loader_process.pid),
    }


def clean_arsim_directories(
    *,
    project_path: str | None = None,
    target: str | None = None,
    run_id: str | None = None,
    keep_latest: int = 2,
    execute: bool = False,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    if not execute:
        return {
            "ok": False,
            "action": "clean",
            "error_code": "CONFIRMATION_REQUIRED",
            "error": "Cleaning ARsim directories requires execute=true.",
        }
    keep_count = max(0, int(keep_latest))
    records = load_instances(registry_path)

    # Map normalized run_directory -> candidate info
    candidates_by_dir: dict[str, dict[str, Any]] = {}
    rejected_paths: list[str] = []

    for rec in records:
        if not _matches_filters(rec, project_path=project_path, target=target, run_id=run_id):
            continue
        run_dir_str = str(rec.get("run_directory") or "")
        if not run_dir_str:
            continue
        if not is_codex_arsim_run_dir(run_dir_str):
            rejected_paths.append(run_dir_str)
            continue
        norm = _norm_path(run_dir_str)
        candidates_by_dir[norm] = {
            "run_id": rec.get("run_id"),
            "run_directory": run_dir_str,
            "runtime_directory": str(rec.get("runtime_directory") or (Path(run_dir_str) / "runtime")),
            "record": rec,
            "sort_key": str(rec.get("created_at") or ""),
        }

    # Also discover unregistered subdirectories under <project>/Temp/Simulation/codex-arsim when project_path is given
    if project_path and not run_id:
        proj = Path(project_path)
        proj_dir = proj if proj.is_dir() else proj.parent
        codex_root = proj_dir / "Temp" / "Simulation" / "codex-arsim"
        if codex_root.is_dir():
            for child in codex_root.iterdir():
                if not child.is_dir() or child.is_symlink():
                    continue
                norm = _norm_path(child)
                if norm in candidates_by_dir:
                    continue
                if target:
                    req_file = child / "request.json"
                    if req_file.is_file():
                        try:
                            req = json.loads(req_file.read_text(encoding="utf-8-sig"))
                            if str(req.get("target") or "").casefold() != target.casefold():
                                continue
                        except (OSError, json.JSONDecodeError):
                            pass
                mtime = datetime.fromtimestamp(child.stat().st_mtime, tz=UTC).isoformat()
                candidates_by_dir[norm] = {
                    "run_id": child.name,
                    "run_directory": str(child),
                    "runtime_directory": str(child / "runtime"),
                    "record": None,
                    "sort_key": mtime,
                }

    if rejected_paths and not candidates_by_dir:
        return {
            "ok": False,
            "action": "clean",
            "error_code": "ARSIM_UNSAFE_CLEAN_PATH",
            "error": "Refusing to clean directories outside codex-arsim.",
            "rejected_paths": rejected_paths,
        }

    skipped_running: list[dict[str, Any]] = []
    stopped_candidates: list[dict[str, Any]] = []

    for item in candidates_by_dir.values():
        rec = item["record"]
        runtime_dir = item["runtime_directory"]
        if rec is not None:
            proc_state = inspect_instance_processes(rec)
            is_running = proc_state["running"]
        else:
            is_running = bool(list_processes_under_directory(runtime_dir))
        if is_running:
            skipped_running.append(
                {
                    "run_id": item["run_id"],
                    "run_directory": item["run_directory"],
                }
            )
        else:
            stopped_candidates.append(item)

    stopped_candidates.sort(key=lambda item: item["sort_key"], reverse=True)
    kept_items = stopped_candidates[:keep_count]
    to_remove = stopped_candidates[keep_count:]

    removed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    removed_run_ids: set[str] = set()

    for item in to_remove:
        run_dir = Path(item["run_directory"])
        if not is_codex_arsim_run_dir(run_dir):
            rejected_paths.append(str(run_dir))
            continue
        try:
            if run_dir.exists():
                shutil.rmtree(run_dir)
            removed.append({"run_id": item["run_id"], "run_directory": str(run_dir)})
            if item["run_id"]:
                removed_run_ids.add(str(item["run_id"]))
        except OSError as exc:
            errors.append({"run_id": item["run_id"], "run_directory": str(run_dir), "error": str(exc)})

    if removed_run_ids:
        remove_instances(removed_run_ids, registry_path=registry_path)

    return {
        "ok": len(errors) == 0 and len(rejected_paths) == 0,
        "action": "clean",
        "keep_latest": keep_count,
        "removed_count": len(removed),
        "removed": removed,
        "kept": [{"run_id": item["run_id"], "run_directory": item["run_directory"]} for item in kept_items],
        "skipped_running": skipped_running,
        "rejected_paths": rejected_paths,
        "errors": errors,
        **({"error_code": "ARSIM_UNSAFE_CLEAN_PATH"} if rejected_paths else {}),
    }
