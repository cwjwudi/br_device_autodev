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
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

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
        self._var_list_cache: dict[tuple[str, str | None], tuple[float, str, list[str]]] = {}
        self._var_list_cache_ttl_s: float = 30.0
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
            self._var_list_cache.clear()
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
            self._var_list_cache.clear()

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
        refresh: bool = False,
    ) -> dict[str, Any]:
        VariableRef(name="_list", scope=scope, task=task).validate()
        cache_key = (scope, task if scope == "task" else None)
        now = time.monotonic()
        cached = self._var_list_cache.get(cache_key)
        if (
            not refresh
            and cached is not None
            and (now - cached[0]) < self._var_list_cache_ttl_s
        ):
            _, cached_at_iso, source = cached
            cache_hit = True
        else:
            parent = self._get_task(str(task)) if scope == "task" else self._cpu
            source = _read_variable_names(parent)
            cached_at_iso = datetime.now(UTC).isoformat()
            self._var_list_cache[cache_key] = (now, cached_at_iso, source)
            cache_hit = False

        matched = [name for name in source if fnmatch.fnmatchcase(name, pattern)]
        effective_limit = max(1, min(limit, 5000))
        offset = max(0, offset)
        page = matched[offset:offset + effective_limit]
        next_offset = offset + len(page)
        has_more = next_offset < len(matched)
        return {
            "ok": True,
            "target": self.target.name,
            "scope": scope,
            "task": task,
            "pattern": pattern,
            "total_matches": len(matched),
            "total_matched": len(matched),
            "offset": offset,
            "limit": effective_limit,
            "has_more": has_more,
            "truncated": has_more,
            "next_offset": next_offset if has_more else None,
            "cache_hit": cache_hit,
            "cached_at": cached_at_iso,
            "cache_ttl_seconds": self._var_list_cache_ttl_s,
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

    @staticmethod
    def _member_depth(member_suffix: str) -> int:
        stripped = member_suffix.lstrip(".")
        if not stripped:
            return 0
        return stripped.count(".") + 1

    @staticmethod
    def _expand_array_indices(indices: Any) -> list[str]:
        if not indices or not isinstance(indices, (list, tuple)):
            return []
        if len(indices) == 1:
            low, high = int(indices[0][0]), int(indices[0][1])
            return [f"[{i}]" for i in range(low, high + 1)]
        if len(indices) == 2:
            lo1, hi1 = int(indices[0][0]), int(indices[0][1])
            lo2, hi2 = int(indices[1][0]), int(indices[1][1])
            return [f"[{i},{j}]" for i in range(lo1, hi1 + 1) for j in range(lo2, hi2 + 1)]
        return []

    def _expand_variable_leaves(
        self,
        ref: VariableRef,
        variable: Any,
        *,
        data_type: str,
        is_array: bool,
        is_structure: bool,
        max_depth: int,
        max_fields: int,
    ) -> dict[str, Any]:
        max_depth = max(1, min(int(max_depth), 16))
        max_fields = max(1, min(int(max_fields), 512))
        parent_readable = bool(variable.readable)
        parent_writable = bool(variable.writable)

        fields: list[dict[str, Any]] = []
        total_discovered = 0
        truncated = False

        def add_leaf(
            suffix: str,
            leaf_type: str,
            readable: bool,
            writable: bool,
        ) -> None:
            nonlocal total_discovered, truncated
            total_discovered += 1
            if len(fields) >= max_fields:
                truncated = True
                return
            if not suffix:
                full_name = ref.name
            elif suffix.startswith(".") or suffix.startswith("["):
                full_name = f"{ref.name}{suffix}"
            else:
                full_name = f"{ref.name}.{suffix}"
            leaf_ref = VariableRef(name=full_name, scope=ref.scope, task=ref.task)
            fields.append(
                {
                    "canonical": leaf_ref.canonical,
                    "name": full_name,
                    "data_type": leaf_type,
                    "readable": readable,
                    "writable": writable,
                }
            )

        if is_structure:
            struct_members = getattr(variable, "_struct_members", None)
            if isinstance(struct_members, Mapping) and struct_members:
                for member_key, member_td in struct_members.items():
                    suffix = str(getattr(member_td, "name", None) or member_key)
                    if not suffix.startswith(".") and not suffix.startswith("["):
                        suffix = f".{suffix}"
                    depth = self._member_depth(suffix)
                    if depth > max_depth:
                        truncated = True
                        continue
                    vt = getattr(member_td, "vt", None)
                    leaf_type = (
                        str(vt.value)
                        if hasattr(vt, "value")
                        else (str(vt) if vt is not None else "unknown")
                    )
                    member_at = str(getattr(member_td, "at", "") or "")
                    readable = ("r" in member_at) if member_at else parent_readable
                    writable = ("w" in member_at) if member_at else parent_writable

                    arr_indices = None
                    get_indices = getattr(member_td, "get_array_indices", None)
                    if callable(get_indices):
                        try:
                            arr_indices = get_indices()
                        except Exception:
                            arr_indices = None

                    if arr_indices:
                        elem_suffixes = self._expand_array_indices(arr_indices)
                        if elem_suffixes:
                            for elem_idx in elem_suffixes:
                                add_leaf(f"{suffix}{elem_idx}", leaf_type, readable, writable)
                            continue
                    add_leaf(suffix, leaf_type, readable, writable)

                return {
                    "expanded": True,
                    "expansion_source": "pvi",
                    "max_depth": max_depth,
                    "max_fields": max_fields,
                    "total_discovered": total_discovered,
                    "truncated": truncated,
                    "fields": fields,
                }

            return {
                "expanded": True,
                "expansion_source": "unavailable",
                "max_depth": max_depth,
                "max_fields": max_fields,
                "total_discovered": 0,
                "truncated": False,
                "fields": [],
                "expansion_note": (
                    "PVI did not expose structure member descriptors for this variable; "
                    "inspect the project .typ definition to determine member paths."
                ),
            }

        if is_array:
            type_desc = getattr(variable, "_type_description", None)
            arr_indices = None
            get_indices = getattr(type_desc, "get_array_indices", None) if type_desc is not None else None
            if callable(get_indices):
                try:
                    arr_indices = get_indices()
                except Exception:
                    arr_indices = None
            elem_suffixes = self._expand_array_indices(arr_indices) if arr_indices else []
            if elem_suffixes:
                elem_type = data_type.split("[", 1)[0] if isinstance(data_type, str) else str(data_type)
                for elem_idx in elem_suffixes:
                    add_leaf(elem_idx, elem_type, parent_readable, parent_writable)
                return {
                    "expanded": True,
                    "expansion_source": "pvi",
                    "max_depth": max_depth,
                    "max_fields": max_fields,
                    "total_discovered": total_discovered,
                    "truncated": truncated,
                    "fields": fields,
                }
            return {
                "expanded": True,
                "expansion_source": "unavailable",
                "max_depth": max_depth,
                "max_fields": max_fields,
                "total_discovered": 0,
                "truncated": False,
                "fields": [],
                "expansion_note": "PVI did not expose array index bounds for this variable.",
            }

        add_leaf("", str(data_type), parent_readable, parent_writable)
        return {
            "expanded": True,
            "expansion_source": "pvi",
            "max_depth": max_depth,
            "max_fields": max_fields,
            "total_discovered": total_discovered,
            "truncated": truncated,
            "fields": fields,
        }

    def _variable_info(
        self,
        ref: VariableRef,
        expand: bool = False,
        max_depth: int = 3,
        max_fields: int = 128,
    ) -> dict[str, Any]:
        variable = self._get_variable(ref)
        data_type = variable.dataType
        is_array = bool(variable.isArray)
        is_structure = bool(variable.isStructure)
        info: dict[str, Any] = {
            "ok": True,
            "target": self.target.name,
            **self._ref_dict(ref),
            "pvi_path": variable.name,
            "data_type": data_type,
            "readable": variable.readable,
            "writable": variable.writable,
            "is_array": is_array,
            "is_structure": is_structure,
            "attributes": json_safe(variable.attributes),
            "descriptor": json_safe(variable.descriptor),
        }
        if expand:
            info.update(
                self._expand_variable_leaves(
                    ref,
                    variable,
                    data_type=str(data_type),
                    is_array=is_array,
                    is_structure=is_structure,
                    max_depth=max_depth,
                    max_fields=max_fields,
                )
            )
        return info

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

    def _write_many(
        self,
        writes: list[tuple[VariableRef, Any]],
        readback_wait_ms: int = 50,
    ) -> dict[str, Any]:
        prepared: list[tuple[int, VariableRef, Any, str, Any, Any]] = []
        results: list[dict[str, Any] | None] = [None] * len(writes)

        for idx, (ref, value) in enumerate(writes):
            try:
                variable = self._get_variable(ref)
                data_type = variable.dataType
                if not variable.writable:
                    raise PermissionError(f"Variable {ref.canonical!r} is not writable")
                before = variable.value if variable.readable else None
                coerced = coerce_write_value(value, data_type)
                variable.value = coerced
                prepared.append((idx, ref, variable, str(data_type), before, coerced))
            except Exception as exc:
                results[idx] = {"ok": False, **self._ref_dict(ref), "error": str(exc)}

        if prepared:
            wait_s = max(0.0, float(readback_wait_ms) / 1000.0)
            if wait_s > 0:
                self._pump_for(wait_s)
            else:
                self._do_events()

            for idx, ref, variable, data_type, before, coerced in prepared:
                try:
                    readback = variable.value if variable.readable else None
                    verified = values_equal(coerced, readback) if variable.readable else None
                    entry: dict[str, Any] = {
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
                        entry["warning_code"] = "PVI_READBACK_MISMATCH"
                        entry["warning"] = (
                            "PVI write completed, but readback does not match the requested value."
                        )
                    elif verified is None:
                        entry["warning_code"] = "PVI_READBACK_UNAVAILABLE"
                        entry["warning"] = (
                            "PVI write completed, but readback is unavailable for this variable."
                        )
                    results[idx] = entry
                except Exception as exc:
                    results[idx] = {"ok": False, **self._ref_dict(ref), "error": str(exc)}

        final_results = [item for item in results if item is not None]
        return {
            "ok": bool(final_results) and all(item["ok"] for item in final_results),
            "atomic": False,
            "results": final_results,
        }

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
        self._var_list_cache.clear()

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
        self._var_list_cache.clear()
        if self._connection is not None:
            try:
                self._connection.stop()
            except Exception:
                pass
        self._cpu = self._device = self._line = self._connection = None
        gc.collect()

