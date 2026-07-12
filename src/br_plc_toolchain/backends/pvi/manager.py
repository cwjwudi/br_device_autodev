"""Multi-target lifecycle manager for persistent PVI workers."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .models import PviTarget
from .worker import PviWorker


class PviSessionManager:
    def __init__(self, worker_factory: Callable[[PviTarget], PviWorker] = PviWorker):
        self._worker_factory = worker_factory
        self._workers: dict[str, PviWorker] = {}
        self._lock = threading.RLock()

    def get(self, target: PviTarget) -> PviWorker:
        with self._lock:
            worker = self._workers.get(target.key)
            if worker is None or not worker.running:
                if worker is not None:
                    worker.close()
                worker = self._worker_factory(target)
                worker.start()
                self._workers[target.key] = worker
            return worker

    def call(self, target: PviTarget, operation: str, **arguments: Any) -> Any:
        return self.get(target).call(operation, **arguments)

    def invalidate(self, target: PviTarget) -> None:
        with self._lock:
            worker = self._workers.pop(target.key, None)
        if worker is not None:
            worker.close()

    def close_all(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.close()

    def active_targets(self) -> list[str]:
        with self._lock:
            return sorted(worker.target.name for worker in self._workers.values() if worker.running)

    def __enter__(self) -> "PviSessionManager":
        return self

    def __exit__(self, *_: object) -> None:
        self.close_all()

