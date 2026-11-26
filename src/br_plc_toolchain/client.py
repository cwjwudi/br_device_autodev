"""High-level public Python SDK for policy-enforced Runtime PVI orchestration."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from br_plc_toolchain.backends.pvi import VariableRef, parse_variable_ref
from br_plc_toolchain.backends.pvi.models import Scope
from br_plc_toolchain.config import load_project_config, resolve_toolchain
from br_plc_toolchain.config.loader import REPO_ROOT
from br_plc_toolchain.services.pvi_trace import TraceManager
from br_plc_toolchain.services.runtime_pvi import MAX_READ_BATCH, RuntimePviService


class PviClient:
    """Policy-aware high-level client wrapping RuntimePviService and TraceManager."""

    def __init__(
        self,
        *,
        service: RuntimePviService,
        target_name: str,
        trace_manager: TraceManager | None = None,
        owns_service: bool = True,
        project_config: dict[str, Any] | None = None,
        project_config_path: Path | None = None,
    ) -> None:
        self.service = service
        self.target_name = target_name
        self.trace_manager = trace_manager or TraceManager(service)
        self._owns_service = owns_service
        self.project_config = project_config
        self.project_config_path = project_config_path
        self._closed = False

    @classmethod
    def from_project(
        cls,
        project_path: str | Path,
        *,
        target: str | None = None,
        environment: str | None = None,
        toolchain: str | None = None,
        toolchains_path: str | Path | None = None,
        trace_root: str | Path | None = None,
        service: RuntimePviService | None = None,
    ) -> PviClient:
        """Create a PviClient bound to a project's br-auto-dev.json target and policy."""
        if environment:
            raise ValueError("Named environments are no longer supported; use project_path and target.")

        candidate = Path(project_path)
        if not candidate.is_absolute() and candidate.exists():
            candidate = candidate.resolve()

        project, config_path = load_project_config(str(candidate), REPO_ROOT)
        if config_path is None:
            raise ValueError(f"Project configuration (br-auto-dev.json) was not found for {project_path!r}")

        target_name = str(target or project.get("target") or "").strip()
        if not target_name:
            raise ValueError("Target name must not be empty")
        targets = project.get("targets") or {}
        target_config = targets.get(target_name)
        if not isinstance(target_config, dict):
            raise ValueError(f"Target {target_name!r} is not configured in {config_path}")

        selected_toolchain_id = str(toolchain or project.get("toolchain") or "").strip() or None
        resolved_toolchain = resolve_toolchain(selected_toolchain_id, registry_path=toolchains_path)
        pvi_dll_path = str(resolved_toolchain.pvi_dll_dir) if resolved_toolchain.pvi_dll_dir else None

        owns_service = service is None
        svc = service or RuntimePviService()
        try:
            svc.register_ephemeral_target(
                ip=str(target_config["ip"]),
                name=target_name,
                declared_role=str(target_config["role"]),
                pvi_dll_path=pvi_dll_path,
                project_config=project,
            )
            trace_mgr = TraceManager(
                svc, root=(Path(trace_root) if trace_root is not None else None)
            )
        except Exception:
            if owns_service:
                svc.close()
            raise

        return cls(
            service=svc,
            target_name=target_name,
            trace_manager=trace_mgr,
            owns_service=owns_service,
            project_config=project,
            project_config_path=config_path,
        )

    @classmethod
    def from_target(
        cls,
        *,
        ip: str,
        name: str | None = None,
        declared_role: str | None = "arsim",
        project_config: dict[str, Any] | None = None,
        toolchain: str | None = None,
        toolchains_path: str | Path | None = None,
        trace_root: str | Path | None = None,
        service: RuntimePviService | None = None,
    ) -> PviClient:
        """Create a PviClient directly from an explicit target IP and declared role."""
        resolved_toolchain = resolve_toolchain(toolchain or None, registry_path=toolchains_path)
        pvi_dll_path = str(resolved_toolchain.pvi_dll_dir) if resolved_toolchain.pvi_dll_dir else None

        owns_service = service is None
        svc = service or RuntimePviService()
        try:
            registration = svc.register_ephemeral_target(
                ip=str(ip),
                name=name,
                declared_role=declared_role,
                pvi_dll_path=pvi_dll_path,
                project_config=project_config,
            )
            target_name = str(registration["target"]["name"])
            trace_mgr = TraceManager(
                svc, root=(Path(trace_root) if trace_root is not None else None)
            )
        except Exception:
            if owns_service:
                svc.close()
            raise

        return cls(
            service=svc,
            target_name=target_name,
            trace_manager=trace_mgr,
            owns_service=owns_service,
            project_config=project_config,
        )

    def __enter__(self) -> PviClient:
        if self._closed:
            raise RuntimeError("PviClient is already closed")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Stop active traces and close the underlying PVI worker if owned."""
        if self._closed:
            return
        self._closed = True
        try:
            self.trace_manager.close()
        finally:
            if self._owns_service:
                self.service.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("PviClient is closed")

    @staticmethod
    def _to_ref(variable: VariableRef | str) -> VariableRef:
        if isinstance(variable, VariableRef):
            variable.validate()
            return variable
        if isinstance(variable, str):
            return parse_variable_ref(variable)
        raise TypeError(f"Expected str or VariableRef, got {type(variable).__name__}")

    def _to_refs(self, variables: Sequence[VariableRef | str]) -> list[VariableRef]:
        if isinstance(variables, (str, bytes)) or not isinstance(variables, Sequence):
            raise TypeError("variables must be a sequence of variable names or VariableRef objects")
        return [self._to_ref(item) for item in variables]

    def discover(self, refresh: bool = False) -> dict[str, Any]:
        """Discover target health and task list, optionally invalidating any existing worker."""
        self._ensure_open()
        if refresh:
            invalidate = getattr(self.service.manager, "invalidate", None)
            if callable(invalidate):
                target, _ = self.service._resolve(self.target_name)
                invalidate(target)
        return self.service.discover_target(self.target_name)

    def health(self) -> dict[str, Any]:
        """Return target PVI Manager, CPU, runtime, and cache status."""
        self._ensure_open()
        return self.service.health(self.target_name)

    def list_tasks(self) -> dict[str, Any]:
        """List task names from the connected PLC/ARsim image."""
        self._ensure_open()
        return self.service.list_tasks(self.target_name)

    def list_variables(
        self,
        scope: Scope = "task",
        task: str | None = None,
        pattern: str = "*",
        limit: int = 200,
        offset: int = 0,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """List online task or global variable names matching a glob pattern."""
        self._ensure_open()
        return self.service.list_variables(
            self.target_name,
            scope=scope,
            task=task,
            pattern=pattern,
            limit=limit,
            offset=offset,
            refresh=refresh,
        )

    def variable_info(
        self,
        variable: VariableRef | str,
        *,
        expand: bool = False,
        max_depth: int = 3,
        max_fields: int = 128,
    ) -> dict[str, Any]:
        """Return online PVI type, readability, writability, and metadata for one variable."""
        self._ensure_open()
        return self.service.variable_info(
            self.target_name,
            self._to_ref(variable),
            expand=expand,
            max_depth=max_depth,
            max_fields=max_fields,
        )

    def expand_variable(
        self,
        variable: VariableRef | str,
        *,
        max_depth: int = 3,
        max_fields: int = 128,
    ) -> dict[str, Any]:
        """Expand a structure or array variable into leaf PVI variable paths."""
        return self.variable_info(
            variable,
            expand=True,
            max_depth=max_depth,
            max_fields=max_fields,
        )

    def read_structure(
        self,
        variable: VariableRef | str,
        *,
        max_depth: int = 2,
        max_fields: int = 128,
    ) -> dict[str, Any]:
        """Expand a structure/array variable and read its readable leaf paths via read_chunked."""
        self._ensure_open()
        ref = self._to_ref(variable)
        expanded = self.expand_variable(ref, max_depth=max_depth, max_fields=max_fields)
        fields = expanded.get("fields") or []
        readable_paths = [
            str(item["canonical"])
            for item in fields
            if isinstance(item, dict) and item.get("canonical") and item.get("readable", True)
        ]
        if not readable_paths:
            return {
                "ok": False,
                "target": self.target_name,
                "variable": ref.canonical,
                "expansion_source": expanded.get("expansion_source", "unavailable"),
                "truncated": bool(expanded.get("truncated", False)),
                "total_discovered": int(expanded.get("total_discovered", 0)),
                "fields": fields,
                "values": {},
                "errors": {},
                "note": expanded.get("expansion_note") or "No readable leaf fields were discovered.",
            }
        read_res = self.read_chunked(readable_paths)
        return {
            "ok": bool(read_res.get("ok")),
            "target": self.target_name,
            "variable": ref.canonical,
            "expansion_source": expanded.get("expansion_source", "pvi"),
            "truncated": bool(expanded.get("truncated", False)),
            "total_discovered": int(expanded.get("total_discovered", len(fields))),
            "fields": fields,
            "values": read_res.get("values") or {},
            "errors": read_res.get("errors") or {},
        }

    def read(self, variable: VariableRef | str) -> dict[str, Any]:
        """Read a single PLC variable via the policy-checked RuntimePviService."""
        self._ensure_open()
        return self.service.read(self.target_name, self._to_ref(variable))

    def read_many(
        self,
        variables: Sequence[VariableRef | str],
        *,
        chunked: bool = False,
    ) -> dict[str, Any]:
        """Read up to 128 variables in one batch, or chunked when chunked=True."""
        self._ensure_open()
        if chunked:
            return self.read_chunked(variables)
        refs = self._to_refs(variables)
        return self.service.read_many(self.target_name, refs)

    def read_chunked(self, variables: Sequence[VariableRef | str]) -> dict[str, Any]:
        """Read an arbitrary number of variables in sequential 128-variable chunks."""
        self._ensure_open()
        refs = self._to_refs(variables)
        if not refs:
            raise ValueError("variables must be a non-empty sequence")
        unique: list[VariableRef] = []
        seen: set[str] = set()
        for ref in refs:
            if ref.canonical not in seen:
                seen.add(ref.canonical)
                unique.append(ref)

        values: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        chunks = [
            unique[index : index + MAX_READ_BATCH]
            for index in range(0, len(unique), MAX_READ_BATCH)
        ]
        for chunk in chunks:
            batch = self.service.read_many(self.target_name, chunk)
            values.update(batch.get("values") or {})
            errors.update(batch.get("errors") or {})
        return {
            "ok": bool(unique) and not errors,
            "target": self.target_name,
            "count": len(unique),
            "chunks": len(chunks),
            "values": values,
            "errors": errors,
        }

    def write(
        self,
        variable: VariableRef | str,
        value: Any,
        *,
        execute: bool = True,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Write a single PLC variable through RuntimePolicy authorization and readback."""
        self._ensure_open()
        return self.service.write(
            self.target_name,
            self._to_ref(variable),
            value,
            execute=execute,
            session_id=session_id,
        )

    def write_many(
        self,
        writes: Mapping[VariableRef | str, Any] | Sequence[tuple[VariableRef | str, Any]],
        *,
        execute: bool = True,
        session_id: str | None = None,
        stop_on_error: bool = True,
        readback_wait_ms: int = 50,
    ) -> dict[str, Any]:
        """Write multiple variables through RuntimePviService.write_many with preflight validation."""
        self._ensure_open()
        if isinstance(writes, Mapping):
            pairs = list(writes.items())
        elif isinstance(writes, Sequence) and not isinstance(writes, (str, bytes)):
            pairs = []
            for item in writes:
                if not isinstance(item, (tuple, list)) or len(item) != 2:
                    raise ValueError("Each write entry must be a (variable, value) pair")
                pairs.append((item[0], item[1]))
        else:
            raise TypeError("writes must be a mapping or sequence of (variable, value) pairs")

        if not pairs:
            raise ValueError("writes must be non-empty")

        ref_pairs = [(self._to_ref(variable), value) for variable, value in pairs]
        return self.service.write_many(
            self.target_name,
            ref_pairs,
            execute=execute,
            stop_on_error=stop_on_error,
            readback_wait_ms=readback_wait_ms,
            session_id=session_id,
        )

    def start_trace(
        self,
        variables: Sequence[VariableRef | str],
        *,
        duration_seconds: int = 30,
        interval_ms: int = 100,
    ) -> dict[str, Any]:
        """Start a background read-only PVI trace for up to 128 variables at >=20 ms."""
        self._ensure_open()
        refs = self._to_refs(variables)
        return self.trace_manager.start(
            self.target_name,
            refs,
            duration_seconds=duration_seconds,
            interval_ms=interval_ms,
        )

    def trace_status(self, trace_id: str) -> dict[str, Any]:
        """Return compact status metadata and trace_file path for a running or finished trace."""
        self._ensure_open()
        return self.trace_manager.status(trace_id)

    def read_trace(
        self,
        trace_id: str,
        *,
        from_ms: int = 0,
        to_ms: int | None = None,
        max_samples: int = 1000,
        downsample: int = 1,
    ) -> dict[str, Any]:
        """Read bounded columnar samples from a trace."""
        self._ensure_open()
        return self.trace_manager.read(
            trace_id,
            from_ms=from_ms,
            to_ms=to_ms,
            max_samples=max_samples,
            downsample=downsample,
        )

    def stop_trace(self, trace_id: str) -> dict[str, Any]:
        """Stop an active trace and return its final summary."""
        self._ensure_open()
        return self.trace_manager.stop(trace_id)

    def wait_trace(
        self,
        trace_id: str,
        *,
        poll_interval_s: float = 0.1,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """Block until a trace enters a terminal state and return its final summary."""
        self._ensure_open()
        return self.trace_manager.wait(
            trace_id,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    def open_test_session(
        self, *, execute: bool = True, ttl_minutes: int | None = None
    ) -> dict[str, Any]:
        """Open a target-bound runtime test session."""
        self._ensure_open()
        return self.service.open_test_session(
            self.target_name, execute=execute, ttl_minutes=ttl_minutes
        )

    def close_test_session(self, session_id: str) -> dict[str, Any]:
        """Close a runtime test session by session_id."""
        self._ensure_open()
        return self.service.close_test_session(session_id)

    def restart(
        self,
        mode: str = "warm",
        *,
        execute: bool = False,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        """Perform a policy-checked Warmstart or Coldstart on the target PLC/ARsim."""
        self._ensure_open()
        return self.service.restart_target(
            self.target_name,
            mode=mode,
            execute=execute,
            timeout_seconds=timeout_seconds,
        )

    def wait_until(
        self,
        variable: VariableRef | str | Sequence[VariableRef | str],
        predicate: Callable[[Any], bool],
        *,
        timeout_s: float = 10.0,
        interval_s: float = 0.05,
    ) -> dict[str, Any]:
        """Poll one variable (or a small batch) until predicate returns truthy or timeout expires."""
        self._ensure_open()
        if timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")

        is_single = isinstance(variable, (str, VariableRef))
        single_ref = self._to_ref(variable) if is_single else None
        batch_refs = None if is_single else self._to_refs(variable)  # type: ignore[arg-type]
        if batch_refs is not None and not batch_refs:
            raise ValueError("variables must be a non-empty sequence")

        started = time.monotonic()
        deadline = started + timeout_s
        polls = 0
        last_result: dict[str, Any] | None = None
        while True:
            polls += 1
            if single_ref is not None:
                res = self.service.read(self.target_name, single_ref)
                last_result = res
                if res.get("ok") and predicate(res.get("value")):
                    return {
                        "ok": True,
                        "variable": single_ref.canonical,
                        "value": res.get("value"),
                        "type": res.get("type"),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "polls": polls,
                    }
            else:
                assert batch_refs is not None
                res = self.service.read_many(self.target_name, batch_refs)
                last_result = res
                values_map = {
                    name: item.get("value")
                    for name, item in (res.get("values") or {}).items()
                }
                if res.get("ok") and predicate(values_map):
                    return {
                        "ok": True,
                        "variables": [ref.canonical for ref in batch_refs],
                        "values": values_map,
                        "raw": res,
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "polls": polls,
                    }

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"wait_until timed out after {timeout_s}s; last_result={last_result!r}"
                )
            time.sleep(min(interval_s, remaining))
