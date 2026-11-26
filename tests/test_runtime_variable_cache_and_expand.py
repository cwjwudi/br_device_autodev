from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace
from typing import Any

import pytest

from br_plc_toolchain import PviClient, PviTarget, RuntimePviService, VariableRef
from br_plc_toolchain.backends.pvi import worker as worker_mod
from br_plc_toolchain.backends.pvi.worker import PviWorker


def _make_td(
    name: str,
    vt_value: str,
    *,
    at: str = "rw",
    array_indices: list[tuple[int, int]] | None = None,
) -> Any:
    return SimpleNamespace(
        name=name,
        vt=SimpleNamespace(value=vt_value),
        at=at,
        get_array_indices=lambda: array_indices or [],
    )


def _make_fake_variable(
    name: str,
    *,
    data_type: str = "struct",
    readable: bool = True,
    writable: bool = True,
    is_array: bool = False,
    is_structure: bool = False,
    struct_members: OrderedDict[str, Any] | None = None,
    array_indices: list[tuple[int, int]] | None = None,
) -> Any:
    return SimpleNamespace(
        name=name,
        dataType=data_type,
        readable=readable,
        writable=writable,
        isArray=is_array,
        isStructure=is_structure,
        attributes={"AT": "rw"},
        descriptor={"CD": name},
        _struct_members=struct_members if struct_members is not None else OrderedDict(),
        _type_description=SimpleNamespace(get_array_indices=lambda: array_indices or []),
    )


def test_list_variables_cache_paging_refresh_ttl_and_restart_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = PviTarget(name="sim", ip="127.0.0.1", role="arsim")
    w = PviWorker(target)
    w._cpu = SimpleNamespace(status={"RunState": "RUN"}, tasks=["Main"], warmStart=lambda: None)
    w._tasks["Main"] = SimpleNamespace(name="Main")
    w._manager_connected = True
    w._cpu_connected = True

    scan_count = 0
    fake_now = [1000.0]

    def fake_scan(parent: Any) -> list[str]:
        nonlocal scan_count
        scan_count += 1
        return [f"v{i:02d}" for i in range(10)]

    monkeypatch.setattr(worker_mod, "_read_variable_names", fake_scan)
    monkeypatch.setattr(worker_mod.time, "monotonic", lambda: fake_now[0])

    # Page 1: miss -> scans once
    p1 = w._list_variables(scope="task", task="Main", limit=4, offset=0)
    assert p1["cache_hit"] is False
    assert p1["total_matched"] == 10
    assert p1["has_more"] is True
    assert p1["variables"] == ["v00", "v01", "v02", "v03"]
    assert scan_count == 1

    # Page 2 & 3: hit cache -> no additional scans
    p2 = w._list_variables(scope="task", task="Main", limit=4, offset=4)
    assert p2["cache_hit"] is True
    assert p2["has_more"] is True
    assert p2["variables"] == ["v04", "v05", "v06", "v07"]
    p3 = w._list_variables(scope="task", task="Main", limit=4, offset=8)
    assert p3["cache_hit"] is True
    assert p3["has_more"] is False
    assert p3["next_offset"] is None
    assert p3["variables"] == ["v08", "v09"]
    assert scan_count == 1

    # Explicit refresh=True -> rescans
    pr = w._list_variables(scope="task", task="Main", limit=4, offset=0, refresh=True)
    assert pr["cache_hit"] is False
    assert scan_count == 2

    # TTL expiration (>30s) -> rescans
    fake_now[0] += 31.0
    pe = w._list_variables(scope="task", task="Main", limit=4, offset=0)
    assert pe["cache_hit"] is False
    assert scan_count == 3

    # CPU error invalidates cache
    w._on_cpu_error(12004)
    assert w._var_list_cache == {}
    w._on_cpu_error(0)
    pa = w._list_variables(scope="task", task="Main", limit=4, offset=0)
    assert pa["cache_hit"] is False
    assert scan_count == 4

    # Restart invalidates cache (restore real monotonic clock before _restart wait loops)
    monkeypatch.undo()
    w._restart(mode="warm", wait_ready_timeout=0.5)
    assert w._var_list_cache == {}


def test_variable_info_expand_struct_depth_max_fields_array_and_unavailable() -> None:
    target = PviTarget(name="sim", ip="127.0.0.1", role="arsim")
    w = PviWorker(target)

    # Nested struct with depth 1, 2, 3 and an array leaf
    members = OrderedDict(
        [
            (".Enable", _make_td(".Enable", "boolean", at="rw")),
            (".Cmd.Speed", _make_td(".Cmd.Speed", "f32", at="rw")),
            (".Cmd.Deep.Level3", _make_td(".Cmd.Deep.Level3", "i32", at="r")),
            (".Offsets", _make_td(".Offsets", "u16", at="rw", array_indices=[(0, 2)])),
        ]
    )
    struct_var = _make_fake_variable("Main:gAxis", is_structure=True, struct_members=members)
    ref_struct = VariableRef(name="gAxis", task="Main")
    w._variables[ref_struct.key] = struct_var

    # Depth limit = 2 skips .Cmd.Deep.Level3 and marks truncated=True
    info_d2 = w._variable_info(ref_struct, expand=True, max_depth=2, max_fields=128)
    assert info_d2["expansion_source"] == "pvi"
    assert info_d2["truncated"] is True
    canonicals_d2 = [f["canonical"] for f in info_d2["fields"]]
    assert "Main:gAxis.Enable" in canonicals_d2
    assert "Main:gAxis.Cmd.Speed" in canonicals_d2
    assert "Main:gAxis.Offsets[0]" in canonicals_d2
    assert "Main:gAxis.Offsets[2]" in canonicals_d2
    assert "Main:gAxis.Cmd.Deep.Level3" not in canonicals_d2

    # max_fields = 2 truncates cleanly
    info_f2 = w._variable_info(ref_struct, expand=True, max_depth=3, max_fields=2)
    assert len(info_f2["fields"]) == 2
    assert info_f2["total_discovered"] == 6
    assert info_f2["truncated"] is True

    # 1D array expansion
    arr_var = _make_fake_variable(
        "Main:aScores",
        data_type="i32[0..3]",
        is_array=True,
        array_indices=[(0, 3)],
    )
    ref_arr = VariableRef(name="aScores", task="Main")
    w._variables[ref_arr.key] = arr_var
    info_arr = w._variable_info(ref_arr, expand=True, max_fields=3)
    assert info_arr["expansion_source"] == "pvi"
    assert [f["canonical"] for f in info_arr["fields"]] == [
        "Main:aScores[0]",
        "Main:aScores[1]",
        "Main:aScores[2]",
    ]
    assert info_arr["total_discovered"] == 4
    assert info_arr["truncated"] is True

    # Unavailable descriptor fallback
    opaque_var = _make_fake_variable("Main:gOpaque", is_structure=True, struct_members=OrderedDict())
    ref_opaque = VariableRef(name="gOpaque", task="Main")
    w._variables[ref_opaque.key] = opaque_var
    info_unavail = w._variable_info(ref_opaque, expand=True)
    assert info_unavail["expansion_source"] == "unavailable"
    assert info_unavail["fields"] == []
    assert "expansion_note" in info_unavail


def test_pvi_client_expand_and_read_structure(tmp_path) -> None:
    class FakeExpandManager:
        def call(self, target: PviTarget, operation: str, **arguments: Any) -> dict[str, Any]:
            if operation == "variable_info":
                return {
                    "ok": True,
                    "variable": arguments["ref"].canonical,
                    "is_structure": True,
                    "expanded": True,
                    "expansion_source": "pvi",
                    "truncated": False,
                    "total_discovered": 2,
                    "fields": [
                        {"canonical": "Main:stCfg.Enable", "data_type": "boolean", "readable": True, "writable": True},
                        {"canonical": "Main:stCfg.Speed", "data_type": "f32", "readable": True, "writable": True},
                    ],
                }
            if operation == "read_many":
                return {
                    "ok": True,
                    "results": [
                        {"ok": True, "variable": "Main:stCfg.Enable", "value": True, "data_type": "boolean"},
                        {"ok": True, "variable": "Main:stCfg.Speed", "value": 12.5, "data_type": "f32"},
                    ],
                }
            raise AssertionError(operation)

        def close_all(self) -> None:
            pass

    svc = RuntimePviService(manager=FakeExpandManager(), discovery_root=tmp_path / "disc")
    with PviClient.from_target(ip="127.0.0.1", name="sim", declared_role="arsim", service=svc) as plc:
        snap = plc.read_structure("Main:stCfg", max_depth=2)
        assert snap["ok"] is True
        assert snap["expansion_source"] == "pvi"
        assert snap["values"]["Main:stCfg.Enable"]["value"] is True
        assert snap["values"]["Main:stCfg.Speed"]["value"] == 12.5
