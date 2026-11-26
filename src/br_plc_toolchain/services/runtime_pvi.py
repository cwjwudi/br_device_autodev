"""Policy-aware runtime PVI discovery and data service."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from br_plc_toolchain.backends.pvi import PviSessionManager, PviTarget, VariableRef
from br_plc_toolchain.backends.pvi.values import coerce_write_value
from br_plc_toolchain.config.loader import (
    REPO_ROOT,
    create_ephemeral_target_config,
    save_local_target,
)
from br_plc_toolchain.policy import RuntimePolicy, TestSessionManager


TARGET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_READ_BATCH = 128
MAX_WRITE_BATCH = 20


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
        project_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if name:
            validate_target_name(name)
        config = create_ephemeral_target_config(ip=ip, name=name, declared_role=declared_role,
                                                project_config=project_config)
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
        offset: int = 0,
        refresh: bool = False,
    ) -> dict[str, Any]:
        target, _ = self._resolve(target_name)
        kwargs: dict[str, Any] = {
            "scope": scope,
            "task": task,
            "pattern": pattern,
            "limit": limit,
            "offset": offset,
        }
        if refresh:
            kwargs["refresh"] = True
        result = self.manager.call(target, "list_variables", **kwargs)
        with self._lock:
            target_catalog = self._discovered.setdefault(target_name, {})
            for name in result.get("variables", []):
                ref = VariableRef(name=name, scope=scope, task=task)  # type: ignore[arg-type]
                target_catalog.setdefault(
                    ref.canonical,
                    {"variable": ref.canonical, "scope": scope, "task": task, "name": name},
                )
        return result

    def variable_info(
        self,
        target_name: str,
        ref: VariableRef,
        *,
        expand: bool = False,
        max_depth: int = 3,
        max_fields: int = 128,
    ) -> dict[str, Any]:
        target, _ = self._resolve(target_name)
        kwargs: dict[str, Any] = {"ref": ref}
        if expand:
            kwargs["expand"] = True
            kwargs["max_depth"] = max_depth
            kwargs["max_fields"] = max_fields
        info = self.manager.call(target, "variable_info", **kwargs)
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
        if len(refs) > MAX_READ_BATCH:
            raise ValueError(f"variables may contain at most {MAX_READ_BATCH} items")
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
        decision = self.policy.authorize_write(
            config=config,
            variable=ref.canonical,
            current_value=before.get("value"),
            requested_value=value,
            writable=bool(info.get("writable")),
            execute=execute,
            session_valid=False,
        )
        self.policy.require(decision)
        result = self.manager.call(target, "write", ref=ref, value=value)
        result["access_decision"] = decision.to_dict()
        result["session_id"] = session_id
        return result

    def write_many(
        self,
        target_name: str,
        writes: list[tuple[VariableRef, Any]],
        *,
        execute: bool,
        stop_on_error: bool = True,
        readback_wait_ms: int = 50,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Preflight-validate and write up to MAX_WRITE_BATCH variables.

        When stop_on_error=True (default), every item is preflighted for ref validity,
        writability, type coercion (rejecting whole-structure writes), and RuntimePolicy
        authorization BEFORE any variable is written; any failure rejects the entire batch.
        """
        if not writes:
            raise ValueError("writes must be a non-empty list")
        if len(writes) > MAX_WRITE_BATCH:
            raise ValueError(f"writes may contain at most {MAX_WRITE_BATCH} items")
        target, config = self._resolve(target_name)

        preflight_ok: list[tuple[int, VariableRef, Any, dict[str, Any]]] = []
        preflight_errors: dict[int, tuple[VariableRef, Exception]] = {}

        for index, (ref, value) in enumerate(writes):
            try:
                ref.validate()
                info = self.variable_info(target_name, ref)
                data_type = str(info.get("data_type") or "")
                if info.get("is_structure") is True or isinstance(value, dict):
                    raise ValueError(
                        f"Structure writes are not supported by pvipy for {ref.canonical!r}; write leaf fields instead."
                    )
                if data_type:
                    coerce_write_value(value, data_type)
                before = (
                    self.manager.call(target, "read", ref=ref)
                    if bool(info.get("readable", True))
                    else {"value": None}
                )
                decision = self.policy.authorize_write(
                    config=config,
                    variable=ref.canonical,
                    current_value=before.get("value"),
                    requested_value=value,
                    writable=bool(info.get("writable")),
                    execute=execute,
                    session_valid=False,
                )
                self.policy.require(decision)
                preflight_ok.append((index, ref, value, decision.to_dict()))
            except Exception as exc:
                if stop_on_error:
                    raise
                preflight_errors[index] = (ref, exc)

        results_by_index: dict[int, dict[str, Any]] = {}
        for index, (ref, exc) in preflight_errors.items():
            results_by_index[index] = {
                "ok": False,
                "target": target.name,
                "variable": ref.canonical,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

        if preflight_ok:
            worker_pairs = [(ref, value) for _, ref, value, _ in preflight_ok]
            worker_result = self.manager.call(
                target,
                "write_many",
                writes=worker_pairs,
                readback_wait_ms=max(0, int(readback_wait_ms)),
            )
            worker_items = list(worker_result.get("results") or [])
            for pos, (index, ref, _value, decision_dict) in enumerate(preflight_ok):
                item = (
                    dict(worker_items[pos])
                    if pos < len(worker_items)
                    else {"ok": False, "target": target.name, "variable": ref.canonical, "error": "Missing batch write result"}
                )
                item["access_decision"] = decision_dict
                item["session_id"] = session_id
                results_by_index[index] = item

        ordered = [results_by_index[i] for i in range(len(writes))]
        return {
            "ok": bool(ordered) and all(bool(item.get("ok")) for item in ordered),
            "target": target.name,
            "atomic": False,
            "count": len(ordered),
            "results": ordered,
            "writes": ordered,
        }

    def restart_target(
        self,
        target_name: str,
        *,
        mode: str = "warm",
        execute: bool = False,
        timeout_seconds: float = 30.0,
        pvi_transfer_exe: str | None = None,
    ) -> dict[str, Any]:
        normalized = str(mode or "").strip().lower()
        mode_map = {
            "warm": "warm",
            "warmstart": "warm",
            "cold": "cold",
            "coldstart": "cold",
        }
        if normalized not in mode_map:
            raise ValueError(f"Unsupported restart mode {mode!r}; expected 'warmstart'/'warm' or 'coldstart'/'cold'.")
        resolved_mode = mode_map[normalized]
        target, config = self._resolve(target_name)

        if target.role == "production":
            raise PermissionError(
                "POLICY_DENIED: Runtime control (warmstart/coldstart) is permanently denied for production targets."
            )
        if not execute:
            raise PermissionError(
                "CONFIRMATION_REQUIRED: Runtime control (warmstart/coldstart) requires execute=true."
            )
        if target.role == "arsim":
            pass
        elif target.role in {"dedicated_test_plc", "test_plc"}:
            targets_map = config.get("targets") if isinstance(config.get("targets"), dict) else {}
            target_cfg = targets_map.get(target_name) if isinstance(targets_map.get(target_name), dict) else {}
            if not target_cfg and isinstance(config.get("target"), dict):
                target_cfg = config["target"]
            allow_ctrl = target_cfg.get("allow_runtime_control") is True
            allow_dl = target_cfg.get("allow_auto_download") is True
            if not (allow_ctrl or allow_dl):
                raise PermissionError(
                    "POLICY_DENIED: Runtime control on a physical test PLC requires "
                    "allow_runtime_control=true (or allow_auto_download=true) in target configuration."
                )
        else:
            raise PermissionError(
                f"POLICY_DENIED: Runtime control is not permitted for target role {target.role!r}."
            )

        return self.manager.call(
            target,
            "restart",
            mode=resolved_mode,
            wait_ready_timeout=float(timeout_seconds),
            pvi_transfer_exe=pvi_transfer_exe,
        )

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
