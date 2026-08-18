# PLC MCP / Skill / Prompt Roadmap

本文记录 PLC 工具链从本地脚本、Skill、MCP Server 到提示词约束的演进路线。

当前重点是 ARsim 下载可靠性：构建成功不等于目标可安装，下载必须经过目标探针、RUC 元数据和分区兼容性检查，并在传输失败后确认目标状态。

<!-- BEGIN GENERATED MCP TOOL CATALOG -->
当前已实现工具：

MCP server version: `0.14.0`. Full catalog: [../skills/br-plc-toolchain/references/mcp-tools.md](../skills/br-plc-toolchain/references/mcp-tools.md)

| MCP Tool | Risk | Backend | Confirmation | Description |
| --- | --- | --- | --- | --- |
| `plc_doctor` | `readonly` | `MCP native diagnostics` | - | Check local Python, PowerShell, Automation Studio, PVITransfer, PVI Python dependency, target config, project/config, ARsim loader, and generated-output write access. |
| `plc_validate_environment` | `readonly` | `MCP native diagnostics` | - | Validate the selected environment or explicit project/config/target/targets_path mapping without connecting to a PLC. |
| `plc_list_reports` | `readonly` | `MCP native report index` | - | List compact metadata for historical JSON reports under var/reports without returning report bodies. |
| `plc_read_report_summary` | `readonly` | `MCP native report summary` | - | Read a compact summary of one JSON report confined to var/reports. Does not return large logs or arbitrary report fields. |
| `plc_build_project` | `local_write` | `Build` | - | Build the B&R Automation Studio project. Optionally generate a RUC package for download. |
| `plc_find_library_for_symbol` | `readonly` | `as_library_manager.py find` | - | Find the trusted, locally installed Automation Studio libraries that declare a missing function, function block, type, constant, or C symbol. |
| `plc_plan_project_library` | `readonly` | `as_library_manager.py plan` | - | Plan adding an installed Automation Studio library and its dependencies without modifying the project. Rejects ambiguous versions, incompatible Technology Packages, and Safety-related libraries. |
| `plc_add_project_library` | `project_write` | `as_library_manager.py add + Build` | `execute=true` | Transactionally copy a trusted installed Automation Studio library and dependencies into Logical/Libraries, update Package.pkg, and rebuild by default. Requires execute=true and rolls back automatically when the validation build fails. |
| `plc_start_arsim` | `target_change` | `StartArsim` | `execute=true` | Start or reuse an existing ARsim simulation instance. readiness=application requires configured PLC status, bAlive, interface-version, and stage-marker checks. |
| `plc_probe_target` | `local_write` | `Probe` | - | Read-only probe of a configured B&R PLC/ARsim target via PVITransfer. Returns CPU type, AR version, PLC status, and log paths. |
| `plc_describe_ruc_package` | `readonly` | `DescribePackage` | - | Read the metadata of a RUC package zip file: CPU type, AR version, config version, runtime type, etc. |
| `plc_check_download` | `local_write` | `CheckDownload` | - | Run the download safety check without downloading. Compares the RUC package metadata with the target probe result. |
| `plc_download_ruc` | `target_change` | `Download` | `execute=true` | Download the RUC package to the target. Safety gate: requires execute=true, and plc_check_download must pass on the server side before actual transfer. |
| `plc_verify_opcua` | `local_write` | `VerifyOpcUa` | - | Read OPC UA validation nodes from the target. Returns values, types, and timestamps for each configured node. |
| `plc_read_logger` | `local_write` | `ReadLogger` | - | Read a whitelisted PLC/AR logger module through PVITransfer Logger. Returns report/log paths and a compact summary, never raw HTML/CSV content. |
| `plc_run_arsim_closed_loop` | `target_change` | `RunArsimClosedLoop` | `execute=true` | Run the standard ARsim closed loop: build RUC package, start ARsim, probe, describe package, safety check, optional explicit download, and verification report. |
| `plc_run_test_suite` | `target_change` | `RunTestSuite` | `execute=true` | Run a full PLC IO test suite and write a report with per-case writes, readback, checks, and restore results. |
| `plc_reset_test_harness` | `target_change` | `ResetTestHarness` | `execute=true` | Restore/reset the PLC test harness using pvi.restore_writes. Requires execute=true and refuses production targets. |
| `plc_list_targets` | `readonly` | `ListTargets` | - | List configured PLC/ARsim targets with IP, role, and automatic-download permission. |
| `plc_search_variables` | `local_write` | `plc_symbol_index.py` | - | Search PLC variables by text, module/task, and read/write access while preserving catalog source, confidence, provenance, and warnings. |
| `plc_discover_runtime_target` | `local_write` | `persistent PVI runtime` | - | Connect through persistent PVI without source code or a policy file. Unknown physical targets are read-only; test roles must be explicitly declared. |
| `plc_read_runtime_variable` | `readonly` | `persistent PVI runtime` | - | Read an online PVI variable. Missing external policy defaults to safe read-only discovery. |
| `plc_write_runtime_variable` | `target_change` | `persistent PVI runtime + policy` | `execute=true` | Write a discovered variable with before/readback diagnostics. ARsim and dedicated test PLC writes require execute=true but no test session. |


## Hidden Tools

以下 21 个工具被 `config/mcp/tool_filter.json` 隐藏（实现仍注册，仅供内部编排调用，MCP 列表与直接调用不可用）：

`plc_read_pvi`, `plc_read_pvi_batch`, `plc_write_pvi`, `plc_run_verification_suite`, `plc_run_io_test_case`, `plc_get_target_config`, `plc_list_environments`, `plc_list_variables`, `plc_list_toolchains`, `plc_get_toolchain`, `plc_runtime_health`, `plc_save_runtime_target`, `plc_list_runtime_tasks`, `plc_list_runtime_variables`, `plc_get_runtime_variable_info`, `plc_start_pvi_trace`, `plc_get_pvi_trace_status`, `plc_read_pvi_trace`, `plc_stop_pvi_trace`, `plc_open_test_session`, `plc_close_test_session`
<!-- END GENERATED MCP TOOL CATALOG -->

## 后续路线

1. 完成 ARsim 下载安全闸门、传输进程清理和应用 readiness 验证。
2. 统一旧 PVI CLI 与 Runtime PVI 的读回、错误分类和会话安全语义。
3. 完善 MCP 的结构化错误、取消、并发控制、审计保留和验证脚本。
4. 保持完整 RUC 构建和 PVITransfer 单一路径，不增加 Automation Studio 增量 Transfer。
