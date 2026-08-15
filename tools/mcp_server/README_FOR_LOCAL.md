# PLC MCP Server Local Notes

## 启动

从仓库根目录运行：

```powershell
python tools\mcp_server\server.py
```

或从 `tools/mcp_server/` 目录运行：

```powershell
python server.py
```

## 架构

此服务器是一个轻量 stdio JSON-RPC MCP 封装，不自行实现 PLC 逻辑；实际工作委托给：

```powershell
tools\plc_toolchain.ps1
tools\as_library_manager.py
```

服务器默认以仓库根目录为工作目录运行所有命令。

## 已暴露工具

<!-- BEGIN GENERATED MCP TOOL CATALOG -->
当前 stdio MCP 暴露以下工具：

MCP server version: `0.14.0`. Full catalog: [../../skills/br-plc-toolchain/references/mcp-tools.md](../../skills/br-plc-toolchain/references/mcp-tools.md)

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
| `plc_read_pvi` | `local_write` | `ReadPvi` | - | Read PLC variables via PVI using hilch/Pvi.py. ARsim and dedicated test PLC targets permit any explicitly named variable; other roles retain policy checks. |
| `plc_read_pvi_batch` | `readonly` | `persistent PVI runtime or legacy ReadPvi adapter` | - | Read up to 64 explicitly named PLC variables in one compact request. Runtime uses the persistent PVI worker; legacy is retained only for compatibility. |
| `plc_read_logger` | `local_write` | `ReadLogger` | - | Read a whitelisted PLC/AR logger module through PVITransfer Logger. Returns report/log paths and a compact summary, never raw HTML/CSV content. |
| `plc_write_pvi` | `target_change` | `WritePvi` | `execute=true` | Write any PVI-writable variable on ARsim or a dedicated test PLC. Requires execute=true; production and unknown targets remain denied. |
| `plc_run_arsim_closed_loop` | `target_change` | `RunArsimClosedLoop` | `execute=true` | Run the standard ARsim closed loop: build RUC package, start ARsim, probe, describe package, safety check, optional explicit download, and verification report. |
| `plc_run_verification_suite` | `local_write` | `RunVerificationSuite` | - | Run feedback verification and write a unified report. OPC UA is attempted first; PVI is used as a fallback. |
| `plc_run_io_test_case` | `target_change` | `RunIoTestCase` | `execute=true` | Run one PLC IO test case from a suite: reset, access-policy-gated PVI writes, settle, readback, checks, and restore. |
| `plc_run_test_suite` | `target_change` | `RunTestSuite` | `execute=true` | Run a full PLC IO test suite and write a report with per-case writes, readback, checks, and restore results. |
| `plc_reset_test_harness` | `target_change` | `ResetTestHarness` | `execute=true` | Restore/reset the PLC test harness using pvi.restore_writes. Requires execute=true and refuses production targets. |
| `plc_get_target_config` | `readonly` | `GetTargetConfig` | - | Read the configured target entry, OPC UA whitelist, and PVI whitelist for a target. |
| `plc_list_targets` | `readonly` | `ListTargets` | - | List configured PLC/ARsim targets with IP, role, and automatic-download permission. |
| `plc_list_environments` | `readonly` | `MCP native` | - | List named PLC toolchain environments from config/environments/environments.json. |
| `plc_list_variables` | `local_write` | `plc_symbol_index.py` | - | Build and page through the PLC variable catalog, preferring fresh Automation Studio build artifacts and falling back to source scanning. The complete catalog is saved locally; MCP responses are bounded. |
| `plc_search_variables` | `local_write` | `plc_symbol_index.py` | - | Search PLC variables by text, module/task, and read/write access while preserving catalog source, confidence, provenance, and warnings. |
| `plc_list_toolchains` | `readonly` | `structured config` | - | List configured AS4/AS6 toolchains, selected paths, PVI family and local availability. |
| `plc_get_toolchain` | `readonly` | `structured config` | - | Resolve one global AS4/AS6 toolchain and return its compiler, libraries and PVI paths. |
| `plc_discover_runtime_target` | `local_write` | `persistent PVI runtime` | - | Connect through persistent PVI without source code or a policy file. Unknown physical targets are read-only; test roles must be explicitly declared. |
| `plc_runtime_health` | `readonly` | `persistent PVI runtime` | - | Return persistent PVI Manager, CPU, runtime, license and cache status. |
| `plc_save_runtime_target` | `project_write` | `structured config` | `execute=true` | Explicitly persist an already loaded ephemeral target under Git-ignored config/local. Never performed automatically. |
| `plc_list_runtime_tasks` | `readonly` | `persistent PVI runtime` | - | List tasks from the running PLC image through PVI, independent of local source code. |
| `plc_list_runtime_variables` | `readonly` | `persistent PVI runtime` | - | List online task or global variables from the running PLC image through PVI. |
| `plc_get_runtime_variable_info` | `readonly` | `persistent PVI runtime` | - | Read online PVI type, access rights and metadata for a discovered variable. |
| `plc_read_runtime_variable` | `readonly` | `persistent PVI runtime` | - | Read an online PVI variable. Missing external policy defaults to safe read-only discovery. |
| `plc_start_pvi_trace` | `local_write` | `Runtime PVI TraceManager` | - | Start a read-only asynchronous Runtime PVI trace for explicitly named variables. Data is retained locally and queried by trace id. |
| `plc_get_pvi_trace_status` | `readonly` | `Runtime PVI TraceManager` | - | Return a compact status summary for a Runtime PVI trace. |
| `plc_read_pvi_trace` | `readonly` | `Runtime PVI TraceManager` | - | Read a bounded time range from a Runtime PVI trace as compact columnar rows. |
| `plc_stop_pvi_trace` | `local_write` | `Runtime PVI TraceManager` | - | Stop a Runtime PVI trace and return its final compact summary. Idempotent for completed traces. |
| `plc_open_test_session` | `target_change` | `runtime test-session policy` | `execute=true` | Open a legacy expiring read-write session. Trusted ARsim and dedicated test PLC writes no longer require a session. |
| `plc_close_test_session` | `local_write` | `runtime test-session policy` | - | Close a temporary runtime PVI test session immediately. |
| `plc_write_runtime_variable` | `target_change` | `persistent PVI runtime + policy` | `execute=true` | Write a discovered variable with before/readback diagnostics. ARsim and dedicated test PLC writes require execute=true but no test session. |
<!-- END GENERATED MCP TOOL CATALOG -->

## 默认配置

- 默认目标：`arsim`
- 工程路径和 config 由调用方通过 `environment` 或显式 `project_path`/`config` 参数提供
- 配置文件：`config\targets\default-safe.json`

## 环境切换

MCP 支持通过 `environment` 参数一键切换环境。环境清单在：

```text
config\environments\environments.json
```

当前已配置：

- `default_safe`：保守默认，使用 `config\targets\default-safe.json`，仅允许白名单访问。
- `default`：`default_safe` 的兼容别名。
- `dev_agent_directed`：显式开发环境，使用 `config\examples\targets\development.example.json`，仅面向本机 ARsim。
- `test_whitelist`：专用测试 PLC 模板，使用 `config\examples\targets\office-test.example.json`，默认禁止自动下载。
- `readonly_diagnostics`：只读诊断模板，使用 `config\examples\targets\readonly.example.json`。
- `cwj_as6_x3687x`：今天验证通过的本机 AS6 + `x3687x` ARsim 环境，目标配置文件为 `config\examples\machines\cwj-as6-x3687x.example.json`。
- `cwj_test_plc_x1685`：同一套本机 AS6 配置，用于 `192.168.50.222` 物理测试 PLC 和 `x1685` config。

三个 `*.example.json` 文件必须先按本机路径、目标地址和变量白名单完成配置。开放的 `agent_directed` 模式不会由默认环境隐式启用。

示例：

```json
{"environment":"default_safe"}
```

显式传入的 `target`、`project_path`、`config`、`targets_path` 会覆盖环境默认值。

## 访问策略

`tools\plc_access_policy.py` 是 PVI/OPC UA 变量访问判断的唯一权威实现。Python 工具直接调用该模块，PowerShell 通过 `tools\plc_access_policy_cli.py` 获取同一份结构化结论；策略响应包含 `ok`、`errors`、`policy_mode`、`target_role`、`requested_items` 和 `blocked_reason`。

## 锁与审计

构建、工程修改和所有目标变更工具由 MCP Server 自动加锁。工程锁按 `project_path + config` 隔离，目标锁按 `targets_path + target` 隔离；锁文件位于 `var\locks\`。关键调用在开始及成功、失败、拒绝或锁冲突时写入 `var\audit\`，审计只记录 PVI 写入变量名和数量，不记录写入值。

## 测试夹具报告

IO 测试套件可声明 `fixture` 元数据和 reset 策略。报告使用固定的 `failure_stage` / `failure_stages` 分类：`validation`、`write`、`read`、`assert`、`restore`，并在 `reset_records` 中保存套件与 case 的前后恢复记录。任何 restore 失败都会把整体测试判为失败；前置 reset 失败时不会继续写测试输入。

## 变量目录可信度

变量目录优先读取 Automation Studio 生成的 `Temp\Includes\**\*var.h`，并结合 `Temp\Objects\Symbols.map` 判断为高可信构建产物。若产物缺失、无法解析或比 `.var` 源文件旧，则自动退回源码扫描。目录顶层和单个变量都返回 `catalog_source`、`confidence`、`generated_from`、`warnings`，Agent 必须在动态读写前检查这些字段。

## 诊断与历史报告

- `plc_doctor`：检查 Python、PowerShell、Automation Studio、PVITransfer、PVI Python、目标配置、工程/config、ARsim loader 和生成目录写权限。
- `plc_validate_environment`：只校验所选 environment 或显式参数映射，不连接 PLC。
- `plc_list_reports`：按类型和通过/失败状态列出紧凑报告元数据。
- `plc_read_report_summary`：读取单个报告的状态、计数、失败阶段和 case 摘要，路径强制限制在 `var\reports\`。

## 通用参数

所有工具均接收：

- `target`：目标名称；目标变更工具必须显式传入 `target` 或 `environment`，只读和本地工具未选择时回退到 `arsim`
- `environment`：环境名，来自 `config\environments\environments.json`
- `project_path`：AS 工程路径
- `config`：配置名称，默认 `x1685`
- `targets_path`：目标配置 JSON 路径，可覆盖 `environment` 中的配置
- `timeout_seconds`：超时秒数

## 返回结构

```json
{
  "ok": true,
  "tool": "plc_xxx",
  "target": "arsim",
  "summary": "可读摘要",
  "data": {},
  "logs": ["路径列表"],
  "warnings": [],
  "next_actions": ["建议的下一步操作"]
}
```

## 测试验证

手动测试命令：

```powershell
# 列出所有工具
echo "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}" | python tools\mcp_server\server.py

# 构建
echo "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_build_project\",\"arguments\":{}}}" | python tools\mcp_server\server.py

# 根据缺失符号查找库，然后生成添加计划
echo "{\"jsonrpc\":\"2.0\",\"id\":20,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_find_library_for_symbol\",\"arguments\":{\"symbol\":\"TcpOpen\",\"environment\":\"cwj_as6_x3687x\"}}}" | python tools\mcp_server\server.py
echo "{\"jsonrpc\":\"2.0\",\"id\":21,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_plan_project_library\",\"arguments\":{\"library\":\"AsTCP\",\"environment\":\"cwj_as6_x3687x\"}}}" | python tools\mcp_server\server.py

# 审查计划后添加并重新构建；构建失败会自动回滚
echo "{\"jsonrpc\":\"2.0\",\"id\":22,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_add_project_library\",\"arguments\":{\"library\":\"AsTCP\",\"environment\":\"cwj_as6_x3687x\",\"execute\":true}}}" | python tools\mcp_server\server.py

# 探针
echo "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_probe_target\",\"arguments\":{}}}" | python tools\mcp_server\server.py

# OPC UA 验证
echo "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_verify_opcua\",\"arguments\":{}}}" | python tools\mcp_server\server.py

# 目标列表
echo "{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_list_targets\",\"arguments\":{}}}" | python tools\mcp_server\server.py
```

## MCP 客户端接入

任何支持 stdio 模式的 MCP 客户端均可接入，配置如下：

```json
{
  "mcpServers": {
    "br-plc-toolchain": {
      "type": "stdio",
      "command": "python",
      "args": ["tools/mcp_server/server.py"],
      "cwd": "D:\\codex_ws\\motion_svg_test"
    }
  }
}
```
