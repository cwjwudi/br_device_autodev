import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from pvi_read import compact_variable_name, compact_variable_result  # noqa: E402


def test_compact_success_result_contains_only_public_value_fields() -> None:
    parsed = {"name": "bAlive", "raw": "gstAtStatus.stApplication.bAlive"}

    result = compact_variable_result(
        "gstAtStatus.stApplication.bAlive",
        parsed,
        value=True,
        data_type="boolean",
    )

    assert result == {
        "name": "gstAtStatus.stApplication.bAlive",
        "value": True,
        "type": "boolean",
    }


def test_compact_task_name_preserves_requested_address() -> None:
    raw = {"name": "bReady", "task": "MainTask"}
    parsed = {"name": "bReady", "scope": "task", "task": "MainTask"}

    assert compact_variable_name(raw, parsed) == "MainTask:bReady"


def test_compact_error_result_contains_variable_and_error_only() -> None:
    parsed = {"name": "bAlive", "raw": "bAlive"}

    result = compact_variable_result(
        "bAlive",
        parsed,
        error="PVI variable not found",
    )

    assert result == {"name": "bAlive", "error": "PVI variable not found"}
