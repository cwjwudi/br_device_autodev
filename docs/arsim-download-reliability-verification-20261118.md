# ARsim 下载闭环验收

验收在 2026 年 11 月 18 日北京时间进行。三个工程的环境检查、Doctor 检查和 RUC 构建均通过。p103 使用默认仿真目录，p801 与 p803 使用各自指定的仿真目录。所有目标均为回环地址。下载逐次运行，先进行独立安全检查，工具内部再次执行检查。期间共观察到 7 个 ARsim loader，同时运行实例数低于 10。

## 实测结果

首轮运行 50 次，最终版运行 50 次并补充 3 次。按下文排除规则保留 50 次最终版验收样本。所有验收样本均通过两轮安全检查并进入传输阶段。

| 工程 | 最终版验收样本 | 传输成功 | 传输未知 | 客户端收到原响应及查询结果 | 后置探测可达 | 应用就绪通过 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p103 | 40 | 40 | 0 | 40 | 40 | 0 |
| p801 | 3 | 2 | 1 | 3 | 3 | 0 |
| p803 | 7 | 6 | 1 | 7 | 7 | 0 |
| 合计 | 50 | 48 | 2 | 50 | 50 | 0 |

全部 50 次确认下载进程退出，并关联到成对审计记录。客户端实测用时 11.196–43.318 秒，服务端从收包到 stdout 刷新最长 43.318 秒。三个工程均未配置应用就绪验证字段。

闭环要求每次都能读取相同操作编号的结论、原因或证据范围、进程退出状态和后续动作。客户端收包与服务器的序列化、stdout 写入和刷新通过 JSON-RPC ID 和操作编号对应。

首轮 p801 第 18 次因内部探测没有返回有效 CPU 类型而被拒绝，工具返回 `DOWNLOAD_SAFETY_FAILED` 和 `not_started`。首轮 p103 第 45 次和最终轮的 p801 第 11 次、p803 第 17 次均在建立连接时中止。PVITransfer 返回 28331，传输日志停在 `Establishing Connection...`，后置探测确认目标可达，所属下载进程均已退出。工具返回 `TRANSFER_STATE_UNKNOWN` 并要求暂停自动下载。 [B&R PVITransfer 错误码](https://help.br-automation.com/#/en/6/automationnet/pvitransfer/general/pvitransfer%5Ferrornumbers%2Ehtml)

最终轮在首轮 p103 中止前已排队。首轮 p103 中止后已有进程退出与后置探测记录，最终轮有 3 次 p103 调用先于额外的独立只读复核。验收统计剔除这 3 次，并使用另一套已确认归属的 p103 ARsim 补足。最终轮的 p801 与 p803 在结果转为未知后暂停到测试结束。

## 返回链路与恢复

- 新启动的 Codex MCP 客户端在临时 70 秒等待设置下收到实际下载响应，用时 15.088 秒。请求传入 180 秒，服务端报告实际生效 60 秒。随后按原编号查回了同一操作。非 ASCII 演练响应可解析。
- 将服务端单次时限设为 1 秒，Codex 收到 `DOWNLOAD_TIMEOUT`、`not_started` 和进程退出确认。把客户端等待上限单独设为 2 秒，客户端在约 2.02 秒报告超时。按原编号先查到 `in_progress`，随后查到 `OPERATION_CANCELLED` 和 `not_started`。两项测试均使用临时配置。
- 用独立客户端发送实际下载后断开 stdout，服务端为操作 `25ab633e738144e1b637c3b8c1554a4a` 记录 `stdout_failed`。新连接用 `lost-reply-b92cbd53a947` 找回传输成功与进程退出。该次原后置探测未确认目标，随后只读探测返回 `WarmStart`。复用相同编号与参数取回原操作，变更参数后复用相同编号返回冲突。
- 当前聊天已连接的旧 MCP 进程用 11.537 秒返回了演练响应。新流程的实际下载和恢复在新连接中验证。历史 300 秒等待发生时缺少 stdout 与客户端收包证据，原故障的确切丢失位置仍未定位。

自动化测试 211 项通过，另有 216 项子测试通过。故障注入覆盖共享访问冲突、日志证据冲突、进程卡住、清理无法确认、下载中取消、服务进程中止、请求重放以及 UTF-8。真实 PLC 与业务层验收不在本轮范围内。

测试结束后，按运行目录和进程身份停止本轮释放的四个 ARsim。清理后无本轮实例和 PVITransfer 进程残留，三个原有 loader 仍在运行。仿真目录与取证日志已保留。

## 原始记录

- [初轮 50 次原始结果](../var/arsim-download-reliability-50.jsonl)
- [最终轮原始结果](../var/arsim-download-reliability-final.jsonl) · [补充轮原始结果](../var/arsim-download-reliability-supplemental.jsonl)
- [最终轮服务端与客户端时间对照](../var/arsim-download-reliability-final-correlated-stdio.jsonl) · [汇总](../var/arsim-download-reliability-summary.json)
- [有效样本及排除编号](../var/arsim-download-reliability-accepted.json) · [进程清理记录](../var/arsim-download-reliability-cleanup.json)
- [Codex 实际下载、演练及 1 秒服务端时限](../var/download-codex-client.jsonl) · [Codex 2 秒客户端时限](../var/download-codex-limit.jsonl)
- [断流恢复](../var/download-disconnected-client.jsonl) · [只读复核](../var/download-recovery-target-probes.jsonl) · [请求重放](../var/download-replay-evidence.jsonl)
- [服务端响应追踪](../var/reports/download_stdio.jsonl) · [审计](../var/audit/2026-11-18/) · [传输与进程证据](../var/downloads/)
