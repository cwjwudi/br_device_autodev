from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "mcp_server"))

import toolchain  # noqa: E402


class _TimedOutProcess:
    pid = 12345
    returncode = None

    def __init__(self) -> None:
        self.calls = 0

    def communicate(self, timeout=None):
        self.calls += 1
        if self.calls == 1:
            raise subprocess.TimeoutExpired(cmd="Download", timeout=timeout)
        self.returncode = 1
        return "", ""

    def kill(self) -> None:
        self.returncode = 1


def test_outer_timeout_uses_successful_transfer_log(tmp_path, monkeypatch) -> None:
    operation_id = "operation-success-log"
    log_path = tmp_path / "var" / "downloads" / operation_id / "pvi_download_arsim.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        'Transfer "RUCPackage.zip" SUCCESSFUL\nPROCESS FINISHED (SUCCESS)\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(toolchain, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(toolchain, "DOWNLOAD_LOG_SUCCESS_GRACE_SECONDS", 0.0)

    with patch.object(toolchain.subprocess, "Popen", return_value=_TimedOutProcess()), patch.object(
        toolchain, "terminate_process_tree", return_value={"attempted": True, "succeeded": True}
    ):
        result = toolchain.run_plc_toolchain(
            "Download",
            target="arsim",
            operation_id=operation_id,
            timeout_seconds=1,
        )

    assert result["ok"] is True
    assert result["download_ok"] is True
    assert result["deployment_state"] == "transfer_completed"
    assert result["log_path"] == str(log_path)
