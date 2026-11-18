# ARsim 下载与结果恢复

下发前生成并保留唯一的 `request_id`，如 UUID。在 `plc_check_download` 通过后，将该编号与显式工程、目标及 `execute=true` 一起传给 `plc_download_ruc`。服务端会再次执行安全检查。相同编号和相同参数返回已有操作。相同编号配不同参数会返回 `DOWNLOAD_REQUEST_ID_CONFLICT`。兼容调用可省略编号，此时只有收到原响应后才知道服务端生成的编号。

服务端从接到请求开始计时。缺省上限来自 `config/defaults/base.json` 的 `download.timeout_seconds`，默认 60 秒。工程 `br-auto-dev.json` 中的同名字段只能缩短该上限。两处配置均要求 1 到 60 之间的整数。单次调用可省略 `timeout_seconds`，也可传入正整数。实际使用三者中最短的有效时限，并返回 `effective_timeout_seconds`。预算包含安全检查、传输、后置探测和进程清理。独立的 `plc_check_download` 使用自身时限。

原响应丢失、客户端超时或断开后，调用 `plc_get_download_result` 并提供原 `request_id`。该查询读取服务端记录和进程及日志证据。它返回操作编号、阶段、有效时限、进程状态、传输证据、已有目标探测和审计路径。诊断输出按操作编号记录在 `var/reports/download_stdio.jsonl`，客户端可用 JSON-RPC 编号关联收包时间。

| `download_state` | 后续动作 |
| --- | --- |
| `not_started` | 根据错误修正问题，重新跑安全检查。通过后可用新编号做一次有限重试。 |
| `in_progress` | 继续查询原编号，等当前操作结束。 |
| `transfer_succeeded` | 核对 `probe_after` 和 `application_readiness`。目标未确认时先做只读探测，避免重发。 |
| `transfer_failed` | 查看传输日志和错误原因。确认旧进程退出，重新通过安全检查后可用新编号做一次有限重试。 |
| `unknown` | 暂停自动下载。结合原编号查询、进程状态、日志及目标探测确认。记录缺失也属于此状态。 |

下载操作记录保存在 `var/downloads/operations.sqlite3`。Windows Job Object 约束已登记的下载进程树。重启或清理未完成时，服务端检查旧进程归属，直到确认退出才解除目标保护。保留操作数据库和关联日志，便于追查断线前的请求。

Codex 的 MCP 客户端等待设置独立于服务端预算。新连接可以通过 `mcp_servers.br-plc-toolchain.tool_timeout_sec` 给传输和客户端处理留出余量。该项适用于该服务的所有工具，短时限也会影响长耗时构建。其他宿主的等待设置由各自的平台控制。若客户端先超时，按原请求编号查询。 [Codex 配置参考](https://developers.openai.com/codex/config-reference/)

## 复测

启动并确认三个回环目标归属后，在仓库根目录运行以下命令。逐次结果、JSON-RPC 收发时间和查询响应会写入指定的 JSONL 文件。结果未知的目标会暂停，脚本继续其他目标。

```powershell
.\.venv\Scripts\python.exe scripts\verify_arsim_downloads.py `
    --case ..\p103_test_pos_gen p103_download_test `
    --case ..\p803_amount_var_test p803_download_test `
    --case ..\p801_plc_debug_log arsim `
    --count 50 --output var\arsim-download-reliability-run.jsonl
```
