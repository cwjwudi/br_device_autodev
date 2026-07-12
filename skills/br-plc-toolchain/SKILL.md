---
name: br-plc-toolchain
description: B&R Automation Studio PLC 构建、下载、反馈验证的自动化工具链。在修改 ST/C/C++ 代码后需要构建和验证时使用此 Skill。
---

# B&R PLC Toolchain Skill

## 何时使用

当任务涉及以下任一操作时，必须使用此 Skill：

- 修改 `PrintDemo/` 下的 ST、C、C++ 或 mappView 代码
- 构建 B&R Automation Studio 工程
- 下载 RUC 包到 ARsim 或测试 PLC
- 通过 OPC UA 或 PVI 读取 PLC 反馈变量
- 验证代码修改是否在 PLC 上生效
- AI 生成的代码引用了当前工程尚未包含的 Automation Studio Library

## 前置必读

执行任何操作前，先阅读以下文档获取上下文：

1. `docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md` — 工具链整体上下文
2. `docs/PLC_TOOLCHAIN_IMPLEMENTATION_PLAN.md` — 已验证事实和约束
3. `config/targets/default-safe.json` — 当前可用的目标、白名单和路径

## MCP 工具集

全部操作通过 MCP Server 完成，不直接调用 PowerShell 脚本。完整工具、风险等级、后端和确认参数见：

- `skills/br-plc-toolchain/references/mcp-tools.md`

该目录由 `tools/generate_mcp_docs.py` 从 MCP schema 自动生成，不手工维护工具表。

## 标准操作顺序

### 缺失 Library 处理流程

```
1. plc_build_project                         → 获取 Automation Studio 缺失符号错误
2. plc_find_library_for_symbol(symbol=...)  → 从本机可信 AS 库中查找唯一候选
3. plc_plan_project_library(library=...)    → 审查版本、递归依赖和 Technology Package
4. plc_add_project_library(execute=true)    → 事务式复制、更新 Package.pkg、重新构建
```

不得从互联网任意下载 Library。候选不唯一、版本不兼容、依赖缺失或涉及 Safety 时必须停止并报告。

### ARsim config 和仿真文件规则

- Automation Studio 的 config 名必须按项目实际读取和传入，例如 `x1685`、`x3687x`；不要写死 `Config1`。
- 开启某个 config 的仿真模式时，检查 `PrintDemo/Physical/<config>/Hardware.hw` 中 CPU 模块下的 `Simulation` 参数，按需设置为 `Value="1"`。
- 修改仿真设置后必须重新构建该 config。构建成功后，Automation Studio 会在 `PrintDemo/Temp/Simulation/<config>/<CPU>/` 下生成仿真文件。
- 启动 ARsim 时使用实际生成的 loader：`PrintDemo/Temp/Simulation/<config>/<CPU>/ar000loader.exe`。示例：`PrintDemo/Temp/Simulation/x3687x/X20CP3687X/ar000loader.exe`。
- `config/targets/default-safe.json` 中 `targets.arsim.arsim_loader_exe` 必须指向实际生成的 `ar000loader.exe`，config 名和 CPU 目录都要与当前构建目标一致。

### 当前配置确认

- 在动态变量读写或下载前，先读取当前 `config/targets/default-safe.json` 或传入的 `targets_path`，确认 `access_policy.mode`、`allow_dynamic_*`、目标 `role` 和 `arsim_loader_exe`。
- 不要假设 default 配置一定是 `whitelist` 或 `agent_directed`；最终行为以本次实际加载的配置为准。
- 如果为了测试临时派生配置，最终报告必须说明使用的是临时配置还是 default 配置；用户要求 default 时，应不传 `targets_path` 再跑一次关键验证。

### 闭环验证流程

```
1. plc_doctor / plc_validate_environment                    → 检查本机依赖和所选环境
2. 确认实际 config、Simulation=1 和 arsim_loader_exe 路径
3. plc_build_project(config=<config>, build_ruc_package=true) → 构建 + 生成 RUC 包/仿真文件
4. plc_start_arsim(target=arsim, config=<config>, execute=true) → 确保 ARsim 在运行
5. plc_probe_target(config=<config>)                         → 确认目标状态
6. plc_describe_ruc_package(config=<config>)                 → 读取包信息
7. plc_check_download(config=<config>)                       → 安全检查
8. plc_download_ruc(target=arsim, config=<config>, execute=true) → 下载到 ARsim
9. plc_verify_opcua(config=<config>) / plc_read_pvi(config=<config>) → 反馈验证
```

历史结果先用 `plc_list_reports` 定位，再用 `plc_read_report_summary` 读取紧凑摘要；不要通过报告工具读取大型日志正文。

如果用户明确授权“ARsim 强制下载”，只可对 `target=arsim` 添加 `force_arsim_download=true`。该模式仍必须先执行 `probe`、`describe_package` 和 `check_download`，仍要求 `execute=true`，且不得用于物理 PLC 或生产目标。

### 只读安全检查流程

```
1. plc_probe_target         → 目标状态
2. plc_describe_ruc_package → 包信息
3. plc_check_download       → 兼容性判定
```

### M6 输入输出测试流程（待实现）

```
1. plc_build_project(build_ruc_package=true)       → 构建 + 生成包
2. plc_probe_target + plc_check_download           → 下载前安全检查
3. plc_download_ruc(target=<明确目标>, execute=true) → 下载到 ARsim 或测试 PLC
4. plc_search_variables / plc_list_variables       → Agent 查询变量目录并选择输入/输出变量
5. plc_reset_test_harness(target=<明确目标>, execute=true) → 测试前复位
6. plc_run_test_suite(target=<明确目标>, execute=true)     → 写输入、读输出、断言
7. plc_reset_test_harness(target=<明确目标>, execute=true) → 测试后恢复
```

### 变量访问模式

`config/targets/default-safe.json` 中的 `access_policy.mode` 控制 Agent 是否可以使用白名单外变量：

所有 PVI/OPC UA 访问结论以 `tools/plc_access_policy.py` 为准；PowerShell、Python 和 MCP 路径共享该策略引擎，不应在调用层自行放宽或重写策略。

- `whitelist`：默认模式，只允许读取/写入配置文件中列出的 OPC UA/PVI 白名单。
- `catalog_policy`：允许 Agent 从变量目录中选择变量，但变量必须在 catalog 中声明对应 `read`/`write` 能力。
- `agent_directed`：允许 Agent 自行搜索变量并传入读写请求；底层仍会拒绝 production 目标、Safety/物理 I/O/system 名称，写入仍必须 `execute=true`。

在 `catalog_policy` 或 `agent_directed` 模式下，Agent 不应凭空猜测变量名。标准顺序是先调用 `plc_search_variables` 或 `plc_list_variables`，再把选出的变量名传给 `plc_read_pvi`、`plc_verify_opcua`、`plc_write_pvi` 或 IO 测试工具。

使用 catalog 前必须检查 `catalog_source`、`confidence`、`generated_from` 和 `warnings`。优先使用新鲜 Automation Studio 构建产物产生的高可信目录；`source_scan/low` 只作为候选发现依据，实际访问仍需策略校验和读回确认。

动态 PVI 写入的默认验证方式是：

```
1. plc_search_variables / plc_list_variables  → 找到候选变量
2. plc_read_pvi                               → 读取当前值和数据类型
3. plc_write_pvi(execute=true)                → 优先写回当前值，证明写通路
4. plc_read_pvi                               → 独立读回确认
```

除非用户明确要求改变状态，否则优先写同值或测试 harness 中有 restore/reset 保护的低风险值。

## 安全禁止项（必须遵守）

1. **禁止对生产 PLC 自动下载**。`role=production` 的目标直接拒绝。
2. **禁止跳过安全检查**。下载前必须 `probe` + `describe_package` + `check_download`。
3. **禁止修改 Safety 工程**。不修改安全任务、安全 I/O。
4. **禁止默认开放动态写入**。生产环境使用白名单；缺少外部策略时只允许运行时发现和读取。测试 PLC 或 ARsim 必须经过明确角色识别及测试会话才能改变变量值。
5. **禁止无 execute 下载**。`plc_download_ruc` 不带 `execute=true` 只做安全检查，不下载。
6. **禁止跨类型下载**。ARsim 包不可下载到物理 PLC，反之亦然。
7. **禁止无策略写 PLC 变量**。默认只能写 `pvi.write_whitelist`；`agent_directed` 模式下也必须先搜索变量，并通过 production、Safety/I/O/system、`execute=true` 等安全门。
8. **禁止写 Safety、物理 I/O、系统变量**。输出变量默认只读，不写。
9. **禁止把 ARsim 强制下载授权扩展到物理 PLC**。`force_arsim_download=true` 只允许用户明确授权后的 `role=arsim` 目标。
10. **禁止目标变更工具使用隐式目标**。启动、下载、写变量和测试套件必须显式传入 `target` 或 `environment`；只读和本地工具未选择目标时仅回退到本机 `arsim`。
11. **禁止绕过锁和审计执行关键动作**。构建、工程修改、启动、下载、写变量和测试套件应通过 MCP 调用；锁冲突必须等待或停止，审计路径应保留在结果中。
12. **禁止忽略测试恢复失败**。IO 测试报告中的 `failure_stage=restore` 优先级最高；前置 reset 失败不得继续写入，后置 restore 失败必须把整体结果视为失败并提示人工检查。

详细安全规则见：`references/safety.md`

## 失败处理

| 失败场景 | 处理方式 |
|---|---|
| 构建失败（error > 0） | 报告 `error_lines`，修复后重新构建，不继续后续步骤 |
| 安全检查未通过 | 报告 `reasons`，停止流程，不尝试下载 |
| ARsim CPU/型号不匹配 | 默认停止；只有用户明确授权 ARsim 强制下载时，才可用 `force_arsim_download=true` 重新检查和下载 |
| ARsim 首次安装被拒绝 | 报告 PVITransfer 日志；强制 ARsim 模式会生成临时 `Transfer_force_arsim_*.pil` 使用初装限制 |
| 下载失败 | 报告 `log_path` 中的下载日志，检查目标连通性 |
| OPC UA 验证失败 | 尝试 `plc_read_pvi` 作为备用验证 |
| PVI 验证失败 | 检查 PVI Manager、目标连通性、变量名拼写；`Object not found` 通常还要检查当前运行映像是否包含对应任务/变量 |
| ARsim 未启动 | 调用 `plc_start_arsim` 启动，等 3 秒后重试 |

详细流程见：`references/command-flow.md`
详细验证策略见：`references/verification.md`
