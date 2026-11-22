from __future__ import annotations

import sys
import json
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

import server  # noqa: E402
import toolchain  # noqa: E402


class FakeRuntimeService:
    def __init__(self):
        self.registered = False
        self.registration_kwargs = None

    def register_ephemeral_target(self, **kwargs):
        self.registered = True
        self.registration_kwargs = kwargs
        return {"target": {"name": kwargs.get("name") or "discovered"}}

    def discover_target(self, target):
        return {"ok": True, "target_name": target, "tasks": ["Main"]}

    def health(self, target):
        return {"ok": True, "target": target}

    def save_target(self, target, **kwargs):
        return {"ok": True, "target": target, "config_path": "config/local/plc.json", **kwargs}

    def list_tasks(self, target):
        return {"ok": True, "target": target, "tasks": ["Main"]}

    def list_variables(self, target, **kwargs):
        return {"ok": True, "target": target, "variables": ["bEnable"], **kwargs}

    def variable_info(self, target, ref):
        return {"ok": True, "target": target, "variable": ref.canonical, "writable": True}

    def read(self, target, ref):
        return {"ok": True, "name": ref.canonical, "value": False, "type": "boolean"}

    def read_many(self, target, refs):
        return {
            "ok": True,
            "target": target,
            "count": len(refs),
            "values": {
                ref.canonical: {"value": False, "type": "boolean"} for ref in refs
            },
            "errors": {},
        }

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


def call_internal(name: str, arguments: dict):
    with patch.object(server, "DISABLED_TOOLS", frozenset()):
        return call(name, arguments)


def test_mcp_lists_and_resolves_global_toolchains() -> None:
    listed = call_internal("plc_list_toolchains", {})
    assert listed["isError"] is False
    ids = {item["id"] for item in listed["structuredContent"]["data"]["toolchains"]}
    assert {"as4_default", "as6_default"}.issubset(ids)
    selected = call_internal("plc_get_toolchain", {"toolchain": "as6_default"})
    assert selected["structuredContent"]["data"]["toolchain"]["family"] == "AS6"


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
    assert fake.registration_kwargs["pvi_dll_path"].endswith("PVI6\\Bin")


def test_runtime_discovery_rejects_removed_named_environment() -> None:
    fake = FakeRuntimeService()
    with patch.object(toolchain, "_RUNTIME_SERVICE", fake):
        result = call("plc_discover_runtime_target", {"environment": "local_arsim"})
    assert result["isError"] is True
    assert not fake.registered


def test_runtime_variable_tools_use_online_reference() -> None:
    fake = FakeRuntimeService()
    with patch.object(toolchain, "_RUNTIME_SERVICE", fake):
        result = call(
            "plc_read_runtime_variable",
            {"target": "plc", "scope": "task", "task": "Main", "name": "bEnable"},
    )
    assert result["isError"] is False
    assert result["structuredContent"] == {
        "ok": True,
        "name": "Main:bEnable",
        "value": False,
        "type": "boolean",
    }


def test_runtime_batch_read_returns_compact_map() -> None:
    fake = FakeRuntimeService()
    with patch.object(toolchain, "_RUNTIME_SERVICE", fake):
        result = call_internal(
            "plc_read_pvi_batch",
            {
                "target": "plc",
                "variables": ["Main:bEnable", "Main:bEnable", "gstAtStatus.stApplication.bAlive"],
            },
        )
    assert result["isError"] is False
    data = result["structuredContent"]
    assert data["count"] == 2
    assert set(data["values"]) == {"Main:bEnable", "gstAtStatus.stApplication.bAlive"}
    assert data["errors"] == {}


def test_legacy_batch_uses_explicit_target_reader_and_keeps_errors() -> None:
    payload = {
        "command": "ReadPvi",
        "ok": False,
        "variables": [
            {"name": "DataSQLBat:bSimEnable", "value": True, "type": "boolean"},
            {"name": "DataSQLBat:Missing", "error": "Pvi-Error 11033"},
        ],
    }
    completed = type(
        "Completed",
        (),
        {"stdout": json.dumps(payload), "stderr": "", "returncode": 1},
    )()
    with patch.object(toolchain.subprocess, "run", return_value=completed) as run:
        result = call_internal(
            "plc_read_pvi_batch",
            {
                "backend": "legacy",
                "ip": "192.168.50.233",
                "toolchain": "as4_default",
                "variables": ["DataSQLBat:bSimEnable", "DataSQLBat:Missing"],
            },
        )
    data = result["structuredContent"]
    assert data["values"]["DataSQLBat:bSimEnable"] == {"value": True, "type": "boolean"}
    assert data["errors"] == {"DataSQLBat:Missing": "Pvi-Error 11033"}
    command = run.call_args.args[0]
    assert command.count("--variable") == 2


def test_runtime_write_requires_explicit_execute_at_schema_layer() -> None:
    result = call(
        "plc_write_runtime_variable",
        {"target": "plc", "scope": "task", "task": "Main", "name": "bEnable", "value": True},
    )
    assert result["isError"] is True
    assert result["structuredContent"]["error"] == "Tool argument validation failed."


def test_save_runtime_target_requires_confirmation_and_is_audited(tmp_path) -> None:
    rejected = call_internal("plc_save_runtime_target", {"target": "plc", "filename": "plc.json"})
    assert rejected["isError"] is True
    fake = FakeRuntimeService()
    with (
        patch.object(toolchain, "_RUNTIME_SERVICE", fake),
        patch.object(server, "AUDIT_DIR", tmp_path / "audit"),
        patch.object(server, "LOCK_DIR", tmp_path / "locks"),
    ):
        saved = call_internal(
            "plc_save_runtime_target",
            {"target": "plc", "filename": "plc.json", "execute": True},
        )
    assert saved["isError"] is False
    assert saved["structuredContent"]["audit"]


def test_runtime_write_and_test_session_are_audited_target_changes(tmp_path) -> None:
    fake = FakeRuntimeService()
    with (
        patch.object(toolchain, "_RUNTIME_SERVICE", fake),
        patch.object(server, "AUDIT_DIR", tmp_path / "audit"),
        patch.object(server, "LOCK_DIR", tmp_path / "locks"),
    ):
        opened = call_internal(
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


def test_newly_enabled_runtime_tools_are_visible_and_enforce_128_20ms_contract(tmp_path) -> None:
    visible_names = {item["name"] for item in server.visible_definitions(server.DISABLED_TOOLS)}
    expected_enabled = {
        "plc_read_pvi_batch",
        "plc_start_pvi_trace",
        "plc_get_pvi_trace_status",
        "plc_read_pvi_trace",
        "plc_stop_pvi_trace",
        "plc_runtime_health",
        "plc_get_runtime_variable_info",
    }
    assert expected_enabled.issubset(visible_names)

    by_name = server.TOOL_DEFINITIONS_BY_NAME
    assert by_name["plc_read_pvi_batch"]["inputSchema"]["properties"]["variables"]["maxItems"] == 128
    trace_props = by_name["plc_start_pvi_trace"]["inputSchema"]["properties"]
    assert trace_props["variables"]["maxItems"] == 128
    assert trace_props["interval_ms"]["minimum"] == 20
    assert by_name["plc_read_pvi_trace"]["inputSchema"]["properties"]["max_samples"]["maximum"] == 30000

    fake = FakeRuntimeService()
    with (
        patch.object(toolchain, "_RUNTIME_SERVICE", fake),
        patch.object(toolchain, "_TRACE_MANAGER", None),
    ):
        batch_ok = call(
            "plc_read_pvi_batch",
            {"target": "plc", "variables": [f"Main:v{i}" for i in range(128)]},
        )
        assert batch_ok["isError"] is False
        assert batch_ok["structuredContent"]["count"] == 128

        batch_too_many = call(
            "plc_read_pvi_batch",
            {"target": "plc", "variables": [f"Main:v{i}" for i in range(129)]},
        )
        assert batch_too_many["isError"] is True

        trace_too_fast = call(
            "plc_start_pvi_trace",
            {"target": "plc", "variables": ["Main:v0"], "interval_ms": 19},
        )
        assert trace_too_fast["isError"] is True

        trace_too_many = call(
            "plc_start_pvi_trace",
            {"target": "plc", "variables": [f"Main:v{i}" for i in range(129)], "interval_ms": 20},
        )
        assert trace_too_many["isError"] is True

        from br_plc_toolchain.services.pvi_trace import TraceManager

        trace_mgr = TraceManager(fake, root=tmp_path / "traces")
        with patch.object(toolchain, "_TRACE_MANAGER", trace_mgr):
            try:
                started = call(
                    "plc_start_pvi_trace",
                    {
                        "target": "plc",
                        "variables": [f"Main:v{i}" for i in range(128)],
                        "duration_seconds": 1,
                        "interval_ms": 20,
                    },
                )
                assert started["isError"] is False
                trace_id = started["structuredContent"]["trace_id"]
                stopped = call("plc_stop_pvi_trace", {"target": "plc", "trace_id": trace_id})
                assert stopped["isError"] is False
                assert stopped["structuredContent"]["trace_file"]
                read = call("plc_read_pvi_trace", {"target": "plc", "trace_id": trace_id})
                assert read["isError"] is False
                assert len(read["structuredContent"]["variables"]) == 128
            finally:
                trace_mgr.close()
