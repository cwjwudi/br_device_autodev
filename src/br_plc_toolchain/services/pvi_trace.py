"""Background, read-only Runtime PVI trace collection."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from br_plc_toolchain.backends.pvi import VariableRef
from br_plc_toolchain.services.runtime_pvi import validate_target_name


TRACE_STATES = {"running", "completed", "stopped", "failed", "expired"}
DEFAULT_DURATION_SECONDS = 30
MAX_DURATION_SECONDS = 600
DEFAULT_INTERVAL_MS = 500
MIN_INTERVAL_MS = 100
MAX_VARIABLES = 32
MAX_SAMPLES = 10_000
MAX_FILE_BYTES = 50 * 1024 * 1024
RETENTION_DAYS = 7


class PviTraceError(RuntimeError):
    def __init__(self, message: str, *, error_code: str = "PVI_TRACE_ERROR", retryable: bool = False):
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


@dataclass
class _Trace:
    trace_id: str
    target: str
    refs: list[VariableRef]
    duration_seconds: int
    interval_ms: int
    path: Path
    started_at: datetime
    started_monotonic: float
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    state: str = "running"
    sample_count: int = 0
    dropped_samples: int = 0
    error_count: int = 0
    last_sample: list[Any] | None = None
    last_sample_monotonic: float | None = None
    actual_interval_ms: float | None = None
    error_code: str | None = None
    end_at: datetime | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def variable_names(self) -> list[str]:
        return [ref.canonical for ref in self.refs]


class TraceManager:
    """Own trace lifecycle and files independently from MCP request workers."""

    def __init__(self, service: Any, root: Path | None = None):
        self.service = service
        self.root = root or Path(__file__).resolve().parents[3] / "var" / "traces"
        self._lock = threading.RLock()
        self._traces: dict[str, _Trace] = {}

    def _cleanup_expired_files(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - RETENTION_DAYS * 24 * 60 * 60
        for path in self.root.glob("trace-*.jsonl"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue

    @staticmethod
    def _unique_refs(refs: list[VariableRef]) -> list[VariableRef]:
        unique: list[VariableRef] = []
        seen: set[str] = set()
        for ref in refs:
            ref.validate()
            if ref.canonical not in seen:
                seen.add(ref.canonical)
                unique.append(ref)
        return unique

    def start(
        self,
        target: str,
        refs: list[VariableRef],
        *,
        duration_seconds: int = DEFAULT_DURATION_SECONDS,
        interval_ms: int = DEFAULT_INTERVAL_MS,
    ) -> dict[str, Any]:
        validate_target_name(target)
        if not 1 <= duration_seconds <= MAX_DURATION_SECONDS:
            raise PviTraceError(
                f"duration_seconds must be between 1 and {MAX_DURATION_SECONDS}",
                error_code="TRACE_DURATION_INVALID",
            )
        if interval_ms < MIN_INTERVAL_MS:
            raise PviTraceError(
                f"interval_ms must be at least {MIN_INTERVAL_MS}",
                error_code="TRACE_INTERVAL_INVALID",
            )
        unique = self._unique_refs(refs)
        if not unique:
            raise PviTraceError("variables must be a non-empty array", error_code="TRACE_VARIABLES_REQUIRED")
        if len(unique) > MAX_VARIABLES:
            raise PviTraceError(
                f"a trace may contain at most {MAX_VARIABLES} variables",
                error_code="TRACE_VARIABLE_LIMIT",
            )
        with self._lock:
            for trace in self._traces.values():
                with trace.lock:
                    if trace.target == target and trace.state == "running":
                        raise PviTraceError(
                            f"target {target!r} already has an active trace",
                            error_code="TRACE_ALREADY_RUNNING",
                        )
            self._cleanup_expired_files()
            trace_id = f"trace-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
            path = self.root / f"{trace_id}.jsonl"
            now = datetime.now(UTC)
            trace = _Trace(
                trace_id=trace_id,
                target=target,
                refs=unique,
                duration_seconds=duration_seconds,
                interval_ms=interval_ms,
                path=path,
                started_at=now,
                started_monotonic=time.monotonic(),
            )
            header = {
                "kind": "header",
                "trace_id": trace_id,
                "target": target,
                "variables": trace.variable_names,
                "types": [None] * len(unique),
                "requested_interval_ms": interval_ms,
                "duration_seconds": duration_seconds,
                "started_at": now.isoformat(),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")
            trace.thread = threading.Thread(
                target=self._run,
                args=(trace,),
                name=f"pvi-trace-{trace_id}",
                daemon=True,
            )
            self._traces[trace_id] = trace
            trace.thread.start()
        return self._summary(trace)

    def _append(self, trace: _Trace, payload: dict[str, Any]) -> bool:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with trace.path.open("a", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()
        try:
            return trace.path.stat().st_size <= MAX_FILE_BYTES
        except OSError:
            return False

    @staticmethod
    def _error_code(message: str) -> str | None:
        for code in ("PVI_OPERATION_TIMEOUT", "PVI_WORKER_DIRTY", "PVI_TARGET_STATE_UNKNOWN"):
            if message.startswith(code):
                return code
        return None

    def _run(self, trace: _Trace) -> None:
        next_deadline = trace.started_monotonic
        try:
            while True:
                if trace.stop_event.is_set():
                    with trace.lock:
                        trace.state = "stopped"
                    break
                now = time.monotonic()
                elapsed = now - trace.started_monotonic
                if elapsed >= trace.duration_seconds:
                    with trace.lock:
                        trace.state = "completed"
                    break
                with trace.lock:
                    if trace.sample_count >= MAX_SAMPLES:
                        trace.state = "expired"
                        break
                wait_s = next_deadline - now
                if wait_s > 0:
                    trace.stop_event.wait(wait_s)
                    continue

                sample_started = time.monotonic()
                errors: list[dict[str, Any]] = []
                try:
                    result = self.service.read_many(trace.target, trace.refs)
                    values = result.get("values", {})
                    row_values = []
                    for ref in trace.refs:
                        name = ref.canonical
                        item = values.get(name)
                        if item is not None:
                            row_values.append(item.get("value"))
                        else:
                            row_values.append(None)
                            errors.append(
                                {
                                    "variable": name,
                                    "error": (result.get("errors") or {}).get(name, "PVI read failed"),
                                }
                            )
                    critical = next(
                        (self._error_code(str(item.get("error", ""))) for item in errors),
                        None,
                    )
                except Exception as exc:  # the sample is retained, target state is not guessed
                    row_values = [None] * len(trace.refs)
                    errors = [{"variable": name, "error": str(exc)} for name in trace.variable_names]
                    critical = self._error_code(str(exc)) or "PVI_TARGET_STATE_UNKNOWN"

                t_ms = max(0, int((sample_started - trace.started_monotonic) * 1000))
                sample_payload = {
                    "kind": "sample",
                    "t_ms": t_ms,
                    "values": row_values,
                    "errors": errors,
                }
                if not self._append(trace, sample_payload):
                    with trace.lock:
                        trace.state = "expired"
                        trace.error_code = "TRACE_FILE_LIMIT"
                    break
                with trace.lock:
                    trace.sample_count += 1
                    trace.error_count += len(errors)
                    trace.last_sample = row_values
                    if trace.last_sample_monotonic is not None:
                        trace.actual_interval_ms = (sample_started - trace.last_sample_monotonic) * 1000
                    trace.last_sample_monotonic = sample_started
                    if critical:
                        trace.state = "failed"
                        trace.error_code = critical
                if critical:
                    break

                next_deadline += trace.interval_ms / 1000
                current = time.monotonic()
                if current > next_deadline:
                    skipped = int((current - next_deadline) / (trace.interval_ms / 1000)) + 1
                    with trace.lock:
                        trace.dropped_samples += skipped
                    next_deadline += skipped * trace.interval_ms / 1000
        finally:
            with trace.lock:
                if trace.state == "running":
                    trace.state = "stopped" if trace.stop_event.is_set() else "completed"
                trace.end_at = datetime.now(UTC)
                footer = {
                    "kind": "footer",
                    "state": trace.state,
                    "sample_count": trace.sample_count,
                    "dropped_samples": trace.dropped_samples,
                    "error_count": trace.error_count,
                    "error_code": trace.error_code,
                    "ended_at": trace.end_at.isoformat(),
                }
            try:
                self._append(trace, footer)
            except OSError:
                pass

    @staticmethod
    def _summary(trace: _Trace) -> dict[str, Any]:
        with trace.lock:
            end = time.monotonic() if trace.state == "running" else (
                trace.started_monotonic
                + ((trace.end_at - trace.started_at).total_seconds() if trace.end_at else 0)
            )
            elapsed_ms = max(0, int((end - trace.started_monotonic) * 1000))
            return {
                "ok": True,
                "trace_id": trace.trace_id,
                "state": trace.state,
                "target": trace.target,
                "variables": trace.variable_names,
                "requested_interval_ms": trace.interval_ms,
                "duration_seconds": trace.duration_seconds,
                "sample_count": trace.sample_count,
                "dropped_samples": trace.dropped_samples,
                "elapsed_ms": elapsed_ms,
                "actual_interval_ms": round(trace.actual_interval_ms, 3) if trace.actual_interval_ms is not None else None,
                "last_sample": trace.last_sample,
                "error_count": trace.error_count,
                "error_code": trace.error_code,
            }

    def _get(self, trace_id: str) -> _Trace:
        if not isinstance(trace_id, str) or not trace_id.startswith("trace-"):
            raise PviTraceError("invalid trace_id", error_code="TRACE_NOT_FOUND")
        with self._lock:
            trace = self._traces.get(trace_id)
        if trace is None:
            raise PviTraceError(f"trace {trace_id!r} was not found", error_code="TRACE_NOT_FOUND")
        return trace

    def status(self, trace_id: str) -> dict[str, Any]:
        return self._summary(self._get(trace_id))

    def stop(self, trace_id: str) -> dict[str, Any]:
        trace = self._get(trace_id)
        with trace.lock:
            if trace.state == "running":
                trace.stop_event.set()
                thread = trace.thread
            else:
                thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        return self._summary(trace)

    def read(
        self,
        trace_id: str,
        *,
        from_ms: int = 0,
        to_ms: int | None = None,
        max_samples: int = 1000,
        downsample: int = 1,
    ) -> dict[str, Any]:
        trace = self._get(trace_id)
        if from_ms < 0 or (to_ms is not None and to_ms < from_ms):
            raise PviTraceError("invalid trace time range", error_code="TRACE_RANGE_INVALID")
        if not 1 <= max_samples <= MAX_SAMPLES:
            raise PviTraceError("max_samples is out of range", error_code="TRACE_MAX_SAMPLES_INVALID")
        if downsample < 1:
            raise PviTraceError("downsample must be at least 1", error_code="TRACE_DOWNSAMPLE_INVALID")
        if not trace.path.exists():
            raise PviTraceError("trace data file is missing", error_code="TRACE_DATA_UNAVAILABLE")
        variables = trace.variable_names
        rows: list[dict[str, Any]] = []
        with trace.path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise PviTraceError("trace data file is corrupt", error_code="TRACE_DATA_CORRUPT") from exc
                if item.get("kind") != "sample":
                    continue
                t_ms = int(item.get("t_ms", 0))
                if t_ms < from_ms or (to_ms is not None and t_ms > to_ms):
                    continue
                rows.append(item)
        rows = rows[::downsample]
        if len(rows) > max_samples:
            if max_samples == 1:
                rows = [rows[0]]
            else:
                indices = [round(index * (len(rows) - 1) / (max_samples - 1)) for index in range(max_samples)]
                rows = [rows[index] for index in indices]
        samples = [[item.get("t_ms"), *(item.get("values") or [])] for item in rows]
        errors = [
            {"t_ms": item.get("t_ms"), **error}
            for item in rows
            for error in (item.get("errors") or [])
        ]
        with trace.lock:
            dropped = trace.dropped_samples
        return {
            "ok": True,
            "trace_id": trace_id,
            "variables": variables,
            "samples": samples,
            "sample_count": len(samples),
            "dropped_samples": dropped,
            "errors": errors,
        }

    def close(self) -> None:
        with self._lock:
            traces = list(self._traces.values())
        for trace in traces:
            with trace.lock:
                active = trace.state == "running"
            if active:
                self.stop(trace.trace_id)
