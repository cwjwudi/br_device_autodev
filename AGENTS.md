# AGENTS.md

本工程是贝加莱 B&R Automation Studio 项目。

在处理自动化构建、下载、调试、PVI/OPC UA 反馈验证相关任务前，请先阅读：

- docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md

关键原则：

- 优先使用 Automation Studio 官方工具链。
- 构建使用 BR.AS.Build.exe。
- 下载优先使用 RUC Package + PVITransfer.exe。
- 反馈验证优先使用 OPC UA，其次 PVI。
- 禁止直接对生产 PLC 自动下载，除非用户明确确认。
- 优先在 ARsim 或测试 PLC 上验证。
