# AS4 / AS6 全局工具链配置

## 职责分离

- `config/toolchains/toolchains.json`：仓库默认的 Automation Studio、Library、PVITransfer 和 PVI DLL 路径。
- `config/local/toolchains.json`：本机覆盖文件，Git 忽略；存在时自动优先于仓库默认文件。
- `config/environments/environments.json`：通过 `toolchain` 字段把工程、AS Config、PLC 目标与某套 AS4/AS6 工具链组合起来。
- `config/targets/*.json`：只保存 PLC、安全角色、白名单和 ARsim loader，不再保存开发机软件路径。

本机配置可从 `config/examples/toolchains/toolchains.local.example.json` 复制。

## Toolchain 结构

每个条目必须明确声明：

- 唯一 ID，例如 `as4_12`、`as6_5`。
- `family`：只能是 `AS4` 或 `AS6`。
- AS 版本、安装根目录、编译器、bin 目录和 Library 根目录。
- PVI family、PVITransfer 和 PVI DLL 目录。
- `enabled`：尚未安装或路径未配置时设为 `false`。

不通过 PLC Runtime 版本、目录名或 PATH 猜测 AS 版本。

## 选择顺序

```text
本次 MCP/CLI 显式 toolchain
→ environment.toolchain
→ registry.default_toolchain
```

Registry 路径选择顺序：

```text
显式 toolchains_path
→ config/local/toolchains.json（存在时）
→ config/toolchains/toolchains.json
```

## MCP 工具

- `plc_list_toolchains`：列出 AS4/AS6 条目和本机可用性。
- `plc_get_toolchain`：查看当前解析结果。
- `plc_validate_environment`：检查工程声明的 AS major version 是否与选中 family 一致。
- `plc_doctor`：检查编译器、PVITransfer、Python PVI 和 ARsim loader。

所有构建、Library、PVITransfer 和旧 PVI CLI 工具都会继承 environment 的 toolchain。

## PVI4 / PVI6 限制

PVI DLL 在 Python 进程中加载后不能安全地通过修改环境变量切换主版本。因此同一个 MCP Server 进程拒绝混用 PVI4 与 PVI6 DLL。切换主版本前必须关闭并重新启动 MCP Server。不同版本并行运行需要后续采用独立 worker process。

## 当前机器验证

- `as6_default`：本机编译器、PVITransfer 和包含 `Pvi6Com64.dll` 的 `PVI6/Bin` 路径存在，已完成 AS6.5 工程真实构建。
- `as4_default`：本机未发现 AS4/PVI4，保持 disabled；配置真实路径后再启用。
