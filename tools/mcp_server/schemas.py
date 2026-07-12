from __future__ import annotations

from typing import Any


COMMON_PROPERTIES: dict[str, Any] = {
    "environment": {
        "type": "string",
        "description": "Named PLC toolchain environment from config/environments/environments.json. Explicit arguments override environment defaults.",
    },
    "target": {
        "type": "string",
        "description": "Target name from the selected targets file. Target-changing tools require an explicit target or environment; read-only and local tools fall back to arsim.",
        "minLength": 1,
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
        "default": "config\\targets\\default-safe.json",
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


def required_schema(schema: dict[str, Any], *required: str) -> dict[str, Any]:
    result = dict(schema)
    result["required"] = list(dict.fromkeys([*(schema.get("required") or []), *required]))
    return result


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
    schema = {
        "type": "object",
        "properties": merged,
        "additionalProperties": False,
    }
    if require_execute:
        schema["required"] = ["execute"]
    return schema


RUNTIME_TARGET_PROPERTIES: dict[str, Any] = {
    "target": {
        "type": "string",
        "description": "Runtime target name created during online discovery.",
        "minLength": 1,
    },
    "ip": {
        "type": "string",
        "description": "PLC/ARsim IP; required when first discovering a runtime target.",
        "minLength": 1,
    },
    "declared_role": {
        "type": "string",
        "description": "Explicit user declaration; omit for unknown read-only discovery.",
        "enum": ["dedicated_test_plc", "production", "arsim"],
    },
}


def runtime_schema(
    properties: dict[str, Any], *required: str, include_target: bool = True
) -> dict[str, Any]:
    merged = dict(RUNTIME_TARGET_PROPERTIES) if include_target else {}
    merged.update(properties)
    return {
        "type": "object",
        "properties": merged,
        "required": list(required),
        "additionalProperties": False,
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "plc_doctor",
        "description": "Check local Python, PowerShell, Automation Studio, PVITransfer, PVI Python dependency, target config, project/config, ARsim loader, and generated-output write access.",
        "inputSchema": object_schema({}),
    },
    {
        "name": "plc_validate_environment",
        "description": "Validate the selected environment or explicit project/config/target/targets_path mapping without connecting to a PLC.",
        "inputSchema": object_schema({}),
    },
    {
        "name": "plc_list_reports",
        "description": "List compact metadata for historical JSON reports under tools/.generated/reports without returning report bodies.",
        "inputSchema": object_schema(
            {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of newest reports to return.",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                },
                "kind": {
                    "type": "string",
                    "description": "Optional report kind filter.",
                    "enum": ["all", "io_test", "verification", "closed_loop", "reset", "build", "other"],
                    "default": "all",
                },
                "status": {
                    "type": "string",
                    "description": "Optional pass/fail filter.",
                    "enum": ["all", "passed", "failed"],
                    "default": "all",
                },
            }
        ),
    },
    {
        "name": "plc_read_report_summary",
        "description": "Read a compact summary of one JSON report confined to tools/.generated/reports. Does not return large logs or arbitrary report fields.",
        "inputSchema": required_schema(
            object_schema(
                {
                    "report_path": {
                        "type": "string",
                        "description": "Report filename or repository/report path returned by plc_list_reports.",
                        "minLength": 1,
                    },
                }
            ),
            "report_path",
        ),
    },
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
        "name": "plc_find_library_for_symbol",
        "description": "Find the trusted, locally installed Automation Studio libraries that declare a missing function, function block, type, constant, or C symbol.",
        "inputSchema": required_schema(
            object_schema(
                {
                    "symbol": {
                        "type": "string",
                        "description": "Exact unresolved symbol from Automation Studio build output, for example TcpOpen or AsTcpMcsType.",
                        "minLength": 1,
                    },
                }
            ),
            "symbol",
        ),
    },
    {
        "name": "plc_plan_project_library",
        "description": "Plan adding an installed Automation Studio library and its dependencies without modifying the project. Rejects ambiguous versions, incompatible Technology Packages, and Safety-related libraries.",
        "inputSchema": required_schema(
            object_schema(
                {
                    "library": {
                        "type": "string",
                        "description": "Exact Automation Studio library name, for example AsTCP.",
                        "minLength": 1,
                    },
                    "version": {
                        "type": "string",
                        "description": "Optional exact library or Technology Package version when more than one compatible candidate exists.",
                    },
                }
            ),
            "library",
        ),
    },
    {
        "name": "plc_add_project_library",
        "description": "Transactionally copy a trusted installed Automation Studio library and dependencies into Logical/Libraries, update Package.pkg, and rebuild by default. Requires execute=true and rolls back automatically when the validation build fails.",
        "inputSchema": required_schema(
            build_schema(
                {
                    "library": {
                        "type": "string",
                        "description": "Exact Automation Studio library name, for example AsTCP.",
                        "minLength": 1,
                    },
                    "version": {
                        "type": "string",
                        "description": "Optional exact library or Technology Package version.",
                    },
                    "rebuild": {
                        "type": "boolean",
                        "description": "Rebuild the project after adding the library and roll back on failure. Defaults to true.",
                        "default": True,
                    },
                },
                require_execute=True,
                require_timeout=True,
            ),
            "library",
            "execute",
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
            require_execute=True,
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
                "force_arsim_download": {
                    "type": "boolean",
                    "description": "If true, allow an explicit ARsim target download even when the RUC package CPU/order does not match the probed ARsim CPU. Never applies to physical or production targets.",
                    "default": False,
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
                "force_arsim_download": {
                    "type": "boolean",
                    "description": "If true with execute=true, allow an explicit ARsim target download even when the RUC package CPU/order does not match the probed ARsim CPU. Never applies to physical or production targets.",
                    "default": False,
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
                    "description": "Optional OPC UA node IDs to read. Overrides the selected target configuration whitelist.",
                    "items": {"type": "string"},
                },
            },
        ),
    },
    {
        "name": "plc_read_pvi",
        "description": "Read PLC variables via PVI using hilch/Pvi.py. Default whitelist mode requires configured variables; Agent-directed mode allows explicit variables after policy checks.",
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
        "description": "Write PVI variables under access_policy. Default whitelist mode requires pvi.write_whitelist; Agent-directed mode allows explicit variables after policy checks. Requires execute=true and refuses production targets.",
        "inputSchema": required_schema(
            build_schema(
                {
                    "writes": {
                        "type": "array",
                        "description": "Write objects such as {\"variable\":\"LQR:bLqrEnable\",\"value\":true}. Every variable must pass the current access_policy.",
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
            "writes",
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
        "description": "Run one PLC IO test case from a suite: reset, access-policy-gated PVI writes, settle, readback, checks, and restore.",
        "inputSchema": required_schema(
            build_schema(
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
            "case_name",
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
        "description": "List named PLC toolchain environments from config/environments/environments.json.",
        "inputSchema": object_schema({}),
    },
    {
        "name": "plc_list_variables",
        "description": "Build and list the PLC variable catalog, preferring fresh Automation Studio build artifacts and falling back to source scanning. Returns source, confidence, provenance, and warnings.",
        "inputSchema": object_schema({}),
    },
    {
        "name": "plc_search_variables",
        "description": "Search PLC variables by text, module/task, and read/write access while preserving catalog source, confidence, provenance, and warnings.",
        "inputSchema": object_schema(
            {
                "query": {
                    "type": "string",
                    "description": "Free-text search over variable name, task/module, PVI name, OPC UA node, type, and source path.",
                },
                "module": {
                    "type": "string",
                    "description": "Optional task/module name, for example LQR or SVG.",
                },
                "access": {
                    "type": "string",
                    "description": "Optional access filter.",
                    "enum": ["read", "write"],
                },
            }
        ),
    },
    {
        "name": "plc_discover_runtime_target",
        "description": "Connect through persistent PVI without source code or a policy file. Unknown physical targets are read-only; test roles must be explicitly declared.",
        "inputSchema": runtime_schema({}, "ip"),
    },
    {
        "name": "plc_runtime_health",
        "description": "Return persistent PVI Manager, CPU, runtime, license and cache status.",
        "inputSchema": runtime_schema({}, "target"),
    },
    {
        "name": "plc_list_runtime_tasks",
        "description": "List tasks from the running PLC image through PVI, independent of local source code.",
        "inputSchema": runtime_schema({}, "target"),
    },
    {
        "name": "plc_list_runtime_variables",
        "description": "List online task or global variables from the running PLC image through PVI.",
        "inputSchema": runtime_schema(
            {
                "scope": {"type": "string", "enum": ["task", "global"], "default": "task"},
                "task": {"type": "string"},
                "pattern": {"type": "string", "default": "*"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 200},
            },
            "target",
        ),
    },
    {
        "name": "plc_get_runtime_variable_info",
        "description": "Read online PVI type, access rights and metadata for a discovered variable.",
        "inputSchema": runtime_schema(
            {
                "scope": {"type": "string", "enum": ["task", "global"], "default": "task"},
                "task": {"type": "string"},
                "name": {"type": "string", "minLength": 1},
            },
            "target", "name",
        ),
    },
    {
        "name": "plc_read_runtime_variable",
        "description": "Read an online PVI variable. Missing external policy defaults to safe read-only discovery.",
        "inputSchema": runtime_schema(
            {
                "scope": {"type": "string", "enum": ["task", "global"], "default": "task"},
                "task": {"type": "string"},
                "name": {"type": "string", "minLength": 1},
            },
            "target", "name",
        ),
    },
    {
        "name": "plc_open_test_session",
        "description": "Open an expiring read-write session for ARsim or an explicitly declared dedicated test PLC.",
        "inputSchema": runtime_schema(
            {
                "ttl_minutes": {"type": "integer", "minimum": 1, "maximum": 480, "default": 60},
                "execute": {"type": "boolean"},
            },
            "target", "execute",
        ),
    },
    {
        "name": "plc_close_test_session",
        "description": "Close a temporary runtime PVI test session immediately.",
        "inputSchema": runtime_schema(
            {"session_id": {"type": "string", "minLength": 1}},
            "session_id",
        ),
    },
    {
        "name": "plc_write_runtime_variable",
        "description": "Write a discovered variable with before/readback verification. Changed values require a target-bound test session.",
        "inputSchema": runtime_schema(
            {
                "scope": {"type": "string", "enum": ["task", "global"], "default": "task"},
                "task": {"type": "string"},
                "name": {"type": "string", "minLength": 1},
                "value": {},
                "session_id": {"type": "string"},
                "execute": {"type": "boolean"},
            },
            "target", "name", "value", "execute",
        ),
    },
]


TOOL_RISK_LEVELS: dict[str, str] = {
    "plc_doctor": "readonly",
    "plc_validate_environment": "readonly",
    "plc_list_reports": "readonly",
    "plc_read_report_summary": "readonly",
    "plc_add_project_library": "project_write",
    "plc_build_project": "local_write",
    "plc_check_download": "local_write",
    "plc_describe_ruc_package": "readonly",
    "plc_download_ruc": "target_change",
    "plc_find_library_for_symbol": "readonly",
    "plc_get_target_config": "readonly",
    "plc_list_environments": "readonly",
    "plc_list_targets": "readonly",
    "plc_list_variables": "local_write",
    "plc_plan_project_library": "readonly",
    "plc_probe_target": "local_write",
    "plc_read_logger": "local_write",
    "plc_read_pvi": "local_write",
    "plc_reset_test_harness": "target_change",
    "plc_run_arsim_closed_loop": "target_change",
    "plc_run_io_test_case": "target_change",
    "plc_run_test_suite": "target_change",
    "plc_run_verification_suite": "local_write",
    "plc_search_variables": "local_write",
    "plc_start_arsim": "target_change",
    "plc_verify_opcua": "local_write",
    "plc_write_pvi": "target_change",
    "plc_discover_runtime_target": "local_write",
    "plc_runtime_health": "readonly",
    "plc_list_runtime_tasks": "readonly",
    "plc_list_runtime_variables": "readonly",
    "plc_get_runtime_variable_info": "readonly",
    "plc_read_runtime_variable": "readonly",
    "plc_open_test_session": "target_change",
    "plc_close_test_session": "local_write",
    "plc_write_runtime_variable": "target_change",
}

TOOL_BACKENDS: dict[str, str] = {
    "plc_doctor": "MCP native diagnostics",
    "plc_validate_environment": "MCP native diagnostics",
    "plc_list_reports": "MCP native report index",
    "plc_read_report_summary": "MCP native report summary",
    "plc_add_project_library": "as_library_manager.py add + Build",
    "plc_build_project": "Build",
    "plc_check_download": "CheckDownload",
    "plc_describe_ruc_package": "DescribePackage",
    "plc_download_ruc": "Download",
    "plc_find_library_for_symbol": "as_library_manager.py find",
    "plc_get_target_config": "GetTargetConfig",
    "plc_list_environments": "MCP native",
    "plc_list_targets": "ListTargets",
    "plc_list_variables": "plc_symbol_index.py",
    "plc_plan_project_library": "as_library_manager.py plan",
    "plc_probe_target": "Probe",
    "plc_read_logger": "ReadLogger",
    "plc_read_pvi": "ReadPvi",
    "plc_reset_test_harness": "ResetTestHarness",
    "plc_run_arsim_closed_loop": "RunArsimClosedLoop",
    "plc_run_io_test_case": "RunIoTestCase",
    "plc_run_test_suite": "RunTestSuite",
    "plc_run_verification_suite": "RunVerificationSuite",
    "plc_search_variables": "plc_symbol_index.py",
    "plc_start_arsim": "StartArsim",
    "plc_verify_opcua": "VerifyOpcUa",
    "plc_write_pvi": "WritePvi",
    "plc_discover_runtime_target": "persistent PVI runtime",
    "plc_runtime_health": "persistent PVI runtime",
    "plc_list_runtime_tasks": "persistent PVI runtime",
    "plc_list_runtime_variables": "persistent PVI runtime",
    "plc_get_runtime_variable_info": "persistent PVI runtime",
    "plc_read_runtime_variable": "persistent PVI runtime",
    "plc_open_test_session": "runtime test-session policy",
    "plc_close_test_session": "runtime test-session policy",
    "plc_write_runtime_variable": "persistent PVI runtime + policy",
}

CONFIRMATION_REQUIRED_RISK_LEVELS = {"project_write", "target_change"}
EXPLICIT_TARGET_RISK_LEVELS = {"target_change"}


for definition in TOOL_DEFINITIONS:
    risk_level = TOOL_RISK_LEVELS.get(definition["name"])
    if risk_level is None:
        continue
    definition["annotations"] = {
        "readOnlyHint": risk_level == "readonly",
        "destructiveHint": risk_level in CONFIRMATION_REQUIRED_RISK_LEVELS,
        "idempotentHint": risk_level == "readonly",
        "openWorldHint": False,
    }
    definition["_meta"] = {
        "br-automation/riskLevel": risk_level,
        "br-automation/backend": TOOL_BACKENDS.get(definition["name"]),
    }
