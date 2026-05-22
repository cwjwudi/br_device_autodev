from __future__ import annotations

from typing import Any


COMMON_PROPERTIES: dict[str, Any] = {
    "target": {
        "type": "string",
        "description": "Target name from tools/plc_targets.local.json. Defaults to arsim.",
        "default": "arsim",
    },
    "project_path": {
        "type": "string",
        "description": "Automation Studio project path, relative to the repository root unless absolute.",
        "default": "PrintDemo\\Huitong_FrontEval.apj",
    },
    "config": {
        "type": "string",
        "description": "Automation Studio configuration name.",
        "default": "Config1",
    },
    "targets_path": {
        "type": "string",
        "description": "Toolchain target configuration JSON path.",
        "default": "tools\\plc_targets.local.json",
    },
    "timeout_seconds": {
        "type": "integer",
        "description": "Maximum seconds to wait for the local CLI command.",
        "minimum": 1,
    },
}


def object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    merged = dict(COMMON_PROPERTIES)
    merged.update(properties)
    return {
        "type": "object",
        "properties": merged,
        "additionalProperties": False,
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "plc_probe_target",
        "description": "Read-only probe of a configured B&R PLC/ARsim target via PVITransfer. Returns CPU type, AR version, PLC status, and log paths.",
        "inputSchema": object_schema({}),
    },
    {
        "name": "plc_read_pvi",
        "description": "Read whitelisted or explicitly supplied PLC variables via PVI using hilch/Pvi.py. This is read-only feedback verification.",
        "inputSchema": object_schema(
            {
                "pvi_variables": {
                    "type": "array",
                    "description": "Optional PVI variable specs. Examples: gstHmi.stOutputs.diSImage, SVG:strTransform, ns=5;s=::SVG:strTransform.",
                    "items": {"type": "string"},
                }
            }
        ),
    },
    {
        "name": "plc_check_download",
        "description": "Run the download safety check without downloading. Compares the RUC package metadata with the target probe result.",
        "inputSchema": object_schema(
            {
                "package_path": {
                    "type": "string",
                    "description": "Optional RUC package zip path.",
                },
                "transfer_pil_path": {
                    "type": "string",
                    "description": "Optional Transfer.pil path.",
                },
            }
        ),
    },
]
