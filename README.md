# B&R PLC 构建、下载、反馈验证工具链

通过 MCP 把 Automation Studio 构建、RUC 下载、ARsim/测试 PLC 验证交给 Agent 或 CI。真实执行走官方 `BR.AS.Build.exe` 和 `PVITransfer.exe`，不另造一套编译器。

```text
改代码 → 构建 → 生成 RUC 包 → 下载到 ARsim 或测试 PLC → OPC UA / PVI 读反馈 → 报告
```

默认只在 **ARsim** 或 **已声明的专用测试 PLC** 上动手。生产目标禁止自动下载。Agent 应使用 MCP，不要直接跑 PowerShell 脚本。

---

## 怎么用：人准备，AI 执行

不必为每个 AS/AR 版本从零写一套工具。仓库已经按 AS4 / AS6 两套全局 toolchain 设计。交给 AI 之前，人要把「这台电脑、这个工程、这台 PLC」绑好；AI 进场后先校验配置，再按闭环调用 MCP。

### 人需要做的

1. **本机装好对应的 Automation Studio 和 PVI**，并确认路径写在 toolchain 里。仓库默认：
   - `as6_default`：AS6 + PVI6
   - `as4_default`：AS4.12 + PVI4.12  
   本机路径与仓库不一致时，复制 `config/examples/toolchains/toolchains.local.example.json` 为 `config/local/toolchains.json`（Git 忽略），不要把开发机路径写进 PLC targets。
2. **为每个工程建一个 environment**，写进 `config/environments/environments.json` 或本机覆盖。至少包含：
   - `project_path`（`.apj`）
   - Automation Studio **config 名**（用工程里的真实名字，不要写死 `Config1`）
   - `toolchain`（与工程 major version 一致：AS4 工程配 AS4，AS6 配 AS6）
   - `target`（`arsim` 或测试 PLC）
3. **为每台 PLC 写清角色**：`arsim`、`dedicated_test_plc` 或 `production`。测试机必须由人显式声明，未知 IP 只能只读发现。
4. **告诉 AI 这次用哪个 `environment`**，以及是否允许 `execute=true`（下载、写变量、启动 ARsim、跑测试套件）。
5. **旧 Runtime 现场把 toolchain 绑对。** 例如 AR `J4.93` 的办公室 PLC 要用 `as4_default` / PVI4；默认 `as6_default` 的 PVI6 会拒绝 Logger 等诊断命令（错误 28345）。同一 MCP 进程不能混用 PVI4 与 PVI6，切主版本必须重启 MCP。
6. **ARsim 还要核对仿真路径**：对应 config 的 `Simulation=1`，`arsim_loader_exe` 指向实际生成的 `Temp/Simulation/<config>/<CPU>/ar000loader.exe`。

人**不要**让 AI 猜 AS 版本、猜 config 名、或把未知物理 PLC 当成测试机。

### AI 进场后做的

1. 先调 `plc_doctor` 和 `plc_validate_environment`，确认本机工具、environment、toolchain 与工程 major version 一致。
2. 缺工程路径或 config 时，只能做发现、读变量、下 logger；不要继续构建或下载。
3. 不要凭空猜变量名：先 `plc_search_variables` 或 `plc_discover_runtime_target`，再读/写。
4. 改变目标状态的操作必须带用户授权的 `execute=true`，并显式传 `target` 或 `environment`。
5. 按下面的任务选流程，失败就停，不要跳过安全检查。

---

## 按任务需要准备什么

| 任务 | 人要提前准备 | AI 调用 | 不需要 |
| --- | --- | --- | --- |
| 只连 PLC 读变量 / 下 logger | IP、角色、匹配的 toolchain | `plc_discover_runtime_target`、`plc_read_runtime_variable`、`plc_read_logger` | 源工程、变量白名单 |
| 改代码后构建并下到 ARsim | environment（工程 + config + `as6_default`/`as4_default` + `arsim`）、仿真 loader | doctor → validate → build → start_arsim → probe → describe → check → download → 读反馈 | 全量变量表 |
| 下到物理测试 PLC | 同上，且 RUC 包 CPU/AR 与实物匹配；`allow_auto_download` | 同上，`target` 指向测试 PLC | ARsim 包；不得对 production 下 |
| OPC UA 闭环校验 | `opcua.validation_node_ids` | `plc_verify_opcua` | — |
| IO 测试套件 | 套件 JSON（写入点、期望、restore） | `plc_reset_test_harness` / `plc_run_test_suite`（均需 `execute=true`） | 把 Safety/物理 I/O 放进套件 |

`plc_validate_environment` 报 `PROJECT_CONFIG_REQUIRED` 是缺工程/config，不是工具坏了。无源码的办公室 PLC 可以只做运行时发现和 logger。

---

## 四层配置（不必重复造轮子）

| 层 | 文件 | 谁维护 | 内容 |
| --- | --- | --- | --- |
| 本机工具 | `config/toolchains/toolchains.json` 或 `config/local/toolchains.json` | 人，按开发机填一次 | AS/PVI 安装路径、编译器、PVITransfer、PVI DLL |
| 目标与策略 | `config/targets/*.json` | 团队默认 + `config/local/` 本机覆盖 | IP、`role`、是否允许下载、Logger 模块、OPC UA/PVI 白名单 |
| 命名环境 | `config/environments/environments.json` | 每个现场/每个工程一份 | 工程 + config + 目标 + toolchain 的捆绑名 |
| 访问策略 | `access_policy` + `config/profiles/` | 人定，AI 不能改松 | `whitelist` / `catalog_policy` / `agent_directed`；Safety/I/O 黑名单 |

选择顺序：

```text
本次 MCP 显式参数（toolchain / target / project_path / config）
  → environment 字段
  → 仓库 default_toolchain / default-safe.json
```

新配置从 `config/examples/` 复制，不要改 examples 本身。个人 IP 和凭据只放 `config/local/`。

详细约定见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md) 和 [docs/TOOLCHAINS.md](docs/TOOLCHAINS.md)。

### 白名单要不要写？

- **不必**为「让 AI 能读测试 PLC」先维护全量变量表。已声明的 `arsim` / `dedicated_test_plc` 可用在线发现和 `plc_read_runtime_variable`；写入仍要 `execute=true`，Safety / 物理 I/O / 系统名会被挡住。
- **要**为这些场景准备名单或套件：
  - `plc_verify_opcua` 的校验节点
  - 未知或生产目标（永远受限）
  - Logger 允许模块（默认 `$arlogsys` / `$arlogusr` / `$arlogconn`，`$safety` 默认禁）
  - IO 测试的输入、输出、restore 列表

默认 `access_policy.mode=whitelist` 约束的是 OPC UA 和非可信目标，不是拦住测试 PLC 上的全部 PVI。

---

## AI 标准调用顺序

**ARsim 构建下载验证**

```text
plc_doctor / plc_validate_environment
  → 确认实际 config 与 Simulation=1
  → plc_build_project(build_ruc_package=true)
  → plc_start_arsim(target=arsim, execute=true)
  → plc_probe_target
  → plc_describe_ruc_package
  → plc_check_download
  → plc_download_ruc(target=arsim, execute=true)
  → plc_verify_opcua 或 plc_read_runtime_variable
```

快捷入口：`plc_run_arsim_closed_loop(target="arsim", execute=true)`。

**无源码连测试 PLC**

```text
plc_discover_runtime_target(ip=..., target=..., declared_role="dedicated_test_plc")
  → plc_read_runtime_variable / plc_write_runtime_variable(execute=true)
  → plc_read_logger   # 旧 AR 须显式 toolchain=as4_default
```

**缺 Library**

```text
plc_build_project → 拿到缺失符号
  → plc_find_library_for_symbol
  → plc_plan_project_library
  → plc_add_project_library(execute=true)
```

只允许本机已安装的可信库，禁止自动添加 Safety 库。

---

## MCP 接入

从仓库根目录启动：

```powershell
python tools\mcp_server\server.py
```

客户端配置示例：

```json
{
  "mcpServers": {
    "br-plc-toolchain": {
      "type": "stdio",
      "command": "python",
      "args": ["tools/mcp_server/server.py"],
      "cwd": "<本仓库根目录>"
    }
  }
}
```

下载、写变量、启动 ARsim、跑测试必须 `execute=true`。工具返回统一 JSON：`ok`、`summary`、`data`、`logs`、`warnings`、`next_actions`。

Agent 操作规程：`skills/br-plc-toolchain/SKILL.md`。无源码连办公室 PLC 的补充说明：[docs/OFFICE_TEST_QUICKSTART.md](docs/OFFICE_TEST_QUICKSTART.md)。

<!-- BEGIN GENERATED MCP TOOL CATALOG -->
当前 MCP 工具清单：

MCP server version: `0.14.0`. Full catalog: [skills/br-plc-toolchain/references/mcp-tools.md](skills/br-plc-toolchain/references/mcp-tools.md)

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

---

## 安全边界

- 禁止对 `role=production` 自动下载。
- 下载前必须 `probe` + `describe_package` + `check_download`；`plc_download_ruc` 不带 `execute=true` 只做检查。
- ARsim 包不能下到物理 PLC；物理包下到 ARsim 默认拒绝。`force_arsim_download=true` 仅在用户明确授权后用于 `role=arsim`。
- 不自动修改 Safety 工程、安全任务或安全 I/O。
- OPC UA 不自动开放全部变量。测试 PLC / ARsim 的 PVI 写入仍要 `execute=true`。
- 构建、下载、写变量、测试套件走 MCP 锁和审计；锁冲突必须等待，不要绕过。

---

## 仓库结构

```text
config/          工具链、目标、环境、策略；本机覆盖放 local/
docs/            上下文、配置约定、实现计划
skills/          Agent Skill 与自动生成的工具目录
tools/           MCP Server 与 CLI 后端
scripts/windows/ PVITransfer 等厂商工具包装
src/             运行时 PVI 与策略实现
tests/           pytest
var/             报告、logger、锁、审计（Git 忽略）
```

更多文档：

- [docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md](docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md) — 工具链整体上下文
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — 配置目录与 profile
- [docs/TOOLCHAINS.md](docs/TOOLCHAINS.md) — AS4/AS6 选择与 PVI 混用限制
- [docs/OFFICE_TEST_QUICKSTART.md](docs/OFFICE_TEST_QUICKSTART.md) — 无源码连测试 PLC
- [docs/PLC_TOOLCHAIN_IMPLEMENTATION_PLAN.md](docs/PLC_TOOLCHAIN_IMPLEMENTATION_PLAN.md) — 已验证事实与实现细节
- [skills/br-plc-toolchain/SKILL.md](skills/br-plc-toolchain/SKILL.md) — Agent 必须遵守的操作顺序
