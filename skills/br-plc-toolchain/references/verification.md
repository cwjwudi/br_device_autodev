# Verification Strategy

## 反馈验证优先级

1. **OPC UA** — 首选方案，默认读取 `opcua.validation_node_ids` 白名单节点
2. **PVI** — 备用方案，当 OPC UA 不可用时使用

## OPC UA 验证

### 默认白名单节点

当前配置在 `tools/plc_targets.local.json` → `opcua.validation_node_ids`：

| 节点 ID | 说明 | 典型值 |
|---|---|---|
| `ns=5;s=::AsGlobalPV:gstHmi.stOutputs.diSImage` | 当前显示图像编号 | 600 |
| `ns=5;s=::AsGlobalPV:gstHmi.stOutputs.diPuWindowIntervalmm` | PU 窗口间隔 | 0 |
| `ns=5;s=::AsGlobalPV:gstHmi.stConfig.strPuChartAdr` | 图表地址 URL | `http://127.0.0.1` |
| `ns=5;s=::AsGlobalPV:gstMainInface.stFromMain.diSImage` | 主接口图像编号 | 600 |
| `ns=5;s=::AsGlobalPV:gstMainInface.stToMain.usiActivePU` | 当前活跃 PU 编号 | 88 |
| `ns=5;s=::SVG:strTransform` | SVG 变换 JSON 字符串 | `[{"select":"#emergency",...}]` |

### 指定自定义节点

```
plc_verify_opcua(arguments: {
  "target": "arsim",
  "opcua_node_ids": [
    "ns=5;s=::AsGlobalPV:gstHmi.stOutputs.diSImage",
    "ns=5;s=::MyTask:myVariable"
  ]
})
```

传入自定义节点时会覆盖默认节点列表，但仍受 `access_policy` 约束。默认 `whitelist` 模式下，自定义节点也必须在 `opcua.validation_node_ids` 中；只有用户手动切换到动态模式后，Agent 才能读取白名单外节点。

### 端点

- ARsim: `opc.tcp://127.0.0.1:4840`
- 端口可通过 `opcua.endpoint_port` 配置

## PVI 验证

### 默认白名单变量

当前配置在 `tools/plc_targets.local.json` → `pvi.validation_variables`：

| 变量名 | 作用域 | Task | 数据类型 | 典型值 |
|---|---|---|---|---|
| `gstHmi.stOutputs.diSImage` | global | — | i32 | 600 |
| `gstHmi.stConfig.strPuChartAdr` | global | — | string | `http://127.0.0.1` |
| `gstMainInface.stToMain.usiActivePU` | global | — | u8 | 88 |
| `strTransform` | task | SVG | string | JSON 数组 |

### 指定自定义变量

```
plc_read_pvi(arguments: {
  "target": "arsim",
  "pvi_variables": [
    "gstHmi.stOutputs.diSImage",
    "SVG:strTransform"
  ]
})
```

- 全局变量：直接写变量名，如 `gstHmi.stOutputs.diSImage`
- Task 变量：`<TaskName>:<VarName>` 格式，如 `SVG:strTransform`
- 自定义变量仍受 `access_policy` 约束。默认 `whitelist` 模式下必须在 PVI 读取白名单中；动态模式下应先调用 `plc_search_variables` 查询变量。

### PVI 动态变量诊断

PVI 动态读取失败时，先区分两类问题：

| 现象 | 含义 | 下一步 |
|---|---|---|
| MCP 返回策略错误、`access_policy`、`blocked_name_patterns` 或目标角色错误 | 策略门控拒绝 | 检查当前 `access_policy.mode`、`allow_dynamic_*`、目标 `role` 和变量名 |
| PVI 返回 `Object not found` / `11033` | 策略已经放行，但当前运行映像里找不到该 PVI 对象 | 确认对应任务/变量已参与构建，ARsim/PLC 已下载最新映像，任务正在运行 |
| PVI 连接失败 / ANSL 建链失败 | 目标或 PVI 通道不可达 | 先 `plc_probe_target`，检查 ARsim/PVI Manager/IP/端口 |

因此，`Object not found` 不应直接解释为“白名单拦截”。它更常见地表示当前 ARsim 或 PLC 上运行的程序版本还没有该任务/变量。

### 动态 PVI 写入读回

动态写入必须形成读写闭环：

```text
plc_read_pvi       → 记录 before、数据类型和变量属性
plc_write_pvi      → 传 execute=true，优先写入 before 的同值
plc_read_pvi       → 独立读回，确认 readback
```

默认优先写同值，因为它能验证 PVI 写入通路，同时避免改变控制逻辑状态。只有用户明确要求改变状态，或测试 suite 提供 restore/reset，才写入不同值。

## 验证内容

### 构建后验证

验证重点：确保下载后程序运行正确。

1. 读取关键状态变量，确认值在预期范围内
2. 读取 SVG 变换数据 (`strTransform`)，确认可视化输出正确
3. 读取活跃 PU 编号，确认任务调度正常

### 回归验证

验证重点：确保修改没有引入回归。

1. 对比修改前后的关键变量值
2. 检查警告日志
3. 确认所有验证节点可读

### 调试验证

验证重点：问题诊断。

1. 逐个读取相关变量
2. 使用 `plc_search_variables` 查询相关变量，再按 `access_policy` 读取自定义节点或变量
3. 对比 OPC UA 和 PVI 的两个读数交叉验证
4. 对动态写入，优先执行“读当前值 -> 写同值 -> 独立读回”，并记录 before/readback

## 报告格式

每次验证应输出：

```json
{
  "build": {
    "ok": true,
    "errors": 0,
    "warnings": 2,
    "log_path": "..."
  },
  "package": {
    "cpu_type": "AR000",
    "ar_version": "6.5.1"
  },
  "target": {
    "cpu_type": "X20CP3687X",
    "ar_version": "6.5.1",
    "plc_status": "WarmStart"
  },
  "download": {
    "ok": true,
    "executed": true
  },
  "verification": {
    "method": "opcua",
    "nodes_ok": 6,
    "nodes_total": 6,
    "key_values": {
      "diSImage": 600,
      "usiActivePU": 88
    }
  }
}
```

## 底层工具

验证使用的 Python 脚本：

- `tools/opcua_read.py` — OPC UA 读取 (依赖 `asyncua`)
- `tools/pvi_read.py` — PVI 读取 (依赖 B&R PVI DLL)

MCP Server 调用这些脚本，Agent 不需要直接调用。

## M6 输入输出测试验证（待实现）

现有验证只证明变量可读和下载后程序在线。M6 需要验证控制逻辑本身：

```text
写入输入
-> 等待 settle_ms
-> 读取输出
-> 比较 expected/tolerance
-> 输出 pass/fail
-> restore/reset
```

### LQR 推荐 read/write 分层

写入白名单：

| 变量 | 用途 |
|---|---|
| `LQR:bLqrEnable` | 控制器使能 |
| `LQR:bLqrReset` | 测试复位 |
| `LQR:arLqrX` | 状态向量 |
| `LQR:arLqrXRef` | 参考状态 |
| `LQR:arLqrK` | LQR 增益矩阵，2x4 展平 |
| `LQR:rLqrMaxAbsU` | 输出限幅 |

读取/断言变量：

| 变量 | 断言内容 |
|---|---|
| `LQR:arLqrU` | `u = -K * (x - x_ref)`，带容差 |
| `LQR:arLqrError` | `x - x_ref` |
| `LQR:stLqrStatus.bValid` | 控制器是否产生有效输出 |
| `LQR:stLqrStatus.bSaturated` | 是否触发限幅 |
| `LQR:stLqrStatus.usiErrorCode` | 错误码是否符合预期 |

### 推荐测试用例

1. `zero_state_zero_output`
   - 输入：`x=[0,0,0,0]`，`x_ref=[0,0,0,0]`
   - 期望：`u=[0,0]`
2. `nominal_tracking_error`
   - 输入：非零 `x` 和固定 `K`
   - 期望：`u=-K*(x-x_ref)`
3. `saturation_limit`
   - 输入：大误差，小 `rLqrMaxAbsU`
   - 期望：输出被限幅，`bSaturated=true`
4. `disabled_zero_output`
   - 输入：`bLqrEnable=false`
   - 期望：输出清零，`bValid=false`
5. `reset_clears_output`
   - 输入：`bLqrReset=true`
   - 期望：输出和误差清零

### IO 测试报告格式

```json
{
  "ok": true,
  "target": "test_plc",
  "suite": "lqr_io_tests",
  "cases_total": 5,
  "cases_passed": 5,
  "cases_failed": 0,
  "cases": [
    {
      "name": "nominal_tracking_error",
      "ok": true,
      "writes": [],
      "readback": {},
      "checks": [
        {
          "variable": "LQR:arLqrU[0]",
          "expected": -2.0,
          "actual": -2.0,
          "tolerance": 0.001,
          "ok": true
        }
      ],
      "restore_ok": true
    }
  ]
}
```
