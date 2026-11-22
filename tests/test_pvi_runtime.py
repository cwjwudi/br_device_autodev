from __future__ import annotations

import datetime as dt
import ctypes

import pytest

from br_plc_toolchain.backends.pvi.manager import PviSessionManager
from br_plc_toolchain.backends.pvi.models import PviTarget, VariableRef, parse_variable_ref
from br_plc_toolchain.backends.pvi.values import coerce_write_value, json_safe, values_equal
from br_plc_toolchain.backends.pvi.worker import PviWorker, is_pvi_transport_error
from br_plc_toolchain.backends.pvi import worker as pvi_worker


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


class ReconnectingFakeWorker(FakeWorker):
    calls = 0

    def call(self, operation: str, **arguments):
        ReconnectingFakeWorker.calls += 1
        if ReconnectingFakeWorker.calls == 1:
            raise RuntimeError("Pvi-Error 12059 : Communication timeout")
        return super().call(operation, **arguments)


class StuckFakeWorker(ReconnectingFakeWorker):
    def close(self) -> None:
        self.closed = True
        self.running = True


def test_variable_ref_validation_and_canonical_name() -> None:
    ref = VariableRef(name="bEnable", task="Main")
    ref.validate()
    assert ref.canonical == "Main:bEnable"
    with pytest.raises(ValueError, match="task is required"):
        VariableRef(name="bEnable").validate()


def test_large_pvi_list_grows_buffer_and_pages(monkeypatch) -> None:
    from pvi.pvi_objects import include

    names = [f"Point{i:05d}" for i in range(11000)]
    payload = "\t".join(f"{name} SC=g VT=i32" for name in names).encode("ascii")
    sizes = []

    def read(_handle, _link, _access, _arg, _arg_size, buffer, size):
        sizes.append(size)
        ctypes.memmove(buffer, payload, min(len(payload), size))
        return 0

    monkeypatch.setattr(include, "PviXRead", read)
    parent = type("Parent", (), {"_hPvi": 1, "_linkID": 2})()
    assert pvi_worker._read_variable_names(parent) == names
    assert sizes[0] == 65536 and sizes[-1] > len(payload)
    worker = PviWorker(PviTarget(name="plc", ip="127.0.0.1"))
    worker._cpu = parent
    first = worker._list_variables(scope="global", limit=5000)
    second = worker._list_variables(scope="global", limit=5000, offset=first["next_offset"])
    third = worker._list_variables(scope="global", limit=5000, offset=second["next_offset"])
    assert first["variables"] + second["variables"] + third["variables"] == names
    assert third["total_matches"] == 11000 and third["next_offset"] is None


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


def test_session_manager_reconnects_once_for_read_transport_failure() -> None:
    FakeWorker.created = 0
    ReconnectingFakeWorker.calls = 0
    target = PviTarget(name="plc", ip="192.168.50.233")
    manager = PviSessionManager(worker_factory=ReconnectingFakeWorker)  # type: ignore[arg-type]
    result = manager.call(target, "read", ref=VariableRef(name="bEnable", task="Main"))
    assert result["operation"] == "read"
    assert ReconnectingFakeWorker.calls == 2
    assert FakeWorker.created == 2


def test_session_manager_does_not_retry_write_transport_failure() -> None:
    ReconnectingFakeWorker.calls = 0
    target = PviTarget(name="plc", ip="192.168.50.233")
    manager = PviSessionManager(worker_factory=ReconnectingFakeWorker)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="12059"):
        manager.call(target, "write", ref=VariableRef(name="bEnable", task="Main"), value=True)
    assert ReconnectingFakeWorker.calls == 1


def test_session_manager_does_not_overlap_a_stuck_native_operation() -> None:
    FakeWorker.created = 0
    ReconnectingFakeWorker.calls = 0
    target = PviTarget(name="plc", ip="192.168.50.233")
    manager = PviSessionManager(worker_factory=StuckFakeWorker)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="PVI_WORKER_DIRTY"):
        manager.call(target, "read", ref=VariableRef(name="bEnable", task="Main"))
    assert FakeWorker.created == 1


def test_worker_health_does_not_query_native_properties_while_disconnected() -> None:
    worker = PviWorker(PviTarget(name="plc", ip="192.168.50.233"))
    worker._connection = object()  # type: ignore[attr-defined]
    worker._cpu = object()  # type: ignore[attr-defined]
    result = worker._health()  # type: ignore[attr-defined]
    assert result["ok"] is False
    assert result["cpu_status"] == {"ok": False, "error": "PVI CPU is not connected"}


def test_batch_timeout_scales_with_variable_link_budget() -> None:
    worker = PviWorker(
        PviTarget(
            name="plc",
            ip="192.168.50.233",
            request_timeout_s=1,
            manager_timeout_s=5,
            startup_wait_s=5,
            variable_link_wait_s=0.25,
        )
    )
    timeout = worker._operation_timeout(  # type: ignore[attr-defined]
        "read_many", {"refs": [VariableRef(name=f"v{i}", task="Main") for i in range(64)]}
    )
    assert timeout >= 34


def test_transport_error_classifier_handles_manager_timeout() -> None:
    assert is_pvi_transport_error(RuntimeError("Pvi-Error 12059 : Communication timeout"))
    assert is_pvi_transport_error(RuntimeError("Pvi-Error 12004 : Undefined object handle"))
    assert is_pvi_transport_error(RuntimeError("PVI_CONNECTION_UNAVAILABLE: manager did not connect"))
    assert not is_pvi_transport_error(RuntimeError("Pvi-Error 11033 : Object not found"))


def test_manager_disconnect_marks_link_hierarchy_dirty() -> None:
    worker = PviWorker(PviTarget(name="plc", ip="127.0.0.1"))
    worker._manager_connected = True  # type: ignore[attr-defined]

    worker._on_manager_connection(False)  # type: ignore[attr-defined]

    assert worker.dirty is True


def test_batch_timeout_for_128_variables_stays_bounded() -> None:
    worker = PviWorker(
        PviTarget(
            name="arsim",
            ip="127.0.0.1",
            request_timeout_s=15,
            manager_timeout_s=5,
            startup_wait_s=5,
            variable_link_wait_s=0.25,
        )
    )
    timeout = worker._operation_timeout(  # type: ignore[attr-defined]
        "read_many", {"refs": [VariableRef(name=f"v{i}", task="Main") for i in range(128)]}
    )
    assert 50.0 <= timeout <= 60.0


def test_parse_variable_ref_supports_global_and_task_aliases() -> None:
    assert parse_variable_ref("gAlive") == VariableRef(name="gAlive", scope="global")
    assert parse_variable_ref("::gAlive") == VariableRef(name="gAlive", scope="global")
    assert parse_variable_ref("global::gAlive") == VariableRef(name="gAlive", scope="global")
    assert parse_variable_ref("::AsGlobalPV:gAlive") == VariableRef(name="gAlive", scope="global")
    assert parse_variable_ref("Main:bEnable") == VariableRef(name="bEnable", scope="task", task="Main")
    assert parse_variable_ref("Main::bEnable") == VariableRef(name="bEnable", scope="task", task="Main")
    assert parse_variable_ref("::Main:bEnable") == VariableRef(name="bEnable", scope="task", task="Main")
    for invalid in ("", "   ", "::", "Main:", ":bEnable", "Main::", "Main:::bEnable"):
        with pytest.raises(ValueError):
            parse_variable_ref(invalid)
