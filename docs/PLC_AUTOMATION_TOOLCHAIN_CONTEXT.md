# PLC Automation Toolchain Context

目标：建立一个自动化下载与调试工具链，使 Agent 能够根据功能需求生成或修改贝加莱 PLC 程序，自动构建、下载到 ARsim/测试 PLC，并通过 PVI 或 OPC UA 读取反馈验证结果。

推荐链路：

需求描述
-> 生成/修改 AS 工程中的 ST/C/C++ 代码
-> 使用 BR.AS.Build.exe 命令行编译
-> 生成 RUC Package / Transfer.pil
-> 使用 PVITransfer.exe 下载
-> 使用 OPC UA 或 PVI 读取变量反馈
-> 自动判定测试结果
-> 输出报告 / 回滚 / 人工确认上线

必要工具：
- B&R Automation Studio，版本需匹配工程。
- BR.AS.Build.exe，用于命令行构建。
- PVI / Runtime Utility Center / PVITransfer.exe，用于下载 RUC 包。
- OPC UA 或 PVI API，用于读取/写入 PLC 变量。
- ARsim 或测试 PLC，用于安全验证。

推荐安全边界：
- 默认只允许下载到 ARsim 或白名单测试 PLC。
- 生产 PLC 下载必须人工确认。
- 下载前备份当前工程、RUC 包和关键变量。
- 禁止自动修改 Safety 工程、安全任务、安全 I/O。
- 生成代码必须经过 diff 审查。
- 失败后允许回滚到上一个 RUC 包。

MVP：
1. 准备一个标准 AS 工程模板。
2. 生成 ST 功能块和测试 harness。
3. 用 BR.AS.Build.exe 编译。
4. 用 PVITransfer.exe 下载到 ARsim。
5. Python 通过 OPC UA/PVI 写入测试输入。
6. 读取 Pass/ErrorCode/OutputValue。
7. 输出测试报告。