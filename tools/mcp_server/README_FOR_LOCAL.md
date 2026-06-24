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

MCP server version: `0.6.0`. Full catalog: [../../skills/br-plc-toolchain/references/mcp-tools.md](../../skills/br-plc-toolchain/references/mcp-tools.md)

| MCP Tool | Risk | Backend | Confirmation | Description |
| --- | --- | --- | --- | --- |
| `plc_build_project` | `local_write` | `Build` | - | Build the B&R Automation Studio project. Optionally generate a RUC package for download. |
| `plc_find_library_for_symbol` | `readonly` | `as_library_manager.py find` | - | Find the trusted, locally installed Automation Studio libraries that declare a missing function, function block, type, constant, or C symbol. |
| `plc_plan_project_library` | `readonly` | `as_library_manager.py plan` | - | Plan adding an installed Automation Studio library and its dependencies without modifying the project. Rejects ambiguous versions, incompatible Technology Packages, and Safety-related libraries. |
| `plc_add_project_library` | `project_write` | `as_library_manager.py add + Build` | `execute=true` | Transactionally copy a trusted installed Automation Studio library and dependencies into Logical/Libraries, update Package.pkg, and rebuild by default. Requires execute=true and rolls back automatically when the validation build fails. |
| `plc_start_arsim` | `target_change` | `StartArsim` | `execute=true` | Start or reuse an existing ARsim simulation instance for the specified target. |
| `plc_probe_target` | `local_write` | `Probe` | - | Read-only probe of a configured B&R PLC/ARsim target via PVITransfer. Returns CPU type, AR version, PLC status, and log paths. |
| `plc_describe_ruc_package` | `readonly` | `DescribePackage` | - | Read the metadata of a RUC package zip file: CPU type, AR version, config version, runtime type, etc. |
| `plc_check_download` | `local_write` | `CheckDownload` | - | Run the download safety check without downloading. Compares the RUC package metadata with the target probe result. |
| `plc_download_ruc` | `target_change` | `Download` | `execute=true` | Download the RUC package to the target. Safety gate: requires execute=true, and plc_check_download must pass on the server side before actual transfer. |
| `plc_verify_opcua` | `local_write` | `VerifyOpcUa` | - | Read OPC UA validation nodes from the target. Returns values, types, and timestamps for each configured node. |
| `plc_read_pvi` | `local_write` | `ReadPvi` | - | Read PLC variables via PVI using hilch/Pvi.py. Default whitelist mode requires configured variables; Agent-directed mode allows explicit variables after policy checks. |
| `plc_read_logger` | `local_write` | `ReadLogger` | - | Read a whitelisted PLC/AR logger module through PVITransfer Logger. Returns report/log paths and a compact summary, never raw HTML/CSV content. |
| `plc_write_pvi` | `target_change` | `WritePvi` | `execute=true` | Write PVI variables under access_policy. Default whitelist mode requires pvi.write_whitelist; Agent-directed mode allows explicit variables after policy checks. Requires execute=true and refuses production targets. |
| `plc_run_arsim_closed_loop` | `target_change` | `RunArsimClosedLoop` | `execute=true` | Run the standard ARsim closed loop: build RUC package, start ARsim, probe, describe package, safety check, optional explicit download, and verification report. |
| `plc_run_verification_suite` | `local_write` | `RunVerificationSuite` | - | Run feedback verification and write a unified report. OPC UA is attempted first; PVI is used as a fallback. |
| `plc_run_io_test_case` | `target_change` | `RunIoTestCase` | `execute=true` | Run one PLC IO test case from a suite: reset, access-policy-gated PVI writes, settle, readback, checks, and restore. |
| `plc_run_test_suite` | `target_change` | `RunTestSuite` | `execute=true` | Run a full PLC IO test suite and write a report with per-case writes, readback, checks, and restore results. |
| `plc_reset_test_harness` | `target_change` | `ResetTestHarness` | `execute=true` | Restore/reset the PLC test harness using pvi.restore_writes. Requires execute=true and refuses production targets. |
| `plc_get_target_config` | `readonly` | `GetTargetConfig` | - | Read the configured target entry, OPC UA whitelist, and PVI whitelist for a target. |
| `plc_list_targets` | `readonly` | `ListTargets` | - | List configured PLC/ARsim targets with IP, role, and automatic-download permission. |
| `plc_list_environments` | `readonly` | `MCP native` | - | List named PLC toolchain environments from tools/plc_environments.json for one-step switching. |
| `plc_list_variables` | `local_write` | `plc_symbol_index.py` | - | Build and list the PLC variable catalog from project source files and target access policy. Use before Agent-directed reads/writes. |
| `plc_search_variables` | `local_write` | `plc_symbol_index.py` | - | Search PLC variables by text, module/task, and read/write access under the current access_policy. |
<!-- END GENERATED MCP TOOL CATALOG -->

## 默认配置

- 默认目标：`arsim`
- 默认工程：`PrintDemo\Huitong_FrontEval.apj`
- 默认配置：`x1685`
- 配置文件：`tools\plc_targets.local.json`

## 环境切换

MCP 支持通过 `environment` 参数一键切换环境。环境清单在：

```text
tools\plc_environments.json
```

当前已配置：

- `default_safe`：保守默认，使用 `tools\plc_targets.local.json`，仅允许白名单访问。
- `default`：`default_safe` 的兼容别名。
- `dev_agent_directed`：显式开发环境，使用 `tools\plc_targets.dev.example.json`，仅面向本机 ARsim。
- `test_whitelist`：专用测试 PLC 模板，使用 `tools\plc_targets.test.example.json`，默认禁止自动下载。
- `readonly_diagnostics`：只读诊断模板，使用 `tools\plc_targets.readonly.example.json`。
- `cwj_as6_x3687x`：今天验证通过的本机 AS6 + `x3687x` ARsim 环境，目标配置文件为 `tools\plc_targets.cwj_as6_x3687x.json`。
- `cwj_test_plc_x1685`：同一套本机 AS6 配置，用于 `192.168.50.222` 物理测试 PLC 和 `x1685` config。

三个 `*.example.json` 文件必须先按本机路径、目标地址和变量白名单完成配置。开放的 `agent_directed` 模式不会由默认环境隐式启用。

示例：

```json
{"environment":"default_safe"}
```

显式传入的 `target`、`project_path`、`config`、`targets_path` 会覆盖环境默认值。

## 通用参数

所有工具均接收：

- `target`：目标名称；目标变更工具必须显式传入 `target` 或 `environment`，只读和本地工具未选择时回退到 `arsim`
- `environment`：环境名，来自 `tools\plc_environments.json`
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
