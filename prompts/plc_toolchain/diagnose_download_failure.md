# Diagnose Download Failure

请诊断 PLC 下载失败，不执行新的下载。

输入：

- 目标：`{target}`
- 配置：`{config}`，必须使用项目实际 Automation Studio config 名，例如 `x1685` 或 `x3687x`
- 最近失败日志或现象：`{failure_observation}`

流程：

1. 阅读 `docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md` 和 `skills/br-plc-toolchain/references/command-flow.md`。
2. 如果目标是 `arsim`，检查 `PrintDemo/Physical/{config}/Hardware.hw` 中 `Simulation` 是否为 `Value="1"`；重新构建后，loader 应在 `PrintDemo/Temp/Simulation/{config}/<CPU>/ar000loader.exe`，例如 `PrintDemo/Temp/Simulation/x3687x/X20CP3687X/ar000loader.exe`。
3. 执行 `plc_probe_target(config="{config}", target="{target}")`，确认目标可达性和状态。
4. 执行 `plc_describe_ruc_package(config="{config}", target="{target}")`，确认包信息。
5. 执行 `plc_check_download(config="{config}", target="{target}")`，判断包-目标兼容性。
6. 读取相关日志路径：
   - `tools/.generated/probe_{target}.log`
   - 下载结果返回的 `log_path`
   - 构建日志 `tools/.generated/build_{config}.log`

输出：

- 最可能原因。
- 支持该判断的证据。
- 下一步修复建议。

禁止：

- 不执行下载。
- 不修改 PLC 程序。
- 不修改目标配置，除非用户明确要求。
