"""Multi-target lifecycle manager for persistent PVI workers."""

from __future__ import annotations

import threading
import os
from collections.abc import Callable
from typing import Any

from .models import PviTarget
from .worker import PviWorker, is_pvi_transport_error


_RECONNECTABLE_OPERATIONS = {
    "health",
    "list_tasks",
    "list_variables",
    "variable_info",
    "read",
    "read_many",
}


class PviSessionManager:
    def __init__(self, worker_factory: Callable[[PviTarget], PviWorker] = PviWorker):
        self._worker_factory = worker_factory
        self._workers: dict[str, PviWorker] = {}
        self._lock = threading.RLock()
        self._pvi_dll_path: str | None = None

    def get(self, target: PviTarget) -> PviWorker:
        with self._lock:
            requested_dll = os.path.normcase(os.path.abspath(target.pvi_dll_path)) if target.pvi_dll_path else None
            if self._pvi_dll_path and requested_dll and requested_dll != self._pvi_dll_path:
                raise RuntimeError(
                    "PVI DLL families cannot be mixed in one MCP process. "
                    "Close the current MCP server before switching AS4/PVI4 and AS6/PVI6."
                )
            if requested_dll:
                self._pvi_dll_path = requested_dll
            worker = self._workers.get(target.key)
            if worker is None or not worker.running or bool(getattr(worker, "dirty", False)):
                if worker is not None:
                    worker.close()
                    if worker.running:
                        raise RuntimeError(
                            "PVI_WORKER_DIRTY: previous operation is still running; target state is unknown"
                        )
                worker = self._worker_factory(target)
                worker.start()
                self._workers[target.key] = worker
            return worker

    def call(self, target: PviTarget, operation: str, **arguments: Any) -> Any:
        attempts = 2 if operation in _RECONNECTABLE_OPERATIONS else 1
        for attempt in range(attempts):
            try:
                return self.get(target).call(operation, **arguments)
            except Exception as exc:
                if attempt + 1 >= attempts or not is_pvi_transport_error(exc):
                    raise
                if not self.invalidate(target):
                    raise RuntimeError(
                        "PVI_WORKER_DIRTY: timed-out native operation is still running; "
                        "target state is unknown"
                    ) from exc
        raise AssertionError("unreachable")

    def invalidate(self, target: PviTarget) -> bool:
        with self._lock:
            worker = self._workers.pop(target.key, None)
        if worker is not None:
            worker.close()
            return not worker.running
        return True

    def close_all(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
            self._pvi_dll_path = None
        for worker in workers:
            worker.close()

    def active_targets(self) -> list[str]:
        with self._lock:
            return sorted(worker.target.name for worker in self._workers.values() if worker.running)

    def worker_state(self, target: PviTarget) -> dict[str, Any]:
        with self._lock:
            worker = self._workers.get(target.key)
            return {
                "active": bool(worker and worker.running),
                "dirty": bool(worker and getattr(worker, "dirty", False)),
            }

    def __enter__(self) -> "PviSessionManager":
        return self

    def __exit__(self, *_: object) -> None:
        self.close_all()
