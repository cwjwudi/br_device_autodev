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

## 前置必读

执行任何操作前，先阅读以下文档获取上下文：

1. `docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md` — 工具链整体上下文
2. `docs/PLC_TOOLCHAIN_IMPLEMENTATION_PLAN.md` — 已验证事实和约束
3. `tools/plc_targets.local.json` — 当前可用的目标、白名单和路径

## MCP 工具集

全部操作通过 MCP Server 完成，不直接调用 PowerShell 脚本。可用工具：

| 工具 | 用途 | 关键约束 |
|---|---|---|
| `plc_build_project` | 构建工程，可选生成 RUC 包 | `build_ruc_package=true` 用于构建后下载 |
| `plc_start_arsim` | 启动或复用 ARsim | 仅限 `target=arsim` |
| `plc_probe_target` | 只读探针：CPU/AR/状态 | 下载前必须先调用 |
| `plc_describe_ruc_package` | 读取 RUC 包元信息 | 下载前必须先调用 |
| `plc_check_download` | 包-目标兼容性安全检查 | 通过后才能下载；ARsim 强制模式需用户授权并传 `force_arsim_download=true` |
| `plc_download_ruc` | 执行下载 | `execute=true` 才实际下载；ARsim 强制模式只允许 `role=arsim` |
| `plc_verify_opcua` | 读取 OPC UA 白名单节点 | 首选反馈验证 |
| `plc_read_pvi` | 读取 PVI 白名单变量 | OPC UA 不可用时的备用方案 |
| `plc_list_variables` | 列出 PLC 变量目录 | Agent 动态读写前先调用 |
| `plc_search_variables` | 按模块/名称/读写权限搜索变量 | Agent 动态读写前先调用 |
| `plc_write_pvi` | 写入 PVI 测试变量或策略允许的动态变量 | 必须 `execute=true`，禁止生产目标 |
| `plc_run_arsim_closed_loop` | ARsim 闭环：构建、检查、下载、验证、报告 | 下载仍需 `execute=true` |
| `plc_run_verification_suite` | OPC UA 优先、PVI 备用的统一验证 | 只读，写报告 |
| `plc_run_io_test_case` | 单个输入输出测试 | 写入和读回均受 `access_policy` 约束 |
| `plc_run_test_suite` | 批量运行测试套件 | 输出 pass/fail 报告 |
| `plc_reset_test_harness` | 恢复测试变量安全状态 | 必须 `execute=true` |
| `plc_get_target_config` | 读取指定目标配置 | 只读 |
| `plc_list_targets` | 列出目标和安全角色 | 只读 |

## 标准操作顺序

### ARsim config 和仿真文件规则

- Automation Studio 的 config 名必须按项目实际读取和传入，例如 `x1685`、`x3687x`；不要写死 `Config1`。
- 开启某个 config 的仿真模式时，检查 `PrintDemo/Physical/<config>/Hardware.hw` 中 CPU 模块下的 `Simulation` 参数，按需设置为 `Value="1"`。
- 修改仿真设置后必须重新构建该 config。构建成功后，Automation Studio 会在 `PrintDemo/Temp/Simulation/<config>/<CPU>/` 下生成仿真文件。
- 启动 ARsim 时使用实际生成的 loader：`PrintDemo/Temp/Simulation/<config>/<CPU>/ar000loader.exe`。示例：`PrintDemo/Temp/Simulation/x3687x/X20CP3687X/ar000loader.exe`。
- `tools/plc_targets.local.json` 中 `targets.arsim.arsim_loader_exe` 必须指向实际生成的 `ar000loader.exe`，config 名和 CPU 目录都要与当前构建目标一致。

### 当前配置确认

- 在动态变量读写或下载前，先读取当前 `tools/plc_targets.local.json` 或传入的 `targets_path`，确认 `access_policy.mode`、`allow_dynamic_*`、目标 `role` 和 `arsim_loader_exe`。
- 不要假设 default 配置一定是 `whitelist` 或 `agent_directed`；最终行为以本次实际加载的配置为准。
- 如果为了测试临时派生配置，最终报告必须说明使用的是临时配置还是 default 配置；用户要求 default 时，应不传 `targets_path` 再跑一次关键验证。

### 闭环验证流程

```
1. 确认实际 config、Simulation=1 和 arsim_loader_exe 路径
2. plc_build_project(config=<config>, build_ruc_package=true) → 构建 + 生成 RUC 包/仿真文件
3. plc_start_arsim(config=<config>)                          → 确保 ARsim 在运行
4. plc_probe_target(config=<config>)                         → 确认目标状态
5. plc_describe_ruc_package(config=<config>)                 → 读取包信息
6. plc_check_download(config=<config>)                       → 安全检查
7. plc_download_ruc(config=<config>, execute=true)           → 下载到 ARsim
8. plc_verify_opcua(config=<config>)                         → OPC UA 验证（首选）
9. plc_read_pvi(config=<config>)                             → PVI 验证（备用）
```

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
3. plc_download_ruc(execute=true)                  → 下载到 ARsim 或测试 PLC
4. plc_search_variables / plc_list_variables       → Agent 查询变量目录并选择输入/输出变量
5. plc_reset_test_harness(execute=true)            → 测试前复位
6. plc_run_test_suite(execute=true)                → 写输入、读输出、断言
7. plc_reset_test_harness(execute=true)            → 测试后恢复
```

### 变量访问模式

`tools/plc_targets.local.json` 中的 `access_policy.mode` 控制 Agent 是否可以使用白名单外变量：

- `whitelist`：默认模式，只允许读取/写入配置文件中列出的 OPC UA/PVI 白名单。
- `catalog_policy`：允许 Agent 从变量目录中选择变量，但变量必须在 catalog 中声明对应 `read`/`write` 能力。
- `agent_directed`：允许 Agent 自行搜索变量并传入读写请求；底层仍会拒绝 production 目标、Safety/物理 I/O/system 名称，写入仍必须 `execute=true`。

在 `catalog_policy` 或 `agent_directed` 模式下，Agent 不应凭空猜测变量名。标准顺序是先调用 `plc_search_variables` 或 `plc_list_variables`，再把选出的变量名传给 `plc_read_pvi`、`plc_verify_opcua`、`plc_write_pvi` 或 IO 测试工具。

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
4. **禁止默认开放全部 OPC UA/PVI**。默认 `whitelist` 模式只使用 `plc_targets.local.json` 中的白名单；只有用户手动切换 `access_policy.mode` 后才允许动态变量。
5. **禁止无 execute 下载**。`plc_download_ruc` 不带 `execute=true` 只做安全检查，不下载。
6. **禁止跨类型下载**。ARsim 包不可下载到物理 PLC，反之亦然。
7. **禁止无策略写 PLC 变量**。默认只能写 `pvi.write_whitelist`；`agent_directed` 模式下也必须先搜索变量，并通过 production、Safety/I/O/system、`execute=true` 等安全门。
8. **禁止写 Safety、物理 I/O、系统变量**。输出变量默认只读，不写。
9. **禁止把 ARsim 强制下载授权扩展到物理 PLC**。`force_arsim_download=true` 只允许用户明确授权后的 `role=arsim` 目标。

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
