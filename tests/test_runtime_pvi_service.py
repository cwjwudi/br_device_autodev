from __future__ import annotations

from typing import Any

import pytest

from br_plc_toolchain.backends.pvi.models import VariableRef
from br_plc_toolchain.services.runtime_pvi import RuntimePviService
from br_plc_toolchain.config import loader


class FakeManager:
    def __init__(self):
        self.value = False
        self.generation = 1
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, target, operation: str, **arguments):
        self.calls.append((operation, arguments))
        if operation == "health":
            return {
                "ok": True,
                "generation": self.generation,
                "cpu_version": {"ok": True, "value": "J4.93"},
                "cpu_type": {"ok": True, "value": "X20CP1586"},
                "order_number": {"ok": True, "value": "X20CP1586"},
                "ar_version": {"ok": True, "value": "J4.93"},
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
        if operation == "read_many":
            results = []
            for ref in arguments["refs"]:
                if ref.name == "Unknown":
                    results.append({"ok": False, "variable": ref.canonical, "error": "PVI variable not found"})
                else:
                    results.append(
                        {
                            "ok": True,
                            "variable": ref.canonical,
                            "value": self.value,
                            "writable": True,
                            "readable": True,
                            "data_type": "boolean",
                        }
                    )
            return {"ok": all(item["ok"] for item in results), "results": results}
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


def test_changed_value_does_not_require_target_bound_session(tmp_path) -> None:
    service = build_service(tmp_path)
    service.register_ephemeral_target(ip="192.168.50.233", name="plc", declared_role="test")
    ref = VariableRef(name="bEnable", task="Main")
    result = service.write("plc", ref, True, execute=True)
    assert result["ok"]
    assert result["access_decision"]["requires_session"] is False
    opened = service.open_test_session("plc", execute=True)
    session_id = opened["session"]["session_id"]
    result = service.write("plc", ref, True, execute=True, session_id=session_id)
    assert result["verified"] is True


def test_unknown_target_can_discover_and_read_but_not_write(tmp_path) -> None:
    service = build_service(tmp_path)
    service.register_ephemeral_target(ip="192.168.50.10", name="unknown")
    ref = VariableRef(name="bEnable", task="Main")
    assert service.read("unknown", ref) == {
        "ok": True,
        "name": "Main:bEnable",
        "value": False,
        "type": "boolean",
    }
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


def test_trusted_write_ignores_legacy_session_identity_change(tmp_path) -> None:
    manager = FakeManager()
    service = RuntimePviService(manager=manager, discovery_root=tmp_path)
    service.register_ephemeral_target(ip="192.168.50.233", name="plc", declared_role="test")
    opened = service.open_test_session("plc", execute=True)
    manager.generation = 2
    result = service.write(
        "plc",
        VariableRef(name="bEnable", task="Main"),
        True,
        execute=True,
        session_id=opened["session"]["session_id"],
    )
    assert result["ok"]


def test_read_many_deduplicates_and_submits_one_worker_operation(tmp_path) -> None:
    service = build_service(tmp_path)
    service.register_ephemeral_target(ip="192.168.50.233", name="plc", declared_role="test")
    manager = service.manager
    result = service.read_many(
        "plc",
        [
            VariableRef(name="bEnable", task="Main"),
            VariableRef(name="bEnable", task="Main"),
            VariableRef(name="bOther", task="Main"),
            VariableRef(name="Unknown", task="Main"),
        ],
    )
    assert result["ok"] is False
    assert result["count"] == 3
    assert set(result["values"]) == {"Main:bEnable", "Main:bOther"}
    assert result["errors"] == {"Main:Unknown": "PVI variable not found"}
    calls = [item for item in manager.calls if item[0] == "read_many"]
    assert len(calls) == 1
    assert [ref.canonical for ref in calls[0][1]["refs"]] == ["Main:bEnable", "Main:bOther", "Main:Unknown"]


def test_trusted_write_ignores_incomplete_legacy_session_identity(tmp_path) -> None:
    manager = FakeManager()
    service = RuntimePviService(manager=manager, discovery_root=tmp_path)
    service.register_ephemeral_target(ip="192.168.50.233", name="plc", declared_role="test")
    opened = service.open_test_session("plc", execute=True)
    original_call = manager.call

    def incomplete_health(target, operation: str, **arguments):
        result = original_call(target, operation, **arguments)
        if operation == "health":
            result["order_number"] = {"ok": False, "error": "unavailable"}
        return result

    manager.call = incomplete_health  # type: ignore[method-assign]
    result = service.write(
        "plc",
        VariableRef(name="bEnable", task="Main"),
        True,
        execute=True,
        session_id=opened["session"]["session_id"],
    )
    assert result["ok"]


def test_runtime_target_name_cannot_escape_discovery_root(tmp_path) -> None:
    service = build_service(tmp_path)
    with pytest.raises(ValueError, match="INVALID_TARGET_NAME"):
        service.register_ephemeral_target(
            ip="192.168.50.233", name="../escaped", declared_role="test"
        )
