# Add PLC Feature With Feedback

请为当前 B&R Automation Studio 工程实现以下 PLC 功能：

`{feature_request}`

要求：

1. 阅读 `docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md`、`docs/PLC_MCP_SKILL_PROMPT_ROADMAP.md` 和 `skills/br-plc-toolchain/SKILL.md`。
2. 阅读 `PrintDemo/` 下相关 ST/C/C++/mappView 现有实现。
3. 只修改功能相关文件，不触碰 Safety 工程。
4. 修改后构建 `PrintDemo/Huitong_FrontEval.apj` 的 `Config1`。
5. 优先在 ARsim 上执行闭环验证。
6. 使用 OPC UA 读取白名单节点验证；失败时使用 PVI 备用读取。
7. 输出 diff 摘要、构建摘要、验证摘要和统一报告路径。

安全边界：

- 不下载生产 PLC。
- 不开放全部 OPC UA 变量。
- 不写 PLC 变量。
- 下载必须先经过探针、包描述、安全检查，并显式传入 `execute=true`。
