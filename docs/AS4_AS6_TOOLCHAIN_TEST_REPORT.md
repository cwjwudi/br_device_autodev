# AS4 / AS6 全局工具链测试报告

## 自动测试

- 全量测试：`119 passed, 224 subtests passed`（加入最终 DLL 检查后再次回归）。
- 覆盖 AS4/AS6 registry 解析、默认选择、未知 ID、可用性、environment 继承和 MCP schema。
- 覆盖 AS4 工程选择 AS6 toolchain 时拒绝执行。
- 覆盖 Library Manager 只搜索所选 toolchain 的 Library roots。
- 覆盖同一 MCP 进程混用 PVI4/PVI6 DLL 时拒绝，并允许关闭 manager 后切换。

## 本机安装检查

- 找到 AS6 编译器：`C:\Program Files (x86)\BRAutomation\AS6\bin-en\BR.AS.Build.exe`。
- 找到 PVI6 Transfer：`C:\Program Files (x86)\BRAutomation\PVI6\PVI\Tools\PVITransfer\PVITransfer.exe`。
- 找到 PVI6 DLL：`C:\Program Files (x86)\BRAutomation\PVI6\Bin\Pvi6Com64.dll`。
- 未找到 AS4/PVI4，因此 `as4_default` 保持 `enabled=false`、`available=false`，没有伪造 AS4 实机构建结果。

## AS6 真实构建

- Environment：`default_safe`
- Toolchain：`as6_default`
- 工程声明：Automation Studio `6.5.0.306`
- Config：`x1685`
- 结果：`Build: 0 error(s), 4 warning(s)`
- 构建报告明确记录 `toolchain=as6_default`、`toolchain_family=AS6`、`toolchain_version=6.x`。

4 个 warning 为两个未纳入工程的附加文件、一条 C `statement with no effect` 和一个未使用变量；本次工具链选择改造没有引入编译错误。

## PVI6 只读实机回归

- PLC：`192.168.50.233`
- Toolchain：`as6_default`
- MCP 工具数：39
- 自动发现：成功，11 个任务
- 读取：`DataSQLBat:bSimEnable=false`，类型 `boolean`
- 未执行 PLC 写入、下载或状态修改。

首次测试曾把 `dll_dir` 指向 PVI 根目录并被 pvipy 拒绝。根据实际 DLL 位置修正为 `PVI6\Bin` 后复测通过；registry 可用性和 Doctor 现同时检查具体通信 DLL，防止该配置错误再次发生。
