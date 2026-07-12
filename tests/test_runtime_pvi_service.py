from __future__ import annotations

from typing import Any

import pytest

from br_plc_toolchain.backends.pvi.models import VariableRef
from br_plc_toolchain.services.runtime_pvi import RuntimePviService
from br_plc_toolchain.config import loader


class FakeManager:
    def __init__(self):
        self.value = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, target, operation: str, **arguments):
        self.calls.append((operation, arguments))
        if operation == "health":
            return {
                "ok": True,
                "generation": 1,
                "cpu_version": {"ok": True, "value": "J4.93"},
                "cpu_status": {"ok": True, "value": {"RunState": "RUN"}},
            }
        if operation == "list_tasks":
            return {"ok": True, "tasks": ["Main"], "count": 1}
        if operation == "list_variables":
            return {"ok": True, "variables": ["bEnable"], "total_matches": 1}
        if operation == "variable_info":
            return {
                "ok": True,
                "variable": arguments["ref"].canonical,
                "writable": True,
                "readable": True,
                "data_type": "boolean",
            }
        if operation == "read":
            return {
                "ok": True,
                "variable": arguments["ref"].canonical,
                "value": self.value,
                "writable": True,
                "readable": True,
                "data_type": "boolean",
            }
        if operation == "write":
            self.value = arguments["value"]
            return {"ok": True, "requested": self.value, "readback": self.value, "verified": True}
        raise AssertionError(operation)

    def close_all(self):
        pass


def build_service(tmp_path):
    return RuntimePviService(manager=FakeManager(), discovery_root=tmp_path)


def test_service_discovers_without_source_program(tmp_path) -> None:
    service = build_service(tmp_path)
    service.register_ephemeral_target(ip="192.168.50.233", name="plc", declared_role="test")
    result = service.discover_target("plc")
    assert result["ok"]
    assert result["tasks"] == ["Main"]
    assert (tmp_path / "plc.json").exists()


def test_same_value_write_does_not_require_session(tmp_path) -> None:
    service = build_service(tmp_path)
    service.register_ephemeral_target(ip="192.168.50.233", name="plc", declared_role="test")
    result = service.write(
        "plc", VariableRef(name="bEnable", task="Main"), False, execute=True
    )
    assert result["ok"]
    assert result["access_decision"]["operation"] == "same_value_write"


def test_changed_value_requires_target_bound_session(tmp_path) -> None:
    service = build_service(tmp_path)
    service.register_ephemeral_target(ip="192.168.50.233", name="plc", declared_role="test")
    ref = VariableRef(name="bEnable", task="Main")
    with pytest.raises(PermissionError, match="test session"):
        service.write("plc", ref, True, execute=True)
    opened = service.open_test_session("plc", execute=True)
    session_id = opened["session"]["session_id"]
    result = service.write("plc", ref, True, execute=True, session_id=session_id)
    assert result["verified"] is True


def test_unknown_target_can_discover_and_read_but_not_write(tmp_path) -> None:
    service = build_service(tmp_path)
    service.register_ephemeral_target(ip="192.168.50.10", name="unknown")
    ref = VariableRef(name="bEnable", task="Main")
    assert service.read("unknown", ref)["ok"]
    with pytest.raises(PermissionError, match="same-value"):
        service.write("unknown", ref, False, execute=True)


def test_save_target_is_explicit_and_uses_ignored_local_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(loader, "LOCAL_ROOT", tmp_path / "local")
    service = build_service(tmp_path / "discovery")
    service.register_ephemeral_target(ip="192.168.50.233", name="plc", declared_role="test")
    with pytest.raises(PermissionError, match="execute=true"):
        service.save_target("plc", filename="office-plc.json", execute=False)
    result = service.save_target("plc", filename="office-plc.json", execute=True)
    assert result["ok"] is True
    assert (tmp_path / "local" / "office-plc.json").is_file()
