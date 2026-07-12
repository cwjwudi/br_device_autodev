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
        ip="192.168.50.233", declared_role="dedicated_test_plc"
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


def test_changed_value_requires_session_and_execute() -> None:
    policy = RuntimePolicy()
    config = create_ephemeral_target_config(
        ip="192.168.50.233", declared_role="dedicated_test_plc"
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
    assert not no_session.allowed
    assert no_session.requires_session
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


@pytest.mark.parametrize("name", ["Safety:enable", "Main:physicalIoOut", "sys:value"])
def test_immutable_name_blocks_cannot_be_overridden(name: str) -> None:
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
    assert not decision.allowed


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

