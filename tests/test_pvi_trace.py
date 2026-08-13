from __future__ import annotations

import time

import pytest

from br_plc_toolchain.backends.pvi import VariableRef
from br_plc_toolchain.services.pvi_trace import PviTraceError, TraceManager


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


def wait_for(manager: TraceManager, trace_id: str, state: str, timeout: float = 3) -> dict:
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
    final = wait_for(manager, started["trace_id"], "completed")
    assert final["sample_count"] >= 8
    data = manager.read(started["trace_id"], from_ms=0, to_ms=500, max_samples=3)
    assert data["ok"]
    assert data["variables"] == ["Cycle"]
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
    manager = TraceManager(FakeTraceService(), root=tmp_path)
    with pytest.raises(PviTraceError, match="at least 100"):
        manager.start("arsim", [VariableRef(name="Cycle", scope="global")], interval_ms=10)
    with pytest.raises(PviTraceError, match="at most 32"):
        manager.start(
            "arsim",
            [VariableRef(name=f"V{i}", scope="global") for i in range(33)],
        )
