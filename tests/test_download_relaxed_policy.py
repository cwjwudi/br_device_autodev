from __future__ import annotations

from pathlib import Path

from tools.mcp_server.schemas import TOOL_DEFINITIONS


ROOT = Path(__file__).resolve().parents[1]


def _tool(name: str) -> dict:
    return next(item for item in TOOL_DEFINITIONS if item["name"] == name)


def test_download_tools_expose_explicit_safety_bypass() -> None:
    for name in ("plc_check_download", "plc_download_ruc", "plc_run_arsim_closed_loop"):
        properties = _tool(name)["inputSchema"]["properties"]
        assert properties["bypass_download_safety"]["default"] is False
        assert "force_arsim_download" in properties


def test_powershell_keeps_hard_guards_but_relaxes_compatibility() -> None:
    script = (ROOT / "tools" / "plc_toolchain.ps1").read_text(encoding="utf-8-sig")
    assert '$isTrustedDevelopmentTarget = $targetRole -in @("arsim", "dedicated_test_plc")' in script
    assert "Target '$Target' does not allow automatic download." in script
    assert "A physical PLC RUC package cannot be downloaded to ARsim." in script
    assert "Compatibility warning: $reason" in script
    assert "safety_bypassed = $safetyBypassed" in script
    assert "incremental Transfer" not in script
