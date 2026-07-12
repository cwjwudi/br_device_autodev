from __future__ import annotations

import json

import pytest

from br_plc_toolchain.config.loader import (
    ConfigError,
    create_ephemeral_target_config,
    load_environment_map,
    load_profile,
    save_local_target,
)


def test_missing_policy_physical_target_defaults_to_readonly_discovery() -> None:
    config = create_ephemeral_target_config(ip="192.168.50.10")
    assert config["profile"] == "readonly-discovery"
    assert config["target"]["role"] == "unregistered"
    assert config["access"]["dynamic_read"] is True
    assert config["access"]["same_value_write"] is False
    assert config["access"]["changed_value_write"] is False


def test_explicit_test_target_uses_office_profile() -> None:
    config = create_ephemeral_target_config(
        ip="192.168.50.233", declared_role="dedicated_test_plc"
    )
    assert config["profile"] == "office-test"
    assert config["target"]["role"] == "dedicated_test_plc"
    assert config["access"]["dynamic_read"] is True
    assert config["access"]["same_value_write"] is True
    assert config["access"]["changed_value_requires_session"] is True


def test_loopback_is_arsim_but_still_requires_session_for_changed_values() -> None:
    config = create_ephemeral_target_config(ip="127.0.0.1")
    assert config["profile"] == "arsim-development"
    assert config["target"]["role"] == "arsim"
    assert config["access"]["changed_value_write"] is True
    assert config["access"]["changed_value_requires_session"] is True


def test_production_profile_cannot_weaken_immutable_baseline() -> None:
    config = load_profile("production-locked")
    assert config["immutable_safety"]["deny_production_write"] is True
    assert config["immutable_safety"]["deny_safety_write"] is True
    assert config["access"]["changed_value_write"] is False


def test_environment_map_contains_office_test_and_arsim() -> None:
    environments = load_environment_map()
    assert environments["office_test_233"]["ip"] == "192.168.50.233"
    assert environments["local_arsim"]["access_profile"] == "arsim-development"


def test_save_local_target_requires_explicit_generated_config(tmp_path, monkeypatch) -> None:
    import br_plc_toolchain.config.loader as loader

    monkeypatch.setattr(loader, "LOCAL_ROOT", tmp_path)
    config = create_ephemeral_target_config(
        ip="192.168.50.233", declared_role="dedicated_test_plc"
    )
    path = save_local_target(config, filename="test-plc-233.json")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["target"]["persistent"] is True
    assert saved["target"]["source"] == "local_saved"
    with pytest.raises(ConfigError, match="overwrite"):
        save_local_target(config, filename="test-plc-233.json")

