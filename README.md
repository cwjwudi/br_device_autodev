# B&R PLC 自动构建、下载、反馈验证工具链

本项目是一个贝加莱 B&R Automation Studio 工程，同时在工程外侧建设一套自动化工具链，使人、Codex、CI 或 MCP Server 能够以可审计、可验证的方式完成 PLC 构建、下载和反馈验证。

当前工程入口：

- `PrintDemo/Huitong_FrontEval.apj`
- 配置：`Config1`
- 当前已验证 ARsim 目标：`127.0.0.1`
- 当前已验证测试 PLC 只读目标：`192.168.50.233`

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

已验证结果：

- 构建：`Build: 0 error(s), 2 warning(s)`
- ARsim 探针：
  - CPU：`X20CP3687X`
  - AR：`6.5.1`
  - 状态：`WarmStart`
- 测试 PLC 只读探针：
  - CPU：`X20CP1586`
  - AR：`J4.93`
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
- `opcua.validation_node_ids`
- `pvi.validation_variables`

## 下一步

计划继续推进：

1. 创建 `br-plc-toolchain` Skill，固化 Agent 操作规范和安全边界。
2. 创建 Prompt 模板，用于构建验证、下载前检查、功能修改和失败诊断。
3. 生成统一验证报告：
   - 构建摘要
   - RUC 包信息
   - 目标探针信息
   - 下载日志
   - OPC UA / PVI 读数
4. 实现 M3 第二批 MCP 工具：
   - `plc_run_arsim_closed_loop` — 一键 ARsim 闭环
   - `plc_run_verification_suite` — 统合 OPC UA + PVI 验证
   - `plc_get_target_config` / `plc_list_targets` — 目标配置查询

详细计划见：

- `docs/PLC_TOOLCHAIN_IMPLEMENTATION_PLAN.md`
- `docs/PLC_MCP_SKILL_PROMPT_ROADMAP.md`
