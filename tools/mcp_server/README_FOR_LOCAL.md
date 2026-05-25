# PLC MCP Server Local Notes

## 启动

从仓库根目录运行：

```powershell
python tools\mcp_server\server.py
```

或从 `tools/mcp_server/` 目录运行：

```powershell
python server.py
```

## 架构

此服务器是一个轻量 stdio JSON-RPC MCP 封装，不自行实现 PLC 逻辑；所有实际工作委托给：

```powershell
tools\plc_toolchain.ps1
```

服务器默认以仓库根目录为工作目录运行所有命令。

## 已暴露工具

第一批 8 个工具和第二批 4 个工具均已实现：

| MCP 工具 | CLI 命令 | 安全门 |
|---|---|---|
| `plc_build_project` | `Build` | 无 |
| `plc_start_arsim` | `StartArsim` | 仅限 arsim 角色目标 |
| `plc_probe_target` | `Probe` | 只读 |
| `plc_describe_ruc_package` | `DescribePackage` | 只读 |
| `plc_check_download` | `CheckDownload` | 只读 |
| `plc_download_ruc` | `Download` | **必须 `execute=true`** |
| `plc_verify_opcua` | `VerifyOpcUa` | 只读，默认白名单 |
| `plc_read_pvi` | `ReadPvi` | 只读，默认白名单 |
| `plc_run_arsim_closed_loop` | `RunArsimClosedLoop` | **下载仍必须 `execute=true`** |
| `plc_run_verification_suite` | `RunVerificationSuite` | 只读，写统一报告 |
| `plc_get_target_config` | `GetTargetConfig` | 只读 |
| `plc_list_targets` | `ListTargets` | 只读 |

## 默认配置

- 默认目标：`arsim`
- 默认工程：`PrintDemo\Huitong_FrontEval.apj`
- 默认配置：`Config1`
- 配置文件：`tools\plc_targets.local.json`

## 通用参数

所有工具均接收：

- `target`：目标名称，默认 `arsim`
- `project_path`：AS 工程路径
- `config`：配置名称，默认 `Config1`
- `targets_path`：目标配置 JSON 路径
- `timeout_seconds`：超时秒数

## 返回结构

```json
{
  "ok": true,
  "tool": "plc_xxx",
  "target": "arsim",
  "summary": "可读摘要",
  "data": {},
  "logs": ["路径列表"],
  "warnings": [],
  "next_actions": ["建议的下一步操作"]
}
```

## 测试验证

手动测试命令：

```powershell
# 列出所有工具
echo "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}" | python tools\mcp_server\server.py

# 构建
echo "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_build_project\",\"arguments\":{}}}" | python tools\mcp_server\server.py

# 探针
echo "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_probe_target\",\"arguments\":{}}}" | python tools\mcp_server\server.py

# OPC UA 验证
echo "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_verify_opcua\",\"arguments\":{}}}" | python tools\mcp_server\server.py

# 目标列表
echo "{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"tools/call\",\"params\":{\"name\":\"plc_list_targets\",\"arguments\":{}}}" | python tools\mcp_server\server.py
```

## MCP 客户端接入

任何支持 stdio 模式的 MCP 客户端均可接入，配置如下：

```json
{
  "mcpServers": {
    "br-plc-toolchain": {
      "type": "stdio",
      "command": "python",
      "args": ["tools/mcp_server/server.py"],
      "cwd": "D:\\codex_ws\\motion_svg_test"
    }
  }
}
```
