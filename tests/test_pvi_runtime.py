from __future__ import annotations

import datetime as dt

import pytest

from br_plc_toolchain.backends.pvi.manager import PviSessionManager
from br_plc_toolchain.backends.pvi.models import PviTarget, VariableRef
from br_plc_toolchain.backends.pvi.values import coerce_write_value, json_safe, values_equal


class FakeWorker:
    created = 0

    def __init__(self, target: PviTarget):
        self.target = target
        self.running = False
        self.closed = False
        FakeWorker.created += 1

    def start(self) -> None:
        self.running = True

    def close(self) -> None:
        self.running = False
        self.closed = True

    def call(self, operation: str, **arguments):
        return {"operation": operation, "target": self.target.name, **arguments}


def test_variable_ref_validation_and_canonical_name() -> None:
    ref = VariableRef(name="bEnable", task="Main")
    ref.validate()
    assert ref.canonical == "Main:bEnable"
    with pytest.raises(ValueError, match="task is required"):
        VariableRef(name="bEnable").validate()


def test_json_and_write_value_conversion() -> None:
    assert json_safe(b"abc\x00") == "abc"
    assert json_safe(dt.timedelta(milliseconds=10)) == 10
    assert coerce_write_value("true", "boolean") is True
    assert coerce_write_value(["1", "2"], "i16[0..1]") == [1, 2]
    assert coerce_write_value("abc", "string") == b"abc"
    with pytest.raises(ValueError, match="Structure"):
        coerce_write_value({"member": 1}, "struct")


def test_value_comparison_handles_float_arrays() -> None:
    assert values_equal([0.1 + 0.2, 1.0], [0.3, 1.0])


def test_session_manager_reuses_and_invalidates_workers() -> None:
    FakeWorker.created = 0
    target = PviTarget(name="plc", ip="192.168.50.233")
    manager = PviSessionManager(worker_factory=FakeWorker)  # type: ignore[arg-type]
    first = manager.get(target)
    second = manager.get(target)
    assert first is second
    assert FakeWorker.created == 1
    assert manager.active_targets() == ["plc"]
    manager.invalidate(target)
    assert first.closed is True
    third = manager.get(target)
    assert third is not first
    manager.close_all()
    assert third.closed is True


def test_session_manager_rejects_mixed_pvi_dll_families() -> None:
    manager = PviSessionManager(worker_factory=FakeWorker)  # type: ignore[arg-type]
    manager.get(PviTarget(name="as4", ip="127.0.0.1", pvi_dll_path="C:/PVI4"))
    with pytest.raises(RuntimeError, match="cannot be mixed"):
        manager.get(PviTarget(name="as6", ip="127.0.0.2", pvi_dll_path="C:/PVI6"))
    manager.close_all()
    manager.get(PviTarget(name="as6", ip="127.0.0.2", pvi_dll_path="C:/PVI6"))
    manager.close_all()
