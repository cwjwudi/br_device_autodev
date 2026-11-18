import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "mcp_server"))

import locks
import server
import toolchain
from project_config import load_project_config


@pytest.fixture
def project(tmp_path):
    directory = tmp_path / "project"
    directory.mkdir()
    apj = directory / "demo.apj"
    apj.write_text("<Project/>", encoding="utf-8")
    config = {"project_path": "project/demo.apj", "config": "Sim", "toolchain": "as6_default",
              "target": "arsim", "targets": {"arsim": {"ip": "127.0.0.1", "role": "arsim"}}}
    path = tmp_path / "br-auto-dev.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return apj, path, config


def test_parent_config_is_used_by_execution_and_lock(project):
    apj, path, _ = project
    args = {"project_path": str(apj), "target": "arsim"}
    options = toolchain.resolve_call_options(args)
    context = locks.resolve_scope_context(args)
    assert options["project_path"] == context["project_path"] == str(apj)
    assert options["config"] == context["config"] == "Sim"
    assert options["targets_path"] == context["targets_path"] == str(path)
    assert "target:127.0.0.1" in locks.lock_keys_for_tool("plc_start_arsim", args)


def test_project_directory_and_explicit_overrides(project):
    apj, path, config = project
    config["project_path"] = "demo.apj"
    local = apj.parent / path.name
    local.write_text(json.dumps(config), encoding="utf-8")
    options = toolchain.resolve_call_options({"project_path": str(apj.parent), "config": "Other"})
    assert options["project_path"] == str(apj)
    assert options["config"] == "Other"
    assert options["project_config_path"] == str(local)


def test_bad_and_mismatched_configs_fail_closed(project):
    apj, path, config = project
    config["project_path"] = "project/other.apj"
    (apj.parent / "other.apj").write_text("<Project/>", encoding="utf-8")
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="different project"):
        load_project_config(str(apj), ROOT)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid project configuration"):
        load_project_config(str(apj), ROOT)


def test_legacy_access_policy_requires_explicit_migration(project):
    apj, path, config = project
    config["access_policy"] = {"mode": "whitelist", "blocked_name_patterns": ["*custom*"]}
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="removed access_policy"):
        load_project_config(str(apj), ROOT)


def test_config_does_not_bypass_explicit_target(project):
    apj, _, _ = project
    with pytest.raises(ValueError, match="explicit"):
        toolchain.resolve_call_options({"project_path": str(apj)}, require_explicit_target=True)


def test_physical_project_target_is_used_by_runtime_discovery(project):
    apj, path, config = project
    config["targets"]["arsim"] = {"ip": "192.0.2.1", "role": "dedicated_test_plc"}
    config["pvi"] = {"write_whitelist": ["Main:Allowed"]}
    path.write_text(json.dumps(config), encoding="utf-8")
    from unittest.mock import Mock, patch
    service = Mock()
    service.register_ephemeral_target.return_value = {"target": {"name": "arsim"}}
    with patch.object(toolchain, "runtime_pvi_service", return_value=service):
        toolchain._ensure_runtime_target({"project_path": str(apj), "target": "arsim"})
    assert service.register_ephemeral_target.call_args.kwargs["project_config"]["pvi"] == config["pvi"]
    with patch.object(toolchain, "runtime_pvi_service", return_value=service):
        with pytest.raises(ValueError, match="IP does not match"):
            toolchain._ensure_runtime_target({"project_path": str(apj), "target": "arsim", "ip": "192.0.2.2"})


def test_arsim_must_be_loopback(project):
    apj, path, config = project
    config["targets"]["arsim"]["ip"] = "192.0.2.1"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="loopback"):
        toolchain.resolve_call_options({"project_path": str(apj)})


def test_download_permission_must_be_boolean(project):
    apj, path, config = project
    config["targets"]["arsim"]["allow_auto_download"] = "false"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a boolean"):
        load_project_config(str(apj), ROOT)


def test_same_ip_has_same_lock_across_config_files(project, tmp_path):
    apj, _, config = project
    other = tmp_path / "other.json"
    other.write_text(json.dumps(config), encoding="utf-8")
    left = locks.lock_keys_for_tool("plc_start_arsim", {"target": "arsim", "project_path": str(apj)})
    right = locks.lock_keys_for_tool("plc_start_arsim", {"target": "arsim", "targets_path": str(other)})
    assert left == right == ["target:127.0.0.1"]
