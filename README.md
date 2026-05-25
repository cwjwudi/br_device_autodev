# B&R PLC 自动构建、下载、反馈验证工具链

本项目是一个贝加莱 B&R Automation Studio 工程，同时在工程外侧建设一套自动化工具链，使人、Codex、CI 或 MCP Server 能够以可审计、可验证的方式完成 PLC 构建、下载和反馈验证。

当前工程入口：

- `PrintDemo/Huitong_FrontEval.apj`
- 配置：`Config1`
- 当前已验证 ARsim 目标：`127.0.0.1`
- 当前配置测试 PLC 只读目标：`192.168.50.222`
- 历史已验证测试 PLC 只读目标：`192.168.50.233`

## 项目目标

目标链路：

```text
需求描述
-> 修改或生成 AS 工程代码
-> 使用 BR.AS.Build.exe 构建
-> 生成 RUC Package / Transfer.pil
-> 使用 PVITransfer.exe 下载到 ARsim 或白名单测试 PLC
-> 使用 OPC UA 或 PVI 读取变量反馈
-> 自动判定结果并输出报告
```

优先级：

1. 构建使用 Automation Studio 官方 `BR.AS.Build.exe`。
2. 下载优先使用 RUC Package + `PVITransfer.exe`。
3. 反馈验证优先使用 OPC UA，其次使用 PVI。
4. 默认只在 ARsim 或白名单测试 PLC 上验证。

## 安全边界

- 禁止直接对生产 PLC 自动下载，除非用户明确确认并提供目标。
- 下载前必须执行只读探针和下载安全检查。
- 当前 ARsim RUC 包不能下载到真实测试 PLC；工具链会拒绝这种 CPU/Runtime 不匹配。
- OPC UA 默认白名单变量，不自动开放全部 PLC 变量。
- PVI 读取默认白名单变量。
- 不自动修改 Safety 工程、安全任务或安全 I/O。

## 目录结构

```text
docs/
  PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md
  PLC_TOOLCHAIN_IMPLEMENTATION_PLAN.md
  PLC_MCP_SKILL_PROMPT_ROADMAP.md

tools/
  plc_toolchain.ps1
  invoke_pvitransfer_silent.ps1
  opcua_read.py
  pvi_read.py
  plc_targets.local.json
  mcp_server/
    server.py
    toolchain.py
    schemas.py
    README_FOR_LOCAL.md

PrintDemo/
  Huitong_FrontEval.apj
```

## 当前进度

已完成：

- 定位 Automation Studio 构建工具：
  - `D:\BRAutomation\AS65\AS6\bin-en\BR.AS.Build.exe`
- 定位 PVITransfer：
  - `D:\BRAutomation\AS65\PVI6\PVI\Tools\PVITransfer\PVITransfer.exe`
- 实现本地 CLI：
  - `tools/plc_toolchain.ps1`
- 实现 PVITransfer 静默包装：
  - `tools/invoke_pvitransfer_silent.ps1`
- 实现 ARsim 启动、探针、安全检查、下载闭环。
- 实现 OPC UA 白名单读取验证：
  - `tools/opcua_read.py`
- 实现 PVI 协议读取验证：
  - `tools/pvi_read.py`
- 完成 M1：
  - CLI 核心命令统一为 MCP 友好的 JSON 输出和退出码。
- 完成 M2：全部 8 个 MCP 工具已实现并通过 ARsim 闭环测试：
  - `plc_build_project`
  - `plc_start_arsim`
  - `plc_probe_target`
  - `plc_describe_ruc_package`
  - `plc_check_download`
  - `plc_download_ruc`
  - `plc_verify_opcua`
  - `plc_read_pvi`
- 完成 M3：创建 `br-plc-toolchain` Skill，固化 Agent 操作规范和安全边界：
  - `skills/br-plc-toolchain/SKILL.md`
  - `skills/br-plc-toolchain/references/safety.md`
  - `skills/br-plc-toolchain/references/command-flow.md`
  - `skills/br-plc-toolchain/references/verification.md`
- 完成 M4：创建标准 Prompt 模板：
  - `prompts/plc_toolchain/build_and_verify_arsim.md`
  - `prompts/plc_toolchain/safe_download_check.md`
  - `prompts/plc_toolchain/add_plc_feature_with_feedback.md`
  - `prompts/plc_toolchain/diagnose_download_failure.md`
- 完成 M5：统一验证报告，输出到 `tools/.generated/reports/*.json`。
- 完成第二批 MCP 工具：
  - `plc_run_arsim_closed_loop`
  - `plc_run_verification_suite`
  - `plc_get_target_config`
  - `plc_list_targets`

已验证结果：

- 构建：`Build: 0 error(s), 2 warning(s)`
- ARsim 探针：
  - CPU：`X20CP3687X`
  - AR：`6.5.1`
  - 状态：`WarmStart`
- 历史测试 PLC 只读探针：
  - CPU：`X20CP1586`
  - AR：`J4.93`
  - 状态：`WarmStart`
- 当前测试 PLC 只读探针（2026-05-25）：
  - IP：`192.168.50.222`
  - CPU：`X20CP1685`
  - AR：`6.5.1`
  - 状态：`WarmStart`
- ARsim 下载：
  - `Transfer "RUCPackage.zip" ... SUCCESSFUL`
- OPC UA 读取：
  - `gstHmi.stOutputs.diSImage=600`
  - `gstHmi.stConfig.strPuChartAdr=http://127.0.0.1`
  - `SVG:strTransform` 可读
- PVI 读取：
  - `gstHmi.stOutputs.diSImage=600`
  - `gstMainInface.stToMain.usiActivePU=88`
  - `SVG:strTransform` 可读

## 常用命令

构建并生成 RUC Package：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command Build -BuildRucPackage
```

启动或复用 ARsim：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command StartArsim -Target arsim
```

探针读取目标：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command Probe -Target arsim
```

下载前安全检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command CheckDownload -Target arsim
```

下载到 ARsim：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command Download -Target arsim -Execute
```

OPC UA 验证：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command VerifyOpcUa -Target arsim
```

PVI 验证：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command ReadPvi -Target arsim
```

## MCP Server

当前 MCP Server 是一个轻量 stdio JSON-RPC 封装，真实执行仍然委托给 `tools/plc_toolchain.ps1`。

启动：

```powershell
python tools\mcp_server\server.py
```

**全部 8 个工具：**

| 工具 | CLI 命令 | 用途 | 安全门 |
|---|---|---|---|
| `plc_build_project` | `Build` | 构建 AS 工程，可选生成 RUC 包 | 无 |
| `plc_start_arsim` | `StartArsim` | 启动或复用已有 ARsim 实例 | 仅限 arsim 角色目标 |
| `plc_probe_target` | `Probe` | 只读探针：CPU 类型、AR 版本、PLC 状态 | 只读 |
| `plc_describe_ruc_package` | `DescribePackage` | 读取 RUC 包元信息：CPU/AR/Runtime 类型 | 只读 |
| `plc_check_download` | `CheckDownload` | 包-目标兼容性安全检查 | 只读 |
| `plc_download_ruc` | `Download` | 安全检查通过后执行下载 | **必须 `execute=true`** |
| `plc_verify_opcua` | `VerifyOpcUa` | 读取 OPC UA 白名单节点值 | 只读，默认白名单 |
| `plc_read_pvi` | `ReadPvi` | 读取 PVI 白名单变量值 | 只读，默认白名单 |
| `plc_run_arsim_closed_loop` | `RunArsimClosedLoop` | 一键 ARsim 构建、检查、下载和验证 | 下载仍必须 `execute=true` |
| `plc_run_verification_suite` | `RunVerificationSuite` | OPC UA 优先、PVI 备用的统一验证 | 只读 |
| `plc_get_target_config` | `GetTargetConfig` | 读取指定目标配置和验证白名单 | 只读 |
| `plc_list_targets` | `ListTargets` | 列出可用目标和安全角色 | 只读 |

VSCode / Codex / Cursor 等 MCP 客户端配置示例：

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

所有工具返回统一结构：

```json
{
  "ok": true,
  "tool": "plc_probe_target",
  "target": "arsim",
  "summary": "X20CP3687X / 6.5.1 / WarmStart",
  "data": {},
  "logs": [],
  "warnings": [],
  "next_actions": []
}
```

### 标准 ARsim 闭环流程

```text
plc_build_project(build_ruc_package=true)
  -> plc_start_arsim
  -> plc_probe_target
  -> plc_describe_ruc_package
  -> plc_check_download
  -> plc_download_ruc(execute=true)
  -> plc_verify_opcua  (fallback: plc_read_pvi)
```

第二批工具可执行同等流程：

```text
plc_run_arsim_closed_loop(target="arsim", execute=true)
  -> writes tools/.generated/reports/*_closed_loop_arsim.json

plc_run_verification_suite(target="arsim")
  -> writes tools/.generated/reports/*_verification_arsim.json
```

### 测试验证结果（2026-05-22）

| 工具 | 测试状态 | 实际输出 |
|---|---|---|
| `plc_build_project` | ✅ | 0 error(s), 2 warning(s) |
| `plc_start_arsim` | ✅ | reused existing ARsim (pid=42572) |
| `plc_probe_target` | ✅ | X20CP3687X / 6.5.1 / WarmStart |
| `plc_describe_ruc_package` | ✅ | AR000 / 6.5.1 / AR Simulation / 1.0.0 |
| `plc_check_download` | ✅ | download allowed: package AR000 -> target X20CP3687X |
| `plc_download_ruc` (no execute) | ✅ | Safety gate: "execute not set — dry run" |
| `plc_verify_opcua` | ✅ | read 6/6 OPC UA nodes |
| `plc_read_pvi` | ✅ | read 4/4 PVI variables |

### 关键安全机制

- **下载双重门**：MCP 层要求 `execute=true`，CLI 层再次检查；缺少任一则拒绝。
- **生产拒绝**：角色为 `production` 的目标直接拒绝下载。
- **包-目标匹配**：ARsim 包不能下载到物理 PLC，反之亦然。
- **只读反馈**：OPC UA 和 PVI 工具均为只读，无写入能力。
- **白名单控制**：OPC UA 和 PVI 使用 `plc_targets.local.json` 中配置的白名单变量。

## 配置

目标和工具路径配置在：

```text
tools/plc_targets.local.json
```

当前包含：

- `automation_studio.build_exe`
- `automation_studio.pvi_transfer_exe`
- `targets.arsim`
- `targets.test_plc`
- `targets.test_plc_233`
- `opcua.validation_node_ids`
- `pvi.validation_variables`

## Skill

项目包含 `br-plc-toolchain` Skill（`skills/br-plc-toolchain/`），为 Codex 等 Agent 提供操作规范和安全边界：

- `SKILL.md` — 触发条件、工具速查、操作顺序、安全禁止项、失败处理
- `references/safety.md` — 目标分类权限、下载检查清单、生产/Safety/OPC UA/PVI 规则
- `references/command-flow.md` — 5 种标准流程：闭环验证、安全检查、功能修改、失败诊断、只读验证
- `references/verification.md` — OPC UA/PVI 白名单节点、读取策略、报告格式

## 下一步

计划继续推进 M6：输入输出测试闭环。

目标是把当前“构建、下载、变量可读”升级为“写入测试输入、读取输出、自动判定 pass/fail”。

建议实施顺序：

1. 新增 PVI 白名单写入能力：
   - `tools/pvi_write.py`
   - CLI：`WritePvi`
   - MCP：`plc_write_pvi`
   - 必须 `execute=true`
2. 扩展 `tools/plc_targets.local.json`：
   - `pvi.read_whitelist`
   - `pvi.write_whitelist`
   - `pvi.restore_writes`
3. 新增输入输出测试 runner：
   - `tools/plc_io_test_runner.py`
   - CLI：`RunIoTestCase`、`RunTestSuite`、`ResetTestHarness`
   - MCP：`plc_run_io_test_case`、`plc_run_test_suite`、`plc_reset_test_harness`
4. 新增测试套件：
   - `tests/plc/lqr_io_tests.json`
5. 首批 LQR 测试场景：
   - 零输入零输出
   - 常规跟踪误差：`u = -K * (x - x_ref)`
   - 输出限幅
   - 未使能输出清零
   - reset 清零
6. 输出统一 IO 测试报告：
   - `tools/.generated/reports/*_io_test_<suite>.json`

M6 安全边界：

- 只允许写 `pvi.write_whitelist` 中的测试 harness 变量。
- 禁止写 Safety、物理 I/O、系统变量和生产 PLC。
- 输出变量默认只读，不写。
- 每次写入必须记录 write、readback、restore 和报告路径。

详细计划见：

- `docs/PLC_TOOLCHAIN_IMPLEMENTATION_PLAN.md`
- `docs/PLC_MCP_SKILL_PROMPT_ROADMAP.md`
