"""Policy-aware runtime PVI discovery and data service."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from br_plc_toolchain.backends.pvi import PviSessionManager, PviTarget, VariableRef
from br_plc_toolchain.config.loader import (
    REPO_ROOT,
    create_ephemeral_target_config,
    save_local_target,
)
from br_plc_toolchain.policy import RuntimePolicy, TestSessionManager


TARGET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_target_name(name: str) -> str:
    if not TARGET_NAME_PATTERN.fullmatch(name):
        raise ValueError("INVALID_TARGET_NAME: target name must match ^[A-Za-z0-9][A-Za-z0-9._-]*$")
    return name


def target_fingerprint(target: PviTarget, health: dict[str, Any]) -> dict[str, Any]:
    def value(name: str) -> Any:
        item = health.get(name)
        return item.get("value") if isinstance(item, dict) else item

    return {
        "ip": target.ip,
        "cpu_type": value("cpu_type"),
        "order_number": value("order_number"),
        "ar_version": value("ar_version") or value("cpu_version"),
        "generation": health.get("generation"),
    }


def missing_fingerprint_fields(fingerprint: dict[str, Any]) -> list[str]:
    return [
        name
        for name in ("ip", "cpu_type", "order_number", "ar_version", "generation")
        if fingerprint.get(name) in (None, "")
    ]


class RuntimePviService:
    def __init__(
        self,
        manager: PviSessionManager | None = None,
        sessions: TestSessionManager | None = None,
        policy: RuntimePolicy | None = None,
        discovery_root: Path | None = None,
    ):
        self.manager = manager or PviSessionManager()
        self.sessions = sessions or TestSessionManager()
        self.policy = policy or RuntimePolicy()
        self.discovery_root = discovery_root or REPO_ROOT / "var" / "discovery"
        self._configs: dict[str, dict[str, Any]] = {}
        self._targets: dict[str, PviTarget] = {}
        self._discovered: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def register_ephemeral_target(
        self,
        *,
        ip: str,
        name: str | None = None,
        declared_role: str | None = None,
        pvi_dll_path: str | None = None,
    ) -> dict[str, Any]:
        if name:
            validate_target_name(name)
        config = create_ephemeral_target_config(ip=ip, name=name, declared_role=declared_role)
        target_data = config["target"]
        target = PviTarget(
            name=target_data["name"],
            ip=target_data["ip"],
            role=target_data["role"],
            pvi_dll_path=pvi_dll_path,
        )
        config["target"]["pvi_dll_path"] = pvi_dll_path
        with self._lock:
            self._configs[target.name] = config
            self._targets[target.name] = target
            self._discovered.setdefault(target.name, {})
        return {"ok": True, "target": target_data, "profile": config["profile"]}

    def _resolve(self, target_name: str) -> tuple[PviTarget, dict[str, Any]]:
        with self._lock:
            if target_name not in self._targets:
                raise KeyError(f"Runtime target {target_name!r} is not registered")
            return self._targets[target_name], self._configs[target_name]

    def discover_target(self, target_name: str) -> dict[str, Any]:
        target, config = self._resolve(target_name)
        health = self.manager.call(target, "health")
        tasks = self.manager.call(target, "list_tasks")
        manifest = {
            "schema_version": 1,
            "discovered_at": datetime.now(UTC).isoformat(),
            "target": config["target"],
            "profile": config["profile"],
            "health": health,
            "tasks": tasks.get("tasks", []),
        }
        self._write_manifest(target.name, manifest)
        return {"ok": bool(health.get("ok")), **manifest}

    def save_target(
        self,
        target_name: str,
        *,
        filename: str,
        execute: bool,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if not execute:
            raise PermissionError("Saving a runtime target requires execute=true")
        _, config = self._resolve(target_name)
        path = save_local_target(config, filename=filename, overwrite=overwrite)
        return {
            "ok": True,
            "target": target_name,
            "config_path": str(path),
            "loaded_in_current_session": True,
        }

    def list_tasks(self, target_name: str) -> dict[str, Any]:
        target, _ = self._resolve(target_name)
        return self.manager.call(target, "list_tasks")

    def health(self, target_name: str) -> dict[str, Any]:
        target, config = self._resolve(target_name)
        result = self.manager.call(target, "health")
        result["worker"] = self.manager.worker_state(target)
        result["configuration"] = {
            "target": config.get("target"),
            "profile": config.get("profile"),
            "access": config.get("access"),
        }
        result["active_sessions"] = [
            session for session in self.sessions.list_active() if session.get("target_name") == target.name
        ]
        result["recent_error"] = result.get("last_event_error") or result.get("last_cpu_error")
        return result

    def list_variables(
        self,
        target_name: str,
        *,
        scope: str = "task",
        task: str | None = None,
        pattern: str = "*",
        limit: int = 200,
    ) -> dict[str, Any]:
        target, _ = self._resolve(target_name)
        result = self.manager.call(
            target, "list_variables", scope=scope, task=task, pattern=pattern, limit=limit
        )
        with self._lock:
            target_catalog = self._discovered.setdefault(target_name, {})
            for name in result.get("variables", []):
                ref = VariableRef(name=name, scope=scope, task=task)  # type: ignore[arg-type]
                target_catalog.setdefault(
                    ref.canonical,
                    {"variable": ref.canonical, "scope": scope, "task": task, "name": name},
                )
        return result

    def variable_info(self, target_name: str, ref: VariableRef) -> dict[str, Any]:
        target, _ = self._resolve(target_name)
        info = self.manager.call(target, "variable_info", ref=ref)
        with self._lock:
            self._discovered.setdefault(target_name, {})[ref.canonical] = dict(info)
        return info

    def read(self, target_name: str, ref: VariableRef) -> dict[str, Any]:
        result = self.read_many(target_name, [ref])
        compact = {"ok": bool(result["ok"]), "name": ref.canonical}
        if ref.canonical in result["values"]:
            compact.update(result["values"][ref.canonical])
        else:
            compact["error"] = result["errors"].get(ref.canonical, "PVI read failed")
        return compact

    def read_many(self, target_name: str, refs: list[VariableRef]) -> dict[str, Any]:
        """Read a de-duplicated set of variables with one worker operation.

        Authorization is intentionally evaluated per variable so one denied or
        missing symbol does not prevent independent read-only symbols from
        being returned.
        """
        if not refs:
            raise ValueError("variables must be a non-empty array")
        if len(refs) > 64:
            raise ValueError("variables may contain at most 64 items")
        target, config = self._resolve(target_name)
        unique: list[VariableRef] = []
        seen: set[str] = set()
        for ref in refs:
            ref.validate()
            if ref.canonical not in seen:
                seen.add(ref.canonical)
                unique.append(ref)

        values: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        allowed: list[VariableRef] = []
        for ref in unique:
            decision = self.policy.authorize_read(config=config, variable=ref.canonical)
            try:
                self.policy.require(decision)
            except PermissionError as exc:
                errors[ref.canonical] = str(exc)
                continue
            allowed.append(ref)

        if allowed:
            result = self.manager.call(target, "read_many", refs=allowed)
            for item in result.get("results", []):
                name = str(item.get("variable") or "")
                if not name:
                    continue
                if item.get("ok"):
                    values[name] = {
                        "value": item.get("value"),
                        "type": item.get("data_type") or "unknown",
                    }
                    with self._lock:
                        self._discovered.setdefault(target_name, {})[name] = {
                            **self._discovered.get(target_name, {}).get(name, {}),
                            **{
                                key: item.get(key)
                                for key in ("variable", "scope", "task", "name", "data_type", "readable", "writable")
                            },
                        }
                else:
                    errors[name] = str(item.get("error") or "PVI read failed")
        return {
            "ok": bool(unique) and not errors,
            "target": target.name,
            "count": len(unique),
            "values": values,
            "errors": errors,
        }

    def open_test_session(
        self, target_name: str, *, execute: bool, ttl_minutes: int | None = None
    ) -> dict[str, Any]:
        target, config = self._resolve(target_name)
        health = self.manager.call(target, "health")
        if not health.get("ok"):
            raise RuntimeError("Target must be connected before opening a test session")
        fingerprint = target_fingerprint(target, health)
        missing = missing_fingerprint_fields(fingerprint)
        if missing:
            raise PermissionError(
                "PVI_SESSION_FINGERPRINT_MISMATCH: complete target identity is unavailable "
                f"({', '.join(missing)})"
            )
        ttl = ttl_minutes or int((config.get("access") or {}).get("session_ttl_minutes", 60))
        session = self.sessions.open(
            target_key=target.key,
            target_name=target.name,
            role=target.role,
            ttl_minutes=ttl,
            fingerprint=fingerprint,
            execute=execute,
        )
        return {"ok": True, "session": session.to_dict()}

    def close_test_session(self, session_id: str) -> dict[str, Any]:
        return {"ok": self.sessions.close(session_id), "session_id": session_id}

    def write(
        self,
        target_name: str,
        ref: VariableRef,
        value: Any,
        *,
        execute: bool,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        target, config = self._resolve(target_name)
        # Automatic online discovery is authoritative when no source/catalog exists.
        info = self.variable_info(target_name, ref)
        before = (
            self.manager.call(target, "read", ref=ref)
            if bool(info.get("readable", True))
            else {"value": None}
        )
        trusted_role = target.role.lower() in {"arsim", "dedicated_test_plc"}
        session_valid = False
        if session_id and not trusted_role:
            current_health = self.manager.call(target, "health")
            if not current_health.get("ok"):
                raise PermissionError("PVI_SESSION_FINGERPRINT_MISMATCH: target health is unavailable")
            current_fingerprint = target_fingerprint(target, current_health)
            missing = missing_fingerprint_fields(current_fingerprint)
            if missing:
                raise PermissionError(
                    "PVI_SESSION_FINGERPRINT_MISMATCH: complete target identity is unavailable "
                    f"({', '.join(missing)})"
                )
            self.sessions.require(
                session_id,
                target_key=target.key,
                fingerprint=current_fingerprint,
            )
            session_valid = True
        decision = self.policy.authorize_write(
            config=config,
            variable=ref.canonical,
            current_value=before.get("value"),
            requested_value=value,
            writable=bool(info.get("writable")),
            execute=execute,
            session_valid=session_valid,
        )
        self.policy.require(decision)
        result = self.manager.call(target, "write", ref=ref, value=value)
        result["access_decision"] = decision.to_dict()
        result["session_id"] = session_id
        return result

    def _write_manifest(self, target_name: str, manifest: dict[str, Any]) -> None:
        validate_target_name(target_name)
        self.discovery_root.mkdir(parents=True, exist_ok=True)
        root = self.discovery_root.resolve()
        path = (root / f"{target_name}.json").resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("INVALID_TARGET_NAME: discovery manifest escaped its root") from exc
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def close(self) -> None:
        self.manager.close_all()
