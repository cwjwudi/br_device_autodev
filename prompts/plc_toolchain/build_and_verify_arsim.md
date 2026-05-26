# Build And Verify ARsim

请使用 `br-plc-toolchain` 流程完成一次 ARsim 闭环验证。

要求：

1. 阅读 `docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md` 和 `docs/PLC_MCP_SKILL_PROMPT_ROADMAP.md`。
2. 确认实际 Automation Studio config 名，例如 `x1685` 或 `x3687x`；不要写死 `Config1`。
3. 若该 config 要使用 ARsim，检查 `PrintDemo/Physical/<config>/Hardware.hw` 中 CPU 模块下的 `Simulation` 参数，按需设置为 `Value="1"`。
4. 构建 `PrintDemo/Huitong_FrontEval.apj` 的实际 config，并生成 RUC Package；构建后确认仿真文件生成在 `PrintDemo/Temp/Simulation/<config>/<CPU>/`。
5. 确认 `tools/plc_targets.local.json` 的 `targets.arsim.arsim_loader_exe` 指向实际生成的 `PrintDemo/Temp/Simulation/<config>/<CPU>/ar000loader.exe`，例如 `PrintDemo/Temp/Simulation/x3687x/X20CP3687X/ar000loader.exe`。
6. 启动或复用 `arsim`。
7. 执行目标探针，确认 ARsim CPU、AR 版本和 PLC 状态。
8. 描述 RUC 包并执行下载安全检查。
9. 仅当安全检查通过时，使用显式 `execute=true` 下载到 ARsim。
10. 下载后优先执行 OPC UA 验证；如果失败，使用 PVI 作为备用验证。
11. 输出实际 config 名、构建、仿真 loader 路径、包信息、目标状态、下载、验证摘要和统一报告路径。

禁止：

- 不下载到生产 PLC。
- 不修改 Safety 工程。
- 不开放全部 OPC UA 变量。
