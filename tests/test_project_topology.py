from __future__ import annotations

import sys
from pathlib import Path

import pytest

from br_plc_toolchain.project import inspect_project


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_sample_project(
    root: Path,
    *,
    as_version: str = "6.1.0",
    cpu_type: str = "X20CP3687X",
    ar_version: str = "6.7.8",
    sim_ip: str | None = "127.0.0.5",
    include_safety: bool = False,
) -> Path:
    _write_text(
        root / "Demo.apj",
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<?AutomationStudio Version="{as_version}" WorkingVersion="{as_version}"?>\n'
        f'<Project xmlns="http://br-automation.co.at/AS/Project" />\n',
    )
    _write_text(
        root / "Physical" / "Physical.pkg",
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Physical xmlns="http://br-automation.co.at/AS/Physical">\n'
        '  <Objects>\n'
        '    <Object Type="Configuration">ConfigA</Object>\n'
        '    <Object Type="Configuration">ConfigB</Object>\n'
        '  </Objects>\n'
        '</Physical>\n',
    )
    _write_text(
        root / "Physical" / "ConfigA" / "Config.pkg",
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<Configuration xmlns="http://br-automation.co.at/AS/Configuration">\n'
        f'  <Objects>\n'
        f'    <Object Type="File">Hardware.hw</Object>\n'
        f'    <Object Type="Cpu">{cpu_type}</Object>\n'
        f'  </Objects>\n'
        f'</Configuration>\n',
    )
    safety_module = (
        '  <Module Name="SL1" Type="X20SL8101" Version="1.0.0.0" />\n'
        if include_safety
        else ""
    )
    sim_param = (
        f'    <Parameter ID="SimulationIPAddress" Value="{sim_ip}" />\n'
        if sim_ip is not None
        else ""
    )
    _write_text(
        root / "Physical" / "ConfigA" / "Hardware.hw",
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<Hardware xmlns="http://br-automation.co.at/AS/Hardware">\n'
        f'  <Module Name="{cpu_type}" Type="{cpu_type}" Version="1.0.0.0">\n'
        f'{sim_param}'
        f'  </Module>\n'
        f'{safety_module}'
        f'</Hardware>\n',
    )
    safety_rel = "1.10" if include_safety else "0.0"
    _write_text(
        root / "Physical" / "ConfigA" / cpu_type / "Cpu.pkg",
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<Cpu xmlns="http://br-automation.co.at/AS/Cpu">\n'
        f'  <Objects>\n'
        f'    <Object Type="File">Cpu.sw</Object>\n'
        f'  </Objects>\n'
        f'  <Configuration ModuleId="{cpu_type}">\n'
        f'    <AutomationRuntime Version="{ar_version}" />\n'
        f'    <Safety SafetyRelease="{safety_rel}" />\n'
        f'  </Configuration>\n'
        f'</Cpu>\n',
    )
    _write_text(
        root / "Physical" / "ConfigA" / cpu_type / "Cpu.sw",
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<SwConfiguration CpuAddress="SL1" xmlns="http://br-automation.co.at/AS/SwConfiguration">\n'
        '  <TaskClass Name="Cyclic#1">\n'
        '    <Task Name="Main" Source="App.Main.prg" Memory="UserROM" Language="IEC" Debugging="true" />\n'
        '    <Task Name="DisabledT" Source="App.DisabledT.prg" Memory="UserROM" Language="IEC" Disabled="true" />\n'
        '  </TaskClass>\n'
        '  <TaskClass Name="Cyclic#4" />\n'
        '</SwConfiguration>\n',
    )
    _write_text(
        root / "Logical" / "Package.pkg",
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Package xmlns="http://br-automation.co.at/AS/Package">\n'
        '  <Objects>\n'
        '    <Object Type="File">Global.var</Object>\n'
        '    <Object Type="File">Global.typ</Object>\n'
        '    <Object Type="Package">App</Object>\n'
        '  </Objects>\n'
        '</Package>\n',
    )
    _write_text(root / "Logical" / "Global.var", "VAR\n  gAlive : BOOL;\nEND_VAR\n")
    _write_text(root / "Logical" / "Global.typ", "TYPE\nEND_TYPE\n")
    _write_text(
        root / "Logical" / "App" / "Package.pkg",
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Package xmlns="http://br-automation.co.at/AS/Package">\n'
        '  <Objects>\n'
        '    <Object Type="File">App.var</Object>\n'
        '    <Object Type="Program" Language="IEC">Main</Object>\n'
        '    <Object Type="Program" Language="IEC">DisabledT</Object>\n'
        '  </Objects>\n'
        '</Package>\n',
    )
    _write_text(root / "Logical" / "App" / "App.var", "VAR\nEND_VAR\n")
    _write_text(
        root / "Logical" / "App" / "Main" / "IEC.prg",
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Program xmlns="http://br-automation.co.at/AS/Program">\n'
        '  <Files>\n'
        '    <File>Main.st</File>\n'
        '    <File Private="true">Variables.var</File>\n'
        '  </Files>\n'
        '</Program>\n',
    )
    _write_text(root / "Logical" / "App" / "Main" / "Main.st", "PROGRAM _CYCLIC\nEND_PROGRAM\n")
    _write_text(root / "Logical" / "App" / "Main" / "Variables.var", "VAR\nEND_VAR\n")
    _write_text(
        root / "Logical" / "App" / "DisabledT" / "IEC.prg",
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Program xmlns="http://br-automation.co.at/AS/Program">\n'
        '  <Files>\n'
        '    <File>DisabledT.st</File>\n'
        '  </Files>\n'
        '</Program>\n',
    )
    _write_text(root / "Logical" / "App" / "DisabledT" / "DisabledT.st", "PROGRAM _CYCLIC\nEND_PROGRAM\n")
    return root


def test_inspect_as6_and_as4_project_topology(tmp_path: Path) -> None:
    as6_dir = _create_sample_project(
        tmp_path / "as6",
        as_version="6.1.0",
        cpu_type="X20CP3687X",
        ar_version="6.7.8",
        sim_ip="127.0.0.9",
        include_safety=True,
    )
    res6 = inspect_project(as6_dir, include_files=True, check_integrity=True)
    assert res6["ok"] is True
    assert res6["project"]["family"] == "AS6"
    assert res6["project"]["available_configs"] == ["ConfigA", "ConfigB"]
    assert res6["project"]["selected_config"] == "ConfigA"
    assert res6["hardware"]["cpu_type"] == "X20CP3687X"
    assert res6["hardware"]["ar_version"] == "6.7.8"
    assert res6["hardware"]["simulation_ip"] == "127.0.0.9"
    assert res6["hardware"]["simulation_ip_is_default"] is False
    assert res6["hardware"]["has_safety_hardware"] is True
    assert res6["task_summary"] == {"total_tasks": 2, "enabled_tasks": 1, "disabled_tasks": 1}
    cyclic1 = res6["task_classes"][0]
    assert cyclic1["name"] == "Cyclic#1"
    main_task = cyclic1["tasks"][0]
    assert main_task["name"] == "Main"
    assert main_task["enabled"] is True
    assert main_task["source_dir"] == "Logical/App/Main"
    assert main_task["files"] == ["Logical/App/Main/Main.st", "Logical/App/Main/Variables.var"]
    assert res6["global_declarations"]["global_var"] == "Logical/Global.var"
    assert res6["global_declarations"]["global_typ"] == "Logical/Global.typ"
    assert res6["integrity"]["ok"] is True
    assert res6["integrity"]["issues"] == []

    # AS4 with default simulation IP and no safety hardware
    as4_dir = _create_sample_project(
        tmp_path / "as4",
        as_version="4.12.4.107",
        cpu_type="X20CP3586",
        ar_version="J4.93",
        sim_ip=None,
        include_safety=False,
    )
    res4 = inspect_project(as4_dir, include_files=False, check_integrity=True)
    assert res4["project"]["family"] == "AS4"
    assert res4["hardware"]["simulation_ip"] == "127.0.0.1"
    assert res4["hardware"]["simulation_ip_is_default"] is True
    assert res4["hardware"]["has_safety_hardware"] is False
    assert "files" not in res4["task_classes"][0]["tasks"][0]
    assert res4["integrity"]["ok"] is True


def test_static_integrity_detects_dangling_refs_broken_task_duplicates_and_malformed_xml(
    tmp_path: Path,
) -> None:
    proj = _create_sample_project(tmp_path / "broken")

    # 1. Dangling Package.pkg reference + duplicate object
    _write_text(
        proj / "Logical" / "App" / "Package.pkg",
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Package xmlns="http://br-automation.co.at/AS/Package">\n'
        '  <Objects>\n'
        '    <Object Type="File">App.var</Object>\n'
        '    <Object Type="File">App.var</Object>\n'
        '    <Object Type="File">MissingFile.st</Object>\n'
        '    <Object Type="Program" Language="IEC">Main</Object>\n'
        '  </Objects>\n'
        '</Package>\n',
    )
    # 2. Broken Cpu.sw task source
    _write_text(
        proj / "Physical" / "ConfigA" / "X20CP3687X" / "Cpu.sw",
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<SwConfiguration CpuAddress="SL1" xmlns="http://br-automation.co.at/AS/SwConfiguration">\n'
        '  <TaskClass Name="Cyclic#1">\n'
        '    <Task Name="Ghost" Source="App.DoesNotExist.prg" Memory="UserROM" Language="IEC" />\n'
        '  </TaskClass>\n'
        '</SwConfiguration>\n',
    )
    # 3. Malformed XML in Main/IEC.prg
    _write_text(
        proj / "Logical" / "App" / "Main" / "IEC.prg",
        '<?xml version="1.0" encoding="utf-8"?><Program><Files><File>Main.st</Program>',
    )

    res = inspect_project(proj, check_integrity=True)
    assert res["ok"] is True  # Tool returns structured report without crashing
    assert res["integrity"]["ok"] is False
    codes = {issue["code"] for issue in res["integrity"]["issues"]}
    assert "MISSING_REFERENCED_FILE" in codes
    assert "DUPLICATE_PACKAGE_OBJECT" in codes
    assert "BROKEN_TASK_SOURCE" in codes
    assert "MALFORMED_XML" in codes


def test_mcp_plc_inspect_project_works_without_br_auto_dev_json(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tools" / "mcp_server"))
    import server

    proj = _create_sample_project(tmp_path / "unconfigured")
    response = server.handle_tools_call(
        {
            "name": "plc_inspect_project",
            "arguments": {"project_path": str(proj), "check_integrity": True},
        }
    )
    assert response["isError"] is False
    payload = response["structuredContent"]
    assert payload["ok"] is True
    assert payload["project"]["family"] == "AS6"
    assert payload["integrity"]["ok"] is True
