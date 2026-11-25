from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

from br_plc_toolchain.config.loader import load_project_config  # noqa: E402
import project_init  # noqa: E402
import server  # noqa: E402


def _make_fake_project(tmp_path: Path, *, as_version: str = "6.3.1.32", sim_ip: str | None = "127.0.0.4") -> Path:
    proj_dir = tmp_path / "SampleProj"
    proj_dir.mkdir(parents=True, exist_ok=True)
    apj = proj_dir / "SampleProj.apj"
    apj.write_text(
        f'<?xml version="1.0" encoding="utf-8"?>\n<?AutomationStudio Version="{as_version}" WorkingVersion="{as_version[:3]}"?>\n<Project />\n',
        encoding="utf-8",
    )
    phys = proj_dir / "Physical"
    phys.mkdir()
    (phys / "Physical.pkg").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Physical xmlns="http://br-automation.co.at/AS/Physical">\n'
        '  <Objects>\n'
        '    <Object Type="Configuration">RealHardware</Object>\n'
        '    <Object Type="Configuration">SimConfig</Object>\n'
        '  </Objects>\n'
        '</Physical>\n',
        encoding="utf-8",
    )
    (phys / "RealHardware").mkdir()
    (phys / "RealHardware" / "Hardware.hw").write_text("<Hardware />", encoding="utf-8")
    (phys / "SimConfig").mkdir()
    if sim_ip:
        (phys / "SimConfig" / "Hardware.hw").write_text(
            f'<Hardware><Parameter ID="SimulationIPAddress" Value="{sim_ip}" /></Hardware>',
            encoding="utf-8",
        )
    else:
        (phys / "SimConfig" / "Hardware.hw").write_text("<Hardware />", encoding="utf-8")
    return proj_dir


@pytest.mark.parametrize("as_version,expected_family", [("6.3.1.32", "AS6"), ("4.12.2.93", "AS4")])
def test_init_project_config_discovers_apj_configs_and_toolchain(
    tmp_path: Path, as_version: str, expected_family: str
) -> None:
    proj_dir = _make_fake_project(tmp_path, as_version=as_version, sim_ip="127.0.0.7")

    preview = project_init.init_project_config(project_path=proj_dir, execute=False)
    assert preview["ok"] is True
    assert preview["executed"] is False
    assert preview["written"] is False
    assert preview["family"] == expected_family
    assert preview["matched_toolchain"]["family"] == expected_family
    assert [c["name"] for c in preview["available_configs"]] == ["RealHardware", "SimConfig"]
    assert preview["selected_config"] == "SimConfig"
    assert preview["recommended_config"]["targets"]["arsim"]["ip"] == "127.0.0.7"
    assert not (proj_dir / "br-auto-dev.json").exists()

    written = project_init.init_project_config(project_path=proj_dir, execute=True)
    assert written["ok"] is True
    assert written["written"] is True
    assert (proj_dir / "br-auto-dev.json").is_file()

    # Overwrite protection when overwrite=False
    blocked = project_init.init_project_config(project_path=proj_dir, execute=True, overwrite=False)
    assert blocked["ok"] is False
    assert blocked["error_code"] == "CONFIG_ALREADY_EXISTS"

    # Overwrite succeeds when overwrite=True
    updated = project_init.init_project_config(
        project_path=proj_dir,
        template="test_plc_blacklist",
        ip="192.0.2.25",
        execute=True,
        overwrite=True,
    )
    assert updated["ok"] is True
    assert updated["written"] is True
    loaded, _ = load_project_config(str(proj_dir))
    assert loaded["pvi"]["write_policy"] == "blacklist"
    assert loaded["targets"]["test_plc"]["ip"] == "192.0.2.25"


def test_legacy_access_policy_error_includes_migration_guidance(tmp_path: Path) -> None:
    proj_dir = _make_fake_project(tmp_path)
    cfg = {
        "project_path": "SampleProj.apj",
        "config": "SimConfig",
        "toolchain": "as6_default",
        "target": "arsim",
        "targets": {"arsim": {"ip": "127.0.0.1", "role": "arsim"}},
        "access_policy": {"mode": "legacy"},
    }
    (proj_dir / "br-auto-dev.json").write_text(json.dumps(cfg), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_project_config(str(proj_dir))
    msg = str(exc_info.value)
    assert "access_policy" in msg
    assert "write_policy" in msg
    assert "write_whitelist" in msg
    assert "write_blacklist" in msg
    assert "allow_auto_download" in msg


def test_mcp_plc_init_project_config_works_without_existing_config(tmp_path: Path) -> None:
    proj_dir = _make_fake_project(tmp_path)
    resp = server.handle_tools_call(
        {
            "name": "plc_init_project_config",
            "arguments": {"project_path": str(proj_dir), "execute": False},
        }
    )
    assert resp["isError"] is False, resp["structuredContent"]
    payload = resp["structuredContent"]
    assert payload["ok"] is True
    assert payload["written"] is False
    assert payload["selected_config"] == "SimConfig"
