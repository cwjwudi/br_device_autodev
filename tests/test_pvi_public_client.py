from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import br_plc_toolchain
from br_plc_toolchain import (
    PviClient,
    PviSessionManager,
    PviTarget,
    PviTraceError,
    RuntimePviService,
    TraceManager,
    VariableRef,
    parse_variable_ref,
)


class FakeBackendManager:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {"Main:eState": 1, "Main:bStart": False, "gAlive": True}
        self.closed = False
        self.invalidated = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.poll_step = 0

    def call(self, target: PviTarget, operation: str, **arguments: Any) -> dict[str, Any]:
        self.calls.append((operation, arguments))
        if operation == "health":
            return {
                "ok": True,
                "generation": 1,
                "cpu_type": {"ok": True, "value": "AR000"},
                "order_number": {"ok": True, "value": "AR000"},
                "ar_version": {"ok": True, "value": "6.0"},
                "cpu_status": {"ok": True, "value": {"RunState": "RUN"}},
            }
        if operation == "list_tasks":
            return {"ok": True, "tasks": ["Main", "Safety"], "count": 2}
        if operation == "list_variables":
            return {
                "ok": True,
                "scope": arguments.get("scope"),
                "task": arguments.get("task"),
                "variables": ["eState", "bStart"],
                "total_matches": 2,
            }
        if operation == "variable_info":
            ref: VariableRef = arguments["ref"]
            return {
                "ok": True,
                "variable": ref.canonical,
                "writable": True,
                "readable": True,
                "data_type": "boolean",
            }
        if operation == "read":
            ref = arguments["ref"]
            return {
                "ok": True,
                "variable": ref.canonical,
                "value": self.values.get(ref.canonical, 0),
                "writable": True,
                "readable": True,
                "data_type": "u32",
            }
        if operation == "read_many":
            if self.values.get("Main:bStart") is True:
                self.poll_step += 1
                if self.poll_step >= 3:
                    self.values["Main:eState"] = 3
            results = [
                {
                    "ok": True,
                    "variable": ref.canonical,
                    "value": self.values.get(ref.canonical, index),
                    "writable": True,
                    "readable": True,
                    "data_type": "u32",
                }
                for index, ref in enumerate(arguments["refs"])
            ]
            return {"ok": True, "results": results}
        if operation == "write":
            ref = arguments["ref"]
            value = arguments["value"]
            self.values[ref.canonical] = value
            return {
                "ok": True,
                "variable": ref.canonical,
                "requested": value,
                "readback": value,
                "verified": True,
            }
        if operation == "write_many":
            results = []
            for ref, value in arguments["writes"]:
                before = self.values.get(ref.canonical)
                self.values[ref.canonical] = value
                results.append(
                    {
                        "ok": True,
                        "variable": ref.canonical,
                        "before": before,
                        "requested": value,
                        "readback": value,
                        "verified": True,
                    }
                )
            return {"ok": True, "atomic": False, "results": results}
        raise AssertionError(f"Unexpected operation: {operation}")

    def worker_state(self, target: PviTarget) -> dict[str, Any]:
        return {"active": True, "dirty": False}

    def invalidate(self, target: PviTarget) -> bool:
        self.invalidated += 1
        return True

    def close_all(self) -> None:
        self.closed = True


def _create_project(tmp_path: Path, *, role: str = "arsim", ip: str = "127.0.0.4", pvi: dict[str, Any] | None = None) -> Path:
    apj = tmp_path / "Demo.apj"
    apj.write_text("<Project/>", encoding="utf-8")
    config = {
        "project_path": "Demo.apj",
        "config": "SecPackTest",
        "toolchain": "as6_default",
        "target": "sim",
        "targets": {
            "sim": {"ip": ip, "role": role, "allow_auto_download": role == "arsim"},
        },
        "pvi": pvi
        if pvi is not None
        else {
            "enabled": True,
            "write_policy": "blacklist",
            "write_blacklist": ["*Safety*", "gIOCtrl*", "IOModule:*"],
        },
    }
    (tmp_path / "br-auto-dev.json").write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


def test_top_level_package_exports_public_sdk_symbols() -> None:
    assert PviClient is br_plc_toolchain.PviClient
    assert RuntimePviService is br_plc_toolchain.RuntimePviService
    assert TraceManager is br_plc_toolchain.TraceManager
    assert PviTraceError is br_plc_toolchain.PviTraceError
    assert PviSessionManager is br_plc_toolchain.PviSessionManager
    assert PviTarget is br_plc_toolchain.PviTarget
    assert VariableRef is br_plc_toolchain.VariableRef
    assert parse_variable_ref is br_plc_toolchain.parse_variable_ref


def test_pvi_client_from_project_context_manager_and_lifecycle(tmp_path) -> None:
    project_dir = _create_project(tmp_path)
    manager = FakeBackendManager()
    service = RuntimePviService(manager=manager, discovery_root=tmp_path / "discovery")

    with PviClient.from_project(
        project_dir,
        trace_root=tmp_path / "traces",
        service=service,
    ) as plc:
        assert plc.discover()["ok"] is True
        assert plc.discover(refresh=True)["ok"] is True
        assert manager.invalidated == 1
        assert plc.health()["ok"] is True
        assert plc.list_tasks()["tasks"] == ["Main", "Safety"]
        assert plc.list_variables(task="Main")["variables"] == ["eState", "bStart"]
        assert plc.variable_info("Main::bStart")["variable"] == "Main:bStart"

        assert plc.read("::gAlive")["value"] is True
        assert plc.read("global::gAlive")["value"] is True
        assert plc.read("Main::eState")["value"] == 1

        # read_many up to 128, and read_chunked > 128
        vars_128 = [f"Main:v{i}" for i in range(128)]
        batch = plc.read_many(vars_128)
        assert batch["ok"] is True and batch["count"] == 128
        with pytest.raises(ValueError, match="at most 128"):
            plc.read_many([f"Main:v{i}" for i in range(129)])

        chunked = plc.read_many([f"Main:v{i}" for i in range(260)], chunked=True)
        assert chunked["ok"] is True
        assert chunked["count"] == 260
        assert chunked["chunks"] == 3
        assert len(chunked["values"]) == 260

        # write and write_many
        assert plc.write("Main::bStart", True)["ok"] is True
        wrote = plc.write_many([("Main:bStart", False), ("Main::eState", 2)])
        assert wrote["ok"] is True and wrote["count"] == 2
        wrote_dict = plc.write_many({"Main:bStart": True, "gAlive": False})
        assert wrote_dict["ok"] is True and wrote_dict["count"] == 2

        # wait_until
        waited = plc.wait_until("Main:eState", lambda v: v == 3, timeout_s=2.0, interval_s=0.01)
        assert waited["ok"] is True and waited["value"] == 3

        # trace workflow: start -> wait_trace -> read_trace
        trace = plc.start_trace(["Main:eState", "gAlive"], duration_seconds=1, interval_ms=20)
        assert trace["trace_file"].endswith(f"{trace['trace_id']}.jsonl")
        final = plc.wait_trace(trace["trace_id"], poll_interval_s=0.02, timeout_s=5.0)
        assert final["state"] == "completed"
        assert Path(final["trace_file"]).is_file()
        data = plc.read_trace(trace["trace_id"], max_samples=50)
        assert data["ok"] is True and data["sample_count"] >= 1

    # Context exit closes owned traces; owned service closes when service=None
    with PviClient.from_target(
        ip="127.0.0.1",
        name="direct",
        trace_root=tmp_path / "traces2",
    ) as direct:
        assert direct.target_name == "direct"
        direct.service.manager = manager  # type: ignore[assignment]
        trace2 = direct.start_trace(["gAlive"], duration_seconds=10, interval_ms=50)
    assert manager.closed is True
    assert Path(trace2["trace_file"]).is_file()


def test_pvi_client_security_policies_cannot_be_bypassed(tmp_path) -> None:
    project_dir = _create_project(tmp_path)
    manager = FakeBackendManager()
    service = RuntimePviService(manager=manager, discovery_root=tmp_path / "discovery")

    with PviClient.from_project(project_dir, trace_root=tmp_path / "traces", service=service) as plc:
        # Blacklist enforced on write and write_many
        with pytest.raises(PermissionError, match="blacklist"):
            plc.write("Main:bSafetyStop", True, execute=True)
        with pytest.raises(PermissionError, match="blacklist"):
            plc.write("gIOCtrl.Out1", True, execute=True)
        with pytest.raises(PermissionError, match="blacklist"):
            plc.write("IOModule:Do01", True, execute=True)
        with pytest.raises(PermissionError, match="blacklist"):
            plc.write_many([("Main:bStart", True), ("Main:bSafetyStop", True)], execute=True)
        partial = plc.write_many(
            [("Main:bStart", True), ("Main:bSafetyStop", True)],
            execute=True,
            stop_on_error=False,
        )
        assert partial["ok"] is False
        assert partial["results"][0]["ok"] is True
        assert partial["results"][1]["ok"] is False
        assert "blacklist" in partial["results"][1]["error"]

        # execute=False denied
        with pytest.raises(PermissionError, match="execute=true"):
            plc.write("Main:bStart", True, execute=False)

    # production target rejects writes even with execute=True
    prod_dir = tmp_path / "prod"
    prod_dir.mkdir()
    _create_project(prod_dir, role="production", ip="192.168.10.20", pvi={"enabled": True, "write_policy": "blacklist", "write_blacklist": []})
    prod_service = RuntimePviService(manager=FakeBackendManager(), discovery_root=tmp_path / "disc_prod")
    with PviClient.from_project(prod_dir, trace_root=tmp_path / "traces_prod", service=prod_service) as prod:
        assert prod.read("Main:eState")["ok"] is True
        with pytest.raises(PermissionError, match="Production writes are permanently denied"):
            prod.write("Main:bStart", True, execute=True)
        with pytest.raises(PermissionError, match="Production writes are permanently denied"):
            prod.write_many([("Main:bStart", True)], execute=True)

    # pvi.enabled=False blocks read, read_many, and write via RuntimePolicy
    disabled_dir = tmp_path / "disabled"
    disabled_dir.mkdir()
    _create_project(disabled_dir, pvi={"enabled": False, "write_policy": "blacklist", "write_blacklist": []})
    disabled_service = RuntimePviService(manager=FakeBackendManager(), discovery_root=tmp_path / "disc_dis")
    with PviClient.from_project(disabled_dir, trace_root=tmp_path / "traces_dis", service=disabled_service) as dis:
        read_res = dis.read("Main:eState")
        assert read_res["ok"] is False
        assert "PVI is disabled" in read_res["error"]
        batch_res = dis.read_many(["Main:eState", "gAlive"])
        assert batch_res["ok"] is False
        assert "PVI is disabled" in batch_res["errors"]["Main:eState"]
        with pytest.raises(PermissionError, match="PVI is disabled"):
            dis.write("Main:bStart", True, execute=True)


def test_pvi_client_wait_until_times_out_clearly(tmp_path) -> None:
    project_dir = _create_project(tmp_path)
    manager = FakeBackendManager()
    service = RuntimePviService(manager=manager, discovery_root=tmp_path / "discovery")

    with PviClient.from_project(project_dir, trace_root=tmp_path / "traces", service=service) as plc:
        with pytest.raises(TimeoutError, match="wait_until timed out"):
            plc.wait_until("Main:eState", lambda v: v == 999, timeout_s=0.05, interval_s=0.01)
