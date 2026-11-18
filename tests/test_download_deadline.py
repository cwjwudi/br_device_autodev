import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "mcp_server"))
import download
from download_job import remaining_processes


def test_download_timeout_configuration(tmp_path, monkeypatch):
    assert download.download_timeout({}, None) == 60
    assert download.download_timeout({}, 180) == 60
    assert download.download_timeout({"download": {"timeout_seconds": 25}}, 45) == 25
    assert download.download_timeout({"download": {"timeout_seconds": 25}}, 4) == 4
    for bad in (None, {}, {"timeout_seconds": True}, {"timeout_seconds": 61}):
        with pytest.raises(ValueError, match="download.timeout_seconds"):
            download.download_timeout({"download": bad}, 8)
    defaults = tmp_path / "base.json"
    defaults.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(download, "DOWNLOAD_DEFAULTS", defaults)
    with pytest.raises(ValueError, match="download.timeout_seconds"):
        download.download_timeout({}, None)


def test_sharing_conflict_and_conflicting_log(tmp_path, monkeypatch):
    log = tmp_path / "transfer.log"
    log.write_text("Transfer RUC SUCCESSFUL\nPROCESS FINISHED (ERROR)\n", encoding="utf-8")
    assert download.read_transfer_log(log)[0] == "conflicting"
    with monkeypatch.context() as context:
        def sharing_violation(*args, **kwargs):
            raise PermissionError("sharing violation")
        context.setattr(Path, "open", sharing_violation)
        assert download.read_transfer_log(log) == ("unreadable", "sharing violation")
    assert download.read_transfer_log(log)[0] == "conflicting"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object")
def test_success_evidence_does_not_interrupt_followup_and_timeout_reaps_descendants(tmp_path, monkeypatch):
    operation_id = uuid.uuid4().hex
    monkeypatch.setattr(download, "DOWNLOAD_ROOT", tmp_path)
    evidence_dir = tmp_path / operation_id
    evidence_dir.mkdir()
    (evidence_dir / "transfer-started").touch()
    log = evidence_dir / "pvi_download_arsim.log"
    script = (
        "import pathlib, subprocess, sys, time;"
        "assert int(input()) > 0;"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']);"
        f"pathlib.Path({str(log)!r}).write_text('Transfer RUC SUCCESSFUL');"
        "time.sleep(30)"
    )
    started = time.monotonic()
    result = download.supervise([sys.executable, "-c", script], "arsim", operation_id, started + 1.6)
    assert 1.0 < time.monotonic() - started < 1.9
    assert result["error_code"] == "DOWNLOAD_TIMEOUT"
    assert result["download_state"] == "transfer_succeeded"
    assert result["deployment_state"] == "transfer_completed"
    assert result["cleanup"]["succeeded"]
    assert remaining_processes(operation_id) == 0
