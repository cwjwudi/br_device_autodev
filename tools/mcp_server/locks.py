from __future__ import annotations

import hashlib
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
DEFAULT_ENVIRONMENTS_PATH = REPO_ROOT / "config" / "environments" / "environments.json"
DEFAULT_TARGETS_PATH = "config\\targets\\default-safe.json"
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
        if payload.get("token") == self.token:
            self.path.unlink(missing_ok=True)


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def resolve_scope_context(arguments: dict[str, Any]) -> dict[str, Any]:
    environment = arguments.get("environment")
    env: dict[str, Any] = {}
    if isinstance(environment, str) and environment.strip() and DEFAULT_ENVIRONMENTS_PATH.exists():
        try:
            environments = json.loads(
                DEFAULT_ENVIRONMENTS_PATH.read_text(encoding="utf-8-sig")
            )
            candidate = environments.get(environment)
            if isinstance(candidate, dict):
                env = candidate
        except (json.JSONDecodeError, OSError):
            env = {}

    def pick(name: str, default: str) -> str:
        value = arguments.get(name)
        if value not in (None, ""):
            return str(value)
        if env.get(name) not in (None, ""):
            return str(env[name])
        return default

    context = {
        "environment": environment if isinstance(environment, str) else None,
        "target": pick("target", "arsim"),
        "project_path": pick("project_path", DEFAULT_PROJECT_PATH),
        "config": pick("config", DEFAULT_CONFIG),
        "targets_path": pick("targets_path", DEFAULT_TARGETS_PATH),
        "target_role": None,
    }
    try:
        targets = json.loads(
            _repo_path(context["targets_path"]).read_text(encoding="utf-8-sig")
        )
        target_config = (targets.get("targets") or {}).get(context["target"])
        if isinstance(target_config, dict):
            context["target_role"] = target_config.get("role")
    except (json.JSONDecodeError, OSError):
        pass
    return context


def lock_keys_for_tool(tool: str, arguments: dict[str, Any]) -> list[str]:
    context = resolve_scope_context(arguments)
    keys: list[str] = []
    if tool in PROJECT_SCOPED_TOOLS:
        project = _repo_path(context["project_path"]).resolve()
        keys.append(f"project:{project}:{context['config']}")
    if tool in TARGET_SCOPED_TOOLS:
        targets = _repo_path(context["targets_path"]).resolve()
        keys.append(f"target:{targets}:{context['target']}")
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
            age = time.time() - float(holder.get("created_epoch") or 0)
            if attempt == 0 and age > stale_after_seconds:
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
