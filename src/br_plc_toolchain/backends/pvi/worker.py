"""Single-thread owner for a persistent pvipy connection."""

from __future__ import annotations

import fnmatch
import gc
import logging
import os
import queue
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from ctypes import byref, create_string_buffer, sizeof
from dataclasses import dataclass
from typing import Any, Callable

from .models import PviTarget, Scope, VariableRef
from .values import coerce_write_value, json_safe, values_equal

LOG = logging.getLogger(__name__)
_GENERATION_LOCK = threading.Lock()
_GENERATION_COUNTER = 0


def _read_variable_names(parent: Any) -> list[str]:
    from pvi.pvi_objects.Error import PviError
    from pvi.pvi_objects.include import POBJ_ACC_LIST_PVAR, PviXRead

    # pvipy's fixed 64 KiB buffer silently truncates large PVI lists.
    size = 65536
    while size <= 16 * 1024 * 1024:
        buffer = create_string_buffer(size)
        result = PviXRead(parent._hPvi, parent._linkID, POBJ_ACC_LIST_PVAR, None, 0, byref(buffer), sizeof(buffer))
        if result:
            raise PviError(result, parent)
        if b"\0" in buffer.raw:
            return [item.split(" ")[0] for item in buffer.value.decode("ascii").split("\t") if item]
        size *= 2
    raise RuntimeError("PVI variable list exceeds the 16 MiB scan limit; use project symbols or narrower tasks")
_PVI_TRANSPORT_MARKERS = (
    "Pvi-Error 12004",
    "Pvi-Error 12059",
    "Pvi-Error 12060",
    "Pvi-Error 11021",
    "PVI_OPERATION_TIMEOUT",
    "PVI_CONNECTION_UNAVAILABLE",
)


def is_pvi_transport_error(exc: BaseException) -> bool:
    """Return whether a failure makes the current PVI connection unreliable."""

    message = str(exc)
    return any(marker in message for marker in _PVI_TRANSPORT_MARKERS)


def _next_connection_generation() -> int:
    global _GENERATION_COUNTER
    with _GENERATION_LOCK:
        _GENERATION_COUNTER += 1
        return _GENERATION_COUNTER


@dataclass(slots=True)
class _Command:
    operation: str
    arguments: dict[str, Any]
    future: Future[Any]


class PviWorker:
    """Serialize all PVI access and continuously pump PVI events."""

    def __init__(self, target: PviTarget):
        self.target = target
        self._commands: queue.Queue[_Command] = queue.Queue()
        self._stop = threading.Event()
        self._started = threading.Event()
        self._thread: threading.Thread | None = None
        self._startup_error: BaseException | None = None
        self._connection: Any = None
        self._line: Any = None
        self._device: Any = None
        self._cpu: Any = None
        self._tasks: dict[str, Any] = {}
        self._variables: dict[tuple[str, str | None, str], Any] = {}
        self._manager_connected = False
        self._cpu_connected = False
        self._last_cpu_error: int | None = None
        self._last_event_error: str | None = None
        self._generation = 0
        self._dirty = False

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def dirty(self) -> bool:
        return self._dirty

    def start(self) -> None:
        if self.running:
            return
        self._thread = threading.Thread(
            target=self._run, name=f"pvi-{self.target.name}", daemon=True
        )
        self._thread.start()
        wait_s = self.target.manager_timeout_s + self.target.startup_wait_s + 2
        if not self._started.wait(wait_s):
            raise TimeoutError(f"Timed out starting PVI worker for {self.target.name}")
        if self._startup_error:
            raise RuntimeError(f"PVI startup failed: {self._startup_error}") from self._startup_error

    def close(self) -> None:
        self._stop.set()
        if self.running:
            self._thread.join(timeout=5)

    def call(self, operation: str, **arguments: Any) -> Any:
        if self._dirty:
            raise RuntimeError("PVI_WORKER_DIRTY: the previous operation timed out; reconnect is required")
        if not self.running:
            raise RuntimeError(f"PVI worker for {self.target.name} is not running")
        future: Future[Any] = Future()
        self._commands.put(_Command(operation, arguments, future))
        timeout_s = self._operation_timeout(operation, arguments)
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeoutError as exc:
            self._dirty = True
            self._stop.set()
            # The native PVI call cannot be cancelled safely once it has
            # started.  Leave the Future intact so the owner thread can finish
            # normally, then dispose of this dirty worker.
            raise TimeoutError(
                f"PVI_OPERATION_TIMEOUT: operation {operation!r} timed out after "
                f"{timeout_s:.1f}s; target state is unknown"
            ) from exc

    def _operation_timeout(self, operation: str, arguments: dict[str, Any]) -> float:
        timeout_s = float(self.target.request_timeout_s)
        if operation == "read_many":
            refs = arguments.get("refs") or []
            link_budget = len(refs) * (self.target.variable_link_wait_s + 0.10)
            timeout_s = max(
                timeout_s,
                self.target.manager_timeout_s + self.target.startup_wait_s + link_budget + 2.0,
            )
        elif operation == "restart":
            wait_budget = float(arguments.get("wait_ready_timeout") or 30.0)
            return min(max(timeout_s, wait_budget + 15.0), 180.0)
        return min(timeout_s, 60.0)

    def _run(self) -> None:
        try:
            self._initialize_pvi()
            self._pump_until_cpu_ready(self.target.startup_wait_s)
            if not self._manager_connected or not self._cpu_connected:
                raise RuntimeError(
                    "PVI_CONNECTION_UNAVAILABLE: PVI Manager or target CPU did not connect "
                    f"within {self.target.startup_wait_s:.1f}s"
                )
        except BaseException as exc:
            self._startup_error = exc
            LOG.exception("PVI initialization failed for %s", self.target.name)
        finally:
            self._started.set()
        if self._startup_error:
            self._cleanup()
            return

        operations: dict[str, Callable[..., Any]] = {
            "health": self._health,
            "list_tasks": self._list_tasks,
            "list_variables": self._list_variables,
            "variable_info": self._variable_info,
            "read": self._read,
            "read_many": self._read_many,
            "write": self._write,
            "write_many": self._write_many,
            "restart": self._restart,
        }
        try:
            while not self._stop.is_set():
                try:
                    command = self._commands.get(timeout=self.target.event_poll_s)
                except queue.Empty:
                    self._do_events()
                    continue
                if command.future.cancelled():
                    continue
                try:
                    command.future.set_result(
                        operations[command.operation](**command.arguments)
                    )
                except BaseException as exc:
                    command.future.set_exception(exc)
                    if is_pvi_transport_error(exc):
                        self._dirty = True
                        self._stop.set()
                self._do_events()
        finally:
            self._cleanup()

    def _initialize_pvi(self) -> None:
        if self.target.pvi_dll_path:
            os.environ["PVIPY_PVIDLLPATH"] = self.target.pvi_dll_path
        from pvi import Connection, Cpu, Device, Line

        self._connection = Connection(timeout=self.target.manager_timeout_s)
        self._connection.connectionChanged = self._on_manager_connection
        self._line = Line(self._connection.root, "LNANSL", CD="LNANSL")
        self._device = Device(self._line, "TCP", CD="/IF=TcpIp")
        descriptor = (
            f"/IP={self.target.ip} /COMT={self.target.communication_timeout_ms} "
            f"/PT={self.target.port}"
        )
        self._cpu = Cpu(self._device, self.target.pvi_object_name, CD=descriptor)
        self._cpu.errorChanged = self._on_cpu_error
        self._generation = _next_connection_generation()

    def _on_manager_connection(self, connected: bool) -> None:
        was_connected = self._manager_connected
        self._manager_connected = bool(connected)
        if not connected:
            self._cpu_connected = False
            self._tasks.clear()
            self._variables.clear()
            # pvipy drops its registered object list when PVI Manager
            # disconnects.  Reusing this hierarchy produces invalid LinkID
            # errors after the manager restarts, so force a fresh worker.
            if was_connected:
                self._dirty = True
                self._stop.set()

    def _on_cpu_error(self, error: int) -> None:
        if error == 0 and not self._cpu_connected:
            self._generation = _next_connection_generation()
        self._last_cpu_error = int(error)
        self._cpu_connected = error == 0
        if error != 0:
            self._variables.clear()

    def _do_events(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.doEvents()
            self._last_event_error = None
        except Exception as exc:
            self._last_event_error = repr(exc)
            LOG.warning("PVI event processing failed for %s: %r", self.target.name, exc)

    def _pump_for(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self._stop.is_set():
            self._do_events()
            time.sleep(self.target.event_poll_s)

    def _pump_until_cpu_ready(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self._stop.is_set():
            self._do_events()
            if self._manager_connected and self._cpu_connected:
                return
            time.sleep(self.target.event_poll_s)

    @staticmethod
    def _safe_get(getter: Callable[[], Any]) -> dict[str, Any]:
        try:
            return {"ok": True, "value": json_safe(getter())}
        except Exception as exc:
            if is_pvi_transport_error(exc):
                raise
            return {"ok": False, "error": str(exc)}

    def _health(self) -> dict[str, Any]:
        result = {
            "ok": self._cpu_connected and self._last_event_error is None,
            "target": self.target.name,
            "ip": self.target.ip,
            "role": self.target.role,
            "port": self.target.port,
            "generation": self._generation,
            "pvi_manager_connected": self._manager_connected,
            "cpu_connected": self._cpu_connected,
            "last_cpu_error": self._last_cpu_error,
            "last_event_error": self._last_event_error,
            "cached_tasks": len(self._tasks),
            "cached_variables": len(self._variables),
        }
        if not self._manager_connected or not self._cpu_connected:
            unavailable = {"ok": False, "error": "PVI CPU is not connected"}
            result.update(
                {
                    name: dict(unavailable)
                    for name in (
                        "license",
                        "cpu_type",
                        "order_number",
                        "ar_version",
                        "cpu_status",
                        "cpu_version",
                        "cpu_time",
                    )
                }
            )
            return result
        result.update(
            {
                "license": self._safe_get(lambda: self._connection.license),
                "cpu_type": self._safe_get(
                    lambda: getattr(self._cpu, "type", None)
                    or getattr(self._cpu, "cpuType", None)
                ),
                "order_number": self._safe_get(
                    lambda: getattr(self._cpu, "orderNumber", None)
                    or getattr(self._cpu, "order_number", None)
                ),
                "ar_version": self._safe_get(lambda: self._cpu.version),
                "cpu_status": self._safe_get(lambda: self._cpu.status),
                "cpu_version": self._safe_get(lambda: self._cpu.version),
                "cpu_time": self._safe_get(lambda: self._cpu.time),
            }
        )
        return result

    def _list_tasks(self) -> dict[str, Any]:
        tasks = [item for item in self._cpu.tasks if item]
        return {"ok": True, "target": self.target.name, "count": len(tasks), "tasks": tasks}

    def _get_task(self, task_name: str) -> Any:
        if task_name not in self._tasks:
            from pvi import Task

            self._tasks[task_name] = Task(self._cpu, task_name)
            self._pump_for(self.target.variable_link_wait_s)
        return self._tasks[task_name]

    def _list_variables(
        self,
        scope: Scope = "task",
        task: str | None = None,
        pattern: str = "*",
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        VariableRef(name="_list", scope=scope, task=task).validate()
        parent = self._get_task(str(task)) if scope == "task" else self._cpu
        source = _read_variable_names(parent)
        matched = [name for name in source if fnmatch.fnmatchcase(name, pattern)]
        effective_limit = max(1, min(limit, 5000))
        offset = max(0, offset)
        page = matched[offset:offset + effective_limit]
        next_offset = offset + len(page)
        return {
            "ok": True,
            "target": self.target.name,
            "scope": scope,
            "task": task,
            "pattern": pattern,
            "total_matches": len(matched),
            "offset": offset,
            "limit": effective_limit,
            "truncated": next_offset < len(matched),
            "next_offset": next_offset if next_offset < len(matched) else None,
            "variables": page,
        }

    def _get_variable(self, ref: VariableRef) -> Any:
        ref.validate()
        variable = self._variables.get(ref.key)
        if variable is not None:
            return variable
        from pvi import Variable

        parent = self._get_task(str(ref.task)) if ref.scope == "task" else self._cpu
        variable = Variable(parent, ref.name, RF=0)
        self._variables[ref.key] = variable
        self._pump_for(self.target.variable_link_wait_s)
        return variable

    @staticmethod
    def _ref_dict(ref: VariableRef) -> dict[str, Any]:
        return {"scope": ref.scope, "task": ref.task, "name": ref.name, "variable": ref.canonical}

    def _variable_info(self, ref: VariableRef) -> dict[str, Any]:
        variable = self._get_variable(ref)
        data_type = variable.dataType
        return {
            "ok": True,
            "target": self.target.name,
            **self._ref_dict(ref),
            "pvi_path": variable.name,
            "data_type": data_type,
            "readable": variable.readable,
            "writable": variable.writable,
            "is_array": variable.isArray,
            "is_structure": variable.isStructure,
            "attributes": json_safe(variable.attributes),
            "descriptor": json_safe(variable.descriptor),
        }

    def _read(self, ref: VariableRef) -> dict[str, Any]:
        variable = self._get_variable(ref)
        data_type = variable.dataType
        value = variable.value
        return {
            "ok": True,
            "target": self.target.name,
            **self._ref_dict(ref),
            "pvi_path": variable.name,
            "data_type": data_type,
            "value": json_safe(value),
            "readable": variable.readable,
            "writable": variable.writable,
        }

    def _read_many(self, refs: list[VariableRef]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for index, ref in enumerate(refs):
            try:
                results.append(self._read(ref))
            except Exception as exc:
                results.append({"ok": False, **self._ref_dict(ref), "error": str(exc)})
                if is_pvi_transport_error(exc):
                    for remaining in refs[index + 1 :]:
                        results.append(
                            {
                                "ok": False,
                                **self._ref_dict(remaining),
                                "error": "PVI connection became unavailable during batch read",
                            }
                        )
                    raise RuntimeError(
                        f"PVI_CONNECTION_LOST: batch read aborted after {ref.canonical}: {exc}"
                    ) from exc
        return {"ok": all(item["ok"] for item in results), "results": results}

    def _write(self, ref: VariableRef, value: Any) -> dict[str, Any]:
        variable = self._get_variable(ref)
        data_type = variable.dataType
        if not variable.writable:
            raise PermissionError(f"Variable {ref.canonical!r} is not writable")
        before = variable.value if variable.readable else None
        coerced = coerce_write_value(value, data_type)
        variable.value = coerced
        self._pump_for(0.05)
        readback = variable.value if variable.readable else None
        verified = values_equal(coerced, readback) if variable.readable else None
        result = {
            "ok": True,
            "target": self.target.name,
            **self._ref_dict(ref),
            "pvi_path": variable.name,
            "data_type": data_type,
            "before": json_safe(before),
            "requested": json_safe(coerced),
            "readback": json_safe(readback),
            "verified": verified,
        }
        if verified is False:
            result["warning_code"] = "PVI_READBACK_MISMATCH"
            result["warning"] = "PVI write completed, but readback does not match the requested value."
        elif verified is None:
            result["warning_code"] = "PVI_READBACK_UNAVAILABLE"
            result["warning"] = "PVI write completed, but readback is unavailable for this variable."
        return result

    def _write_many(self, writes: list[tuple[VariableRef, Any]]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for ref, value in writes:
            try:
                results.append(self._write(ref, value))
            except Exception as exc:
                results.append({"ok": False, **self._ref_dict(ref), "error": str(exc)})
        return {"ok": all(item["ok"] for item in results), "atomic": False, "results": results}

    @staticmethod
    def _extract_run_state(raw_status: Any) -> str | None:
        if isinstance(raw_status, dict):
            run_state = raw_status.get("RunState") or raw_status.get("run_state")
            if isinstance(run_state, str) and run_state.strip():
                value = run_state.strip().upper()
                return "SERVICE" if value == "SERV" else value
            st = raw_status.get("ST")
            if isinstance(st, str) and st.strip():
                st_up = st.strip().upper()
                if st_up in {"BOOT", "BOOTING"}:
                    return "BOOT"
                if st_up in {"RESET", "ERROR", "SERV", "SERVICE"}:
                    return "SERVICE"
                if st_up in {"DIAG", "DIAGNOSE"}:
                    return "DIAG"
            return None
        if isinstance(raw_status, str) and raw_status.strip():
            value = raw_status.strip().upper()
            return "SERVICE" if value == "SERV" else value
        return None

    def _restart_via_pvitransfer(self, mode: str, pvi_transfer_exe: str, timeout: float) -> None:
        import subprocess
        import tempfile
        from pathlib import Path

        transfer_exe = Path(pvi_transfer_exe)
        if not transfer_exe.is_file():
            raise FileNotFoundError(f"PVITransfer.exe not found: {transfer_exe}")
        cmd_name = "WarmStart" if mode == "warm" else "ColdStart"
        with tempfile.TemporaryDirectory(prefix="br_restart_") as tmp:
            tmp_dir = Path(tmp)
            pil_path = tmp_dir / "restart.pil"
            log_path = tmp_dir / "restart.log"
            lines = [
                f'Connection "/IF=tcpip", "/IP={self.target.ip} /COMT={self.target.communication_timeout_ms} /AM=* /PT={self.target.port}", "WT=30"',
                cmd_name,
            ]
            pil_path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
            proc = subprocess.Popen(
                [str(transfer_exe), "-silent", f"-{pil_path}", f"-{log_path}"],
                cwd=tmp_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                exit_code = proc.wait(timeout=max(5.0, min(timeout, 30.0)))
            except subprocess.TimeoutExpired as exc:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                raise TimeoutError(f"PVITransfer {cmd_name} timed out") from exc
            log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            if exit_code != 0 and "PROCESS FINISHED (SUCCESS)" not in log_text:
                raise RuntimeError(f"PVITransfer {cmd_name} failed (exit={exit_code}): {log_text[-500:]}")

    def _restart(
        self,
        mode: str = "warm",
        wait_ready_timeout: float = 30.0,
        pvi_transfer_exe: str | None = None,
    ) -> dict[str, Any]:
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"warm", "cold"}:
            raise ValueError(f"Unsupported restart mode: {mode!r}. Expected 'warm' or 'cold'.")
        started = time.monotonic()
        wait_timeout = max(0.1, float(wait_ready_timeout))

        before_raw: Any = None
        before_status: str | None = None
        if self._cpu is not None and self._cpu_connected:
            try:
                before_raw = json_safe(self._cpu.status)
                before_status = self._extract_run_state(before_raw)
            except Exception:
                before_raw = None

        method = "pvi"
        pvi_error: Exception | None = None
        try:
            if self._cpu is None:
                raise RuntimeError("PVI CPU object is not initialized")
            if normalized_mode == "warm":
                if hasattr(self._cpu, "warmStart"):
                    self._cpu.warmStart()
                else:
                    self._cpu.status = "WarmStart"
            else:
                if hasattr(self._cpu, "coldStart"):
                    self._cpu.coldStart()
                else:
                    self._cpu.status = "ColdStart"
        except Exception as exc:
            pvi_error = exc
            if pvi_transfer_exe:
                self._restart_via_pvitransfer(normalized_mode, pvi_transfer_exe, wait_timeout)
                method = "pvitransfer"
            else:
                raise

        # Unlink and invalidate cached variable and task objects before re-creating them after restart
        for obj in list(self._variables.values()) + list(self._tasks.values()):
            try:
                if hasattr(obj, "kill"):
                    obj.kill()
            except Exception:
                LOG.debug("Failed to unlink cached object %r during restart", obj, exc_info=True)
        self._variables.clear()
        self._tasks.clear()

        # Wait briefly for the reboot transition to begin so we do not read stale pre-restart RUN state
        deadline = started + wait_timeout
        saw_transition = before_status not in {"RUN", "SERVICE", "DIAG"}
        transition_wait_until = min(deadline, time.monotonic() + min(2.0, wait_timeout * 0.25))
        while not saw_transition and time.monotonic() < transition_wait_until and not self._stop.is_set():
            self._do_events()
            if not self._cpu_connected:
                saw_transition = True
                break
            try:
                probe_state = self._extract_run_state(json_safe(self._cpu.status))
                if probe_state not in {"RUN", "SERVICE", "DIAG"}:
                    saw_transition = True
                    break
            except Exception:
                saw_transition = True
                break
            time.sleep(min(0.1, max(0.02, transition_wait_until - time.monotonic())))

        last_raw: Any = None
        last_status: str | None = None
        settled_states = {"RUN", "SERVICE", "DIAG"}

        while time.monotonic() < deadline and not self._stop.is_set():
            self._do_events()
            if self._manager_connected and self._cpu_connected and self._cpu is not None:
                try:
                    last_raw = json_safe(self._cpu.status)
                    last_status = self._extract_run_state(last_raw)
                    if last_status in settled_states:
                        # Confirm PVI object layer is responsive (e.g. tasks readable when available)
                        if hasattr(self._cpu, "tasks"):
                            _ = self._cpu.tasks
                        elapsed = round(time.monotonic() - started, 3)
                        return {
                            "ok": True,
                            "target": self.target.name,
                            "mode": normalized_mode,
                            "method": method,
                            "before_status": before_status,
                            "before_status_raw": before_raw,
                            "after_status": last_status,
                            "after_status_raw": last_raw,
                            "elapsed_seconds": elapsed,
                            "cache_cleared": True,
                            **({"pvi_fallback_reason": str(pvi_error)} if pvi_error else {}),
                        }
                except Exception:
                    pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.2, max(0.02, remaining)))

        elapsed = round(time.monotonic() - started, 3)
        return {
            "ok": False,
            "error_code": "RUNTIME_RESTART_TIMEOUT",
            "error": (
                f"Target {self.target.name!r} did not recover to a ready state within "
                f"{wait_timeout:.1f}s after {normalized_mode}start."
            ),
            "target": self.target.name,
            "mode": normalized_mode,
            "method": method,
            "before_status": before_status,
            "after_status": last_status or "UNKNOWN",
            "after_status_raw": last_raw,
            "elapsed_seconds": elapsed,
            "cache_cleared": True,
        }

    def _cleanup(self) -> None:
        objects = list(self._variables.values()) + list(self._tasks.values())
        objects += [self._cpu, self._device, self._line]
        for obj in objects:
            if obj is not None:
                try:
                    obj.kill()
                except Exception:
                    LOG.debug("Failed to unlink %r", obj, exc_info=True)
        self._variables.clear()
        self._tasks.clear()
        if self._connection is not None:
            try:
                self._connection.stop()
            except Exception:
                pass
        self._cpu = self._device = self._line = self._connection = None
        gc.collect()

