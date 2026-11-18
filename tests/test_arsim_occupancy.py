import importlib
import json
import socket
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "mcp_server"))
toolchain = importlib.import_module("toolchain")


def test_detects_listener_on_selected_address():
    with socket.socket() as listener:
        listener.bind(("127.0.0.5", 11169))
        listener.listen()
        result = toolchain.plc_check_arsim_occupancy({"addresses": ["127.0.0.5"], "timeout_seconds": 30})
    assert result["slots"][0]["state"] == "blocked"
    assert any(item["port"] == 11169 and item["pid"] == os.getpid() for item in result["slots"][0]["conflicts"])


def test_rejects_non_loopback():
    with pytest.raises(ValueError):
        toolchain.plc_check_arsim_occupancy({"addresses": ["192.168.0.1"]})
