# `br-auto-dev` 工具链演进路线图与分阶段实施总览

基线版本：`0.15.2a1`（2026-11-24）  
适用仓库：`C:\Users\BR\codex_ws\br_device_autodev`  
状态：规划完成，按阶段独立实施与验收。

---

## 1. 演进目标与阶段划分

本路线图针对当前工具链在 B&R Automation Studio（AS4 / AS6）自动开发与复杂设备调试（如 `ACOPOStrak` 多小车协同）中暴露出的能力空白与架构短板，拆分为 **Phase 0（基线收口）+ 4 个独立可交付阶段**：

| 阶段 | 文档 | 核心目标 | 建议顺序 | 前置依赖 |
| :--- | :--- | :--- | :---: | :--- |
| **Phase 0** | 见本文第 2 节 | 统一 `.venv` 运行环境、清理隐藏工具清单与基线文档 | 0 | 无 |
| **Phase 1** | [phase1-runtime-lifecycle-and-diagnostics-plan.md](phase1-runtime-lifecycle-and-diagnostics-plan.md) | ARsim 全生命周期（停/重启/清理）、PLC Warmstart/Coldstart、Logger 多模块聚合错误诊断、`br-auto-dev.json` 初始化与迁移 | 1 | Phase 0 |
| **Phase 2** | [phase2-project-topology-and-variable-dx-plan.md](phase2-project-topology-and-variable-dx-plan.md) | AS 工程拓扑只读解析与静态校验、在线变量分页缓存、结构体叶子展开、MCP 受控批量写 | 2 | Phase 1（推荐） |
| **Phase 3** | [phase3-architecture-multiprocess-and-python-migration-plan.md](phase3-architecture-multiprocess-and-python-migration-plan.md) | PVI Worker 子进程隔离（同会话共存 AS4/AS6）、全局构建排队锁（根治 9207）、高频采样性能基准与优化、`plc_toolchain.ps1` 逐步迁回 Python | 3 | Phase 1 & 2 |
| **Phase 4** | [phase4-safety-regression-and-real-plc-plan.md](phase4-safety-regression-and-real-plc-plan.md) | ARsim 写策略语义收紧、`PviClient` 场景回归脚手架（`ScenarioRunner`）、测试台架/真机下载超时分级与真机验收 | 4 | Phase 1~3 |

---

## 2. Phase 0：启动前基线收口清单（必做前置）

在启动 Phase 1 之前，执行以下 3 项环境与仓库核对（约 15 分钟）：

1. **统一客户端 MCP Python 解释器**：
   - 核对本机 MCP 客户端配置（如 `C:\Users\BR\.gemini\config\mcp_config.json` 与 `.vscode\mcp.json`），将 `br-plc-toolchain` 的 `command` 统一指向 `C:/Users/BR/codex_ws/br_device_autodev/.venv/Scripts/python.exe` 并设置 `cwd`，重启客户端确认 MCP 工具列表与 `README.md` 一致。
2. **确认基线测试全绿**：
   ```powershell
   cd C:\Users\BR\codex_ws\br_device_autodev
   .\.venv\Scripts\python.exe -m pytest -q
   .\.venv\Scripts\python.exe scripts\maintenance\generate_mcp_docs.py --check
   ```
3. **盘点旧隐藏工具**：
   - 核对 `config/mcp/tool_filter.json` 中 15 个 `disabled_tools`，在各阶段实施时明确标注“保留供兼容 / 由新工具替代 / 计划移除”，避免双轨维护失控。

---

## 3. 给执行 AI 的统一开发与自主验收规范

每个阶段文档均设计为**可交给独立新对话自主执行**。负责实施的 AI 必须严格遵守以下交付纪律：

1. **安全红线不可突破**：
   - 所有涉及目标状态变更的新工具必须显式标注 `risk = "target_change"` 且要求 `execute=true`；
   - `production` 角色永久拒绝下载、重启与写入；
   - Safety 模块、Safety 工程与物理 I/O 永久禁止自动修改或读取/写入绕过；
   - 停止或清理 ARsim 进程前必须同时校验 **PID + 可执行路径归属 + 端口/运行目录**，绝不误杀其他项目实例。
2. **文档与工具清单强制同步**：
   - 任何 MCP 工具增删或 Schema 变更后，必须执行：
     ```powershell
     .\.venv\Scripts\python.exe scripts\maintenance\generate_mcp_docs.py
     .\.venv\Scripts\python.exe scripts\maintenance\generate_mcp_docs.py --check
     ```
   - 同步更新 `.agents/skills/br-plc-toolchain/SKILL.md`（仅保留高频决策规则，避免膨胀）。
3. **禁止“只写代码不实测”或“口头宣称通过”**：
   - 每个阶段必须完成两层测试：
     1. **自动化单元测试 + 故障注入测试**（`pytest`，不得跳过现有用例）；
     2. **本机真实 ARsim 端到端实测**（AS6 优先用 `p106_at_auto_test_3` 或 `p103_test_pos_gen`，AS4 用 `p801_plc_debug_log`；Phase 4 真机部分须在用户明确授权并指定专用测试 PLC 后执行）。
4. **必须产出完整的阶段验收报告（含原始测试结果与证据路径）**：
   - 每个阶段完成后，必须在 `docs/verification/` 下生成一份独立的验收报告（命名：`phase<N>-verification-YYYYMMDD.md`），并将原始测试输出保存到 `var/verification/phase<N>-YYYYMMDD/`。
   - 报告必须至少包含以下 6 个固定章节：
     1. **验收范围与环境基线**（Git commit hash、Python/AS4/AS6/PVI 版本、测试工程与目标 IP）；
     2. **自动化测试结果汇总**（`pytest` 完整命令、总用例数、通过/失败/跳过数、`generate_mcp_docs.py --check` 结果、原始日志路径）；
     3. **端到端实测用例矩阵**（逐项列出 Case ID、操作步骤、预期结果、实测结果、耗时、判定 PASS/FAIL）；
     4. **故障注入与安全护栏验证结果**（越权写入、`execute=false`、进程归属不匹配、`production` 拒绝、超时/断连等负面用例实测结果）；
     5. **原始证据索引**（指向 `var/verification/...`、`var/audit/...`、`var/downloads/...`、`var/reports/...` 的具体文件路径）；
     6. **遗留问题、已知限制与清理确认**（明确区分“已验证”与“未覆盖”，并列出测试结束后本机残留 ARsim/PVITransfer 进程核查结果）。
   - **未提供完整实测数据与证据路径的，视为阶段未完成。**
