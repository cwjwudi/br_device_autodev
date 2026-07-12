# 办公室测试 PLC 快速开始

以下流程不要求 Automation Studio 源工程，也不要求预先创建白名单。

## 只读发现

首次调用 `plc_discover_runtime_target`，传入 IP。未声明角色时系统自动使用只读发现 profile。随后调用：

1. `plc_list_runtime_tasks`
2. `plc_list_runtime_variables`（指定任务）
3. `plc_get_runtime_variable_info`
4. `plc_read_runtime_variable`

## 明确声明测试 PLC

当 PLC 确实是可随意测试的独立设备时，在首次发现调用中传入：

```json
{
  "ip": "192.168.50.233",
  "target": "office233",
  "declared_role": "dedicated_test_plc"
}
```

这会生成内存中的临时 `office-test` 配置，不会自动写入仓库。

## 写入

- 通信验证优先做同值写入：先读当前值，再以 `execute=true` 写回同一值。
- 改变值前调用 `plc_open_test_session`，并显式设置较短 TTL。
- 调用 `plc_write_runtime_variable` 时同时提供 `execute=true` 和 `session_id`。
- 测试完成后恢复原值、独立回读确认，再调用 `plc_close_test_session`。

如果目标角色不明确、变量不可写、命中安全阻断规则、会话超时或会话属于另一个 PLC，写入都会被拒绝。

## 本地 ARsim

回环地址会自动选择 `arsim-development`。仍建议遵循“先发现、先读、记录原值、写后回读、测试后恢复”的流程。ARsim 身份不会解除 Safety 和系统区域阻断。

