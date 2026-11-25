"""Create an isolated ARsim instance from a project RUC without replacing existing data."""

import ipaddress
import json
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import arsim_registry


def verify_as4_ip(project_path, config, ip):
    hardware = Path(project_path).parent / "Physical" / config / "Hardware.hw"
    parameters = ET.parse(hardware).getroot().iter()
    configured = next((node.get("Value") for node in parameters if node.get("ID") == "SimulationIPAddress"), "127.0.0.1")
    if configured != ip:
        raise ValueError(f"AS4 SimulationIPAddress is {configured}, but target IP is {ip}; configure the AS4 simulation address and rebuild the RUC")


def _try_replace_owned_instance(options, ip, before, occupancy, timeout, registry_path):
    """Stop an existing ARsim instance ONLY if every conflict belongs to this project+target."""
    conflicts = (before.get("slots") or [{}])[0].get("conflicts") or []
    if not conflicts:
        return None, "Occupied slot reported no process conflicts to verify ownership."
    records = arsim_registry.load_instances(registry_path)
    matched = [
        rec
        for rec in records
        if arsim_registry._matches_filters(
            rec,
            project_path=options.get("project_path"),
            target=options.get("target"),
            ip=ip,
        )
        and rec.get("runtime_directory")
    ]
    if not matched:
        return None, "No registered ARsim instance matches this project, target, and IP."

    matched_by_run_id: dict[str, dict] = {}
    for conflict in conflicts:
        conflict_path = conflict.get("path")
        if not conflict_path:
            return None, "Conflict process has no executable path; refusing to replace unknown process."
        owner = next(
            (rec for rec in matched if arsim_registry._is_subpath(conflict_path, rec["runtime_directory"])),
            None,
        )
        if owner is None:
            return None, f"Conflict process {conflict_path} does not belong to this project target."
        matched_by_run_id[str(owner["run_id"])] = owner

    stop_results = []
    for run_id in matched_by_run_id:
        res = arsim_registry.stop_arsim_instance(
            run_id=run_id,
            execute=True,
            occupancy=occupancy,
            registry_path=registry_path,
            timeout_seconds=min(timeout, 30),
        )
        stop_results.append(res)
        if not res.get("ok"):
            return None, res.get("error") or res.get("error_code") or "Failed to stop existing owned instance."
    return stop_results, None


def provision(
    options,
    target,
    package,
    chain,
    occupancy,
    timeout,
    *,
    replace_existing=False,
    registry_path=None,
):
    resolved_registry = registry_path if registry_path is not None else arsim_registry.DEFAULT_REGISTRY_PATH
    ip = str(ipaddress.ip_address(target["ip"]))
    if ipaddress.ip_address(ip).version != 4 or not ipaddress.ip_address(ip).is_loopback:
        raise ValueError("ARsim requires an IPv4 loopback address")
    if chain.family == "AS4":
        verify_as4_ip(options["project_path"], options["config"], ip)
        hardware = Path(options["project_path"]).parent / "Physical" / options["config"] / "Hardware.hw"
        if hardware.stat().st_mtime_ns > Path(package["package_path"]).stat().st_mtime_ns:
            raise ValueError("AS4 Hardware.hw is newer than the RUC; rebuild before provisioning")
    before = occupancy({"addresses": [ip], "timeout_seconds": min(timeout, 30)})
    replaced_instances = None
    if not before.get("ok") or before["slots"][0]["state"] != "free":
        if replace_existing and before.get("ok"):
            replaced_instances, reject_reason = _try_replace_owned_instance(
                options, ip, before, occupancy, timeout, resolved_registry
            )
            if replaced_instances is not None:
                before = occupancy({"addresses": [ip], "timeout_seconds": min(timeout, 30)})
            else:
                return {
                    "ok": False,
                    "stage": "occupancy",
                    "error_code": "ARSIM_IP_OCCUPIED",
                    "occupancy": before,
                    "replace_rejected_reason": reject_reason,
                }
        if not before.get("ok") or before["slots"][0]["state"] != "free":
            return {"ok": False, "stage": "occupancy", "error_code": "ARSIM_IP_OCCUPIED", "occupancy": before}

    configured = target.get("arsim_work_dir")
    base = Path(options["project_path"]).parent / "Temp" / "Simulation" if not configured else Path(configured)
    if configured and not base.is_absolute():
        base = Path(options["project_config_path"]).parent / base
    base = base.resolve()
    run_id = uuid.uuid4().hex
    run_dir = base / "codex-arsim" / run_id
    runtime = run_dir / "runtime"
    ruc = Path(package["package_path"]).resolve()
    if any(c in str(path) for path in (run_dir, ruc) for c in "\"'\r\n"):
        raise ValueError("RUC and work directory paths must not contain quotes or newlines")
    run_dir.mkdir(parents=True, exist_ok=False)
    pil, log = run_dir / "install.pil", run_dir / "install.log"
    if chain.family == "AS4":
        command = f'CreateARsimStructure "{ruc}", "{runtime}", "Start=0"'
    elif chain.family == "AS6":
        command = f'OfflineCommissioning "{ruc}", "ARSim", "", "DestinationDirectory=\'{runtime}\'", "Start=0"'
    else:
        raise ValueError(f"Unsupported Automation Studio family: {chain.family}")
    pil.write_text(command + "\n", encoding="utf-8")
    created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    metadata = {
        "run_id": run_id,
        "project_path": options["project_path"],
        "config": options["config"],
        "target": options["target"],
        "ip": ip,
        "package": str(ruc),
        "runtime": str(runtime),
        "run_directory": str(run_dir),
        "runtime_directory": str(runtime),
        "family": chain.family,
        "created_at": created_at,
    }
    (run_dir / "request.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    from toolchain import terminate_process_tree
    transfer = subprocess.Popen([str(chain.pvi_transfer_exe), "-silent", f"-{pil}", f"-{log}"], cwd=run_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        exit_code = transfer.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        cleanup = terminate_process_tree(transfer.pid)
        return {"ok": False, "stage": "offline_install", "error_code": "INSTALL_TIMEOUT", "run_directory": str(run_dir), "log_path": str(log), "cleanup": cleanup}
    loader = runtime / "ar000loader.exe"
    log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    if exit_code != 0 or "PROCESS FINISHED (SUCCESS)" not in log_text or not loader.is_file():
        return {"ok": False, "stage": "offline_install", "error_code": "INSTALL_FAILED", "exit_code": exit_code, "run_directory": str(run_dir), "log_path": str(log), "output_tail": log_text[-3000:]}
    before = occupancy({"addresses": [ip], "timeout_seconds": min(timeout, 30)})
    if not before.get("ok") or before["slots"][0]["state"] != "free":
        return {"ok": False, "stage": "occupancy", "error_code": "ARSIM_IP_OCCUPIED", "occupancy": before, "run_directory": str(run_dir)}
    loader_process = subprocess.Popen([str(loader), "-s", f"-simulationIP={ip}"], cwd=runtime, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.monotonic() + min(timeout, 30)
    while time.monotonic() < deadline:
        addresses = [ip] if ip == "127.0.0.1" else [ip, "127.0.0.1"]
        try:
            sample = occupancy({"addresses": addresses, "timeout_seconds": min(timeout, 10)})
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return {"ok": False, "stage": "startup", "error_code": "OCCUPANCY_FAILED", "error": str(exc), "run_directory": str(run_dir), "loader_pid": loader_process.pid, "cleanup": terminate_process_tree(loader_process.pid)}
        conflicts = sample["slots"][0]["conflicts"] if sample.get("ok") else []
        owned = [item for item in conflicts if item.get("port") == 11169 and item.get("path") and Path(item["path"]).parent.resolve() == runtime.resolve()]
        if owned:
            metadata.update(
                {
                    "loader_exe": str(loader),
                    "loader_pid": loader_process.pid,
                    "runtime_pid": owned[0]["pid"],
                    "status": "running",
                }
            )
            (run_dir / "instance.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            arsim_registry.upsert_instance(metadata, registry_path=resolved_registry)
            result = {
                "ok": True,
                "stage": "runtime_listening",
                "target": options["target"],
                "ip": ip,
                "run_directory": str(run_dir),
                "runtime_directory": str(runtime),
                "log_path": str(log),
                **metadata,
            }
            if replaced_instances is not None:
                result["replaced_instances"] = replaced_instances
            return result
        if sample.get("ok") and len(sample["slots"]) > 1:
            wrong = [item for item in sample["slots"][1]["conflicts"] if item.get("path") and Path(item["path"]).parent.resolve() == runtime.resolve()]
            if wrong:
                return {"ok": False, "stage": "startup", "error_code": "ARSIM_WRONG_IP", "conflicts": wrong, "run_directory": str(run_dir), "loader_pid": loader_process.pid, "cleanup": terminate_process_tree(loader_process.pid)}
        time.sleep(0.5)
    return {"ok": False, "stage": "startup", "error_code": "ARSIM_START_TIMEOUT", "run_directory": str(run_dir), "loader_pid": loader_process.pid, "log_path": str(log), "cleanup": terminate_process_tree(loader_process.pid)}
