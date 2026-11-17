# B&R PLC 自动开发工具链

版本：**0.15.0a1（预发布基线）**。本项目通过 stdio MCP 提供 Automation Studio 构建、RUC 包检查和下载、ARsim 启动，以及 PVI / OPC UA 反馈验证。构建和下载分别调用 B&R 的 `BR.AS.Build.exe`、`PVITransfer.exe`。

本版本仍是开发基线，尚未完成发布验收；使用前请阅读下方的实际安全限制。项目本身不是 Automation Studio 工程，需要另行准备 `.apj` 工程。

## 环境与安装

- Windows、PowerShell、Python 3.11 或更新版本。
- 与工程主版本匹配的 Automation Studio 4 或 6，以及对应版本的 PVI、PVITransfer 和 PVI DLL。切换 PVI4 / PVI6 时重启 MCP Server。
- 从仓库根目录安装依赖；运行 MCP Server 需要保留完整仓库，当前 wheel 只包含 `src` 中的 Python 包。

```powershell
python -m pip install -e .
python -m pip install pytest  # 仅运行测试时需要
python tools\mcp_server\server.py
```

在支持 stdio 的 MCP 客户端中配置，替换为本机绝对路径（JSON 中的 Windows 反斜杠应写成 `\\`，也可使用 `/`）：

```json
{
  "mcpServers": {
    "br-plc-toolchain": {
      "type": "stdio",
      "command": "python",
      "args": ["C:/path/to/br_device_autodev/tools/mcp_server/server.py"],
      "cwd": "C:/path/to/br_device_autodev"
    }
  }
}
```

## 基本配置

日常 ARsim 工程使用两级配置：一份本机全局工具链注册表，以及每个 AS 工程的 `br-auto-dev.json`。现有实现还有内部策略、默认目标和兼容环境配置，见下文；物理目标变更另有显式授权要求。

### 1. 本机全局工具链

仓库的 [config/toolchains/toolchains.json](config/toolchains/toolchains.json) 包含 AS4 / AS6 的完整示例。建议将它复制到被 Git 忽略的 `config/local/toolchains.json`，按本机安装修改；该本机文件存在时优先使用。也可通过 MCP 的 `toolchains_path` 指定注册表。

示例结构如下，所有路径必须改为实际存在的安装路径：

```json
{
  "schema_version": 1,
  "default_toolchain": "as6_default",
  "toolchains": {
    "as6_default": {
      "enabled": true,
      "family": "AS6",
      "version": "6.x",
      "automation_studio": {
        "install_root": "C:/Program Files (x86)/BRAutomation/AS6",
        "bin_dir": "C:/Program Files (x86)/BRAutomation/AS6/bin-en",
        "build_exe": "C:/Program Files (x86)/BRAutomation/AS6/bin-en/BR.AS.Build.exe",
        "library_roots": ["C:/Program Files (x86)/BRAutomation/AS6"]
      },
      "pvi": {
        "family": "PVI6",
        "transfer_exe": "C:/Program Files (x86)/BRAutomation/PVI6/PVI/Tools/PVITransfer/PVITransfer.exe",
        "dll_dir": "C:/Program Files (x86)/BRAutomation/PVI6/Bin"
      }
    }
  }
}
```

### 2. 项目配置

将 [config/examples/br-auto-dev.example.json](config/examples/br-auto-dev.example.json) 复制到工程目录并重命名为 `br-auto-dev.json`。把 `Demo.apj`、`Sim`、`CPU` 换成实际工程、AS config 和 CPU 目录名称；`toolchain` 必须是全局注册表中与工程主版本匹配的 ID。

```json
{
  "project_path": "Demo.apj",
  "config": "Sim",
  "toolchain": "as6_default",
  "target": "arsim",
  "targets": {
    "arsim": {
      "ip": "127.0.0.1",
      "role": "arsim",
      "allow_auto_download": true,
      "arsim_loader_exe": "Temp/Simulation/Sim/CPU/ar000loader.exe"
    }
  },
  "access_policy": {"mode": "whitelist"},
  "opcua": {"endpoint_port": 4840, "validation_node_ids": []},
  "pvi": {"enabled": true, "read_whitelist": [], "write_whitelist": [], "restore_writes": [], "validation_variables": []}
}
```

- MCP 的 `project_path` 可指向含配置的目录或 `.apj`。传 `.apj` 时查找同目录及其上一级；配置里的 `.apj` 必须存在并与传入工程一致。项目配置格式错误时会报错。
- `project_path`、`arsim_loader_exe` 和显式 `access_policy.catalog_path` 的相对路径以配置文件所在目录为基准。调用中的显式参数优先于项目配置；没有项目配置时仍支持旧 environment 与默认目标回退。
- ARsim 的 IP 必须是回环地址。检查 `Physical/<实际config>/Hardware.hw` 中 CPU 的 `Simulation` 为 `1`，重新构建后使用实际生成的 `Temp/Simulation/<实际config>/<CPU>/ar000loader.exe`；如果不配置 loader，程序会尝试在该 config 目录下寻找唯一 loader。
- OPC UA 只读取已配置节点；测试套件需根据实际工程配置输入、断言和恢复值。示例中的空列表不会自动暴露变量，也不能充当实际测试套件。
- 对物理测试 PLC 的状态变更，项目配置本身不能授权：必须显式传入可信的 `targets_path`，并明确目标角色和用户授权。`config/targets/default-safe.json` 是现有的兼容格式参考，不要直接复用其中的现场地址或变量。

内部文件 `config/defaults/`、`config/profiles/`、`config/mcp/tool_filter.json`、`config/environments/environments.json` 和 `config/targets/default-safe.json` 仍被当前运行时、工具过滤或兼容入口读取；不要删除或把它们误当成无作用的示例。`config/local/` 是本机覆盖，`var/` 保存运行报告、审计、锁、日志等，均不应作为发布配置提交。

## 操作流程

以下是 MCP 工具调用顺序，具体参数以客户端展示的工具 schema 为准。状态变更工具须显式指定 `target` 或 `environment`，并按要求传 `execute=true`；配置中的目标不会代替这一显式选择。

1. 调用 `plc_doctor`、`plc_validate_environment`，传入项目路径，确认 AS major、工具路径、实际 config 和目标。
2. 调用 `plc_build_project` 并设置 `build_ruc_package=true`。
3. 调用 `plc_start_arsim`，显式传 `target="arsim"` 和 `execute=true`。
4. 依次调用 `plc_probe_target`、`plc_describe_ruc_package`、`plc_check_download`，检查目标、包与所有告警。
5. 确认目标及用户授权后调用 `plc_download_ruc`，显式传 `target="arsim"`、`execute=true`。
6. 使用 `plc_verify_opcua` 或先 `plc_discover_runtime_target` 再 `plc_read_runtime_variable` 读取实际变量。`Object not found` 时先确认运行映像中是否包含该任务和变量。

缺少 Library 时按 `plc_find_library_for_symbol` → `plc_plan_project_library` → `plc_add_project_library` 处理，只使用可信的本机 AS 安装库，不自动添加 Safety 库。输入输出套件使用 `plc_reset_test_harness` 和 `plc_run_test_suite`；恢复失败必须按失败处理。

## 安全边界与当前实现限制

- 生产角色的自动下载与 PVI 写入被拒绝。下载和写入必须显式传 `execute=true`；ARsim 包和物理 PLC 包不能跨目标类型下载。用户仍须确认目标、包和操作授权。
- **当前代码对 `arsim` 和 `dedicated_test_plc` 的 PVI 读写按可信目标放行，不对变量名应用 Safety、物理 I/O 和系统名称黑名单。** `execute=true`、PVI 可写性等条件仍适用。不要自动修改 Safety 工程、任务或安全 I/O；在此限制修复和验收前，不应依赖名称黑名单保护测试 PLC。
- **当前下载检查对可信开发目标会把部分 CPU、版本、配置、分区和安装模式不匹配降为告警**；允许下载、有效探针及包与目标类型仍是硬条件。人工必须审查所有告警，不应把 `ok=true` 当作完整兼容性证明。
- 代码还暴露 `bypass_download_safety` 和旧参数 `force_arsim_download`，对可信测试目标存在宽松行为；操作规范只允许在用户明确授权后对本机 `role=arsim` 使用强制 ARsim 下载，不把授权扩展到物理 PLC。不要使用绕过参数对物理 PLC 下载。
- 构建、工程修改、下载、写入和测试应经 MCP 锁和审计执行。测试变量优先先读再写同值并独立读回；不要为了验证随意改变控制状态。

## MCP 工具

<!-- BEGIN GENERATED MCP TOOL CATALOG -->
当前 MCP 工具清单：

MCP server version: `0.15.0a1`

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

工具目录由 `python scripts/maintenance/generate_mcp_docs.py` 从 MCP schema 生成；用 `--check` 检查文档是否同步。

## 测试与输出

```powershell
python -m pytest -q
```

测试以本地模拟为主，不代表本版本完成实机或 ARsim 验收。测试和调用可能生成 `var/`、`Temp/`、Python 缓存；`var/` 包含审计和历史报告，清理前应先确认保留需求。
