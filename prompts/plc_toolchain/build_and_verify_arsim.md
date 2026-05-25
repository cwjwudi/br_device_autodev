# Build And Verify ARsim

请使用 `br-plc-toolchain` 流程完成一次 ARsim 闭环验证。

要求：

1. 阅读 `docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md` 和 `docs/PLC_MCP_SKILL_PROMPT_ROADMAP.md`。
2. 构建 `PrintDemo/Huitong_FrontEval.apj` 的 `Config1`，并生成 RUC Package。
3. 启动或复用 `arsim`。
4. 执行目标探针，确认 ARsim CPU、AR 版本和 PLC 状态。
5. 描述 RUC 包并执行下载安全检查。
6. 仅当安全检查通过时，使用显式 `execute=true` 下载到 ARsim。
7. 下载后优先执行 OPC UA 验证；如果失败，使用 PVI 作为备用验证。
8. 输出构建、包信息、目标状态、下载、验证摘要和统一报告路径。

禁止：

- 不下载到生产 PLC。
- 不修改 Safety 工程。
- 不开放全部 OPC UA 变量。
