from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


def test_all_examples_load_and_physical_download_is_disabled_by_default(tmp_path) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "tools/mcp_server"))
    from project_config import load_project_config

    (tmp_path / "Demo.apj").write_text("<Project/>", encoding="utf-8")
    for example_path in (ROOT / "config/examples").glob("*.json"):
        example = json.loads(example_path.read_text(encoding="utf-8"))
        (tmp_path / "br-auto-dev.json").write_text(json.dumps(example), encoding="utf-8")
        config, _ = load_project_config(str(tmp_path), ROOT)
        target = config["targets"][config["target"]]
        if target["role"] != "arsim":
            assert not target.get("allow_auto_download", False)
