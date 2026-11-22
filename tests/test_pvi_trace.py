from __future__ import annotations

import json
import time

import pytest

from br_plc_toolchain.backends.pvi import VariableRef
from br_plc_toolchain.services import pvi_trace
from br_plc_toolchain.services.pvi_trace import MAX_SAMPLES, MAX_VARIABLES, MIN_INTERVAL_MS, PviTraceError, TraceManager


class FakeTraceService:
    def __init__(self) -> None:
        self.counter = 0

    def read_many(self, target, refs):
        self.counter += 1
        values = {
            ref.canonical: {"value": self.counter, "type": "u32"}
            for ref in refs
        }
        return {"ok": True, "values": values, "errors": {}}


def wait_for(manager: TraceManager, trace_id: str, state: str, timeout: float = 5) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = manager.status(trace_id)
        if result["state"] == state:
            return result
        time.sleep(0.02)
    pytest.fail(f"trace did not reach {state}: {manager.status(trace_id)}")


def test_trace_completes_and_reads_bounded_columnar_data(tmp_path) -> None:
    manager = TraceManager(FakeTraceService(), root=tmp_path)
    started = manager.start(
        "arsim",
        [VariableRef(name="Cycle", scope="global")],
        duration_seconds=1,
        interval_ms=100,
    )
    assert started["trace_file"]
    final = wait_for(manager, started["trace_id"], "completed")
    assert final["sample_count"] >= 8
    assert final["trace_file"].endswith(f"{started['trace_id']}.jsonl")
    data = manager.read(started["trace_id"], from_ms=0, to_ms=500, max_samples=3)
    assert data["ok"]
    assert data["variables"] == ["Cycle"]
    assert data["trace_file"] == final["trace_file"]
    assert 1 <= len(data["samples"]) <= 3
    assert all(len(row) == 2 for row in data["samples"])
    assert list(tmp_path.glob("trace-*.jsonl"))
    manager.close()


def test_trace_stop_is_idempotent_and_duplicate_target_is_rejected(tmp_path) -> None:
    manager = TraceManager(FakeTraceService(), root=tmp_path)
    started = manager.start(
        "arsim",
        [VariableRef(name="Cycle", scope="global")],
        duration_seconds=10,
        interval_ms=100,
    )
    with pytest.raises(PviTraceError, match="active trace"):
        manager.start(
            "arsim",
            [VariableRef(name="Other", scope="global")],
            duration_seconds=1,
            interval_ms=100,
        )
    stopped = manager.stop(started["trace_id"])
    assert stopped["state"] == "stopped"
    assert manager.stop(started["trace_id"])["state"] == "stopped"
    manager.close()


def test_trace_parameter_limits_are_enforced(tmp_path) -> None:
    assert MIN_INTERVAL_MS == 20
    assert MAX_VARIABLES == 128
    assert MAX_SAMPLES == 30_000
    manager = TraceManager(FakeTraceService(), root=tmp_path)
    with pytest.raises(PviTraceError, match="at least 20"):
        manager.start("arsim", [VariableRef(name="Cycle", scope="global")], interval_ms=19)
    with pytest.raises(PviTraceError, match="at most 128"):
        manager.start(
            "arsim",
            [VariableRef(name=f"V{i}", scope="global") for i in range(129)],
        )
    manager.close()


def test_trace_supports_128_variables_at_20ms(tmp_path) -> None:
    manager = TraceManager(FakeTraceService(), root=tmp_path)
    refs = [VariableRef(name=f"V{i}", scope="global") for i in range(128)]
    started = manager.start("arsim", refs, duration_seconds=1, interval_ms=20)
    assert started["state"] == "running"
    assert len(started["variables"]) == 128
    assert started["requested_interval_ms"] == 20
    final = manager.wait(started["trace_id"], timeout_s=5)
    assert final["state"] == "completed"
    assert final["sample_count"] >= 20
    data = manager.read(started["trace_id"], max_samples=500)
    assert data["ok"]
    assert len(data["variables"]) == 128
    assert len(data["samples"][0]) == 129
    lines = (tmp_path / f"{started['trace_id']}.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["kind"] == "header"
    assert json.loads(lines[-1])["kind"] == "footer"
    manager.close()


def test_trace_supports_more_than_10000_samples_at_20ms(tmp_path, monkeypatch) -> None:
    clock = [1000.0]

    class FastClockService:
        def __init__(self) -> None:
            self.counter = 0

        def read_many(self, target, refs):
            self.counter += 1
            clock[0] += 0.02
            return {
                "ok": True,
                "values": {ref.canonical: {"value": self.counter, "type": "u32"} for ref in refs},
                "errors": {},
            }

    monkeypatch.setattr(pvi_trace.time, "monotonic", lambda: clock[0])
    service = FastClockService()
    manager = TraceManager(service, root=tmp_path)
    started = manager.start(
        "arsim",
        [VariableRef(name="Cycle", scope="global")],
        duration_seconds=220,
        interval_ms=20,
    )
    final = manager.wait(started["trace_id"], poll_interval_s=0.01, timeout_s=300)
    assert final["state"] == "completed"
    assert final["sample_count"] > 10_000
    assert final["sample_count"] <= MAX_SAMPLES
    data = manager.read(started["trace_id"], max_samples=10_500)
    assert data["sample_count"] == 10_500
    manager.close()
