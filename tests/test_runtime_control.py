from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

from br_plc_toolchain import PviClient, PviSessionManager, PviTarget, RuntimePviService  # noqa: E402
from br_plc_toolchain.backends.pvi.worker import PviWorker  # noqa: E402
import server  # noqa: E402


class _FakeCpu:
    def __init__(self, *, statuses: list[Any], fail_restart: bool = False):
        self._statuses = list(statuses)
        self._index = 0
        self.fail_restart = fail_restart
        self.warm_calls = 0
        self.cold_calls = 0

    @property
    def status(self) -> Any:
        if not self._statuses:
            return {"ST": "WarmStart", "RunState": "RUN"}
        val = self._statuses[min(self._index, len(self._statuses) - 1)]
        self._index += 1
        if isinstance(val, Exception):
            raise val
        return val

    def warmStart(self) -> None:
        self.warm_calls += 1
        if self.fail_restart:
            raise RuntimeError("warmStart failed")

    def coldStart(self) -> None:
        self.cold_calls += 1
        if self.fail_restart:
            raise RuntimeError("coldStart failed")


def _make_worker_with_fake_cpu(cpu: _FakeCpu) -> PviWorker:
    target = PviTarget(name="arsim", ip="127.0.0.1", role="arsim", event_poll_s=0.01)
    worker = PviWorker(target)
    worker._cpu = cpu
    worker._manager_connected = True
    worker._cpu_connected = True
    worker._variables = {("global", None, "gAlive"): object()}
    worker._tasks = {"Main": object()}
    worker._do_events = lambda: None  # type: ignore[method-assign]
    return worker


def test_worker_warmstart_clears_cache_and_waits_for_run() -> None:
    cpu = _FakeCpu(
        statuses=[
            {"ST": "Reset", "RunState": "SERV"},
            {"ST": "Boot", "RunState": None},
            {"ST": "WarmStart", "RunState": "RUN"},
        ]
    )
    worker = _make_worker_with_fake_cpu(cpu)
    res = worker._restart(mode="warm", wait_ready_timeout=2.0)

    assert res["ok"] is True
    assert res["mode"] == "warm"
    assert res["method"] == "pvi"
    assert res["before_status"] == "SERVICE"
    assert res["after_status"] == "RUN"
    assert res["cache_cleared"] is True
    assert cpu.warm_calls == 1
    assert worker._variables == {}
    assert worker._tasks == {}


def test_worker_coldstart_success() -> None:
    cpu = _FakeCpu(
        statuses=[
            {"ST": "WarmStart", "RunState": "RUN"},
            {"ST": "ColdStart", "RunState": "RUN"},
        ]
    )
    worker = _make_worker_with_fake_cpu(cpu)
    res = worker._restart(mode="cold", wait_ready_timeout=2.0)

    assert res["ok"] is True
    assert res["mode"] == "cold"
    assert res["after_status"] == "RUN"
    assert cpu.cold_calls == 1


def test_worker_restart_timeout_returns_explicit_error_not_run() -> None:
    cpu = _FakeCpu(
        statuses=[
            {"ST": "WarmStart", "RunState": "RUN"},
            {"ST": "Boot", "RunState": None},
            {"ST": "Boot", "RunState": None},
        ]
    )
    worker = _make_worker_with_fake_cpu(cpu)
    res = worker._restart(mode="warm", wait_ready_timeout=0.15)

    assert res["ok"] is False
    assert res["error_code"] == "RUNTIME_RESTART_TIMEOUT"
    assert res["after_status"] != "RUN"


class _StubWorker:
    def __init__(self, target: PviTarget):
        self.target = target
        self.running = True
        self.dirty = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def start(self) -> None:
        self.running = True

    def close(self) -> None:
        self.running = False

    def call(self, operation: str, **arguments: Any) -> Any:
        self.calls.append((operation, arguments))
        if operation == "restart":
            return {
                "ok": True,
                "target": self.target.name,
                "mode": arguments["mode"],
                "method": "pvi",
                "before_status": "RUN",
                "after_status": "RUN",
                "elapsed_seconds": 0.42,
                "cache_cleared": True,
            }
        raise AssertionError(f"Unexpected op: {operation}")


def test_runtime_control_policy_guards() -> None:
    manager = PviSessionManager(worker_factory=_StubWorker)
    service = RuntimePviService(manager=manager)

    # 1. Production is permanently denied even with execute=True
    service.register_ephemeral_target(ip="192.0.2.50", name="prod_plc", declared_role="production")
    with pytest.raises(PermissionError, match="POLICY_DENIED"):
        service.restart_target("prod_plc", mode="warmstart", execute=True)

    # 2. execute=False is denied on ARsim
    service.register_ephemeral_target(ip="127.0.0.1", name="sim1", declared_role="arsim")
    with pytest.raises(PermissionError, match="CONFIRMATION_REQUIRED"):
        service.restart_target("sim1", mode="warmstart", execute=False)

    # 3. ARsim succeeds with execute=True
    res = service.restart_target("sim1", mode="warmstart", execute=True)
    assert res["ok"] is True
    assert res["mode"] == "warm"

    # 4. Dedicated test PLC without allow_runtime_control / allow_auto_download is denied
    service.register_ephemeral_target(
        ip="192.0.2.10",
        name="bench_denied",
        declared_role="dedicated_test_plc",
        project_config={"targets": {"bench_denied": {"ip": "192.0.2.10", "role": "dedicated_test_plc"}}},
    )
    with pytest.raises(PermissionError, match="POLICY_DENIED"):
        service.restart_target("bench_denied", mode="coldstart", execute=True)

    # 5. Dedicated test PLC with allow_runtime_control=True is allowed
    service.register_ephemeral_target(
        ip="192.0.2.11",
        name="bench_allowed",
        declared_role="dedicated_test_plc",
        project_config={
            "targets": {
                "bench_allowed": {
                    "ip": "192.0.2.11",
                    "role": "dedicated_test_plc",
                    "allow_runtime_control": True,
                }
            }
        },
    )
    res_bench = service.restart_target("bench_allowed", mode="coldstart", execute=True)
    assert res_bench["ok"] is True
    assert res_bench["mode"] == "cold"


def test_pvi_client_restart_public_api() -> None:
    manager = PviSessionManager(worker_factory=_StubWorker)
    service = RuntimePviService(manager=manager)
    with PviClient.from_target(ip="127.0.0.1", name="sim_sdk", declared_role="arsim", service=service) as plc:
        with pytest.raises(PermissionError, match="CONFIRMATION_REQUIRED"):
            plc.restart("warm", execute=False)
        res = plc.restart("cold", execute=True, timeout_seconds=15.0)
        assert res["ok"] is True
        assert res["mode"] == "cold"


def test_mcp_plc_control_runtime_rejects_execute_false(monkeypatch: pytest.MonkeyPatch) -> None:
    import toolchain

    manager = PviSessionManager(worker_factory=_StubWorker)
    service = RuntimePviService(manager=manager)
    service.register_ephemeral_target(ip="127.0.0.1", name="sim_mcp", declared_role="arsim")
    monkeypatch.setattr(toolchain, "_RUNTIME_SERVICE", service)

    resp = server.handle_tools_call(
        {
            "name": "plc_control_runtime",
            "arguments": {"target": "sim_mcp", "action": "warmstart", "execute": False},
        }
    )
    assert resp["isError"] is True
    assert resp["structuredContent"]["error_code"] == "CONFIRMATION_REQUIRED"
