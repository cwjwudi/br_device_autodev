# PVI 运行时实机测试报告

## 范围

- 测试目标：`192.168.50.233`
- 声明角色：`dedicated_test_plc`
- 运行时 profile：`office-test`
- 测试方式：通过正式 stdio MCP 客户端调用运行时工具
- 前置条件：未提供 Automation Studio 源工程或变量白名单

## 结果

- MCP Server 第一轮写入验证时暴露 36 个工具；加入显式本机配置保存能力后，最终冒烟测试为 37 个工具。
- PVI 连接成功，CPU 状态为 `RUN/WarmStart`，Automation Runtime 为 `J4.93`。
- 自动发现 11 个任务。
- `DataSQLBat` 任务自动发现 14 个变量。
- 成功读取 `DataSQLBat:bSimEnable=false`。
- 同值写入 `false` 后回读验证成功。
- 创建 5 分钟、绑定当前目标的临时测试会话。
- 会话内将变量由 `false` 改为 `true`，写后回读成功。
- 将变量恢复为 `false`，再次独立读取确认恢复成功。
- 主动关闭测试会话。
- 升级完成后的最终非破坏性 MCP 冒烟测试再次确认：11 个任务、`DataSQLBat` 14 个变量，`bSimEnable=false` 且类型为 `boolean`。

## 安全与清理确认

- 改值请求只有在 `execute=true` 且提供有效目标绑定会话时执行。
- 每次写入均执行 PVI 回读验证并进入 MCP 审计链。
- 测试结束时 PLC 变量已恢复原值 `false`。
- 自动发现清单属于 `var/discovery/` 运行数据，不提交到 Git，也不会自动变成长期授权。

## 已知环境信息

- PVI 返回的 license 状态为 undefined，不影响本次连接、发现和读写测试。
- PLC 系统时间较旧，应由设备维护流程单独校准；运行时工具不自动修改 PLC 时间。
