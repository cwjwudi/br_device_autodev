from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from br_plc_toolchain.config.loader import create_ephemeral_target_config
from br_plc_toolchain.policy.runtime import RuntimePolicy
from br_plc_toolchain.policy.sessions import TestSessionManager as SessionManager


def test_unknown_target_can_read_but_cannot_write() -> None:
    policy = RuntimePolicy()
    config = create_ephemeral_target_config(ip="192.168.50.99")
    assert policy.authorize_read(config=config, variable="Main:value").allowed
    decision = policy.authorize_write(
        config=config,
        variable="Main:value",
        current_value=1,
        requested_value=1,
        writable=True,
        execute=True,
        session_valid=False,
    )
    assert not decision.allowed


def test_office_test_allows_same_value_without_session() -> None:
    policy = RuntimePolicy()
    config = create_ephemeral_target_config(
        ip="192.168.50.233", declared_role="dedicated_test_plc",
        project_config={"pvi": {"write_whitelist": ["Main:value"]}}
    )
    decision = policy.authorize_write(
        config=config,
        variable="Main:value",
        current_value=1,
        requested_value=1,
        writable=True,
        execute=True,
        session_valid=False,
    )
    assert decision.allowed
    assert decision.operation == "same_value_write"


def test_changed_value_requires_execute_but_not_session() -> None:
    policy = RuntimePolicy()
    config = create_ephemeral_target_config(
        ip="192.168.50.233", declared_role="dedicated_test_plc",
        project_config={"pvi": {"write_whitelist": ["Main:value"]}}
    )
    no_session = policy.authorize_write(
        config=config,
        variable="Main:value",
        current_value=1,
        requested_value=2,
        writable=True,
        execute=True,
        session_valid=False,
    )
    assert no_session.allowed
    assert not no_session.requires_session
    allowed = policy.authorize_write(
        config=config,
        variable="Main:value",
        current_value=1,
        requested_value=2,
        writable=True,
        execute=True,
        session_valid=True,
    )
    assert allowed.allowed
    without_execute = policy.authorize_write(
        config=config,
        variable="Main:value",
        current_value=1,
        requested_value=2,
        writable=True,
        execute=False,
        session_valid=False,
    )
    assert not without_execute.allowed


def test_trusted_target_still_respects_pvi_writable_attribute() -> None:
    config = create_ephemeral_target_config(ip="127.0.0.1")
    decision = RuntimePolicy().authorize_write(
        config=config,
        variable="Safety:readOnly",
        current_value=1,
        requested_value=2,
        writable=False,
        execute=True,
        session_valid=False,
    )
    assert not decision.allowed


@pytest.mark.parametrize("name", ["Safety:enable", "Main:physicalIoOut", "sys:value"])
def test_trusted_target_allows_system_and_io_names(name: str) -> None:
    policy = RuntimePolicy()
    config = create_ephemeral_target_config(ip="127.0.0.1")
    decision = policy.authorize_write(
        config=config,
        variable=name,
        current_value=False,
        requested_value=True,
        writable=True,
        execute=True,
        session_valid=True,
    )
    assert decision.allowed


def test_production_write_is_always_denied() -> None:
    config = create_ephemeral_target_config(ip="192.168.1.1", declared_role="production")
    decision = RuntimePolicy().authorize_write(
        config=config,
        variable="Main:test",
        current_value=0,
        requested_value=0,
        writable=True,
        execute=True,
        session_valid=True,
    )
    assert not decision.allowed


@pytest.mark.parametrize("mode, entries, variable, expected", [
    ("whitelist", [], "Main:Input", False),
    ("whitelist", ["Main:Input"], "Main:Input", True),
    ("whitelist", ["Main:Input"], "Main:Other", False),
    ("blacklist", ["Safety:*"], "Safety:Enable", False),
    ("blacklist", ["Safety:*"], "Main:Input", True),
    ("invalid", [], "Main:Input", False),
])
def test_physical_target_project_write_policy(mode, entries, variable, expected) -> None:
    key = "write_blacklist" if mode == "blacklist" else "write_whitelist"
    config = create_ephemeral_target_config(
        ip="192.0.2.1", declared_role="dedicated_test_plc",
        project_config={"pvi": {"write_policy": mode, key: entries}},
    )
    decision = RuntimePolicy().authorize_write(config=config, variable=variable,
        current_value=0, requested_value=1, writable=True, execute=True, session_valid=False)
    assert decision.allowed is expected


def test_physical_read_unrestricted_even_for_production() -> None:
    config = create_ephemeral_target_config(ip="192.0.2.1", declared_role="production")
    assert RuntimePolicy().authorize_read(config=config, variable="Safety:Input").allowed


def test_loopback_does_not_override_an_explicit_production_role() -> None:
    config = create_ephemeral_target_config(ip="127.0.0.1", declared_role="production",
                                            project_config={"pvi": {"write_policy": "blacklist"}})
    decision = RuntimePolicy().authorize_write(config=config, variable="Main:Input",
        current_value=0, requested_value=1, writable=True, execute=True, session_valid=False)
    assert config["target"]["role"] == "production"
    assert not decision.allowed


def test_test_session_is_target_bound_and_expires() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)
    clock_value = [now]
    manager = SessionManager(clock=lambda: clock_value[0])
    session = manager.open(
        target_key="plc@1",
        target_name="plc",
        role="dedicated_test_plc",
        ttl_minutes=1,
        fingerprint={"cpu": "X20"},
        execute=True,
    )
    assert manager.require(session.session_id, target_key="plc@1") == session
    with pytest.raises(PermissionError, match="different target"):
        manager.require(session.session_id, target_key="plc@2")
    clock_value[0] = now + timedelta(minutes=2)
    with pytest.raises(PermissionError, match="expired"):
        manager.require(session.session_id, target_key="plc@1")

