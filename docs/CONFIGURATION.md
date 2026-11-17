# 配置与运行数据约定

## 项目级配置

使用全局 toolchain 配置机器的 AS/PVI 路径；工程、config、工具链 ID、目标和访问策略可集中放在 `br-auto-dev.json`。MCP 的 `project_path` 可指向该文件所在目录或 `.apj`。指定 `.apj` 时先查找同目录，再查找其上一级；配置的 `project_path` 必须与指定的 `.apj` 一致。

`project_path`、目标的 `arsim_loader_exe` 和显式设置的 `access_policy.catalog_path` 相对于项目配置文件所在目录解析。显式 MCP 参数优先，其次项目配置，再其次旧 environment 和默认设置。已经找到的项目配置若无效则报错，不回退。未传项目路径时不按 MCP 进程的工作目录猜测工程。

项目配置须包含非空 `project_path`、`config`、`toolchain`、`target`，以及选定目标的 `targets` 条目和 `access_policy.mode`。ARsim 必须使用回环 IP。目标变更仍需显式 target/environment 和 execute；项目配置本身不能授权物理目标变更，需显式传入可信 `targets_path`。完整示例见 README。

旧目录和配置仍作为兼容入口保留：

## 目录职责

```text
config/
  defaults/       内置安全基线和运行默认值
  profiles/       readonly、office-test、ARsim、production 策略
  toolchains/     全局 AS4/AS6、Library 与 PVI 工具路径
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
- 本机 AS/PVI 路径放入 `config/local/toolchains.json`；不要放入 PLC targets 文件。

工具链配置、environment 选择和版本切换见 [TOOLCHAINS.md](TOOLCHAINS.md)。

## Profile 选择

| 条件 | Profile | 默认能力 |
| --- | --- | --- |
| 未声明的远程 IP | `readonly-discovery` | 发现、读取 |
| 回环地址/本地 ARsim | `arsim-development` | 开发测试读写 |
| 明确声明专用测试 PLC | `office-test` | 发现、读取；会话内改值 |
| 生产目标 | `production-locked` | 严格限制，使用既有审批/白名单流程 |
