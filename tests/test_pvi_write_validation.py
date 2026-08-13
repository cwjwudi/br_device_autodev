import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from pvi_write import coerce_scalar, verify_write_result  # noqa: E402


def test_invalid_bool_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="Cannot convert"):
        coerce_scalar("maybe", "BOOL")


def test_pvi_write_requires_matching_readback() -> None:
    result = verify_write_result(True, False, 0)
    assert result["ok"] is True
    assert result["warning_code"] == "PVI_READBACK_MISMATCH"


def test_pvi_write_requires_success_status() -> None:
    result = verify_write_result(True, True, 11156)
    assert result["ok"] is False
    assert result["error_code"] == "PVI_STATUS_FAILURE"
    assert result["status_code"] == 11156
    assert "not accepted" in result["status_explanation"]


def test_pvi_write_rejects_unreadable_variable() -> None:
    result = verify_write_result(True, None, 0, readable=False)
    assert result["ok"] is True
    assert result["warning_code"] == "PVI_READBACK_UNAVAILABLE"


def test_pvi_write_accepts_structured_diagnostic_status() -> None:
    result = verify_write_result(True, True, {"ST": "Var", "SC": "l"})
    assert result["ok"] is True
    assert result["status_ok"] is None
    assert result["readback_verified"] is True
