# Phase 1 阶段验收报告（ARsim 生命周期、PLC 运行态控制、Logger 聚合诊断与配置脚手架）

交付版本：`0.16.0a1`  
验收日期：`2026-11-24`  
对应计划：[phase1-runtime-lifecycle-and-diagnostics-plan.md](../plans/phase1-runtime-lifecycle-and-diagnostics-plan.md)

---

## 1. 验收范围与环境基线

- **仓库路径**：`C:\Users\BR\codex_ws\br_device_autodev`
- **基线 Git Commit**：`8f7236a`（`0.15.2a1` → `0.16.0a1`）
- **Python 解释器**：`C:\Users\BR\codex_ws\br_device_autodev\.venv\Scripts\python.exe`（Python 3.14.6，pytest 9.2.0，pvipy 1.2.11）
- **工具链**：`as6_default`（AS6 / PVI6，`PVITransfer.exe` + `Pvi6Com64.dll`）
- **端到端测试工程**：基于 `C:\Users\BR\codex_ws\p103_test_pos_gen\base_prj`（AS6，`Config1`，含已构建 `RUCPackage.zip`）隔离拷贝至 `var/verification/phase1-20261124/e2e_p103_proj`
- **端到端测试目标 IP**：`127.0.0.25`（独立空闲回环地址，未干扰已有 `p101_inmay_at` 实例 PID `104856`）
- **验收范围**：
  1. ARsim 实例注册表（`var/arsim/instances.json`）、`plc_manage_arsim`（`list`/`stop`/`restart`/`clean`）及 `plc_provision_arsim(replace_existing=true)`；
  2. PLC 运行态控制 `plc_control_runtime`（`warmstart`/`coldstart`）与 `PviClient.restart(...)`；
  3. Logger 多模块聚合诊断 `plc_read_logger(mode="aggregate")` 与 Safety 模块不可变拦截；
  4. 工程配置自动初始化 `plc_init_project_config` 与旧配置 `access_policy` 迁移引导。

---

## 2. 自动化测试结果汇总

- **回归命令**：
  ```powershell
  cd C:\Users\BR\codex_ws\br_device_autodev
  .\.venv\Scripts\python.exe -m pytest -v > var\verification\phase1-20261124\pytest.log 2>&1
  .\.venv\Scripts\python.exe scripts\maintenance\generate_mcp_docs.py --check
  ```
- **测试统计**：
  - 基线用例数：228 passed（216 subtests）
  - 新增 Phase 1 专项用例：20 个（覆盖 `tests/test_arsim_lifecycle.py`、`tests/test_runtime_control.py`、`tests/test_logger_aggregate.py`、`tests/test_project_init.py`）
  - 最终全套回归结果：**248 passed, 0 failed, 0 skipped, 231 subtests passed**（退出码 `0`）
- **MCP 文档同步检查**：`scripts/maintenance/generate_mcp_docs.py --check` 退出码 `0`（`README.md` 与 `schemas.py` 一致）。
- **原始日志路径**：`var/verification/phase1-20261124/pytest.log`

---

## 3. 端到端实测用例矩阵（本机真实 ARsim）

所有 6 项实测均通过 `server.handle_tools_call` 走完整 MCP Schema 校验、锁控制与审计链路，原始结构化结果保存于 `var/verification/phase1-20261124/e2e_results.json`。

| Case ID | 验收项 | 操作步骤与关键参数 | 预期结果 | 实测结果摘要 | 耗时 (s) | 判定 |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **P1-E2E-01** | 配置自动初始化 | `plc_init_project_config(project_path=e2e_p103_proj, ip="127.0.0.25", execute=false)` → `execute=true` → `plc_validate_environment` | 自动识别 `.apj`、`Config1`、`as6_default`，预览不落盘，写入后通过环境校验 | `family="AS6"`, `matched_toolchain="as6_default"`, `available_configs=["Config1"]`, `preview_written=false`, `write_written=true`, `validate_ok=true` | 1.356 | **PASS** |
| **P1-E2E-02** | ARsim 释放 + 列表纳管 | `plc_provision_arsim(target="arsim", execute=true)` → `plc_manage_arsim(action="list", project_path=e2e_p103_proj, target="arsim", execute=false)` | 新实例写入注册表并出现在实时列表，PID、IP、目录完全匹配 | `run_id=326c5718...`, `ip=127.0.0.25`, `loader_pid=110844`, `runtime_pid=132700`, `listed_live_status="running"`, `listed_pid_match=true` | 16.852 | **PASS** |
| **P1-E2E-03** | PLC Warmstart 实测 | `plc_discover_runtime_target` → 读变量 `PosGenTest:posgentest` → `plc_control_runtime(action="warmstart", execute=true)` → 再次读变量 | 重启成功，缓存对象清理并重连，状态回到 `RUN`，变量读回正常，审计落盘 | `method="pvi"`, `before_status="RUN"`, `after_status="RUN"`, `cache_cleared=true`, `var_before_ok=true`, `var_after_ok=true`（完整结构体读回）, 审计已落盘 | 5.332 | **PASS** |
| **P1-E2E-04** | Logger 多模块聚合诊断 | `plc_read_logger(mode="aggregate", min_severity="info", max_entries=30)`；随后尝试 `modules=["Safety/$arlogsafe"]` | 返回结构化事件与各模块 `.csvx` 路径；缺失模块不中断其余模块；Safety 被明确拦截 | `System/$arlogsys`(5条)、`User/$arlogusr`(1条)、`Fieldbus/$fieldbus`(1条) 成功并落盘 `.csvx`，`Motion/$motion` 标记 `missing_or_empty`；Safety 返回 `SAFETY_LOGGER_BLOCKED` | 8.326 | **PASS** |
| **P1-E2E-05** | ARsim 安全停止与同 IP 重建 | `plc_manage_arsim(action="stop", run_id=..., execute=true)` → 查 11169 端口 → 同 IP 重建 → `plc_provision_arsim(replace_existing=true, execute=true)` | 仅停自身进程，11169 释放，同 IP 可重建及安全替换；其他项目实例不受影响 | `stop1_ok=true`, `port_11169_released=true`, `occupancy_after_stop="free"`, `rebuild_ok=true`, `replace_existing_ok=true` (`replaced_count=1`)；`p101_inmay_at` PID `104856` 未受影响 | 42.806 | **PASS** |
| **P1-E2E-06** | 历史目录清理 | 1 个运行中实例 + 2 个已停止目录，执行 `plc_manage_arsim(action="clean", keep_latest=1, execute=true)` | 跳过运行中目录，保留最新 1 个已停止目录，清理更旧目录 | `skipped_running=["af16e014..."]`, `kept=["58dcf1b2..."]`, `removed=["326c5718..."]`, `running_dir_still_exists=true` | 0.692 | **PASS** |

> **实测发现并修复的真实缺陷**：首次 E2E 运行 `P1-E2E-03` 时发现 `PviWorker._restart` 仅清空 `_variables`/`_tasks` 字典而未调用 `pvipy` 对象 `.kill()`，且过渡等待仅 `0.25s` 导致在 ARsim 尚未断开重启时即误读旧 `RUN` 状态、紧随其后的变量重读失败。修复为先 `.kill()` 缓存对象再清空，并在重启后等待过渡期及校验 `cpu.tasks` 可读后再返回，修复后 `P1-E2E-03` 一次通过。

---

## 4. 故障注入与安全护栏验证结果

| 负面/安全场景 | 验证层级 | 实测结果 / 错误码 | 判定 |
| :--- | :--- | :--- | :---: |
| `plc_manage_arsim(action="stop", execute=false)` | 实测 + 单测 | `CONFIRMATION_REQUIRED`（拒绝终止） | **PASS** |
| `plc_control_runtime(action="warmstart", execute=false)` | 实测 + 单测 | `CONFIRMATION_REQUIRED`（拒绝重启） | **PASS** |
| `plc_control_runtime` 对 `role="production"` 目标 | 实测 + 单测 | `POLICY_DENIED`（永久拒绝） | **PASS** |
| `plc_control_runtime` 对未配置 `allow_runtime_control` 的 `dedicated_test_plc` | 单测 | `POLICY_DENIED` | **PASS** |
| PID 被 `notepad.exe` 或其他目录 `ar000loader.exe` 复用时 `stop` | 单测故障注入 | `ARSIM_OWNERSHIP_MISMATCH`（零进程被误杀） | **PASS** |
| `replace_existing=true` 遇到外部未知进程占用 IP | 单测故障注入 | `ARSIM_IP_OCCUPIED`（附 `replace_rejected_reason`，拒绝接管） | **PASS** |
| `clean` 指向 `codex-arsim` 之外的任意目录 | 单测故障注入 | `ARSIM_UNSAFE_CLEAN_PATH`（目录未被删除） | **PASS** |
| 重启后目标超时未恢复（一直停留在 `Boot`） | 单测故障注入 | `RUNTIME_RESTART_TIMEOUT`（不伪报 `RUN`） | **PASS** |
| Logger 聚合请求包含 `Safety/$arlogsafe` | 实测 + 单测 | `SAFETY_LOGGER_BLOCKED`（永不调用 PVITransfer） | **PASS** |
| 旧配置含已移除 `access_policy` 字段 | 单测 | `ValueError` 明确输出 `write_policy` / `write_whitelist` / `write_blacklist` / `allow_auto_download` 迁移指引 | **PASS** |

---

## 5. 原始证据索引

- **自动化测试日志**：`var/verification/phase1-20261124/pytest.log`
- **端到端实测脚本与结果**：
  - `var/verification/phase1-20261124/run_phase1_e2e.py`
  - `var/verification/phase1-20261124/e2e_results.json`
  - `var/verification/phase1-20261124/e2e_stdout.log`
- **环境收尾核查日志**：`var/verification/phase1-20261124/cleanup_check.log`
- **Logger 聚合导出 `.csvx` 证据**：
  - `var/logger/20261124_155953_53298_arsim_System_arlogsys.csvx`
  - `var/logger/20261124_155955_78566_arsim_User_arlogusr.csvx`
  - `var/logger/20261124_155959_64256_arsim_Fieldbus_fieldbus.csvx`
- **关键审计记录（`var/audit/2026-11-24/`）**：
  - `plc_init_project_config`: `155927_742268_plc_init_project_config_succeeded_70ca348a.json`
  - `plc_provision_arsim`: `155944_299558_plc_provision_arsim_succeeded_b8a1f2a0.json`, `160045_921663_plc_provision_arsim_succeeded_ef27dde3.json`
  - `plc_control_runtime`: `155952_730243_plc_control_runtime_succeeded_dd5b31ca.json`
  - `plc_manage_arsim`: `160006_213784_plc_manage_arsim_succeeded_4be8dc4d.json`, `160046_608927_plc_manage_arsim_succeeded_6b3b7dd3.json`

---

## 6. 遗留问题、已知限制与清理确认

- **已验证**：AS6 工程配置初始化、ARsim 释放/注册表纳管/安全停止/同 IP 替换/目录清理、PVI Warmstart（含缓存对象 `kill()` 与重连后变量读回）、Logger 多模块聚合与 Safety 拦截、全套安全护栏及 248 个单元测试。
- **未覆盖 / 已知限制**：
  - 物理测试 PLC（`dedicated_test_plc`）上的 Warmstart/Coldstart 仅完成策略层单元测试，未在真机上执行（留待 Phase 4 用户授权专用测试 PLC 后验收）；
  - `PVITransfer` 回退重启路径在真实 ARsim 上因 `pvipy` 原生 `warmStart()` 直接成功而未触发回退，后续可在不支持原生重启的旧 AR 版本上补充实测。
- **环境收尾核查结果**（见 `var/verification/phase1-20261124/cleanup_check.log`）：
  ```text
  === Get-Process ar000loader, ar000, PVITransfer ===
  Name            Id Path
  ----            -- ----
  ar000loader 104856 C:\Users\BR\codex_ws\p101_inmay_at\Application\Temp\Simulation\SecPackTest\X20CP3687X\ar000loader.exe

  === Port 11169 on 127.0.0.25 ===
  {"ok":true,"slots":[{"slot":1,"ip":"127.0.0.25","pviPort":11169,"state":"free","conflicts":[]}]}
  ```
  本次测试创建的全部 ARsim 实例与临时目录均已停止并清理，端口 `127.0.0.25:11169` 为 `free`，无任何测试残留进程，原有 `p101_inmay_at` 实例保持完好。
