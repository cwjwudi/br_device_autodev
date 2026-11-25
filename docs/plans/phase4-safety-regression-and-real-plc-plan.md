# Phase 4 修改计划：安全策略语义收紧、场景回归脚手架与测试台架 / 真机验收

状态：待实施。本文档仅描述拟议修改与验收标准，不代表相关能力已上线。  
前置依赖：完成 [Phase 1](phase1-runtime-lifecycle-and-diagnostics-plan.md)、[Phase 2](phase2-project-topology-and-variable-dx-plan.md) 与 [Phase 3](phase3-architecture-multiprocess-and-python-migration-plan.md)。  
预计交付版本：`0.19.0a1`（向 `1.0.0` 工程级发布基线收口）

---

## 1. 背景与改造目标

在前三阶段补齐工具能力与底层架构后，工具链从“本机 ARsim 辅助开发”迈向“可长期沉淀回归用例、可受控用于专用测试台架 / 物理测试 PLC”仍存在 3 项关键短板：
1. **ARsim 写策略语义与配置不一致**：当前 `src/br_plc_toolchain/policy/runtime.py` 中 `role == "arsim" and mode != "blacklist"` 直接放行，导致在 ARsim 上显式配置 `write_policy: "whitelist"` 与非空 `write_whitelist` 时实际不生效（已有文档标注为待优化）。
2. **复杂闭环验证难以沉淀为可复用回归套件**：每次调通一个复杂状态机（如 `p106` 的“冷启动 → 上电 → 到准备位置 → 48 辆小车校验 → 凸轮多圈运行”）后，临时验证脚本往往随手删掉，后续改代码无法一键回归，也缺少失败自动留证（Trace + Logger + 自动还原变量）的统一框架。
3. **测试台架 / 真实 PLC 缺少分级预算与实战验收**：当前下载总超时在 `config/defaults/base.json` 被硬限制在 `1~60` 秒（对网络较慢或大工程真机可能截断合法下载）；且所有历史可靠性验收均基于回环 ARsim，尚未在专用物理测试 PLC 上完成端到端验收。

本阶段完成上述 **3 项工程化与安全收口任务**。

---

## 2. 现网代码基线核对

| 模块 | 现有文件 | 现状与限制 |
| :--- | :--- | :--- |
| 运行时写策略 | `src/br_plc_toolchain/policy/runtime.py` | 第 23-24 行：`if role == "arsim" and mode != "blacklist": return None`，忽略 ARsim 的白名单配置 |
| 下载超时配置 | `config/defaults/base.json`<br>`tools/mcp_server/download.py` | `download.timeout_seconds` 硬限 `1~60` 秒，不区分 `arsim` 与 `test_plc` |
| 下载安全检查 | `tools/plc_toolchain.ps1`（`Test-DownloadSafety`） | 对可信开发目标把部分 CPU/版本/配置/分区元数据不匹配降级为告警 |
| 公开 Python SDK | `src/br_plc_toolchain/client.py`<br>`src/br_plc_toolchain/__init__.py` | 已提供 `PviClient`（读/写/Trace/`wait_until`），缺少带自动留证与自动还原的场景回归夹具 |

---

## 3. 详细实施方案

### 3.1 收紧并明确 PVI 写策略语义（所见即所得）

1. **修改 `src/br_plc_toolchain/policy/runtime.py`**
   - 支持显式三种 `write_policy`：`whitelist` | `blacklist` | `allow_all`（`allow_all` **仅限 `role == "arsim"`**，物理测试 PLC 和生产机配置 `allow_all` 直接报错拒绝）；
   - 明确 `role == "arsim"` 的精确规则：
     - 未配置 `write_policy` 且未配置白/黑名单 → 默认等效 `allow_all`（保持默认体验平滑）；
     - 显式配置 `write_policy: "whitelist"` 且 `write_whitelist` **非空** → **严格按白名单校验**，不再静默绕过；
     - 显式配置 `write_policy: "whitelist"` 且 `write_whitelist` 为空 → 拒绝写入并提示“ARsim 如需放开全部可写变量，请将 `write_policy` 设为 `allow_all` 或切换为带保护项的 `blacklist`”（同时更新 `config/examples/br-auto-dev.example.json` 示例，避免新工程踩坑）；
     - 显式配置 `write_policy: "blacklist"` → 按黑名单拦截（建议默认模板自带 `*Safety*`、`gIOCtrl*`、`IOModule:*` 护栏）。
   - **不可变底层护栏**：无论任何角色或 `write_policy`，变量路径命中不可变 Safety 模式时永久拒绝写入。
2. **同步更新配置校验与文档**：在 `loader.py`、`README.md` 和 `config/examples/` 中同步说明，彻底消除“配置写了白名单却不起作用”的安全隐患。

### 3.2 公开场景回归测试脚手架（`ScenarioRunner`）

1. **新建 `src/br_plc_toolchain/testing/scenario.py` 并从顶层 `br_plc_toolchain` 导出**
   - 设计为基于 `PviClient` 的轻量 Python 夹具（不增加冗余 MCP 工具，直接服务 AI 与工程师编写项目级回归脚本）：
     ```python
     from br_plc_toolchain import PviClient, ScenarioRunner

     with PviClient.from_project(r"C:\path\to\project", target="arsim") as plc:
         runner = ScenarioRunner(
             plc,
             name="p106_cam_cycle_regression",
             report_dir=r"var/scenarios",
             trace_variables=["Main:eState", "Main:ReadyStep"],
             trace_interval_ms=20,
             auto_logger_on_fail=True,
             auto_restore=True,
         )
         with runner.run() as ctx:
             ctx.step("power_on", lambda: ...)
             ctx.assert_eventually("Main:eState", lambda v: v == 3, timeout_s=10.0)
     ```
   - 核心能力：
     - **结构化分步执行与计时**：记录每个 `step` 的起止时间、断言结果、失败堆栈；
     - **自动后台 Trace**：用例启动自动开启 `start_trace`，结束自动 `stop_trace` 并把 `trace_file` 挂入报告；
     - **失败自动取证**：任一断言失败或异常时，自动触发 `plc_read_logger(mode="aggregate")` 拉取最近 Error/Warning 快照并写入报告；
     - **异常安全还原（`finally`）**：退出时自动按 `br-auto-dev.json` 的 `pvi.restore_writes`（或用例注册的 `on_cleanup` 回调）还原控制变量，并记录还原是否全部读回成功；
     - **结构化产出**：每次运行生成 `var/scenarios/<timestamp>_<name>.json` 与易读 Markdown 摘要。
2. **提供 1 份开箱即用的参考回归模板**（`docs/examples/scenario_regression_template.py`），并在 `SKILL.md` 中说明“复杂状态机修复验收通过后，如何沉淀为项目级回归脚本”。

### 3.3 面向测试台架 / 真实 PLC 的分级超时与安全护栏

1. **下载超时按目标角色分级（`config/defaults/base.json`、`tools/mcp_server/download.py`）**
   - `download.timeout_seconds`（ARsim 默认上限）：保持 `60` 秒；
   - 新增 `download.physical_timeout_seconds`（物理测试 PLC 上限）：默认 `180` 秒（允许工程配置在 `30~300` 秒范围内调整），避免真机网络传输大 RUC 包在 60 秒被误截断；
   - `production` 角色依然在所有下载/重启/写入路径硬拒绝。
2. **收紧物理测试 PLC 的下载安全检查选项**
   - 对 `role == "test_plc"` 增加可配置项 `strict_download_check: true`（默认开启）：当物理目标的 CPU 类型、AR 大版本或配置身份无法确认或存在不匹配时，默认**阻断而非降级为告警**，必须由用户明确核实后方可覆盖；
   - 严禁在 `role == "test_plc"` 上使用 `bypass_download_safety`。

---

## 4. 自主开发测试与验收规程（分两段执行）

### 4.1 第一段：自动化单元测试与本机 ARsim 端到端验收（AI 可完全自主完成）

1. **新增自动化单元测试（`pytest`）**：
   - `tests/test_runtime_policy_v2.py`：全矩阵覆盖 `arsim` / `test_plc` / `production` × `whitelist`（空/非空）/ `blacklist` / `allow_all` / Safety 不可变拦截；
   - `tests/test_scenario_runner.py`：
     - 正常多步通过 → 产出 JSON + Markdown 报告、Trace 自动关闭、`restore_writes` 自动执行；
     - 中途断言失败 → 自动触发 Logger 取证、仍然执行 `restore_writes` 还原、报告状态为 `FAIL` 且保留完整证据路径；
     - 还原阶段失败 → 明确标注 `restore_ok: false` 而不静默吞错；
   - `tests/test_physical_plc_guardrails.py`：验证 `test_plc` 超时预算（最高 300 秒）、`strict_download_check=true` 阻断元数据不匹配、`bypass_download_safety` 对 `test_plc` 永久拒绝、`production` 全路径拒绝。
2. **全套回归命令**：
   ```powershell
   cd C:\Users\BR\codex_ws\br_device_autodev
   .\.venv\Scripts\python.exe -m pytest -v > var\verification\phase4-YYYYMMDD\pytest.log 2>&1
   .\.venv\Scripts\python.exe scripts\maintenance\generate_mcp_docs.py --check
   ```
3. **本机 ARsim 实测验收矩阵（P4-ARSIM-01 ~ P4-ARSIM-04）**：

| Case ID | 验收项 | 操作步骤 | 通过标准 |
| :--- | :--- | :--- | :--- |
| **P4-ARSIM-01** | ARsim 白名单真正生效 | 对测试目标配置 `write_policy="whitelist"` 且仅列入 1 个变量，分别写名单内与名单外变量 | 名单内写入成功；名单外返回 `POLICY_DENIED` |
| **P4-ARSIM-02** | `ScenarioRunner` 正常回归闭环 | 在本机 AS6 ARsim 上运行一个基于 `ScenarioRunner` 的多步回归脚本（含 20 ms Trace、状态等待与退出自动还原） | 报告状态 `PASS`，Trace 文件完整可读，退出后测试变量已还原为初始值 |
| **P4-ARSIM-03** | `ScenarioRunner` 失败自动留证与还原 | 故意注入一个不可能满足的断言条件触发失败 | 报告状态 `FAIL`，自动附带 Trace 与 Logger 聚合快照，且 `restore_writes` 仍完整执行 |
| **P4-ARSIM-04** | 全量现有下载可靠性复测 | 运行 `scripts/verify_arsim_downloads.py` 进行抽样回归（至少 10 次连续下载与 1 次断流恢复） | 全部可闭合查询状态，无残留进程，不退化既有可靠性 |

### 4.2 第二段：专用物理测试 PLC 专项验收（需用户显式授权后执行）

> [!IMPORTANT]
> 本段涉及真实硬件，**绝不可在无用户明确授权和指定专用测试台架 IP 的情况下自动执行**。如验收时尚无可用物理测试 PLC，第一段验收完成后可先交付 `0.19.0a1`，并将本段状态标注为 `PENDING_HARDWARE` 待上台架补测。

获得用户授权并确认台架处于安全空载状态后，按顺序执行以下 6 项真机验收（不得跳过前置检查）：

| Case ID | 验收项 | 操作步骤 | 通过标准 |
| :--- | :--- | :--- | :--- |
| **P4-PLC-01** | 只读探针与安全检查 | `plc_probe_target` → `plc_describe_ruc_package` → `plc_check_download`（启用 `strict_download_check=true`） | CPU 型号、AR 版本、配置身份完整匹配，无未解释阻断项 |
| **P4-PLC-02** | 真机只读发现与变量读取 | `plc_discover_runtime_target` → `plc_read_pvi_batch` → `plc_read_logger(mode="aggregate")` | 成功读回在线变量与非 Safety Logger 摘要 |
| **P4-PLC-03** | 真机安全护栏负向测试 | 尝试写非白名单变量、尝试 `bypass_download_safety=true`、尝试读取 Safety Logger | 全部在服务端被 `POLICY_DENIED` 拦截，未向真机下发任何危险写操作 |
| **P4-PLC-04** | 真机受控白名单写与读回 | 经用户确认 1 个安全无动作标志变量，先读原值 → 写同值/可逆测试值 → 读回校验 → 还原原值 | 写回校验一致，审计日志完整记录 |
| **P4-PLC-05** | 真机 RUC 下载与结果恢复 | 生成 `request_id` → `plc_download_ruc(execute=true)` → `plc_get_download_result(request_id)` → 后置只读探针与变量确认 | 记录实际传输耗时（验证 >60 秒预算生效），状态回到 `RUN`，无残留 `PVITransfer` |
| **P4-PLC-06** | 真机 Warmstart（仅用户单独授权时） | `plc_control_runtime(action="warmstart", execute=true)` → 确认恢复 `RUN` | 正常重启并重连，审计与日志齐全 |

### 4.3 必须交付的完整验收报告

实施完成后，生成 `docs/verification/phase4-verification-YYYYMMDD.md`（原始证据存入 `var/verification/phase4-YYYYMMDD/`），报告必须包含：
1. **自动化测试统计**：总用例数、新增用例数、通过/失败数、`pytest.log` 路径、`generate_mcp_docs.py --check` 结果。
2. **第一段 ARsim 实测矩阵（P4-ARSIM-01 ~ P4-ARSIM-04）**：附 `ScenarioRunner` 产出的 PASS 与 FAIL 两份完整报告路径与摘要。
3. **第二段物理测试 PLC 验收记录（P4-PLC-01 ~ P4-PLC-06）**：如已执行，附上硬件型号、AR 版本、每项耗时、下载与审计证据路径；如暂未接入硬件，明确标注 `PENDING_HARDWARE` 及未验证边界（**不得用 ARsim 结果替代真机验收结论**）。
4. **工具链发布就绪评估**：汇总 Phase 1~4 全部遗留项与已知限制，给出是否具备升级至 `1.0.0` 基线的明确结论。
