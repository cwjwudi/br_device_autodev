from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_default_targets_are_conservative() -> None:
    config = json.loads((ROOT / "config/targets/default-safe.json").read_text(encoding="utf-8-sig"))
    assert config["access_policy"]["mode"] == "whitelist"
    for target in config["targets"].values():
        if target["role"] != "arsim":
            assert target["allow_auto_download"] is False


def test_project_example_loads_with_a_real_project(tmp_path) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "tools/mcp_server"))
    from project_config import load_project_config

    example = json.loads((ROOT / "config/examples/br-auto-dev.example.json").read_text(encoding="utf-8"))
    (tmp_path / "Demo.apj").write_text("<Project/>", encoding="utf-8")
    (tmp_path / "br-auto-dev.json").write_text(json.dumps(example), encoding="utf-8")
    config, path = load_project_config(str(tmp_path), ROOT)
    assert path == tmp_path / "br-auto-dev.json"
    assert config["target"] == "arsim"
    assert config["project_path"] == str(tmp_path / "Demo.apj")
