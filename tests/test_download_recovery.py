import os
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "mcp_server"))
import download
import download_recovery as journal
import server
from toolchain import _CURRENT_OPERATION_ID


def scoped(target):
    return ({"target": target, "target_ip": "127.0.0.2", "project_path": "test.apj"}, ["target:127.0.0.2"], [])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "DOWNLOAD_ROOT", tmp_path / "downloads")
    monkeypatch.setattr(server, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(server, "LOCK_DIR", tmp_path / "locks")


def call(name, arguments):
    return server.handle_tools_call({"name": name, "arguments": arguments})["structuredContent"]


def test_lookup_after_discarding_response_and_duplicate_is_idempotent(monkeypatch):
    runs = []

    def handler(arguments):
        operation_id = _CURRENT_OPERATION_ID.get()
        runs.append(operation_id)
        journal.bind(operation_id, 22, time.monotonic() + 22)
        return {"ok": True, "data": {"download_state": "transfer_succeeded", "processes_ended": True}}

    monkeypatch.setitem(server.TOOLS, "plc_download_ruc", handler)
    args = {"request_id": "discarded-response", "target": "arsim", "execute": True}
    call("plc_download_ruc", args)
    recovered = call("plc_get_download_result", {"request_id": args["request_id"]})
    assert recovered["download_state"] == "transfer_succeeded"
    assert recovered["operation_id"] == runs[0]
    assert recovered["effective_timeout_seconds"] == 22
    assert len(recovered["audit"]) == 2
    assert call("plc_download_ruc", args)["replayed"]
    assert call("plc_download_ruc", {**args, "execute": False})["error_code"] == "DOWNLOAD_REQUEST_ID_CONFLICT"
    assert len(runs) == 1


def test_restart_retains_target_until_owned_processes_are_confirmed_ended(monkeypatch):
    assert call("plc_get_download_result", {"request_id": "missing"})["download_state"] == "unknown"
    assert not download.DOWNLOAD_ROOT.exists()
    operation_id = "1" * 32
    journal.claim("interrupted", operation_id, {})
    token = journal.EXECUTION.set(scoped("sim"))
    try:
        journal.bind(operation_id, 60, time.monotonic() + 60)
    finally:
        journal.EXECUTION.reset(token)
    directory = download.DOWNLOAD_ROOT / operation_id
    directory.mkdir()
    (directory / "transfer-started").touch()
    log = directory / "pvi_download_sim.log"
    log.write_text("Establishing Connection...\n", encoding="utf-8")

    monkeypatch.setattr(journal, "owner_alive", lambda _pid: False)
    monkeypatch.setattr(journal, "remaining_processes", lambda _operation: None)
    active = call("plc_get_download_result", {"request_id": "interrupted"})
    assert active["download_state"] == "unknown" and active["target_protected"]
    assert journal.protected(["target:127.0.0.2"])["request_id"] == "interrupted"
    monkeypatch.setattr(journal, "remaining_processes", lambda _operation: 0)
    assert call("plc_get_download_result", {"request_id": "interrupted"})["download_state"] == "unknown"
    log.write_text("Transfer RUC FAILED\n", encoding="utf-8")
    failed = call("plc_get_download_result", {"request_id": "interrupted"})
    assert failed["download_state"] == "transfer_failed"
    assert failed["result"]["data"]["error_code"] == "TRANSFER_FAILED"
    log.write_text("Transfer RUC SUCCESSFUL\n", encoding="utf-8")
    ended = call("plc_get_download_result", {"request_id": "interrupted"})
    assert ended["download_state"] == "transfer_succeeded"
    assert ended["result"]["data"]["deployment_state"] == "transfer_completed"
    assert not ended["target_protected"]
    assert journal.protected(["target:127.0.0.2"]) is None


def test_duplicate_in_progress_never_calls_handler(monkeypatch):
    args = {"request_id": "in-flight", "target": "arsim", "execute": True}
    journal.claim(args["request_id"], "2" * 32, args)
    monkeypatch.setitem(server.TOOLS, "plc_download_ruc", lambda _args: pytest.fail("duplicate started"))
    replay = call("plc_download_ruc", args)
    assert replay["replayed"] and replay["recovery"]["download_state"] == "in_progress"


def test_admission_rejection_is_queryable_and_never_calls_handler(monkeypatch):
    monkeypatch.setitem(server.TOOLS, "plc_download_ruc", lambda _args: pytest.fail("overload started a transfer"))
    response = server.handle_tools_call({
        "name": "plc_download_ruc", "arguments": {"request_id": "at-capacity", "target": "arsim", "execute": True}
    }, download_busy=True)["structuredContent"]
    assert response["error_code"] == "DOWNLOAD_SERVER_BUSY"
    recovered = call("plc_get_download_result", {"request_id": "at-capacity"})
    assert recovered["download_state"] == "not_started"
    assert recovered["operation_id"] == response["attempt_id"]


def test_restart_with_only_a_passed_safety_checkpoint_is_unknown(monkeypatch):
    operation_id = "4" * 32
    journal.claim("safety-only", operation_id, {})
    token = journal.EXECUTION.set(scoped("sim"))
    try:
        journal.bind(operation_id, 60, time.monotonic() + 60)
    finally:
        journal.EXECUTION.reset(token)
    directory = download.DOWNLOAD_ROOT / operation_id
    directory.mkdir()
    (directory / "safety.json").write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(journal, "owner_alive", lambda _pid: False)
    monkeypatch.setattr(journal, "remaining_processes", lambda _operation: 0)
    recovered = call("plc_get_download_result", {"request_id": "safety-only"})
    assert recovered["download_state"] == "unknown"
    assert recovered["result"]["data"]["error_code"] == "TRANSFER_STATE_UNKNOWN"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object")
def test_cancelled_download_does_not_launch(monkeypatch):
    import threading

    cancelled = threading.Event()
    cancelled.set()
    token = download.CANCELLED.set(cancelled)
    try:
        data = download.supervise([], "arsim", "3" * 32, time.monotonic() + 10)
    finally:
        download.CANCELLED.reset(token)
    assert data["error_code"] == "OPERATION_CANCELLED"
    assert data["download_state"] == "not_started" and data["process_id"] is None
