import json
import os
from pathlib import Path
import subprocess
import sys


def test_stdio_uses_utf8_under_legacy_default_encoding():
    root = Path(__file__).resolve().parents[1]
    request = {"jsonrpc": "2.0", "id": "下载-1", "method": "未注册"}
    completed = subprocess.run(
        [sys.executable, str(root / "tools" / "mcp_server" / "server.py")],
        input=(json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"),
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        timeout=10,
        check=True,
    )
    assert completed.stdout.count(b"\n") == 1
    response = json.loads(completed.stdout.decode("utf-8"))
    assert response["id"] == "下载-1"
    assert response["error"]["message"] == "Method not found: 未注册"
