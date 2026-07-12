"""Policy-aware runtime PVI discovery and data service."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from br_plc_toolchain.backends.pvi import PviSessionManager, PviTarget, VariableRef
from br_plc_toolchain.config.loader import REPO_ROOT, create_ephemeral_target_config
from br_plc_toolchain.policy import RuntimePolicy, TestSessionManager


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
    ) -> dict[str, Any]:
        config = create_ephemeral_target_config(ip=ip, name=name, declared_role=declared_role)
        target_data = config["target"]
        target = PviTarget(
            name=target_data["name"], ip=target_data["ip"], role=target_data["role"]
        )
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

    def list_tasks(self, target_name: str) -> dict[str, Any]:
        target, _ = self._resolve(target_name)
        return self.manager.call(target, "list_tasks")

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
        target, config = self._resolve(target_name)
        decision = self.policy.authorize_read(config=config, variable=ref.canonical)
        self.policy.require(decision)
        result = self.manager.call(target, "read", ref=ref)
        result["access_decision"] = decision.to_dict()
        with self._lock:
            self._discovered.setdefault(target_name, {})[ref.canonical] = {
                **self._discovered.get(target_name, {}).get(ref.canonical, {}),
                **{key: result.get(key) for key in ("variable", "scope", "task", "name", "data_type", "readable", "writable")},
            }
        return result

    def open_test_session(
        self, target_name: str, *, execute: bool, ttl_minutes: int | None = None
    ) -> dict[str, Any]:
        target, config = self._resolve(target_name)
        health = self.manager.call(target, "health")
        if not health.get("ok"):
            raise RuntimeError("Target must be connected before opening a test session")
        fingerprint = {
            "ip": target.ip,
            "cpu_version": (health.get("cpu_version") or {}).get("value"),
            "cpu_status": (health.get("cpu_status") or {}).get("value"),
            "generation": health.get("generation"),
        }
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
        before = self.manager.call(target, "read", ref=ref)
        session_valid = False
        if session_id:
            self.sessions.require(session_id, target_key=target.key)
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
        self.discovery_root.mkdir(parents=True, exist_ok=True)
        path = self.discovery_root / f"{target_name}.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def close(self) -> None:
        self.manager.close_all()

