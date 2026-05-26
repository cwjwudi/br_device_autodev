from __future__ import annotations

from typing import Any


COMMON_PROPERTIES: dict[str, Any] = {
    "environment": {
        "type": "string",
        "description": "Named PLC toolchain environment from tools/plc_environments.json. Explicit target/project_path/config/targets_path arguments override the environment defaults.",
    },
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
        "default": "x1685",
    },
    "targets_path": {
        "type": "string",
        "description": "Toolchain target configuration JSON path. Overrides environment.targets_path when supplied.",
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
            "description": "Must be set to true to actually perform the gated action. Required for safety.",
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
                    "description": "Optional path to the RUC package zip. Defaults to PrintDemo/Binaries/x1685/X20CP1685/RUCPackage/RUCPackage.zip.",
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
    {
        "name": "plc_read_logger",
        "description": "Read a whitelisted PLC/AR logger module through PVITransfer Logger. Returns report/log paths and a compact summary, never raw HTML/CSV content.",
        "inputSchema": object_schema(
            {
                "logger_type": {
                    "type": "string",
                    "description": "Logger module type, for example System, User, or Connectivity.",
                    "default": "System",
                },
                "logger_name": {
                    "type": "string",
                    "description": "Logger module name, for example $arlogsys, $arlogusr, or $arlogconn.",
                    "default": "$arlogsys",
                },
                "format": {
                    "type": "string",
                    "description": "Output format. Supported values: .html, .csvx, .arl, .logpkg.",
                    "default": ".html",
                    "enum": [".html", ".csvx", ".arl", ".logpkg"],
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional output file or directory. Must stay inside the repository. Defaults to tools/.generated/logger/.",
                },
            }
        ),
    },
    {
        "name": "plc_write_pvi",
        "description": "Write PVI test harness variables that are explicitly listed in pvi.write_whitelist. Requires execute=true and refuses production targets.",
        "inputSchema": build_schema(
            {
                "writes": {
                    "type": "array",
                    "description": "Write objects such as {\"variable\":\"LQR:bLqrEnable\",\"value\":true}. Every variable must be in pvi.write_whitelist.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "variable": {"type": "string"},
                            "value": {},
                        },
                        "required": ["variable", "value"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                },
            },
            require_execute=True,
            require_timeout=True,
        ),
    },
    {
        "name": "plc_run_arsim_closed_loop",
        "description": "Run the standard ARsim closed loop: build RUC package, start ARsim, probe, describe package, safety check, optional explicit download, and verification report.",
        "inputSchema": build_schema(
            {},
            require_execute=True,
            require_timeout=True,
        ),
    },
    {
        "name": "plc_run_verification_suite",
        "description": "Run feedback verification and write a unified report. OPC UA is attempted first; PVI is used as a fallback.",
        "inputSchema": object_schema({}),
    },
    {
        "name": "plc_run_io_test_case",
        "description": "Run one PLC IO test case from a suite: reset, whitelisted PVI writes, settle, readback, checks, and restore.",
        "inputSchema": build_schema(
            {
                "suite_path": {
                    "type": "string",
                    "description": "Path to a PLC IO test suite JSON file.",
                    "default": "tests\\plc\\lqr_io_tests.json",
                },
                "case_name": {
                    "type": "string",
                    "description": "Name of the test case to run.",
                },
                "settle_ms": {
                    "type": "integer",
                    "description": "Default milliseconds to wait after writes when the case does not override settle_ms.",
                    "minimum": 0,
                    "default": 100,
                },
            },
            require_execute=True,
            require_timeout=True,
        ),
    },
    {
        "name": "plc_run_test_suite",
        "description": "Run a full PLC IO test suite and write a report with per-case writes, readback, checks, and restore results.",
        "inputSchema": build_schema(
            {
                "suite_path": {
                    "type": "string",
                    "description": "Path to a PLC IO test suite JSON file.",
                    "default": "tests\\plc\\lqr_io_tests.json",
                },
                "settle_ms": {
                    "type": "integer",
                    "description": "Default milliseconds to wait after writes when cases do not override settle_ms.",
                    "minimum": 0,
                    "default": 100,
                },
            },
            require_execute=True,
            require_timeout=True,
        ),
    },
    {
        "name": "plc_reset_test_harness",
        "description": "Restore/reset the PLC test harness using pvi.restore_writes. Requires execute=true and refuses production targets.",
        "inputSchema": build_schema(
            {
                "suite_path": {
                    "type": "string",
                    "description": "Optional suite path used only for report context.",
                    "default": "tests\\plc\\lqr_io_tests.json",
                },
            },
            require_execute=True,
            require_timeout=True,
        ),
    },
    {
        "name": "plc_get_target_config",
        "description": "Read the configured target entry, OPC UA whitelist, and PVI whitelist for a target.",
        "inputSchema": object_schema({}),
    },
    {
        "name": "plc_list_targets",
        "description": "List configured PLC/ARsim targets with IP, role, and automatic-download permission.",
        "inputSchema": object_schema({}),
    },
    {
        "name": "plc_list_environments",
        "description": "List named PLC toolchain environments from tools/plc_environments.json for one-step switching.",
        "inputSchema": object_schema({}),
    },
]
