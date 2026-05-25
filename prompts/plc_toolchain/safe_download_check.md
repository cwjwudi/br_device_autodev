# Safe Download Check

请只执行 PLC 下载前安全检查，不执行下载。

参数：

- 目标：`{target}`
- 项目：`PrintDemo/Huitong_FrontEval.apj`
- 配置：`Config1`

流程：

1. 阅读 `docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md` 和 `skills/br-plc-toolchain/SKILL.md`。
2. 执行 `plc_probe_target(target="{target}")`。
3. 执行 `plc_describe_ruc_package(target="{target}")`。
4. 执行 `plc_check_download(target="{target}")`。

输出：

- 目标 CPU、AR 版本、PLC 状态。
- RUC 包 CPU、Runtime、AR 版本。
- 是否允许下载。
- 如果拒绝，逐条列出原因。

禁止：

- 不执行 `plc_download_ruc`。
- 不使用 `execute=true`。
