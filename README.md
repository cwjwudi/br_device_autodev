# B&R PLC 自动开发工具链

版本：**0.15.2a1（预发布基线）**。本项目通过 stdio MCP 提供 Automation Studio 构建、RUC 包检查和下载、ARsim 启动，以及 PVI 反馈验证。构建和下载分别调用 B&R 的 `BR.AS.Build.exe`、`PVITransfer.exe`。

本版本仍是开发基线，尚未完成发布验收；使用前请阅读下方的实际安全限制。项目本身不是 Automation Studio 工程，需要另行准备 `.apj` 工程。

## 环境与安装

- Windows、PowerShell、Python 3.11 或更新版本。
- 与工程主版本匹配的 Automation Studio 4 或 6，以及对应版本的 PVI、PVITransfer 和 PVI DLL。切换 PVI4 / PVI6 时重启 MCP Server。
- 运行 MCP Server 需要保留完整仓库，当前 wheel 只包含 `src` 中的 Python 包。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_venv.ps1
.\.venv\Scripts\python.exe tools\mcp_server\server.py
```

安装脚本在仓库根目录创建或复用 `.venv`，通过阿里云 PyPI 镜像安装 `requirements.txt` 中的项目及其运行依赖。运行依赖以 `pyproject.toml` 为准；依赖声明变更后可重新运行脚本。

在支持 stdio 的 MCP 客户端中配置，替换为本机绝对路径（JSON 中的 Windows 反斜杠应写成 `\\`，也可使用 `/`）：

```json
{
  "mcpServers": {
    "br-plc-toolchain": {
      "type": "stdio",
      "command": "C:/path/to/br_device_autodev/.venv/Scripts/python.exe",
      "args": ["C:/path/to/br_device_autodev/tools/mcp_server/server.py"],
      "cwd": "C:/path/to/br_device_autodev"
    }
  }
}
```

## 基本配置

使用两级配置：一份本机全局工具链注册表，以及每个 AS 工程的 `br-auto-dev.json`。项目配置定义目标、PVI 写入策略和下载许可。

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
      "role": "arsim"
    }
  },
  "pvi": {"enabled": true, "write_policy": "whitelist", "write_whitelist": [], "restore_writes": [], "validation_variables": []}
}
```

- MCP 的 `project_path` 可指向含配置的目录或 `.apj`。传 `.apj` 时查找同目录及其上一级；配置里的 `.apj` 必须存在并与传入工程一致。项目配置格式错误时会报错。
- `project_path`、`arsim_work_dir`、`arsim_loader_exe` 的相对路径以配置文件所在目录为基准。`arsim_work_dir` 缺省为 `.apj` 所在目录的 `Temp/Simulation`；新建实例时工具在其中创建隔离子目录，不覆盖已有文件。
- ARsim 的 IP 必须是回环地址；AS4 的 `SimulationIPAddress` 必须与目标 IP 一致并在构建前设置。首次安装使用 `plc_provision_arsim`；旧的 `arsim_loader_exe` 仍供 `plc_start_arsim` 启动既有实例。详见 [ARsim 工作流程](docs/arsim-workflow.md)。
- 实时 PVI：调用 `plc_discover_runtime_target` 时传 `project_path` 与 `target`，服务会读取项目中的 IP、角色和 PVI 策略；随后按目标名读写。项目策略更改后重新发现目标。未传项目配置的物理目标可只读发现，但没有写入白名单。

### 可复制的配置示例

- [ARsim](config/examples/br-auto-dev.example.json)：回环地址，PVI 可读写，默认允许下载。
- [物理测试 PLC 白名单](config/examples/br-auto-dev.test-plc-whitelist.example.json)：默认禁止下载，只允许写入列出的变量。
- [物理测试 PLC 黑名单](config/examples/br-auto-dev.test-plc-blacklist.example.json)：默认禁止下载，允许写入未被列出的变量。

复制所选文件到工程目录并命名为 `br-auto-dev.json`，由用户根据实际工程修改 IP、AS config、目标角色和变量名。示例 IP 和变量名仅作格式演示。

`config/defaults/base.json` 和 `config/mcp/tool_filter.json` 是程序内部默认值与工具过滤；`config/local/` 是本机覆盖，`var/` 保存运行报告、审计、锁和日志。

### 给 AI 的配置规则

先读本 README 和 `config/examples/` 中对应目标的示例，再读取用户工程的 `br-auto-dev.json` 和全局 toolchain 配置。不要猜测工程路径、AS config、IP、目标角色或写入变量。物理 PLC 的白名单、黑名单和下载许可应由用户手动确认并修改；AI 不得为了让操作通过自行放宽配置。默认仅做读取，状态变更前确认用户授权。

## 操作流程

以下是 MCP 工具调用顺序，具体参数以客户端展示的工具 schema 为准。状态变更工具须显式指定 `target`，并按要求传 `execute=true`；配置中的目标不会代替这一显式选择。

1. 调用 `plc_doctor`、`plc_validate_environment`，传入项目路径，确认 AS major、工具路径、实际 config 和目标。
2. 调用 `plc_build_project` 并设置 `build_ruc_package=true`。
3. 调用 `plc_check_arsim_occupancy`，首次部署用 `plc_provision_arsim(target="arsim", execute=true)` 离线安装并启动独立仿真；已有实例更新则检查归属后使用下载安全检查和 `plc_download_ruc`。
4. 先调用 `plc_discover_runtime_target(project_path=..., target=...)`，再使用 `plc_read_runtime_variable` 读取实际变量。监听成功不等于 RUN 或功能验证通过。

缺少 Library 时按 `plc_find_library_for_symbol` → `plc_plan_project_library` → `plc_add_project_library` 处理，只使用可信的本机 AS 安装库，不自动添加 Safety 库。

## 安全边界与当前实现限制

- 生产角色的自动下载与 PVI 写入被拒绝。下载和写入必须显式传 `execute=true`；ARsim 包和物理 PLC 包不能跨目标类型下载。用户仍须确认目标、包和操作授权。
- ARsim 默认 PVI 可读写、允许构建和下载；物理目标默认 PVI 可读、写入白名单为空、允许构建但禁止下载。`write_policy` 设为 `whitelist` 时只允许 `write_whitelist` 中的变量；设为 `blacklist` 时允许未命中 `write_blacklist` 的变量，支持 `*` 通配符。**黑名单为空会允许所有可写变量**；禁止自动修改 Safety 工程、任务和安全 I/O。
- OPC UA 读取仅允许 ARsim 和专用测试 PLC，节点必须列在 `opcua.validation_node_ids` 中，且不能匹配 Safety、系统等受限名称。旧配置中的 `access_policy` 已移除：项目配置若保留该项会报错，直接 OPC UA 校验也会拒绝读取。删除前请检查原有自定义角色和名称限制；这些自定义限制和旧的动态读取模式不再支持，节点列表不能替代所有角色限制。变量目录的访问标记仅表示配置中列出的变量，实际 PVI 写入仍由 `write_policy` 和目标角色决定。
- 物理测试 PLC 如需下载，用户必须手动在目标中设置 `allow_auto_download: true` 并授权本次操作。生产目标仍禁止下载和写入。所有 PVI 写入仍要求 `execute=true` 与 PVI 可写性。
- **当前下载检查对可信开发目标会把部分 CPU、版本、配置、分区和安装模式不匹配降为告警**；允许下载、有效探针及包与目标类型仍是硬条件。人工必须审查所有告警，不应把 `ok=true` 当作完整兼容性证明。
- `bypass_download_safety` 和旧参数 `force_arsim_download` 仅限 ARsim；操作规范只允许在用户明确授权后对本机 `role=arsim` 使用强制 ARsim 下载。
- 构建、工程修改、下载、写入和测试应经 MCP 锁和审计执行。测试变量优先先读再写同值并独立读回；不要为了验证随意改变控制状态。

## 公开 Python PVI SDK

除 MCP 工具外，`br_plc_toolchain` 包还导出了受相同 `RuntimePolicy` 约束的高层客户端 `PviClient`（以及 `RuntimePviService`、`TraceManager`、`PviTraceError`、`PviSessionManager`、`PviTarget`、`VariableRef`、`parse_variable_ref`），供多步骤闭环控制、高频 20 ms / 128 变量采样及离线分析脚本直接编排，无需引用 `tools.mcp_server.toolchain` 私有对象：

```python
from br_plc_toolchain import PviClient

with PviClient.from_project(r"C:\path\to\project", target="arsim") as plc:
    plc.discover()
    snapshot = plc.read_many(["Main:bEnable", "gAlive"])
    trace = plc.start_trace(["Main:eState", "gAlive"], duration_seconds=10, interval_ms=20)
    plc.write("Main:bEnable", True, execute=True)
    plc.wait_until("Main:eState", lambda v: v == 3, timeout_s=5.0)
    summary = plc.stop_trace(trace["trace_id"])
    data = plc.read_trace(trace["trace_id"], max_samples=1000)
```

独立 Python 脚本在运行期间维持自己的持久 PVI 连接并在退出 `with` 上下文时自动关闭，不与 MCP Server 共享进程内句柄。

## MCP 工具

<!-- BEGIN GENERATED MCP TOOL CATALOG -->
当前 MCP 工具清单：

MCP server version: `0.17.0a1`

| MCP Tool | Risk | Backend | Confirmation | Description |
| --- | --- | --- | --- | --- |
| `plc_check_arsim_occupancy` | `readonly` | `p802 occupancy sampler` | - | Sample local ARsim address conflicts using p802 TCP/UDP occupancy rules; free is not a reservation. |
| `plc_provision_arsim` | `target_change` | `PVITransfer offline commissioning` | `execute=true` | Install the project's ARsim RUC into a new isolated working directory and start it on the configured free loopback IP. Optionally replaces an owned instance of the same project target when replace_existing=true. |
| `plc_manage_arsim` | `target_change` | `ARsim registry & process manager` | `execute=true` | Manage codex-arsim instances registered in var/arsim/instances.json: list live status (read-only with execute=false), safely stop or restart owned instances with executable-path verification, or clean stopped codex-arsim directories. |
| `plc_inspect_project` | `readonly` | `project/topology.py` | - | Read-only parser and static integrity checker for an Automation Studio project (.apj, Physical.pkg, Config.pkg, Cpu.pkg, Cpu.sw, Hardware.hw, Logical packages/programs). Reports CPU/AR/SimulationIP, safety hardware presence, TaskClass topology, global declarations, and dangling/malformed XML issues without invoking BR.AS.Build.exe. |
| `plc_init_project_config` | `project_write` | `project_init.py` | `execute=true` | Auto-discover an Automation Studio .apj, Physical/Physical.pkg configurations, SimulationIPAddress, and matching toolchain to preview (execute=false) or write (execute=true) br-auto-dev.json. |
| `plc_doctor` | `readonly` | `MCP native diagnostics` | - | Check local Python, PowerShell, Automation Studio, PVITransfer, PVI Python dependency, target config, project/config, ARsim loader, and generated-output write access. |
| `plc_validate_environment` | `readonly` | `MCP native diagnostics` | - | Validate the project configuration, toolchain, and target without connecting to a PLC. |
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
| `plc_download_ruc` | `target_change` | `Download` | `execute=true` | Download the RUC package after the server-side safety check passes. Generate a stable request_id before sending and use plc_get_download_result with that ID if the response is lost. |
| `plc_get_download_result` | `readonly` | `Download operation journal` | - | Look up one download by request_id. Read-only; reports process protection, transfer evidence, target probe and audit. Missing records are unknown. |
| `plc_read_pvi_batch` | `readonly` | `persistent PVI runtime or legacy ReadPvi adapter` | - | Read up to 128 explicitly named PLC variables in one compact request. Runtime uses the persistent PVI worker; legacy is retained only for compatibility. |
| `plc_read_logger` | `local_write` | `ReadLogger` | - | Read a PLC/AR logger module directly through PVITransfer Logger (enabled at project level via logger.enabled=true; Safety modules blocked). Returns report/log paths and a compact summary, defaults to .csvx. |
| `plc_list_targets` | `readonly` | `ListTargets` | - | List configured PLC/ARsim targets with IP, role, and automatic-download permission. |
| `plc_list_variables` | `local_write` | `plc_symbol_index.py` | - | Page through the complete project variable catalog cached in .br-auto-dev; changes refresh it while the server runs and are checked on each query. Fresh build artifacts are preferred; MCP responses are bounded. |
| `plc_search_variables` | `local_write` | `plc_symbol_index.py` | - | Search the full project variable catalog cached in .br-auto-dev. Changes refresh it while the server runs and are checked on each query. Results retain source, confidence, provenance, and warnings. |
| `plc_discover_runtime_target` | `local_write` | `persistent PVI runtime` | - | Connect through persistent PVI without source code or a policy file. Unknown physical targets are read-only; test roles must be explicitly declared. |
| `plc_runtime_health` | `readonly` | `persistent PVI runtime` | - | Return persistent PVI Manager, CPU, runtime, license and cache status. |
| `plc_list_runtime_tasks` | `readonly` | `persistent PVI runtime` | - | List tasks from the running PLC image through PVI, independent of local source code. |
| `plc_list_runtime_variables` | `readonly` | `persistent PVI runtime` | - | Scan online task or global variable names through PVI, then return a bounded page. Uses a 30-second per-(scope, task) in-memory cache so paging does not repeat full scans; pass refresh=true to force a fresh scan. Pattern is a case-sensitive glob, not a regex. |
| `plc_get_runtime_variable_info` | `readonly` | `persistent PVI runtime` | - | Read online PVI type, access rights and metadata for a discovered variable. Pass expand=true to expand structure or array variables into leaf variable paths. |
| `plc_read_runtime_variable` | `readonly` | `persistent PVI runtime` | - | Read an online PVI variable. Missing external policy defaults to safe read-only discovery. |
| `plc_start_pvi_trace` | `local_write` | `Runtime PVI TraceManager` | - | Start a read-only asynchronous Runtime PVI trace for up to 128 explicitly named variables (minimum 20 ms interval). Data is retained locally and queried by trace id. |
| `plc_get_pvi_trace_status` | `readonly` | `Runtime PVI TraceManager` | - | Return a compact status summary for a Runtime PVI trace. |
| `plc_read_pvi_trace` | `readonly` | `Runtime PVI TraceManager` | - | Read a bounded time range from a Runtime PVI trace as compact columnar rows. |
| `plc_stop_pvi_trace` | `local_write` | `Runtime PVI TraceManager` | - | Stop a Runtime PVI trace and return its final compact summary. Idempotent for completed traces. |
| `plc_write_runtime_variable` | `target_change` | `persistent PVI runtime + policy` | `execute=true` | Write a discovered variable under the project PVI policy; requires execute=true. |
| `plc_write_pvi_batch` | `target_change` | `persistent PVI runtime + policy` | `execute=true` | Preflight-validate and write up to 20 PLC variables in one policy-enforced Runtime PVI batch with unified readback verification. Any preflight failure rejects the entire batch before writing. Requires explicit target and execute=true; production is permanently denied. |
| `plc_control_runtime` | `target_change` | `persistent PVI runtime + policy` | `execute=true` | Trigger a policy-checked PLC/ARsim Warmstart or Coldstart via PVI (with controlled PVITransfer fallback), clear cached PVI objects, and wait for runtime recovery. Requires execute=true; production is permanently denied. |


## Hidden Tools

共有 15 个工具被 `config/mcp/tool_filter.json` 隐藏（实现仍注册，仅供内部编排调用，MCP 列表与直接调用不可用）；具体名单见该配置文件。
<!-- END GENERATED MCP TOOL CATALOG -->

工具目录由 `python scripts/maintenance/generate_mcp_docs.py` 从 MCP schema 生成；用 `--check` 检查文档是否同步。

## 测试与输出

需要运行测试时，先安装测试依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest --index-url https://mirrors.aliyun.com/pypi/simple/
.\.venv\Scripts\python.exe -m pytest -q
```

测试以本地模拟为主，不代表本版本完成实机或 ARsim 验收。测试和调用可能生成 `var/`、`Temp/`、Python 缓存；`var/` 包含审计和历史报告，清理前应先确认保留需求。
