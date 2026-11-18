from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from schemas import TOOL_RISK_LEVELS


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_DIR = REPO_ROOT / "var" / "locks"
DEFAULT_TARGETS_PATH = ""
DEFAULT_PROJECT_PATH = ""
DEFAULT_CONFIG = ""

TARGET_SCOPED_TOOLS = {
    name for name, risk in TOOL_RISK_LEVELS.items() if risk == "target_change"
}
PROJECT_SCOPED_TOOLS = {
    name for name, risk in TOOL_RISK_LEVELS.items() if risk == "project_write"
} | {"plc_build_project", "plc_run_arsim_closed_loop"}
CRITICAL_TOOLS = TARGET_SCOPED_TOOLS | PROJECT_SCOPED_TOOLS


class LockConflict(RuntimeError):
    def __init__(self, key: str, path: Path, holder: dict[str, Any] | None = None):
        super().__init__(f"Resource is already locked: {key}")
        self.key = key
        self.path = path
        self.holder = holder or {}


@dataclass
class FileLock:
    key: str
    path: Path
    token: str

    def release(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if payload.get("token") != self.token:
            return
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            # Deleting the lock file is best-effort: a stale lock is reclaimed
            # by acquire_lock() once it exceeds stale_after_seconds, so an
            # unlink failure (e.g. a sandboxed/recycle-bin-less environment)
            # must never turn a successful operation into an error.
            pass


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def resolve_scope_context(arguments: dict[str, Any]) -> dict[str, Any]:
    import toolchain

    options = toolchain.resolve_call_options(arguments)
    context = {
        "environment": arguments.get("environment"),
        "target": options["target"],
        "project_path": options["project_path"],
        "config": options["config"],
        "targets_path": options["targets_path"],
        "target_role": None,
        "target_ip": None,
    }
    try:
        targets = json.loads(_repo_path(context["targets_path"]).read_text(encoding="utf-8-sig"))
        definitions = targets.get("targets") or {}
        target_config = definitions.get(context["target"])
        if target_config is None:
            target_config = next((value for name, value in definitions.items()
                                  if name.casefold() == context["target"].casefold()), None)
        if isinstance(target_config, dict):
            context["target_role"] = target_config.get("role")
            context["target_ip"] = target_config.get("ip")
    except (json.JSONDecodeError, OSError):
        pass
    if arguments.get("ip"):
        context["target_ip"] = str(arguments["ip"])
    elif not context["target_ip"] and toolchain._RUNTIME_SERVICE is not None:
        try:
            target, _ = toolchain._RUNTIME_SERVICE._resolve(context["target"])
            context["target_ip"], context["target_role"] = target.ip, target.role
        except (AttributeError, KeyError):
            pass
    if context["target_ip"]:
        try:
            address = ipaddress.ip_address(context["target_ip"])
            context["target_ip"] = str(getattr(address, "ipv4_mapped", None) or address)
        except ValueError:
            pass
    return context


def lock_keys_for_tool(tool: str, arguments: dict[str, Any]) -> list[str]:
    context = resolve_scope_context(arguments)
    keys: list[str] = []
    if tool == "plc_provision_arsim":
        keys.append("arsim:allocation")
    if tool in PROJECT_SCOPED_TOOLS:
        project = _repo_path(context["project_path"]).resolve()
        keys.append(f"project:{project}:{context['config']}")
    if tool in TARGET_SCOPED_TOOLS:
        targets = _repo_path(context["targets_path"]).resolve()
        identity = context.get("target_ip") or f"{targets}:{context['target']}"
        keys.append(f"target:{identity}")
    return sorted(set(keys))


def lock_path(key: str, directory: Path = LOCK_DIR) -> Path:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_")[:48] or "resource"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return directory / f"{label}_{digest}.lock.json"


def acquire_lock(
    key: str,
    *,
    directory: Path = LOCK_DIR,
    metadata: dict[str, Any] | None = None,
    stale_after_seconds: int = 7200,
) -> FileLock:
    directory.mkdir(parents=True, exist_ok=True)
    path = lock_path(key, directory)
    token = uuid.uuid4().hex
    payload = {
        "key": key,
        "token": token,
        "pid": os.getpid(),
        "created_epoch": time.time(),
        "metadata": metadata or {},
    }

    for attempt in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                holder = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                holder = {}
            try:
                file_time = path.stat().st_mtime
            except FileNotFoundError:
                continue
            age = time.time() - float(holder.get("created_epoch") or file_time)
            metadata = holder.get("metadata") or {}
            if metadata.get("managed_download") is True and metadata.get("operation_id") and isinstance(holder.get("pid"), int):
                from download_job import owner_alive, remaining_processes

                stale = owner_alive(holder["pid"]) is False and remaining_processes(metadata["operation_id"]) == 0
            else:
                stale = age > stale_after_seconds
            if attempt == 0 and stale:
                path.unlink(missing_ok=True)
                continue
            raise LockConflict(key, path, holder)
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            return FileLock(key=key, path=path, token=token)

    raise LockConflict(key, path)


@contextmanager
def acquire_locks(
    keys: list[str],
    *,
    directory: Path = LOCK_DIR,
    metadata: dict[str, Any] | None = None,
) -> Iterator[list[FileLock]]:
    locks: list[FileLock] = []
    try:
        for key in sorted(set(keys)):
            locks.append(acquire_lock(key, directory=directory, metadata=metadata))
        yield locks
    finally:
        for item in reversed(locks):
            item.release()
