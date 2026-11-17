from __future__ import annotations

import json

import pytest

from br_plc_toolchain.config.loader import (
    ConfigError,
    create_ephemeral_target_config,
    save_local_target,
)


def test_missing_policy_physical_target_defaults_to_readonly_discovery() -> None:
    config = create_ephemeral_target_config(ip="192.168.50.10")
    assert config["profile"] == "readonly-discovery"
    assert config["target"]["role"] == "unregistered"
    assert config.get("pvi", {}).get("write_whitelist", []) == []


def test_explicit_test_target_uses_office_profile() -> None:
    config = create_ephemeral_target_config(
        ip="192.168.50.233", declared_role="dedicated_test_plc"
    )
    assert config["profile"] == "office-test"
    assert config["target"]["role"] == "dedicated_test_plc"
    assert config.get("pvi", {}).get("write_whitelist", []) == []


def test_loopback_is_arsim() -> None:
    config = create_ephemeral_target_config(ip="127.0.0.1")
    assert config["profile"] == "arsim-development"
    assert config["target"]["role"] == "arsim"
    assert config["target"]["role"] == "arsim"


def test_production_profile_cannot_weaken_immutable_baseline() -> None:
    config = create_ephemeral_target_config(ip="192.0.2.1", declared_role="production")
    assert config["immutable_safety"]["deny_production_write"] is True


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

