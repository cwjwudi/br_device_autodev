from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_state_is_not_stored_under_tools() -> None:
    assert not (ROOT / "tools" / ".generated").exists()


def test_configuration_is_kept_out_of_tools() -> None:
    config_suffixes = {".json", ".yaml", ".yml", ".toml"}
    misplaced = [
        path
        for path in (ROOT / "tools").rglob("*")
        if path.is_file() and path.suffix.lower() in config_suffixes
    ]
    assert misplaced == []


def test_repository_script_categories_exist() -> None:
    assert (ROOT / "scripts" / "windows" / "invoke-pvitransfer-silent.ps1").is_file()
    assert (ROOT / "scripts" / "maintenance" / "generate_mcp_docs.py").is_file()
