# Verification Strategy

## 反馈验证优先级

1. **OPC UA** — 首选方案，读取 `opcua.validation_node_ids` 白名单节点
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

传入自定义节点时会覆盖默认白名单。

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
2. 使用自定义节点 ID 覆盖白名单
3. 对比 OPC UA 和 PVI 的两个读数交叉验证

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
