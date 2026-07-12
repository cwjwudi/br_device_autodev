from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

import server  # noqa: E402
import toolchain  # noqa: E402


class FakeRuntimeService:
    def __init__(self):
        self.registered = False

    def register_ephemeral_target(self, **kwargs):
        self.registered = True
        return {"target": {"name": kwargs.get("name") or "discovered"}}

    def discover_target(self, target):
        return {"ok": True, "target_name": target, "tasks": ["Main"]}

    def health(self, target):
        return {"ok": True, "target": target}

    def list_tasks(self, target):
        return {"ok": True, "target": target, "tasks": ["Main"]}

    def list_variables(self, target, **kwargs):
        return {"ok": True, "target": target, "variables": ["bEnable"], **kwargs}

    def variable_info(self, target, ref):
        return {"ok": True, "target": target, "variable": ref.canonical, "writable": True}

    def read(self, target, ref):
        return {"ok": True, "target": target, "variable": ref.canonical, "value": False}

    def open_test_session(self, target, **kwargs):
        return {"ok": True, "session": {"session_id": "test-session", "target": target}}

    def close_test_session(self, session_id):
        return {"ok": True, "session_id": session_id}

    def write(self, target, ref, value, **kwargs):
        return {"ok": True, "target": target, "variable": ref.canonical, "readback": value, **kwargs}

    def close(self):
        pass


def call(name: str, arguments: dict):
    return server.handle_tools_call({"name": name, "arguments": arguments})


def test_runtime_discovery_bootstraps_without_policy_file() -> None:
    fake = FakeRuntimeService()
    with patch.object(toolchain, "_RUNTIME_SERVICE", fake):
        result = call(
            "plc_discover_runtime_target",
            {"ip": "192.168.50.233", "target": "plc", "declared_role": "dedicated_test_plc"},
        )
    assert result["isError"] is False
    assert result["structuredContent"]["tasks"] == ["Main"]
    assert fake.registered


def test_runtime_variable_tools_use_online_reference() -> None:
    fake = FakeRuntimeService()
    with patch.object(toolchain, "_RUNTIME_SERVICE", fake):
        result = call(
            "plc_read_runtime_variable",
            {"target": "plc", "scope": "task", "task": "Main", "name": "bEnable"},
        )
    assert result["isError"] is False
    assert result["structuredContent"]["variable"] == "Main:bEnable"


def test_runtime_write_requires_explicit_execute_at_schema_layer() -> None:
    result = call(
        "plc_write_runtime_variable",
        {"target": "plc", "scope": "task", "task": "Main", "name": "bEnable", "value": True},
    )
    assert result["isError"] is True
    assert result["structuredContent"]["error"] == "Tool argument validation failed."


def test_runtime_write_and_test_session_are_audited_target_changes(tmp_path) -> None:
    fake = FakeRuntimeService()
    with (
        patch.object(toolchain, "_RUNTIME_SERVICE", fake),
        patch.object(server, "AUDIT_DIR", tmp_path / "audit"),
        patch.object(server, "LOCK_DIR", tmp_path / "locks"),
    ):
        opened = call(
            "plc_open_test_session", {"target": "plc", "execute": True, "ttl_minutes": 5}
        )
        written = call(
            "plc_write_runtime_variable",
            {
                "target": "plc",
                "scope": "task",
                "task": "Main",
                "name": "bEnable",
                "value": True,
                "execute": True,
                "session_id": "test-session",
            },
        )
    assert opened["isError"] is False and opened["structuredContent"]["audit"]
    assert written["isError"] is False and written["structuredContent"]["audit"]

