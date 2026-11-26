from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from br_plc_toolchain import PviClient, PviTarget, RuntimePviService, VariableRef
from br_plc_toolchain.backends.pvi.worker import PviWorker


class FakeBatchManager:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {f"Main:v{i}": i for i in range(25)}
        self.values["Main:bSafetyStop"] = False
        self.values["Main:roFlag"] = 1
        self.values["Main:stCfg"] = {"a": 1}
        self.writable_map: dict[str, bool] = {"Main:roFlag": False}
        self.type_map: dict[str, str] = {
            "Main:bSafetyStop": "boolean",
            "Main:stCfg": "struct",
        }
        self.write_many_calls: list[list[tuple[str, Any]]] = []

    def call(self, target: PviTarget, operation: str, **arguments: Any) -> dict[str, Any]:
        if operation == "variable_info":
            ref: VariableRef = arguments["ref"]
            dtype = self.type_map.get(ref.canonical, "i32")
            return {
                "ok": True,
                "variable": ref.canonical,
                "data_type": dtype,
                "readable": True,
                "writable": self.writable_map.get(ref.canonical, True),
                "is_structure": dtype == "struct",
                "is_array": False,
            }
        if operation == "read":
            ref = arguments["ref"]
            return {
                "ok": True,
                "variable": ref.canonical,
                "value": self.values.get(ref.canonical),
                "data_type": self.type_map.get(ref.canonical, "i32"),
                "readable": True,
                "writable": self.writable_map.get(ref.canonical, True),
            }
        if operation == "write_many":
            pairs = [(ref.canonical, val) for ref, val in arguments["writes"]]
            self.write_many_calls.append(pairs)
            results = []
            for ref, val in arguments["writes"]:
                before = self.values.get(ref.canonical)
                self.values[ref.canonical] = val
                results.append(
                    {
                        "ok": True,
                        "target": target.name,
                        "variable": ref.canonical,
                        "before": before,
                        "requested": val,
                        "readback": val,
                        "verified": True,
                    }
                )
            return {"ok": True, "atomic": False, "results": results}
        raise AssertionError(f"Unexpected operation: {operation}")

    def close_all(self) -> None:
        pass


def test_batch_write_1_to_20_and_rejects_21(tmp_path: Path) -> None:
    mgr = FakeBatchManager()
    svc = RuntimePviService(manager=mgr, discovery_root=tmp_path)
    svc.register_ephemeral_target(
        ip="127.0.0.1",
        name="sim",
        declared_role="arsim",
        project_config={"pvi": {"enabled": True, "write_policy": "blacklist", "write_blacklist": ["*Safety*"]}},
    )

    writes_20 = [(VariableRef(name=f"v{i}", task="Main"), 100 + i) for i in range(20)]
    res = svc.write_many("sim", writes_20, execute=True)
    assert res["ok"] is True
    assert res["atomic"] is False
    assert res["count"] == 20
    assert len(mgr.write_many_calls) == 1
    assert mgr.values["Main:v0"] == 100
    assert mgr.values["Main:v19"] == 119

    writes_21 = [(VariableRef(name=f"v{i}", task="Main"), i) for i in range(21)]
    with pytest.raises(ValueError, match="at most 20"):
        svc.write_many("sim", writes_21, execute=True)


def test_batch_write_preflight_rejects_entire_batch_without_writing_earlier_items(
    tmp_path: Path,
) -> None:
    mgr = FakeBatchManager()
    svc = RuntimePviService(manager=mgr, discovery_root=tmp_path)
    svc.register_ephemeral_target(
        ip="127.0.0.1",
        name="sim",
        declared_role="arsim",
        project_config={"pvi": {"enabled": True, "write_policy": "blacklist", "write_blacklist": ["*Safety*"]}},
    )

    # Item 3 hits blacklist -> items 1 & 2 must NOT be written
    with pytest.raises(PermissionError, match="blacklist"):
        svc.write_many(
            "sim",
            [
                (VariableRef(name="v0", task="Main"), 999),
                (VariableRef(name="v1", task="Main"), 888),
                (VariableRef(name="bSafetyStop", task="Main"), True),
            ],
            execute=True,
        )
    assert mgr.write_many_calls == []
    assert mgr.values["Main:v0"] == 0
    assert mgr.values["Main:v1"] == 1

    # Item 3 is read-only -> items 1 & 2 must NOT be written
    with pytest.raises(PermissionError, match="not writable"):
        svc.write_many(
            "sim",
            [
                (VariableRef(name="v0", task="Main"), 999),
                (VariableRef(name="v1", task="Main"), 888),
                (VariableRef(name="roFlag", task="Main"), 2),
            ],
            execute=True,
        )
    assert mgr.write_many_calls == []
    assert mgr.values["Main:v0"] == 0

    # Item 2 is whole structure -> item 1 must NOT be written
    with pytest.raises(ValueError, match="Structure writes"):
        svc.write_many(
            "sim",
            [
                (VariableRef(name="v0", task="Main"), 999),
                (VariableRef(name="stCfg", task="Main"), {"a": 2}),
            ],
            execute=True,
        )
    assert mgr.write_many_calls == []
    assert mgr.values["Main:v0"] == 0


def test_batch_write_rejects_execute_false_and_production(tmp_path: Path) -> None:
    mgr = FakeBatchManager()
    svc = RuntimePviService(manager=mgr, discovery_root=tmp_path)
    svc.register_ephemeral_target(ip="127.0.0.1", name="sim", declared_role="arsim")
    with pytest.raises(PermissionError, match="execute=true"):
        svc.write_many("sim", [(VariableRef(name="v0", task="Main"), 5)], execute=False)
    assert mgr.write_many_calls == []

    svc.register_ephemeral_target(ip="192.168.1.10", name="prod", declared_role="production")
    with pytest.raises(PermissionError, match="Production writes are permanently denied"):
        svc.write_many("prod", [(VariableRef(name="v0", task="Main"), 5)], execute=True)
    assert mgr.write_many_calls == []


def test_worker_write_many_pumps_once_per_batch() -> None:
    target = PviTarget(name="sim", ip="127.0.0.1", role="arsim")
    w = PviWorker(target)

    class FakeVar:
        def __init__(self, name: str, val: int) -> None:
            self.name = name
            self.dataType = "i32"
            self.readable = True
            self.writable = True
            self._val = val

        @property
        def value(self) -> int:
            return self._val

        @value.setter
        def value(self, v: int) -> None:
            self._val = v

    pump_calls: list[float] = []
    w._pump_for = lambda seconds: pump_calls.append(seconds)  # type: ignore[method-assign]

    refs = [VariableRef(name=f"v{i}", task="Main") for i in range(5)]
    for i, ref in enumerate(refs):
        w._variables[ref.key] = FakeVar(ref.canonical, i)

    res = w._write_many([(ref, 50 + idx) for idx, ref in enumerate(refs)], readback_wait_ms=40)
    assert res["ok"] is True
    assert res["atomic"] is False
    assert len(pump_calls) == 1
    assert pump_calls[0] == pytest.approx(0.04)
    assert all(item["verified"] is True for item in res["results"])


def test_mcp_plc_write_pvi_batch_and_pvi_client_consistency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tools" / "mcp_server"))
    import server
    import toolchain

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Demo.apj").write_text("<Project/>", encoding="utf-8")
    (proj / "br-auto-dev.json").write_text(
        json.dumps(
            {
                "project_path": "Demo.apj",
                "config": "Config1",
                "toolchain": "as6_default",
                "target": "arsim",
                "targets": {"arsim": {"ip": "127.0.0.1", "role": "arsim"}},
                "pvi": {
                    "enabled": True,
                    "write_policy": "blacklist",
                    "write_blacklist": ["*Safety*"],
                },
            }
        ),
        encoding="utf-8",
    )

    mgr = FakeBatchManager()
    svc = RuntimePviService(manager=mgr, discovery_root=tmp_path / "disc")
    monkeypatch.setattr(toolchain, "_RUNTIME_SERVICE", svc)
    monkeypatch.setattr(server, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(server, "LOCK_DIR", tmp_path / "locks")

    # 1. MCP batch write succeeds and writes audit
    ok_resp = server.handle_tools_call(
        {
            "name": "plc_write_pvi_batch",
            "arguments": {
                "project_path": str(proj),
                "target": "arsim",
                "writes": [
                    {"variable": "Main:v0", "value": 42},
                    {"variable": "Main:v1", "value": 43},
                ],
                "execute": True,
            },
        }
    )
    assert ok_resp["isError"] is False
    payload = ok_resp["structuredContent"]
    assert payload["ok"] is True
    assert payload["atomic"] is False
    assert payload["count"] == 2
    assert payload.get("audit")
    assert mgr.values["Main:v0"] == 42 and mgr.values["Main:v1"] == 43

    # 2. MCP batch write with blacklisted item rejects entire batch
    denied_resp = server.handle_tools_call(
        {
            "name": "plc_write_pvi_batch",
            "arguments": {
                "project_path": str(proj),
                "target": "arsim",
                "writes": [
                    {"variable": "Main:v0", "value": 1000},
                    {"variable": "Main:bSafetyStop", "value": True},
                ],
                "execute": True,
            },
        }
    )
    assert denied_resp["isError"] is True
    assert denied_resp["structuredContent"]["error_code"] == "POLICY_DENIED"
    assert mgr.values["Main:v0"] == 42  # Unchanged!

    # 3. PviClient.write_many uses the same RuntimePviService.write_many contract
    with PviClient.from_project(proj, service=svc) as plc:
        client_res = plc.write_many({"Main:v0": 77, "Main:v1": 78}, execute=True)
        assert client_res["ok"] is True
        assert client_res["atomic"] is False
        assert mgr.values["Main:v0"] == 77 and mgr.values["Main:v1"] == 78
