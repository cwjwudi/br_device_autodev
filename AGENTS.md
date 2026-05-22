# AGENTS.md

本工程是贝加莱 B&R Automation Studio 项目。

在处理自动化构建、下载、调试、PVI/OPC UA 反馈验证相关任务前，请先阅读：

- docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md
- docs/PLC_MCP_SKILL_PROMPT_ROADMAP.md

## 关键原则

- 优先使用 Automation Studio 官方工具链。
- 构建使用 BR.AS.Build.exe。
- 下载优先使用 RUC Package + PVITransfer.exe。
- 反馈验证优先使用 OPC UA，其次 PVI。
- 禁止直接对生产 PLC 自动下载，除非用户明确确认。
- 优先在 ARsim 或测试 PLC 上验证。

## MCP Server

本项目包含一个完整的 MCP Server (`tools/mcp_server/server.py`)，提供 8 个工具：

| 工具 | 说明 |
|---|---|
| `plc_build_project` | 构建 AS 工程，可选生成 RUC 包 |
| `plc_start_arsim` | 启动或复用 ARsim 实例 |
| `plc_probe_target` | 只读探针：CPU/AR/PLC 状态 |
| `plc_describe_ruc_package` | 读取 RUC 包元信息 |
| `plc_check_download` | 下载前安全检查 |
| `plc_download_ruc` | 安全门控下载（需 execute=true） |
| `plc_verify_opcua` | 读取 OPC UA 白名单节点 |
| `plc_read_pvi` | 读取 PVI 白名单变量 |

标准闭环顺序：build -> start_arsim -> probe -> describe_package -> check_download -> download(execute=true) -> verify_opcua / read_pvi

## 安全规则

- `plc_download_ruc` 必须显式传入 `execute=true`，否则只做安全检查不下载。
- 生产角色目标（role=production）自动拒绝下载。
- ARsim RUC 包不能下载到物理 PLC，反之亦然。
- OPC UA 和 PVI 均为只读，无自动写入能力。
- 不自动修改 Safety 工程。
- 不开放全部 OPC UA 变量。

## 配置

目标和工具路径：`tools/plc_targets.local.json`
