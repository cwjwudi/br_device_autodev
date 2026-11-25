from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

import arsim_provision  # noqa: E402
import arsim_registry  # noqa: E402
import server  # noqa: E402


def _make_record(tmp_path: Path, run_id: str, *, target: str = "arsim", ip: str = "127.0.0.2", created_at: str = "2026-11-24T10:00:00Z", loader_pid: int = 1001, runtime_pid: int = 1002) -> dict:
    run_dir = tmp_path / "Temp" / "Simulation" / "codex-arsim" / run_id
    runtime_dir = run_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    loader_exe = runtime_dir / "ar000loader.exe"
    loader_exe.write_text("", encoding="utf-8")
    return {
        "run_id": run_id,
        "project_path": str(tmp_path / "Demo.apj"),
        "config": "Sim",
        "target": target,
        "family": "AS6",
        "ip": ip,
        "run_directory": str(run_dir),
        "runtime_directory": str(runtime_dir),
        "loader_exe": str(loader_exe),
        "loader_pid": loader_pid,
        "runtime_pid": runtime_pid,
        "created_at": created_at,
        "status": "running",
    }


def test_registry_atomic_upsert_and_filtered_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = tmp_path / "instances.json"
    rec_a = _make_record(tmp_path / "projA", "run-a", target="arsim", ip="127.0.0.2", created_at="2026-11-24T10:00:00Z", loader_pid=2001, runtime_pid=2002)
    rec_b = _make_record(tmp_path / "projB", "run-b", target="arsim2", ip="127.0.0.3", created_at="2026-11-24T11:00:00Z", loader_pid=3001, runtime_pid=3002)

    arsim_registry.upsert_instance(rec_a, registry_path=reg)
    arsim_registry.upsert_instance(rec_b, registry_path=reg)

    # Atomic file exists and is valid JSON
    payload = json.loads(reg.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert len(payload["instances"]) == 2

    # Mock process inspection: run-a alive & owned, run-b stopped
    monkeypatch.setattr(
        arsim_registry,
        "get_process_executable_path",
        lambda pid: str(Path(rec_a["runtime_directory"]) / "ar000.exe") if pid == 2002 else None,
    )
    monkeypatch.setattr(arsim_registry, "list_processes_under_directory", lambda d: [])

    all_list = arsim_registry.list_arsim_instances(registry_path=reg)
    assert all_list["ok"] is True
    assert all_list["count"] == 2
    by_id = {item["run_id"]: item for item in all_list["instances"]}
    assert by_id["run-a"]["live_status"] == "running"
    assert by_id["run-b"]["live_status"] == "stopped"

    filtered = arsim_registry.list_arsim_instances(project_path=rec_a["project_path"], target="arsim", registry_path=reg)
    assert filtered["count"] == 1
    assert filtered["instances"][0]["run_id"] == "run-a"


@pytest.mark.parametrize(
    "foreign_exe",
    [
        r"C:\Windows\System32\notepad.exe",
        r"C:\OtherProject\Temp\Simulation\codex-arsim\other-run\runtime\ar000loader.exe",
    ],
)
def test_stop_refuses_ownership_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, foreign_exe: str) -> None:
    reg = tmp_path / "instances.json"
    rec = _make_record(tmp_path, "run-mismatch", loader_pid=5555, runtime_pid=5556)
    arsim_registry.upsert_instance(rec, registry_path=reg)

    monkeypatch.setattr(
        arsim_registry,
        "get_process_executable_path",
        lambda pid: foreign_exe if pid == 5556 else None,
    )
    monkeypatch.setattr(arsim_registry, "list_processes_under_directory", lambda d: [])

    terminated: list[int] = []
    result = arsim_registry.stop_arsim_instance(
        run_id="run-mismatch",
        execute=True,
        terminate_fn=lambda pid: terminated.append(pid) or {"succeeded": True},
        occupancy=lambda _: {"ok": True, "slots": [{"state": "free", "conflicts": []}]},
        registry_path=reg,
    )
    assert result["ok"] is False
    assert result["error_code"] == "ARSIM_OWNERSHIP_MISMATCH"
    assert terminated == []


def test_stop_requires_execute_true(tmp_path: Path) -> None:
    reg = tmp_path / "instances.json"
    res = arsim_registry.stop_arsim_instance(run_id="any", execute=False, registry_path=reg)
    assert res["ok"] is False
    assert res["error_code"] == "CONFIRMATION_REQUIRED"


def test_clean_skips_running_keeps_latest_and_rejects_unsafe_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = tmp_path / "instances.json"
    rec_running = _make_record(tmp_path, "run-1-live", created_at="2026-11-24T09:00:00Z", loader_pid=6001, runtime_pid=6002)
    rec_old = _make_record(tmp_path, "run-2-old", created_at="2026-11-24T10:00:00Z", loader_pid=6003, runtime_pid=6004)
    rec_mid = _make_record(tmp_path, "run-3-mid", created_at="2026-11-24T11:00:00Z", loader_pid=6005, runtime_pid=6006)
    rec_new = _make_record(tmp_path, "run-4-new", created_at="2026-11-24T12:00:00Z", loader_pid=6007, runtime_pid=6008)

    for rec in (rec_running, rec_old, rec_mid, rec_new):
        arsim_registry.upsert_instance(rec, registry_path=reg)

    monkeypatch.setattr(
        arsim_registry,
        "get_process_executable_path",
        lambda pid: str(Path(rec_running["runtime_directory"]) / "ar000.exe") if pid == 6002 else None,
    )
    monkeypatch.setattr(arsim_registry, "list_processes_under_directory", lambda d: [])

    cleaned = arsim_registry.clean_arsim_directories(
        project_path=rec_running["project_path"],
        keep_latest=1,
        execute=True,
        registry_path=reg,
    )
    assert cleaned["ok"] is True
    assert [item["run_id"] for item in cleaned["skipped_running"]] == ["run-1-live"]
    assert [item["run_id"] for item in cleaned["kept"]] == ["run-4-new"]
    assert {item["run_id"] for item in cleaned["removed"]} == {"run-2-old", "run-3-mid"}
    assert Path(rec_running["run_directory"]).exists()
    assert Path(rec_new["run_directory"]).exists()
    assert not Path(rec_old["run_directory"]).exists()
    assert not Path(rec_mid["run_directory"]).exists()

    # Unsafe path outside codex-arsim must be rejected and never deleted
    unsafe_dir = tmp_path / "important_project_data"
    unsafe_dir.mkdir()
    reg_unsafe = tmp_path / "unsafe_instances.json"
    arsim_registry.upsert_instance(
        {
            "run_id": "bad-path",
            "project_path": str(tmp_path / "Demo.apj"),
            "target": "arsim",
            "run_directory": str(unsafe_dir),
            "runtime_directory": str(unsafe_dir / "runtime"),
            "created_at": "2026-11-24T08:00:00Z",
        },
        registry_path=reg_unsafe,
    )
    res_unsafe = arsim_registry.clean_arsim_directories(
        run_id="bad-path",
        keep_latest=0,
        execute=True,
        registry_path=reg_unsafe,
    )
    assert res_unsafe["ok"] is False
    assert res_unsafe["error_code"] == "ARSIM_UNSAFE_CLEAN_PATH"
    assert unsafe_dir.exists()


def test_replace_existing_refuses_unknown_external_process(tmp_path: Path) -> None:
    reg = tmp_path / "instances.json"
    options = {"project_path": str(tmp_path / "Demo.apj"), "config": "Sim", "target": "arsim"}
    external_occupancy = lambda _: {
        "ok": True,
        "slots": [
            {
                "state": "blocked",
                "conflicts": [
                    {"port": 11169, "pid": 9999, "path": r"C:\OtherProject\Temp\Simulation\codex-arsim\xyz\runtime\ar000.exe"}
                ],
            }
        ],
    }
    res = arsim_provision.provision(
        options,
        {"ip": "127.0.0.5"},
        {"package_path": str(tmp_path / "ruc.zip")},
        SimpleNamespace(family="AS6"),
        external_occupancy,
        10,
        replace_existing=True,
        registry_path=reg,
    )
    assert res["ok"] is False
    assert res["error_code"] == "ARSIM_IP_OCCUPIED"
    assert "replace_rejected_reason" in res


def test_mcp_manage_arsim_list_allows_execute_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arsim_registry, "DEFAULT_REGISTRY_PATH", tmp_path / "empty_instances.json")
    response = server.handle_tools_call(
        {"name": "plc_manage_arsim", "arguments": {"action": "list", "execute": False}}
    )
    assert response["isError"] is False
    payload = response["structuredContent"]
    assert payload["ok"] is True
    assert payload["action"] == "list"
    assert payload["count"] == 0
