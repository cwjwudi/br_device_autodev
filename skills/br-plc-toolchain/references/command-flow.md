# Command Flow Reference

## 流程 1：标准 ARsim 闭环验证

**目标：** 修改代码后，构建 → 下载到 ARsim → 验证反馈。

### config 和 Simulation 前置检查

- 先确认本次使用的 Automation Studio config 名，例如 `x1685` 或 `x3687x`；这些名字必须来自项目实际配置，不要写死 `Config1`。
- 若该 config 需要以 ARsim 方式运行，检查 `PrintDemo/Physical/<config>/Hardware.hw`，确保 CPU 模块下存在 `<Parameter ID="Simulation" Value="1" />`。
- 修改 Simulation 设置后必须重新构建该 config；构建成功后，仿真文件应生成到 `PrintDemo/Temp/Simulation/<config>/<CPU>/`。
- `plc_start_arsim` 使用的 loader 必须是实际生成的 `PrintDemo/Temp/Simulation/<config>/<CPU>/ar000loader.exe`。示例：`PrintDemo/Temp/Simulation/x3687x/X20CP3687X/ar000loader.exe`。
- 如果 `plc_start_arsim` 报 loader 不存在，先核对 config 名、CPU 目录、Simulation 设置和 `tools/plc_targets.local.json` 中的 `targets.arsim.arsim_loader_exe`。

快捷工具：

```
plc_run_arsim_closed_loop(arguments: { "config": "<actual_config>", "target": "arsim", "execute": true })
```

该工具会执行下方同等步骤，并写入 `tools/.generated/reports/*_closed_loop_arsim.json`。

### 步骤

```
1. plc_build_project
   arguments: { "config": "<actual_config>", "build_ruc_package": true }
   成功条件: ok=true, parsed_errors=0
   失败: 报告 error_lines，停止

2. plc_start_arsim
   arguments: { "config": "<actual_config>", "target": "arsim" }
   成功条件: ok=true（可能复用已有进程）
   失败: 检查 Simulation 设置和 ar000loader.exe 路径

3. plc_probe_target
   arguments: { "config": "<actual_config>", "target": "arsim" }
   成功条件: ok=true, cpu_type 非空
   失败: 检查 ARsim 是否运行

4. plc_describe_ruc_package
   arguments: { "config": "<actual_config>", "target": "arsim" }
   成功条件: ok=true, 返回包元信息
   失败: 检查 RUC 包是否存在

5. plc_check_download
   arguments: { "config": "<actual_config>", "target": "arsim" }
   成功条件: ok=true, reasons=[]
   失败: 报告 reasons 中每条拒绝原因，停止
   例外: 如果用户明确授权 ARsim 强制下载，可重试
         { "config": "<actual_config>", "target": "arsim", "force_arsim_download": true }

6. plc_download_ruc
   arguments: { "config": "<actual_config>", "target": "arsim", "execute": true }
   成功条件: ok=true, executed=true, download_ok=true
   失败: 检查 safety_check 和下载日志
   例外: 用户明确授权 ARsim 强制下载时，可传
         { "config": "<actual_config>", "target": "arsim", "execute": true, "force_arsim_download": true }

7. plc_verify_opcua
   arguments: { "config": "<actual_config>", "target": "arsim" }
   成功条件: ok=true, 所有节点 ok=true
   失败: 转到步骤 8 (PVI 备用)

8. plc_read_pvi (备用)
   arguments: { "config": "<actual_config>", "target": "arsim" }
   成功条件: ok=true, 所有变量 ok=true
   失败: 检查 PVI Manager
```

### 成功判定

- 步骤 1-6 全部 `ok=true`
- 步骤 7 或 8 至少一个 `ok=true`
- 输出摘要：构建结果、包信息、目标状态、下载结果、验证读数

## 流程 2：仅安全检查（不下載）

**用途：** 验证包与目标的兼容性，不执行下载。

```
1. plc_probe_target
2. plc_describe_ruc_package
3. plc_check_download
```

判断：
- `plc_check_download.ok=true` → 可以下载（安全），但需 `execute=true`
- `plc_check_download.ok=false` → 不可下载，报告 `reasons`

## 流程 3：添加 PLC 功能并反馈验证

**用途：** 修改 ST/C 代码，增加功能，闭环验证。

流程：

1. 阅读 `docs/PLC_AUTOMATION_TOOLCHAIN_CONTEXT.md`
2. 阅读 `PrintDemo/` 下相关现有 ST/C 源码
3. 修改代码（只修改功能相关文件，不触碰 Safety）
4. 执行流程 1（标准 ARsim 闭环）
5. 验证新增变量的值是否符合预期
6. 输出 diff 摘要、构建摘要、验证摘要

## 流程 4：下载失败诊断

**用途：** 下载失败时收集信息，诊断根因。

```
1. plc_probe_target(target="<failed_target>")
   → 确认目标可达性和状态

2. plc_describe_ruc_package(target="<failed_target>")
   → 确认包是否匹配

3. plc_check_download(target="<failed_target>")
   → 检查兼容性判定

4. 读取日志:
   - tools/.generated/probe_<target>.log
   - 下载日志 (data.log_path)
```

### 常见失败原因

| 症状 | 可能原因 | 检查方法 |
|---|---|---|
| 探针无响应 | ARsim 未启动或 IP 不通 | `plc_start_arsim`，检查 IP |
| 包不存在 | 未构建或未生成 RUC | `plc_build_project(build_ruc_package=true)` |
| 安全检查失败 | CPU/Runtime 不匹配 | 对比 `describe_package` 和 `probe` 输出 |
| ARsim 包/探针 CPU 不一致 | ARsim 探针返回虚拟 CPU/order，或包仍是物理构建 | 先确认 `Simulation=1` 并重新构建；用户授权后仅对 ARsim 使用 `force_arsim_download=true` |
| 提示需要 initial installation | ARsim 当前无可更新映像，原 `Transfer.pil` 只允许 update | 用户授权 ARsim 强制下载时，工具会生成临时 `Transfer_force_arsim_*.pil` 使用初装限制 |
| 下载超时 | 目标忙或网络问题 | 检查 PVI 连接，重试 |
| OPC UA 读不到 | OPC UA 服务未就绪 | 等待几秒重试，换用 PVI |
| PVI `Object not found` | 当前运行映像未包含任务/变量，或任务未启动 | 重新确认 build/download 成功，再读变量；不要先判定为策略拦截 |

## 流程 5：测试 PLC 只读验证

**用途：** 对 `test_plc` (192.168.50.222, X20CP1685 / 6.5.1) 执行只读验证，不下载。

```
1. plc_probe_target(target="test_plc")
2. plc_verify_opcua(target="test_plc")
3. plc_read_pvi(target="test_plc")  (备用)
```

注意：
- 当前 RUC 包是 ARsim 包 (`AR000`)，不能下载到物理 `test_plc`
- test_plc 只能做只读探针和反馈验证
- 如需要下载 test_plc，先构建匹配的物理目标包

## 流程 6：输入输出测试闭环

**用途：** 对 LQR 等控制逻辑执行真实输入输出测试。

```
1. plc_build_project(build_ruc_package=true)
   → 构建并生成目标 RUC 包

2. plc_probe_target(target="<target>")
   → 确认目标 CPU/AR/状态

3. plc_describe_ruc_package(target="<target>")
   → 确认包信息

4. plc_check_download(target="<target>")
   → 下载安全检查

5. plc_download_ruc(target="<target>", execute=true)
   → 仅安全检查通过后下载

6. plc_search_variables(target="<target>", module="LQR")
   → Agent 查询变量目录，确定输入变量和读回变量

7. plc_reset_test_harness(target="<target>", execute=true)
   → 清空上一次测试状态

8. plc_run_test_suite(
     target="<target>",
     suite="tests/plc/lqr_io_tests.json",
     execute=true
   )
   → 按 access_policy 写入输入、等待、读取输出、比较期望值

9. plc_reset_test_harness(target="<target>", execute=true)
   → 测试后恢复安全状态
```

### 成功判定

- 构建和下载安全检查通过
- 每个测试用例的写入均通过 `access_policy` 校验
- 每个测试用例的断言均通过
- restore/reset 成功
- 报告写入 `tools/.generated/reports/*_io_test_<suite>.json`

### 失败处置

| 失败场景 | 处理方式 |
|---|---|
| 写入变量不符合 access_policy | 拒绝执行，报告变量名 |
| 目标为 production | 拒绝执行 |
| 断言失败 | 保留 actual/expected/tolerance，继续或按 suite 策略停止 |
| restore 失败 | 标记高风险，报告最后一次 readback |

## 流程 7：动态 PVI 读写验证

**用途：** 用户把 `access_policy.mode` 切换为 `agent_directed` 或 `catalog_policy` 后，让 Agent 自行选择变量并验证 PVI 动态读写通路。

前置条件：

- 先读取当前 `tools/plc_targets.local.json` 或 `targets_path`，确认本次实际模式和 `allow_dynamic_pvi_read/write`。
- 目标必须是 `role=arsim` 或 `role=dedicated_test_plc`，禁止 production。
- 白名单外变量必须先通过 `plc_search_variables` 或 `plc_list_variables` 找到，不凭空猜测。

推荐流程：

```text
1. plc_search_variables(target="<target>", module="<module>", writable=true)
   → 找到候选变量，避开 Safety/物理 I/O/system 名称

2. plc_read_pvi(target="<target>", pvi_variables=["Task:Var"])
   → 读取当前值、数据类型和 PVI 路径

3. plc_write_pvi(
     target="<target>",
     writes=[{"variable":"Task:Var","value":<current_value>}],
     execute=true
   )
   → 优先写回当前值，证明写入通路且降低副作用

4. plc_read_pvi(target="<target>", pvi_variables=["Task:Var"])
   → 独立读回，确认值一致
```

失败诊断：

| 失败场景 | 处理方式 |
|---|---|
| 策略拒绝 | 报告 `access_policy`、目标角色、变量名命中的黑名单或缺少的动态开关 |
| PVI `Object not found` | 先确认当前运行映像已重新构建并下载，任务和变量对象存在 |
| 写入失败但读取成功 | 检查变量属性是否可写、数据类型是否匹配、是否缺少 `execute=true` |
| 写入不同值后读回异常 | 立即 restore/reset 或写回原值，并报告最后一次 readback |
