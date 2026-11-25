from pathlib import Path
from types import SimpleNamespace

import pytest

from test_arsim_occupancy import toolchain

import arsim_provision


@pytest.mark.parametrize("family,command", [("AS4", "CreateARsimStructure"), ("AS6", "OfflineCommissioning")])
@pytest.mark.parametrize("custom", [False, True])
def test_creates_fresh_runtime_in_work_directory(tmp_path, monkeypatch, family, command, custom):
    project = tmp_path / "project.apj"
    project.touch()
    package = tmp_path / "ruc.zip"
    package.touch()
    options = {"project_path": str(project), "project_config_path": str(tmp_path / "br-auto-dev.json"), "config": "Sim", "target": "arsim"}
    target = {"ip": "127.0.0.2"}
    if custom:
        target["arsim_work_dir"] = "custom-work"
    work_root = tmp_path / "custom-work" if custom else tmp_path / "Temp" / "Simulation"
    chain = SimpleNamespace(family=family, pvi_transfer_exe=tmp_path / "transfer.exe")
    hardware = tmp_path / "Physical" / "Sim" / "Hardware.hw"
    hardware.parent.mkdir(parents=True)
    hardware.write_text('<Hardware><Parameter ID="SimulationIPAddress" Value="127.0.0.2" /></Hardware>')
    package.touch()

    def install(args, **kwargs):
        run_dir = Path(kwargs["cwd"])
        assert command in (run_dir / "install.pil").read_text()
        runtime = run_dir / "runtime"
        runtime.mkdir()
        (runtime / "ar000loader.exe").touch()
        (run_dir / "install.log").write_text("PROCESS FINISHED (SUCCESS)")
        return SimpleNamespace(pid=98, wait=lambda timeout: 0)

    monkeypatch.setattr(arsim_provision.subprocess, "Popen", lambda *a, **k: install(*a, **k) if str(a[0][0]).endswith("transfer.exe") else SimpleNamespace(pid=99))
    calls = []

    def occupancy(args):
        calls.append(args)
        conflicts = []
        if len(calls) > 2:
            runtime = next((work_root / "codex-arsim").iterdir()) / "runtime"
            conflicts = [{"port": 11169, "path": str(runtime / "ar000.exe"), "pid": 100}]
        return {"ok": True, "slots": [{"state": "blocked" if conflicts else "free", "conflicts": conflicts}]}

    monkeypatch.setattr(arsim_provision.arsim_registry, "DEFAULT_REGISTRY_PATH", tmp_path / "instances.json")
    result = arsim_provision.provision(options, target, {"package_path": str(package)}, chain, occupancy, 10)
    assert result["ok"] and result["runtime_pid"] == 100
    assert Path(result["runtime_directory"]).is_relative_to(work_root)
    assert (Path(result["run_directory"]) / "instance.json").exists()


def test_occupied_address_never_installs(tmp_path):
    result = arsim_provision.provision({"project_path": str(tmp_path / "p.apj")}, {"ip": "127.0.0.2"}, {}, SimpleNamespace(family="AS6"), lambda _: {"ok": True, "slots": [{"state": "blocked"}]}, 10)
    assert result["error_code"] == "ARSIM_IP_OCCUPIED"
    assert list(tmp_path.iterdir()) == []


def test_as4_rejects_address_mismatch(tmp_path):
    hardware = tmp_path / "Physical" / "Sim" / "Hardware.hw"
    hardware.parent.mkdir(parents=True)
    hardware.write_text("<Hardware />")
    with pytest.raises(ValueError, match="SimulationIPAddress"):
        arsim_provision.verify_as4_ip(tmp_path / "p.apj", "Sim", "127.0.0.2")


def test_wrong_address_cleans_up_only_started_loader(tmp_path, monkeypatch):
    project = tmp_path / "project.apj"
    project.touch()
    package = tmp_path / "ruc.zip"
    package.touch()
    options = {"project_path": str(project), "project_config_path": str(tmp_path / "br-auto-dev.json"), "config": "Sim", "target": "arsim"}
    chain = SimpleNamespace(family="AS6", pvi_transfer_exe=tmp_path / "transfer.exe")

    def spawn(args, **kwargs):
        if str(args[0]).endswith("transfer.exe"):
            run_dir = Path(kwargs["cwd"])
            (run_dir / "runtime").mkdir()
            (run_dir / "runtime" / "ar000loader.exe").touch()
            (run_dir / "install.log").write_text("PROCESS FINISHED (SUCCESS)")
            return SimpleNamespace(pid=98, wait=lambda timeout: 0)
        return SimpleNamespace(pid=99)

    monkeypatch.setattr(arsim_provision.subprocess, "Popen", spawn)
    cleaned = []
    monkeypatch.setattr(toolchain, "terminate_process_tree", lambda pid: cleaned.append(pid) or {"succeeded": True})
    calls = []

    def occupancy(args):
        calls.append(args)
        if len(calls) <= 2:
            return {"ok": True, "slots": [{"state": "free", "conflicts": []}]}
        runtime = next((tmp_path / "Temp" / "Simulation" / "codex-arsim").iterdir()) / "runtime"
        return {"ok": True, "slots": [{"state": "free", "conflicts": []}, {"state": "blocked", "conflicts": [{"port": 80, "path": str(runtime / "ar000.exe"), "pid": 100}]}]}

    result = arsim_provision.provision(options, {"ip": "127.0.0.2"}, {"package_path": str(package)}, chain, occupancy, 10)
    assert result["error_code"] == "ARSIM_WRONG_IP"
    assert cleaned == [99]
