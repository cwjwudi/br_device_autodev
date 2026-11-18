import importlib
import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "mcp_server"))
toolchain = importlib.import_module("toolchain")


def test_detects_listener_on_selected_address():
    with socket.socket() as listener:
        listener.bind(("127.0.0.2", 11169))
        listener.listen()
        result = toolchain.plc_check_arsim_occupancy({"addresses": ["127.0.0.1", "127.0.0.2"], "timeout_seconds": 30})
    assert result["slots"][0]["state"] == "free"
    assert result["slots"][1]["state"] == "blocked"
    assert result["slots"][1]["conflicts"][0]["port"] == 11169


def test_rejects_non_loopback():
    with pytest.raises(ValueError):
        toolchain.plc_check_arsim_occupancy({"addresses": ["192.168.0.1"]})
