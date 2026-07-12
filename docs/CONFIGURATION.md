# 配置与运行数据约定

## 目录职责

```text
config/
  defaults/       内置安全基线和运行默认值
  profiles/       readonly、office-test、ARsim、production 策略
  targets/        可提交的团队目标配置
  environments/   工程、配置和目标的命名组合
  examples/       可复制的模板，不直接作为本机配置
  local/          本机配置，Git 忽略
scripts/
  windows/        Windows 与厂商程序包装器
  maintenance/    文档生成等仓库维护任务
tools/            兼容 CLI 入口和 MCP Server；不存放配置或运行输出
var/              审计、锁、报告、发现清单和临时文件；Git 忽略
```

## 配置优先级

运行时配置由不可变安全基线、profile 和目标声明合并。安全基线只允许收紧，profile 不能移除对 Safety、物理 I/O 和系统区域的阻断。

推荐做法：

- 团队共享的稳定目标放入 `config/targets/`。
- 个人 PLC、临时 IP 和凭据只放入 `config/local/`。
- 新配置从 `config/examples/` 复制，不修改 examples 本身。
- 自动发现先使用内存临时配置；确实需要复用时再显式保存。
- 不把 `var/discovery/*.json` 当作安全策略，它仅记录发现结果。

## Profile 选择

| 条件 | Profile | 默认能力 |
| --- | --- | --- |
| 未声明的远程 IP | `readonly-discovery` | 发现、读取 |
| 回环地址/本地 ARsim | `arsim-development` | 开发测试读写 |
| 明确声明专用测试 PLC | `office-test` | 发现、读取；会话内改值 |
| 生产目标 | `production-locked` | 严格限制，使用既有审批/白名单流程 |

