# Safety Rules

## 目标分类与下载权限

| 目标角色 | 含义 | 下载权限 | 配置示例 |
|---|---|---|---|
| `arsim` | 本机 ARsim 仿真器 | 允许自动下载 | `127.0.0.1` |
| `dedicated_test_plc` | 专用测试 PLC | 允许自动下载（需白名单 `allow_auto_download=true`） | `192.168.50.233` |
| `production` | 生产 PLC | **完全禁止自动下载** | 不配置此类目标 |

## 下载前强制检查清单

任一检查未通过，流程立即停止：

1. **目标鉴别**
   - 检查 `config/targets/default-safe.json` 中目标的 `role` 字段
   - `role=production` → 拒绝，不继续
   - `allow_auto_download=false` → 拒绝，不继续

2. **只读探针** (`plc_probe_target`)
   - 确认目标可达
   - 确认 `cpu_type` 有效
   - 确认 `plc_status` 正常（WarmStart 或 Run）

3. **包信息读取** (`plc_describe_ruc_package`)
   - 确认 RUC 包存在
   - 确认包内 `cpu_type`、`ar_version`、`runtime_type`

4. **兼容性检查** (`plc_check_download`)
   - ARsim 包 (`cpu_type=AR000`) ↔ 物理 PLC → 拒绝
   - 物理包 ↔ ARsim 目标 → 默认拒绝
   - 包 CPU ≠ 目标 CPU → 默认拒绝
   - 包 Runtime ≠ 目标 Runtime → 拒绝
   - 只有用户明确授权且目标 `role=arsim` 时，`force_arsim_download=true` 才可把 ARsim 目标上的 CPU/型号不匹配降级为 warning

5. **显式确认** (`plc_download_ruc`)
   - 必须传入 `execute=true`
   - 缺少此参数 → MCP 返回 dry-run 摘要，不下载

## ARsim 强制下载规则

ARsim 强制下载是为本机仿真调试准备的例外流程，用于处理 ARsim 探针 CPU/order 与 RUC 包元信息不一致，或 ARsim 首次安装需要特殊 `Transfer.pil` 的情况。

允许条件：

1. 用户在当前任务中明确授权 ARsim 强制下载。
2. 目标必须是 `target=arsim` 且配置角色为 `role=arsim`。
3. 仍必须完成 `plc_probe_target`、`plc_describe_ruc_package`、`plc_check_download`。
4. 实际下载仍必须传入 `execute=true`。

禁止条件：

1. 不得用于 `dedicated_test_plc`、任何物理 PLC 或 `role=production`。
2. 不得跳过 production、`allow_auto_download`、Safety、`execute=true` 等安全门。
3. 不得把“ARsim CPU/order mismatch 可放行”推广到物理目标。

实现行为：

- `plc_check_download(force_arsim_download=true)` 只在 ARsim 目标上把 CPU/型号不匹配记录为 warning。
- `plc_download_ruc(force_arsim_download=true, execute=true)` 会在需要时生成临时 `Transfer_force_arsim_*.pil`。
- 临时 PIL 只替换 `InstallRestriction=AllowUpdatesWithoutDataLoss` 为 `InstallRestriction=AllowInitialInstallation`，用于满足 ARsim 首次安装；原始 `Transfer.pil` 不应被覆盖。

## 生产 PLC 规则

1. **绝对禁止**通过 MCP 或 Skill 自动下载到生产 PLC
2. 生产目标不应出现在办公室测试或 ARsim profile 中
3. 如果必须配置，设置 `role=production` 且 `allow_auto_download=false`
4. MCP Server 和 CLI 两层均会拒绝生产目标下载
5. 人工操作生产下载时，应使用 PowerShell CLI 手动执行，并逐项确认

## Safety 工程规则

1. **不修改** `*.saf`、Safety 任务配置
2. **不修改** Safety I/O 映射
3. 构建日志中出现 safety 相关 error 时，立即报告并停止
4. 如需修改 Safety，必须人工在 Automation Studio IDE 中完成

## OPC UA 安全

1. **默认不开放全部变量**。`opcua.auto_expose_all` 必须为 `false`
2. 默认访问模式为 `access_policy.mode=whitelist`
3. 默认可读节点通过 `opcua.validation_node_ids` 白名单控制
4. MCP 工具 `plc_verify_opcua` 仅支持读取，**不支持写入**
5. 只有用户手动切换到 `agent_directed` 并启用 `allow_dynamic_opcua_read=true` 后，Agent 才能传入白名单外 OPC UA 节点尝试读取
6. 如在 AS 工程中修改 OPC UA 配置，必须人工审查

## PVI 安全

1. `arsim`/`dedicated_test_plc` 可读取任意明确命名的 PVI 变量，白名单仅作为默认验证变量集合
2. production 和未知目标继续由 `access_policy` 限制
3. 建议先调用 `plc_search_variables` 或 `plc_list_variables` 查找变量，以减少名称错误
4. 读取变量值的变化仅用于验证，不用于控制

## PVI 写入测试安全

PVI 写入能力直接开放给明确标记为 `arsim` 或 `dedicated_test_plc` 的目标，不检查变量白名单、目录权限或名称黑名单；仍不能绕过显式目标、`execute=true`、变量自身可写属性和审计报告。

强制规则：

1. `plc_write_pvi` 必须显式传入 `execute=true`
2. `arsim`/`dedicated_test_plc` 可写任意由 PVI 标记为可写的变量，不检查 `pvi.write_whitelist`
3. 写入不要求测试会话，但仍必须显式目标和 `execute=true`
4. 禁止写 `role=production` 的目标
5. 可信调试目标不应用变量名称黑名单；production 和未知目标仍受限
6. 每个测试用例结束后必须执行 restore/reset
7. 写入前后都要读取关键变量，并写入报告
8. 动态写入优先执行“读当前值 -> 写同值 -> 独立读回”的低副作用验证；只有用户明确要求改变状态或测试 suite 定义了 restore/reset 时，才写入不同值

建议 LQR 写入白名单：

| 变量 | 类型 | 用途 |
|---|---|---|
| `LQR:bLqrEnable` | BOOL | 启用/停用控制器 |
| `LQR:bLqrReset` | BOOL | 测试前后复位 |
| `LQR:arLqrX` | REAL[4] | 状态输入 |
| `LQR:arLqrXRef` | REAL[4] | 参考输入 |
| `LQR:arLqrK` | REAL[8] | 控制增益 |
| `LQR:rLqrMaxAbsU` | REAL | 输出限幅 |

## 构建结果判断

1. **不以 exit code 判定成功/失败**
2. 必须解析日志中的 `Build: N error(s), M warning(s)` 行
3. `error(s) > 0` → 构建失败，停止后续步骤
4. `error(s) = 0` → 构建成功，可以继续
5. warnings 仅记录，不阻止流程
6. 构建日志保存在 `var/build_<Config>.log`

## 日志和审计

1. 每次构建日志自动保存到 `var/`
2. 每次探针日志保存到 `var/probe_<target>.log`
3. 下载日志在所选工程的 `Binaries/` 下对应目录，或在 `var/` 报告中记录的 `log_path`
4. OPC UA 读取的节点文件保存在 `var/opcua_nodes_<target>.json`
5. PVI 读取的变量文件保存在 `var/pvi_variables_<target>.json`
