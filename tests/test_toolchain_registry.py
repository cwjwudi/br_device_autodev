from __future__ import annotations

import json

import pytest

from br_plc_toolchain.config import ConfigError, list_toolchains, resolve_toolchain


def write_registry(tmp_path):
    root = tmp_path / "AS"
    build = root / "bin-en" / "BR.AS.Build.exe"
    transfer = root / "PVI" / "PVITransfer.exe"
    build.parent.mkdir(parents=True)
    transfer.parent.mkdir(parents=True)
    build.touch()
    transfer.touch()
    (root / "PVI" / "PviCom64.dll").touch()
    path = tmp_path / "toolchains.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default_toolchain": "as4_test",
                "toolchains": {
                    "as4_test": {
                        "family": "AS4",
                        "version": "4.12",
                        "automation_studio": {
                            "install_root": str(root),
                            "bin_dir": str(build.parent),
                            "build_exe": str(build),
                            "library_roots": [str(root / "Libraries")],
                        },
                        "pvi": {
                            "family": "PVI4",
                            "transfer_exe": str(transfer),
                            "dll_dir": str(root / "PVI"),
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path, build


def test_resolve_default_as4_toolchain(tmp_path) -> None:
    path, build = write_registry(tmp_path)
    resolved = resolve_toolchain(registry_path=path)
    assert resolved.id == "as4_test"
    assert resolved.family == "AS4"
    assert resolved.pvi_family == "PVI4"
    assert resolved.build_exe == build


def test_list_toolchains_reports_actual_availability(tmp_path) -> None:
    path, _ = write_registry(tmp_path)
    result = list_toolchains(registry_path=path)
    assert result["toolchains"][0]["available"] is True


def test_unknown_toolchain_is_rejected(tmp_path) -> None:
    path, _ = write_registry(tmp_path)
    with pytest.raises(ConfigError, match="Unknown toolchain"):
        resolve_toolchain("as6_missing", registry_path=path)
