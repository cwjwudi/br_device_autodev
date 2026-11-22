from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

import plc_logger_read  # noqa: E402
import toolchain  # noqa: E402
from project_config import load_project_config  # noqa: E402


SAMPLE_CSVX = """Origin="C:\\Temp\\$arlogsys.bin" formatVersion="1" Count="4"

Severity;RecordID;Time;ID;Area;Entered by;Origin;ASCII Data;Binary Data;Logbook
"Info";"1";"2026-11-22T03:40:01.036000";"31280";"0";"ROOT";;"base log module created";"00";"$arlogsys"
"Warning";"2";"2026-11-22T03:40:09.042000";"30030";"0";"PnPManager";;"SS2.IF1";"00";"$arlogsys"
"Success";"3";"2026-11-22T03:40:14.490000";"3157279";"0";"ROOT";;"Configuration ID="AcpTrakEasy" Configuration version="1.0.0"";"43";"$arlogsys"
"Error";"4";"2026-11-22T03:41:22.671000";"9210";"0";"ROOT";;"Drive communication fault";"00";"$arlogsys"
"""


def _make_project(tmp_path: Path, *, logger_cfg: object = None, extra: dict | None = None) -> tuple[Path, Path]:
    apj = tmp_path / "Demo.apj"
    apj.write_text("<Project/>", encoding="utf-8")
    cfg: dict = {
        "project_path": "Demo.apj",
        "config": "Sim",
        "toolchain": "as6_default",
        "target": "arsim",
        "targets": {
            "arsim": {"ip": "127.0.0.1", "role": "arsim"},
            "prod": {"ip": "192.0.2.10", "role": "production"},
        },
    }
    if logger_cfg is not None:
        cfg["logger"] = logger_cfg
    if extra:
        cfg.update(extra)
    cfg_path = tmp_path / "br-auto-dev.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return apj, cfg_path


def test_project_config_validates_logger_fields(tmp_path: Path) -> None:
    apj, cfg_path = _make_project(tmp_path, logger_cfg={"enabled": True})
    loaded, _ = load_project_config(str(apj), REPO_ROOT)
    assert loaded["logger"]["enabled"] is True

    _, cfg_path = _make_project(tmp_path, logger_cfg={"enabled": "yes"})
    try:
        load_project_config(str(apj), REPO_ROOT)
        raise AssertionError("Expected ValueError for non-boolean logger.enabled")
    except ValueError as exc:
        assert "logger.enabled" in str(exc)

    _, cfg_path = _make_project(tmp_path, extra={"allow_logger": "true"})
    try:
        load_project_config(str(apj), REPO_ROOT)
        raise AssertionError("Expected ValueError for non-boolean allow_logger")
    except ValueError as exc:
        assert "allow_logger" in str(exc)


def test_validate_request_uses_project_level_logger_toggle() -> None:
    base_cfg = {"targets": {"arsim": {"ip": "127.0.0.1", "role": "arsim"}}}

    # Missing logger opt-in -> denied
    _, errors = plc_logger_read.validate_request(
        config=base_cfg,
        target="arsim",
        logger_type="System",
        logger_name="$arlogsys",
        fmt=".csvx",
    )
    assert errors and "logger.enabled" in errors[0]

    # Explicit logger.enabled=true -> allows any non-safety module without per-module whitelist
    enabled_cfg = {**base_cfg, "logger": {"enabled": True}}
    for ltype, lname in (("System", "$arlogsys"), ("User", "$arlogusr"), ("Named", "$motion")):
        _, errors = plc_logger_read.validate_request(
            config=enabled_cfg,
            target="arsim",
            logger_type=ltype,
            logger_name=lname,
            fmt=".csvx",
        )
        assert errors == [], (ltype, lname, errors)

    # Shorthand allow_logger=true works too
    _, errors = plc_logger_read.validate_request(
        config={**base_cfg, "allow_logger": True},
        target="arsim",
        logger_type="Named",
        logger_name="$motion",
        fmt=".csvx",
    )
    assert errors == []

    # Explicit logger.enabled=false overrides even allow_logger=true
    _, errors = plc_logger_read.validate_request(
        config={**base_cfg, "allow_logger": True, "logger": {"enabled": False}},
        target="arsim",
        logger_type="System",
        logger_name="$arlogsys",
        fmt=".csvx",
    )
    assert errors

    # Safety remains immutably blocked
    _, errors = plc_logger_read.validate_request(
        config=enabled_cfg,
        target="arsim",
        logger_type="Safety",
        logger_name="$safety",
        fmt=".csvx",
    )
    assert errors and "safety" in errors[0].lower()


def test_runtime_target_without_project_config_allows_non_safety_logger() -> None:
    target_cfg, errors = plc_logger_read.validate_request(
        config=None,
        target="discovered-127-0-0-9",
        logger_type="Named",
        logger_name="$motion",
        fmt=".csvx",
        target_ip="127.0.0.9",
        target_role="arsim",
        require_config_opt_in=False,
    )
    assert errors == []
    assert target_cfg["ip"] == "127.0.0.9"


def test_parse_csvx_summary_handles_metadata_quotes_filter_and_order(tmp_path: Path) -> None:
    csvx_path = tmp_path / "sample.csvx"
    csvx_path.write_text(SAMPLE_CSVX, encoding="utf-8")

    newest = plc_logger_read.parse_csvx_summary(csvx_path, limit=2, order="newest")
    assert newest["total_entries"] == 4
    assert newest["filtered_entries"] == 4
    assert newest["latest_timestamp"] == "2026-11-22T03:41:22.671000"
    assert newest["severity_counts"] == {"Info": 1, "Warning": 1, "Success": 1, "Error": 1}
    assert [item["record_id"] for item in newest["entries"]] == ["4", "3"]
    assert newest["entries"][1]["message"] == 'Configuration ID="AcpTrakEasy" Configuration version="1.0.0"'

    filtered = plc_logger_read.parse_csvx_summary(csvx_path, limit=10, severity="error,warning", order="oldest")
    assert filtered["filtered_entries"] == 2
    assert [item["record_id"] for item in filtered["entries"]] == ["2", "4"]


def test_read_logger_direct_execution_cleans_temp_files_on_success(tmp_path: Path) -> None:
    transfer_exe = tmp_path / "PVITransfer.exe"
    transfer_exe.write_text("", encoding="utf-8")
    out_file = tmp_path / "out" / "sys.csvx"

    def fake_exec(*, pvi_transfer_path, pil_path, log_path, timeout_seconds=120, grace_seconds=2.0):
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(SAMPLE_CSVX, encoding="utf-8")
        lines = [
            "PROCESS STARTED: 22-11-2026, 11:41:32",
            'Logger "System", "$arlogsys", ".csvx", "...", "en" SUCCESSFUL',
            "PROCESS FINISHED (SUCCESS): 22-11-2026, 11:41:33",
        ]
        log_path.write_text("\n".join(lines), encoding="utf-8")
        return 0, lines, False

    with patch.object(plc_logger_read, "execute_pvitransfer_silent", side_effect=fake_exec):
        report = plc_logger_read.read_logger(
            target="arsim",
            pvi_transfer_path=transfer_exe,
            config={"targets": {"arsim": {"ip": "127.0.0.1", "role": "arsim"}}, "logger": {"enabled": True}},
            output_path=str(out_file),
            keep_temp_files=False,
            repo_root=tmp_path,
        )

    assert report["ok"] is True
    assert report["format"] == ".csvx"
    assert report["pil_path"] is None
    assert report["log_path"] is None
    assert not out_file.with_suffix(".csvx.pil").exists()
    assert report["summary"]["total_entries"] == 4


def test_mcp_plc_read_logger_uses_project_config_directly(tmp_path: Path) -> None:
    apj, _ = _make_project(tmp_path, logger_cfg={"enabled": True})
    fake_report = {
        "command": "ReadLogger",
        "ok": True,
        "target": "arsim",
        "logger_type": "Named",
        "logger_name": "$motion",
        "format": ".csvx",
        "output_path": str(REPO_ROOT / "var" / "logger" / "dummy.csvx"),
        "output_exists": True,
    }
    with patch.object(plc_logger_read, "read_logger", return_value=fake_report) as mock_read:
        result = toolchain.plc_read_logger(
            {
                "project_path": str(apj),
                "target": "arsim",
                "logger_type": "Named",
                "logger_name": "$motion",
            }
        )

    assert result["ok"] is True
    assert result["data"]["format"] == ".csvx"
    kwargs = mock_read.call_args.kwargs
    assert kwargs["require_config_opt_in"] is True
    assert kwargs["config"]["logger"]["enabled"] is True
    assert kwargs["keep_temp_files"] is False
