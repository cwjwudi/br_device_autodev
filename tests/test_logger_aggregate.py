from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import plc_logger_read  # noqa: E402


def _write_csvx(path: Path, rows: list[str]) -> None:
    header = 'Origin="ARsim" formatVersion="1"\nTime;Severity;Event ID;Object ID;Description\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")


def test_diagnose_loggers_mixed_success_missing_and_safety_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called_modules: list[tuple[str, str]] = []

    def fake_read_logger(**kwargs: Any) -> dict[str, Any]:
        ltype = kwargs["logger_type"]
        lname = kwargs["logger_name"]
        called_modules.append((ltype, lname))
        out = tmp_path / f"{ltype}_{lname.replace('$', '')}.csvx"
        if lname == "$arlogsys":
            _write_csvx(
                out,
                [
                    '2026-11-24T12:00:00Z;Info;1001;Sys;System booted',
                    '2026-11-24T12:05:00Z;Warning;2001;Sys;Watchdog "near" limit 中文提示',
                    '2026-11-24T12:10:00Z;Error;3001;Sys;Task cycle violation',
                ],
            )
            return {"ok": True, "output_path": str(out)}
        if lname == "$motion":
            _write_csvx(
                out,
                [
                    '2026-11-24T12:08:00Z;Error;9001;Axis1;Following error exceeded',
                ],
            )
            return {"ok": True, "output_path": str(out)}
        return {"ok": False, "output_path": str(out), "error_summary": "Module not found"}

    monkeypatch.setattr(plc_logger_read, "read_logger", fake_read_logger)

    result = plc_logger_read.diagnose_loggers(
        target="arsim",
        pvi_transfer_path=tmp_path / "PVITransfer.exe",
        modules=[
            ("System", "$arlogsys"),
            ("Motion", "$motion"),
            ("Fieldbus", "$fieldbus"),
            ("Safety", "$arlogsafe"),
        ],
        min_severity="warning",
        max_entries=10,
        config={"logger": {"enabled": True}, "targets": {"arsim": {"ip": "127.0.0.1", "role": "arsim"}}},
        now=datetime(2026, 11, 24, 12, 15, 0, tzinfo=timezone.utc),
    )

    # Safety module must NEVER be passed to read_logger
    assert ("Safety", "$arlogsafe") not in called_modules
    assert result["ok"] is True
    assert len(result["blocked_modules"]) == 1
    assert result["blocked_modules"][0]["error_code"] == "SAFETY_LOGGER_BLOCKED"

    statuses = {item["module"]: item["status"] for item in result["modules"]}
    assert statuses["System/$arlogsys"] == "ok"
    assert statuses["Motion/$motion"] == "ok"
    assert statuses["Fieldbus/$fieldbus"] == "missing_or_empty"
    assert statuses["Safety/$arlogsafe"] == "blocked_safety"

    # Info entry filtered out; 3 entries remain sorted newest first
    assert result["total_entries_before_filter"] == 4
    assert result["total_entries_after_filter"] == 3
    assert [e["event_id"] for e in result["entries"]] == ["3001", "9001", "2001"]
    assert 'Watchdog "near" limit 中文提示' == result["entries"][2]["description"]


def test_diagnose_loggers_since_minutes_and_max_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_read_logger(**kwargs: Any) -> dict[str, Any]:
        out = tmp_path / "sys.csvx"
        _write_csvx(
            out,
            [
                "2026-11-24T10:00:00Z;Error;1;Sys;Too old",
                "2026-11-24T11:55:00Z;Warning;2;Sys;Recent warning",
                "2026-11-24T11:58:00Z;Error;3;Sys;Recent error 1",
                "2026-11-24T11:59:00Z;Error;4;Sys;Recent error 2",
            ],
        )
        return {"ok": True, "output_path": str(out)}

    monkeypatch.setattr(plc_logger_read, "read_logger", fake_read_logger)

    result = plc_logger_read.diagnose_loggers(
        target="arsim",
        pvi_transfer_path=tmp_path / "PVITransfer.exe",
        modules=["System/$arlogsys"],
        min_severity="error",
        since_minutes=10,
        max_entries=1,
        config={"logger": {"enabled": True}, "targets": {"arsim": {"ip": "127.0.0.1", "role": "arsim"}}},
        now=datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert result["ok"] is True
    assert result["total_entries_after_filter"] == 2
    assert result["returned_entries"] == 1
    assert result["entries"][0]["event_id"] == "4"


def test_diagnose_loggers_all_safety_fails_with_blocked_code(tmp_path: Path) -> None:
    result = plc_logger_read.diagnose_loggers(
        target="arsim",
        pvi_transfer_path=tmp_path / "PVITransfer.exe",
        modules=["Safety/$arlogsafe"],
        config={"logger": {"enabled": True}, "targets": {"arsim": {"ip": "127.0.0.1", "role": "arsim"}}},
    )
    assert result["ok"] is False
    assert result["error_code"] == "SAFETY_LOGGER_BLOCKED"
