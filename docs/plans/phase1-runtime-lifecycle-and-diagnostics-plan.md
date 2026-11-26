# Phase 1 修改计划：ARsim 生命周期、PLC 运行态控制、Logger 聚合诊断与配置脚手架

状态：已完成并通过验收（`0.16.0a1`，验收报告见 [phase1-verification-20261124.md](../verification/phase1-verification-20261124.md)）。  
前置依赖：完成 [roadmap-2026-11.md](roadmap-2026-11.md) 中的 Phase 0 基线核对。  
预计交付版本：`0.16.0a1`

---

## 1. 背景与改造目标

在 `p106_at_auto_test_3` 等真实项目排障中，当前工具链暴露出 4 个高频体验断点：
1. **ARsim 能建不能停**：仅有 `plc_provision_arsim` 和 `plc_start_arsim`，缺少停止、重启、列表与目录清理能力，导致单个工程被迫堆砌 5~6 个不同回环 IP 目标和大量残留 `Temp/Simulation/codex-arsim/*` 目录。
2. **PLC 运行态无法控制**：目标进入 `SERVICE` 模式或需要冷/热启动回归时，AI 无法通过工具链执行 Warmstart / Coldstart，只能手写脚本绕行。
3. **Logger 排障成本高**：`plc_read_logger` 每次仅能按准确模块名拉取单份 `.csvx` 落盘，AI 无法一键看全最近 Error/Warning 摘要。
4. **新工程接入与旧配置迁移门槛高**：手工编写 `br-auto-dev.json` 容易写错 `project_path` / `config`，旧字段 `access_policy` 报错缺少迁移引导。

本阶段完成上述 **4 项高价值能力**，全程克制 MCP 工具膨胀（仅新增 3 个高内聚工具 + 增强 1 个现有工具）。

---

## 2. 现网代码基线核对

| 模块 | 现有文件 | 现状与限制 |
| :--- | :--- | :--- |
| ARsim 离线释放 | `tools/mcp_server/arsim_provision.py` | 创建 `codex-arsim/<uuid>/runtime`，写出 `request.json` 与 `instance.json`，但无全局注册表，无 `stop/restart/clean` |
| 锁与作用域 | `tools/mcp_server/locks.py` | 已有 `arsim:allocation` 与 `target:*` 锁 |
| PVI Worker / 服务 | `src/br_plc_toolchain/backends/pvi/worker.py`<br>`src/br_plc_toolchain/services/runtime_pvi.py`<br>`src/br_plc_toolchain/client.py` | 仅实现变量读写/列表/Trace，未封装 CPU Warmstart / Coldstart |
| Logger 读取 | `tools/plc_logger_read.py`<br>`tools/mcp_server/toolchain.py` | 单模块 PVITransfer `Logger` 导出与 `.csvx` 解析，已硬拦截 `safety` 模块 |
| 诊断与配置加载 | `tools/mcp_server/diagnostics.py`<br>`src/br_plc_toolchain/config/loader.py` | 仅校验现有配置，无自动发现 `.apj`/Config 生成模板与迁移提示 |
| Schema 与文档 | `tools/mcp_server/schemas.py`<br>`config/mcp/tool_filter.json`<br>`scripts/maintenance/generate_mcp_docs.py` | `README.md` MCP 工具表由脚本校验同步 |

---

## 3. 详细实施方案

### 3.1 ARsim 实例注册表与全生命周期工具（`plc_manage_arsim`）

1. **新建实例注册表模块 `tools/mcp_server/arsim_registry.py`**
   - 持久化路径：`var/arsim/instances.json`（原子写入：写临时文件后 `os.replace`，受 `arsim:allocation` 文件锁保护）。
   - 单条记录字段：
     ```json
     {
       "run_id": "<uuid>",
       "project_path": "C:/.../Project.apj",
       "config": "SecPackTest",
       "target": "arsim",
       "family": "AS6",
       "ip": "127.0.0.1",
       "run_directory": "C:/.../Temp/Simulation/codex-arsim/<uuid>",
       "runtime_directory": "C:/.../Temp/Simulation/codex-arsim/<uuid>/runtime",
       "loader_exe": "C:/.../runtime/ar000loader.exe",
       "loader_pid": 12345,
       "runtime_pid": 12346,
       "created_at": "2026-11-24T15:00:00Z",
       "status": "running"
     }
     ```
   - 修改 `tools/mcp_server/arsim_provision.py`：
     - `provision()` 成功监听后立即向注册表写入记录；
     - 新增可选参数 `replace_existing: bool = False`（仅在明确 `execute=true` 且被占用进程**经归属校验确认属于当前工程同一 target** 时，先调用安全停止再释放，绝不接管外部或其它项目实例）。

2. **新增 MCP 工具 `plc_manage_arsim`**
   - 参数：`action`（`list` | `stop` | `restart` | `clean`）、`project_path`（可选，用于按工程过滤）、`target`（可选）、`run_id`（可选）、`keep_latest`（`clean` 时默认保留最近 2 个已停止目录）、`execute`（`stop/restart/clean` 必须为 `true`）。
   - 风险级别：`list` 内部只读放行，整体工具声明 `risk = "target_change"`（或将只读列表拆给 `action="list"` 时允许 `execute=false` 返回结果，变更动作无 `execute=true` 返回 `CONFIRMATION_REQUIRED`）。
   - **强制归属校验（安全核心）**：
     - `stop` / `restart` 必须同时满足：
       1. 目标 `run_id` 或 `target` 存在于注册表（或指定 `run_directory` 内存在合法 `instance.json`）；
       2. 待终止进程的 `ExecutablePath` 位于 `runtime_directory` 之下（通过 PowerShell/WMI 或 `psutil`/Win32 API 校验，拒绝仅凭 PID 盲杀以防 PID 复用）；
       3. 终止进程树后再次调用 `occupancy` 复核 11169 端口已释放。
     - `clean` 仅允许删除位于 `*/codex-arsim/<run_id>` 下且确认已无存活进程的目录；若目录内仍有存活进程则跳过并记录 `skipped_running`。

### 3.2 PLC 运行态控制（`plc_control_runtime` + `PviClient.restart`）

1. **PVI 后端实现（`src/br_plc_toolchain/backends/pvi/worker.py`）**
   - 新增 `_restart(mode: str, wait_ready_timeout: float = 30.0)`：
     - 支持 `mode in {"warm", "cold"}`；
     - 优先调用 `pvipy` CPU 重启接口（需先核实 `pvipy==1.2.11` 实际暴露的重启方法名，如 `cpu.restart(...)` 或 `cpu.warmstart()`/`coldstart()`）；若当前 `pvipy` 绑定缺失或不支持特定 AR 版本，则受控回退到 `PVITransfer.exe -silent` 执行单条 `WarmStart` / `ColdStart` `.pil` 指令（复用 Job Object 与超时预算）。
     - 重启发起后主动失效当前变量对象缓存（`self._variables.clear()`），在 `wait_ready_timeout` 内轮询重连并读取 CPU 运行状态（`RUN` / `SERVICE` / `BOOT`），返回重启前状态、执行方式（`pvi` 或 `pvitransfer`）、重启后状态及耗时。
2. **服务层与策略校验（`src/br_plc_toolchain/services/runtime_pvi.py`）**
   - 新增 `restart_target(target_name, *, mode, execute, timeout_seconds=30)`；
   - **安全策略**：
     - `role == "production"` 永久拒绝（错误码 `POLICY_DENIED`）；
     - 物理测试 PLC（`role == "test_plc"`）仅在目标显式配置 `allow_runtime_control: true`（或 `allow_auto_download: true`）且 `execute=true` 时允许；
     - ARsim（`role == "arsim"`）在 `execute=true` 时允许。
3. **MCP 工具与 SDK 暴露**
   - 新增 MCP 工具 `plc_control_runtime`（`action: "warmstart" | "coldstart"`，`target` 必填，`execute=true` 必填，`risk = "target_change"`，受 `target:*` 锁和审计保护）。
   - 在 `PviClient`（`src/br_plc_toolchain/client.py`）公开 `restart(mode="warm", *, execute=False, timeout_seconds=30.0)`，供回归脚本调用。

### 3.3 Logger 多模块聚合诊断（增强 `plc_read_logger`）

1. **后端增强（`tools/plc_logger_read.py`）**
   - 保持现有单模块调用向后兼容；
   - 新增批量/聚合函数 `diagnose_loggers(...)`：
     - 默认模块预设组 `DEFAULT_DIAGNOSTIC_MODULES = [("System", "$arlogsys"), ("User", "$arlogusr"), ("Motion", "$motion"), ("Fieldbus", "$fieldbus")]`（可通过 `modules` 参数覆盖）；
     - 仍然对任何包含 `safety` 的模块名/类型做不可变拦截；
     - 逐个拉取（受总时间预算约束，单模块不存在或空时记为 `missing_or_empty` 而不中断其他模块）；
     - 解析所有成功拉取的 `.csvx`，按 `min_severity`（默认 `"warning"`，可选 `"info" | "warning" | "error"`）与 `since_minutes`（可选）过滤，按时间戳降序合并，默认返回 **Top 50** 条紧凑事件（字段：`timestamp`、`module`、`severity`、`event_id`、`object_id`、`description`），附带各模块原始 `.csvx` 路径和总计过滤前后条数。
2. **MCP 接口扩展**
   - 在 `plc_read_logger` 中增加可选参数：`mode: "single" | "aggregate"`（默认 `"single"` 保持兼容）、`modules`、`min_severity`、`since_minutes`、`max_entries`（默认 50，上限 200）。
   - 这样不增加额外 MCP 工具名，AI 只需传 `mode="aggregate"` 即可一步看全系统与运动报错。

### 3.4 工程配置初始化与旧配置迁移引导（`plc_init_project_config`）

1. **配置发现与生成模块（`tools/mcp_server/project_init.py`）**
   - 输入：`project_dir` 或 `.apj` 路径、目标预设模板（`arsim` | `test_plc_whitelist` | `test_plc_blacklist`，默认 `arsim`）、`config`（可选，未传时自动选择）、`ip`（默认 `127.0.0.1`）、`overwrite: bool = False`、`execute: bool = False`。
   - 自动扫描逻辑：
     - 定位 `.apj` 文件，解析其 `AutomationStudio` 版本号（区分 AS4 / AS6），自动匹配全局 `toolchains.json` 中已启用的对应 `toolchain` ID；
     - 解析 `Physical/Physical.pkg` 列出所有可用 Config 名称，并在可能时读取各 Config 的 `Hardware.hw` 提取 `SimulationIPAddress`；
     - `execute=false` 时仅返回候选 Config 列表、推荐 `br-auto-dev.json` 内容与差异，不写盘；
     - `execute=true` 时安全写入 `br-auto-dev.json`（已存在且 `overwrite=false` 时拒绝覆盖）。
2. **旧配置迁移提示（`src/br_plc_toolchain/config/loader.py`）**
   - 当检测到已废弃字段（如 `access_policy`）时，在错误信息中明确输出迁移对照建议（`write_policy` + `write_whitelist`/`write_blacklist` + `allow_auto_download`），而不是只报未知键错误。

### 3.5 文档与 Skill 同步

- 运行 `scripts/maintenance/generate_mcp_docs.py` 更新 `README.md`；
- 更新 `.agents/skills/br-plc-toolchain/SKILL.md`，补充 `plc_manage_arsim`、`plc_control_runtime`、`plc_read_logger(mode="aggregate")`、`plc_init_project_config` 的标准调用时机。

---

## 4. 自主开发测试与验收规程（必须全部执行）

### 4.1 自动化单元测试与故障注入（`pytest`）

新增并运行以下测试文件，确保新旧测试 100% 通过：

1. **`tests/test_arsim_lifecycle.py`**
   - 注册表读写原子性、按工程/目标过滤 `list`；
   - **归属防误杀测试**：模拟 PID 被 `notepad.exe` 或其他目录 `ar000loader.exe` 占用时，`stop` 必须拒绝终止并返回 `ARSIM_OWNERSHIP_MISMATCH`；
   - `clean` 跳过仍在运行的目录，正确保留 `keep_latest` 个历史目录，拒绝清理 `codex-arsim` 之外的任意路径；
   - `replace_existing=true` 对外部未知占用仍返回 `ARSIM_IP_OCCUPIED`。
2. **`tests/test_runtime_control.py`**
   - `warmstart` / `coldstart` 正常流程（含缓存清空与重连等待）；
   - `execute=false` 拒绝、`production` 角色永久拒绝、未授权物理测试 PLC 拒绝；
   - 重启后超时未恢复返回明确 `RUNTIME_RESTART_TIMEOUT` 且不伪报 `RUN`；
   - `PviClient.restart(...)` 公开接口验证。
3. **`tests/test_logger_aggregate.py`**
   - 多模块混合（2 个成功、1 个模块不存在、1 个含 `safety` 被拦截）时的聚合行为；
   - `min_severity`、`since_minutes`、`max_entries` 过滤与按时间倒序排序正确性；
   - `.csvx` 含特殊引号/非 ASCII 字符解析不崩溃。
4. **`tests/test_project_init.py`**
   - 自动发现 AS4 / AS6 `.apj`、提取 `Physical.pkg` 多 Config、自动匹配 `toolchains.json`；
   - `execute=false` 预览不写文件、`overwrite=false` 保护已有配置；
   - 含旧 `access_policy` 字段的配置文件返回带迁移指引的错误。
5. **全套回归命令**：
   ```powershell
   cd C:\Users\BR\codex_ws\br_device_autodev
   .\.venv\Scripts\python.exe -m pytest -v > var\verification\phase1-YYYYMMDD\pytest.log 2>&1
   .\.venv\Scripts\python.exe scripts\maintenance\generate_mcp_docs.py --check
   ```

### 4.2 本机 ARsim 端到端实测验收

在真实本机环境使用至少 **1 个 AS6 工程**（如 `C:\Users\BR\codex_ws\p106_at_auto_test_3` 或 `p103_test_pos_gen`）完成以下 6 项实测（使用独立空闲回环 IP，不干扰已有实例）：

| Case ID | 验收项 | 操作步骤 | 通过标准 |
| :--- | :--- | :--- | :--- |
| **P1-E2E-01** | 配置自动初始化 | 对临时拷贝或指定工程目录调 `plc_init_project_config(execute=false)` 与 `execute=true` | 正确识别 `.apj`、Config 列表和 `as6_default`，生成配置可通过 `plc_validate_environment` |
| **P1-E2E-02** | ARsim 释放 + 列表纳管 | 调 `plc_provision_arsim(execute=true)` 后调 `plc_manage_arsim(action="list")` | 新实例出现在注册表与实时列表，PID、IP、目录完全匹配 |
| **P1-E2E-03** | PLC Warmstart 实测 | 连上 ARsim 确认初始状态 → 调 `plc_control_runtime(action="warmstart", execute=true)` → 读变量验证 | 重启成功，PVI 自动重连，状态回到 `RUN`，变量读回正常，审计落盘 |
| **P1-E2E-04** | Logger 多模块聚合诊断 | 调 `plc_read_logger(mode="aggregate", min_severity="warning", max_entries=30)` | 返回结构化事件列表与各模块 `.csvx` 路径；若尝试加入 `Safety` 模块被明确拦截 |
| **P1-E2E-05** | ARsim 安全停止与同 IP 重建 | 调 `plc_manage_arsim(action="stop", execute=true)` → 检查端口释放 → `provision(replace_existing=true)` 或再次释放同 IP | 仅停止自身归属进程，11169 端口释放，同 IP 可干净重建；其他已有 ARsim 实例不受影响 |
| **P1-E2E-06** | 历史目录清理 | 调 `plc_manage_arsim(action="clean", keep_latest=1, execute=true)` | 仅清理已停止的旧测试目录，运行中实例目录未被触碰 |

### 4.3 必须交付的完整验收报告

实施完成后，生成 `docs/verification/phase1-verification-YYYYMMDD.md`，并将原始日志存入 `var/verification/phase1-YYYYMMDD/`，内容必须包含：
1. **自动化测试统计**：总测试数、新增测试数、通过/失败数、`pytest.log` 路径、`generate_mcp_docs.py --check` 退出码。
2. **P1-E2E-01 ~ P1-E2E-06 实测结果表**：每项包含实际调用参数、耗时（秒）、关键返回值摘要、对应审计/日志路径与 PASS/FAIL 结论。
3. **负面与安全护栏实测结果**：记录 `execute=false`、`production` 拒绝、归属不匹配拒绝、Safety Logger 拒绝的实际错误码。
4. **环境收尾核查**：附上验收结束后 `Get-Process ar000loader, PVITransfer` 与端口 11169 的核查输出，确认无本次测试残留进程。
