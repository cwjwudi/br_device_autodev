# PVI 运行时架构

## 目标

运行时 PVI 服务允许 AI 在没有 Automation Studio 源工程、符号清单或白名单文件时，先连接 PLC、发现任务与变量并读取数据。写入能力不由“能连接”自动推导，而由目标角色、不可变安全规则、在线变量属性和临时测试会话共同决定。

## 调用链

```text
MCP runtime tools
  -> RuntimePviService
     -> RuntimePolicy / TestSessionManager
     -> PviSessionManager
        -> one PviWorker thread per target
           -> Pvi.py / PVI Manager
```

- MCP Server 生命周期内复用同一连接，不为每次读取重新启动 PVI Manager。
- 每个目标只有一个工作线程负责 PVI 对象和事件泵，避免跨线程访问 COM/PVI 对象。
- 多个 PLC 由 `PviSessionManager` 隔离管理。
- 自动发现结果写入 Git 忽略的 `var/discovery/`，它是运行证据，不是授权文件。
- 临时会话只保存在内存中，服务重启、超时或主动关闭后失效。

## 无策略文件时的行为

缺少安全策略文件不是错误，也不等于完全放行。系统自动生成一个临时目标配置：

1. 未声明角色的远程 PLC 使用 `readonly-discovery`：允许健康检查、任务发现、变量发现和读取，拒绝写入。
2. 回环地址自动识别为 `arsim-development`：允许开发测试写入，但仍执行不可变阻断规则。
3. 用户明确声明 `dedicated_test_plc` 后使用 `office-test`：同值写入可直接验证；改变值必须先创建绑定该 PLC 的短期测试会话。
4. 临时配置默认不落盘。只有显式保存时才进入 `config/local/`，避免“自动发现”暗中形成长期权限。

## 写入判定

写入请求依次通过：

1. 目标必须已连接，变量必须在线存在且由 PVI 报告为可写。
2. Safety、安全 I/O、物理 I/O、系统命名空间等不可变规则始终优先，任何 profile 都不能覆盖。
3. 未知目标和生产 profile 禁止动态写入。
4. 办公室测试 PLC 的同值写入要求 `execute=true`，用于低风险通信验证。
5. 改值写入同时要求 `execute=true` 和有效的、绑定目标指纹的临时会话。
6. 写后必须回读；回读不一致时结果为失败。

临时会话不是万能白名单。它只证明用户在有限时间内明确把当前目标作为测试对象，不能解除不可变阻断规则，也不能用于另一个 IP/CPU 会话。

## 兼容层

`plc_read_pvi`、`plc_write_pvi` 与 `tools/pvi_*.py` 暂时保留，服务既有 CLI、测试套件及白名单生产流程。新开发和无源码探索使用 `plc_*_runtime_*` 工具。后续在调用方完成迁移后，旧脚本应缩减成调用新服务的薄适配器，而不是继续扩展第二套连接实现。

