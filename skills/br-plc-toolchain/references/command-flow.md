# Command Flow Reference

## 流程 1：标准 ARsim 闭环验证

**目标：** 修改代码后，构建 → 下载到 ARsim → 验证反馈。

快捷工具：

```
plc_run_arsim_closed_loop(arguments: { "target": "arsim", "execute": true })
```

该工具会执行下方同等步骤，并写入 `tools/.generated/reports/*_closed_loop_arsim.json`。

### 步骤

```
1. plc_build_project
   arguments: { "build_ruc_package": true }
   成功条件: ok=true, parsed_errors=0
   失败: 报告 error_lines，停止

2. plc_start_arsim
   arguments: { "target": "arsim" }
   成功条件: ok=true（可能复用已有进程）
   失败: 检查 ar000loader.exe 路径

3. plc_probe_target
   arguments: { "target": "arsim" }
   成功条件: ok=true, cpu_type 非空
   失败: 检查 ARsim 是否运行

4. plc_describe_ruc_package
   arguments: { "target": "arsim" }
   成功条件: ok=true, 返回包元信息
   失败: 检查 RUC 包是否存在

5. plc_check_download
   arguments: { "target": "arsim" }
   成功条件: ok=true, reasons=[]
   失败: 报告 reasons 中每条拒绝原因，停止

6. plc_download_ruc
   arguments: { "target": "arsim", "execute": true }
   成功条件: ok=true, executed=true, download_ok=true
   失败: 检查 safety_check 和下载日志

7. plc_verify_opcua
   arguments: { "target": "arsim" }
   成功条件: ok=true, 所有节点 ok=true
   失败: 转到步骤 8 (PVI 备用)

8. plc_read_pvi (备用)
   arguments: { "target": "arsim" }
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
| 下载超时 | 目标忙或网络问题 | 检查 PVI 连接，重试 |
| OPC UA 读不到 | OPC UA 服务未就绪 | 等待几秒重试，换用 PVI |

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
