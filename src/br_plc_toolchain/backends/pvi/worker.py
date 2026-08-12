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
from dataclasses import dataclass
from typing import Any, Callable

from .models import PviTarget, Scope, VariableRef
from .values import coerce_write_value, json_safe, values_equal

LOG = logging.getLogger(__name__)
_GENERATION_LOCK = threading.Lock()
_GENERATION_COUNTER = 0


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
        try:
            return future.result(timeout=self.target.request_timeout_s)
        except FutureTimeoutError as exc:
            self._dirty = True
            self._stop.set()
            future.cancel()
            raise TimeoutError(f"PVI_OPERATION_TIMEOUT: operation {operation!r} timed out; target state is unknown") from exc

    def _run(self) -> None:
        try:
            self._initialize_pvi()
            self._pump_for(self.target.startup_wait_s)
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
        self._manager_connected = bool(connected)
        if not connected:
            self._cpu_connected = False
            self._tasks.clear()
            self._variables.clear()

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

    @staticmethod
    def _safe_get(getter: Callable[[], Any]) -> dict[str, Any]:
        try:
            return {"ok": True, "value": json_safe(getter())}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _health(self) -> dict[str, Any]:
        return {
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
            "license": self._safe_get(lambda: self._connection.license),
            "cpu_type": self._safe_get(
                lambda: getattr(self._cpu, "type", None) or getattr(self._cpu, "cpuType", None)
            ),
            "order_number": self._safe_get(
                lambda: getattr(self._cpu, "orderNumber", None) or getattr(self._cpu, "order_number", None)
            ),
            "ar_version": self._safe_get(lambda: self._cpu.version),
            "cpu_status": self._safe_get(lambda: self._cpu.status),
            "cpu_version": self._safe_get(lambda: self._cpu.version),
            "cpu_time": self._safe_get(lambda: self._cpu.time),
            "cached_tasks": len(self._tasks),
            "cached_variables": len(self._variables),
        }

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
    ) -> dict[str, Any]:
        VariableRef(name="_list", scope=scope, task=task).validate()
        source = self._get_task(str(task)).variables if scope == "task" else self._cpu.variables
        matched = [name for name in source if fnmatch.fnmatchcase(name, pattern)]
        effective_limit = max(1, min(limit, 5000))
        return {
            "ok": True,
            "target": self.target.name,
            "scope": scope,
            "task": task,
            "pattern": pattern,
            "total_matches": len(matched),
            "truncated": len(matched) > effective_limit,
            "variables": matched[:effective_limit],
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
        for ref in refs:
            try:
                results.append(self._read(ref))
            except Exception as exc:
                results.append({"ok": False, **self._ref_dict(ref), "error": str(exc)})
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
        return {
            "ok": verified is not False,
            "target": self.target.name,
            **self._ref_dict(ref),
            "pvi_path": variable.name,
            "data_type": data_type,
            "before": json_safe(before),
            "requested": json_safe(coerced),
            "readback": json_safe(readback),
            "verified": verified,
        }

    def _write_many(self, writes: list[tuple[VariableRef, Any]]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for ref, value in writes:
            try:
                results.append(self._write(ref, value))
            except Exception as exc:
                results.append({"ok": False, **self._ref_dict(ref), "error": str(exc)})
        return {"ok": all(item["ok"] for item in results), "atomic": False, "results": results}

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

