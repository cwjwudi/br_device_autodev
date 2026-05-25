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
| `plc_check_download` | 包-目标兼容性安全检查 | 通过后才能下载 |
| `plc_download_ruc` | 执行下载 | `execute=true` 才实际下载 |
| `plc_verify_opcua` | 读取 OPC UA 白名单节点 | 首选反馈验证 |
| `plc_read_pvi` | 读取 PVI 白名单变量 | OPC UA 不可用时的备用方案 |
| `plc_run_arsim_closed_loop` | ARsim 闭环：构建、检查、下载、验证、报告 | 下载仍需 `execute=true` |
| `plc_run_verification_suite` | OPC UA 优先、PVI 备用的统一验证 | 只读，写报告 |
| `plc_get_target_config` | 读取指定目标配置 | 只读 |
| `plc_list_targets` | 列出目标和安全角色 | 只读 |

## 标准操作顺序

### 闭环验证流程

```
1. plc_build_project(build_ruc_package=true) → 构建 + 生成 RUC 包
2. plc_start_arsim                          → 确保 ARsim 在运行
3. plc_probe_target                         → 确认目标状态
4. plc_describe_ruc_package                 → 读取包信息
5. plc_check_download                       → 安全检查
6. plc_download_ruc(execute=true)           → 下载到 ARsim
7. plc_verify_opcua                         → OPC UA 验证（首选）
8. plc_read_pvi                             → PVI 验证（备用）
```

### 只读安全检查流程

```
1. plc_probe_target         → 目标状态
2. plc_describe_ruc_package → 包信息
3. plc_check_download       → 兼容性判定
```

## 安全禁止项（必须遵守）

1. **禁止对生产 PLC 自动下载**。`role=production` 的目标直接拒绝。
2. **禁止跳过安全检查**。下载前必须 `probe` + `describe_package` + `check_download`。
3. **禁止修改 Safety 工程**。不修改安全任务、安全 I/O。
4. **禁止开放全部 OPC UA**。只使用 `plc_targets.local.json` 中的白名单节点。
5. **禁止无 execute 下载**。`plc_download_ruc` 不带 `execute=true` 只做安全检查，不下载。
6. **禁止跨类型下载**。ARsim 包不可下载到物理 PLC，反之亦然。

详细安全规则见：`references/safety.md`

## 失败处理

| 失败场景 | 处理方式 |
|---|---|
| 构建失败（error > 0） | 报告 `error_lines`，修复后重新构建，不继续后续步骤 |
| 安全检查未通过 | 报告 `reasons`，停止流程，不尝试下载 |
| 下载失败 | 报告 `log_path` 中的下载日志，检查目标连通性 |
| OPC UA 验证失败 | 尝试 `plc_read_pvi` 作为备用验证 |
| PVI 验证失败 | 检查 PVI Manager、目标连通性、变量名拼写 |
| ARsim 未启动 | 调用 `plc_start_arsim` 启动，等 3 秒后重试 |

详细流程见：`references/command-flow.md`
详细验证策略见：`references/verification.md`
