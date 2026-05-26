# Safe Download Check

请只执行 PLC 下载前安全检查，不执行下载。

参数：

- 目标：`{target}`
- 项目：`PrintDemo/Huitong_FrontEval.apj`
- 配置：`{config}`，必须使用项目实际 Automation Studio config 名，例如 `x1685` 或 `x3687x`，不要写死 `Config1`

流程：

1. 阅读 `docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md` 和 `skills/br-plc-toolchain/SKILL.md`。
2. 如果目标是 `arsim`，先确认 `PrintDemo/Physical/{config}/Hardware.hw` 中 `Simulation` 已开启，并确认 `tools/plc_targets.local.json` 的 `targets.arsim.arsim_loader_exe` 指向 `PrintDemo/Temp/Simulation/{config}/<CPU>/ar000loader.exe`。
3. 执行 `plc_probe_target(config="{config}", target="{target}")`。
4. 执行 `plc_describe_ruc_package(config="{config}", target="{target}")`。
5. 执行 `plc_check_download(config="{config}", target="{target}")`。

输出：

- 目标 CPU、AR 版本、PLC 状态。
- 实际 config 名和 ARsim loader 路径（如果目标是 ARsim）。
- RUC 包 CPU、Runtime、AR 版本。
- 是否允许下载。
- 如果拒绝，逐条列出原因。

禁止：

- 不执行 `plc_download_ruc`。
- 不使用 `execute=true`。
