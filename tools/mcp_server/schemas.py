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


def build_schema(
    properties: dict[str, Any],
    *,
    require_execute: bool = False,
    require_timeout: bool = False,
) -> dict[str, Any]:
    merged = dict(COMMON_PROPERTIES)
    merged.update(properties)
    if require_execute:
        merged["execute"] = {
            "type": "boolean",
            "description": "Must be set to true to actually execute the download. Required for safety.",
        }
    if require_timeout:
        merged.setdefault(
            "timeout_seconds",
            {
                "type": "integer",
                "description": "Maximum seconds to wait for the local CLI command.",
                "minimum": 1,
            },
        )
    return {
        "type": "object",
        "properties": merged,
        "additionalProperties": False,
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "plc_build_project",
        "description": "Build the B&R Automation Studio project. Optionally generate a RUC package for download.",
        "inputSchema": build_schema(
            {
                "build_ruc_package": {
                    "type": "boolean",
                    "description": "If true, pass -buildRUCPackage to generate a RUC package for subsequent download.",
                    "default": False,
                },
            },
            require_timeout=True,
        ),
    },
    {
        "name": "plc_start_arsim",
        "description": "Start or reuse an existing ARsim simulation instance for the specified target.",
        "inputSchema": build_schema(
            {
                "start_wait_seconds": {
                    "type": "integer",
                    "description": "Seconds to wait after starting the ARsim loader before returning.",
                    "default": 3,
                    "minimum": 0,
                },
            },
        ),
    },
    {
        "name": "plc_probe_target",
        "description": "Read-only probe of a configured B&R PLC/ARsim target via PVITransfer. Returns CPU type, AR version, PLC status, and log paths.",
        "inputSchema": object_schema({}),
    },
    {
        "name": "plc_describe_ruc_package",
        "description": "Read the metadata of a RUC package zip file: CPU type, AR version, config version, runtime type, etc.",
        "inputSchema": build_schema(
            {
                "package_path": {
                    "type": "string",
                    "description": "Optional path to the RUC package zip. Defaults to PrintDemo/Binaries/Config1/X20CP3687X/RUCPackage/RUCPackage.zip.",
                },
            },
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
    {
        "name": "plc_download_ruc",
        "description": "Download the RUC package to the target. Safety gate: requires execute=true, and plc_check_download must pass on the server side before actual transfer.",
        "inputSchema": build_schema(
            {
                "package_path": {
                    "type": "string",
                    "description": "Optional RUC package zip path.",
                },
                "transfer_pil_path": {
                    "type": "string",
                    "description": "Optional Transfer.pil path.",
                },
            },
            require_execute=True,
            require_timeout=True,
        ),
    },
    {
        "name": "plc_verify_opcua",
        "description": "Read OPC UA validation nodes from the target. Returns values, types, and timestamps for each configured node.",
        "inputSchema": build_schema(
            {
                "opcua_node_ids": {
                    "type": "array",
                    "description": "Optional OPC UA node IDs to read. Overrides the whitelist in plc_targets.local.json.",
                    "items": {"type": "string"},
                },
            },
        ),
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
]
