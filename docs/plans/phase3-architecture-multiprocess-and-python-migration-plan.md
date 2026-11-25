# Phase 3 修改计划：PVI 子进程隔离、全局构建排队、采样性能基准与去 PowerShell 重构

状态：待实施。本文档仅描述拟议修改与验收标准，不代表相关能力已上线。  
前置依赖：完成 [Phase 1](phase1-runtime-lifecycle-and-diagnostics-plan.md) 与 [Phase 2](phase2-project-topology-and-variable-dx-plan.md)。  
预计交付版本：`0.18.0a1`

---

## 1. 背景与改造目标

随着工具链高频用于多工程、跨版本（AS4 + AS6）及毫秒级状态机采样，当前底层架构的 4 项结构性技术债已成为稳定性与并发能力的主要瓶颈：
1. **AS4 / AS6 PVI DLL 不能在同进程共存**：`PviWorker` 运行在 MCP Server 进程内线程中，一旦初始化 PVI6 DLL 就无法连 AS4（反之亦然），必须重启或双开 MCP Server；且底层 C-DLL 崩溃或 PVI Manager 2 小时试用过期会污染整个 Server。
2. **跨工程并行构建直接撞 `9207` 错误**：`locks.py` 目前仅按 `project:<path>:<config>` 加锁，两个不同工程并行调用 `plc_build_project` 时会触发 Automation Studio 内部构建互斥错误 `9207`。
3. **128 变量 / 20 ms Trace 缺少真实吞吐基准与异步优化评估**：`PviWorker._read_many` 目前是单线程串行 `for` 循环读 `variable.value`，在 128 变量高负载下容易超过 20 ms 导致丢点。
4. **双巨无霸胶水层脆弱**：`tools/mcp_server/toolchain.py`（~1950 行）与 `tools/plc_toolchain.ps1`（~1930 行）通过临时文件和 stdout 传参，历史多次出现编码、共享锁冲突与进程树误杀问题。

本阶段以**“对外 MCP 契约与 `PviClient` API 100% 向后兼容”**为前提，系统性完成底层架构升级。

---

## 2. 现网代码基线核对

| 模块 | 现有文件 | 现状与限制 |
| :--- | :--- | :--- |
| PVI 会话管理 | `src/br_plc_toolchain/backends/pvi/manager.py`<br>`src/br_plc_toolchain/backends/pvi/worker.py` | 进程内线程模型，`PviSessionManager` 直接实例化 `PviWorker`；`PVI4` / `PVI6` DLL 路径在进程级互斥 |
| 并发与锁 | `tools/mcp_server/locks.py`<br>`tools/mcp_server/server.py` | `acquire_locks` 为非阻塞抢锁（立即抛 `LockConflict`），无跨工程 `global:as_build` 排队锁 |
| 高频 Trace | `src/br_plc_toolchain/services/pvi_trace.py` | 定时线程周期调用 `service.read_many`，忠实记录 `actual_interval_ms` 与 `dropped_samples` |
| PowerShell 包装与 MCP 胶水 | `tools/plc_toolchain.ps1`<br>`tools/mcp_server/toolchain.py` | `DescribePackage`、`Build`、`Probe`、`Download` 均经 PowerShell 中转；`toolchain.py` 单文件承载全部 30+ 工具实现 |

---

## 3. 详细实施方案

### 3.1 PVI Worker 子进程隔离（同会话共存 AS4 + AS6）

1. **新增子进程 Worker 代理与宿主入口**
   - `src/br_plc_toolchain/backends/pvi/subprocess_worker.py`：实现与 `PviWorker` 完全一致的方法契约（`start()`、`close()`、`call(operation, **arguments)`、`running`、`dirty`）；
   - `src/br_plc_toolchain/backends/pvi/worker_main.py`：轻量独立子进程入口（通过 `sys.executable -m br_plc_toolchain.backends.pvi.worker_main` 启动），在子进程内按 `target.pvi_dll_dir`（`PVI4` 或 `PVI6`）初始化 `pvipy` 并运行现有 `PviWorker`，通过 stdin/stdout 换行分隔 UTF-8 JSON-RPC 帧与父进程通信；
   - 父进程管理：
     - 子进程纳入 Windows Job Object（父进程异常退出时自动回收全部 PVI 子进程，零孤儿进程）；
     - 单个目标子进程崩溃、卡死或检测到 PVI Manager 2 小时授权过期错误时，`PviSessionManager` 仅标记并重建该目标子进程，不影响 MCP Server 或其它目标会话。
2. **改造 `PviSessionManager`（`src/br_plc_toolchain/backends/pvi/manager.py`）**
   - 默认工厂改为 `SubprocessPviWorker`（保留 `PviWorker` 进程内模式及自定义 `worker_factory` 供单元测试注入 Fake Worker）；
   - 目标 `PviTarget` 显式携带 `pvi_family`（`PVI4` / `PVI6`）与 `pvi_dll_dir`（从工程 `br-auto-dev.json` 关联的全局 `toolchains.json` 解析），同一 MCP Server 进程内可同时持有 AS4 目标子进程与 AS6 目标子进程。
   - **独立脚本兼容**：`PviClient` 默认继续零破坏运行，支持可选参数 `isolate_process: bool = False`（独立脚本单目标可直连，多版本或 MCP Server 场景走子进程隔离）。

### 3.2 跨工程全局构建排队锁（根治并行构建 `9207`）

1. **扩展 `tools/mcp_server/locks.py`**
   - 在 `acquire_locks(...)` 中增加可选排队等待机制：`wait_timeout_seconds: float = 0.0`、`poll_interval_seconds: float = 0.5`；
   - 为 `plc_build_project`（以及含构建步骤的 `plc_add_project_library`）增加全局锁键 `global:as_build`；
   - 当检测到另一个工程正在构建时，进入有界排队等待（默认最多等待 `120` 秒，可在 `config/defaults/base.json` 的 `build.queue_timeout_seconds` 配置）；
   - 等待期间支持取消检查；超时未获得锁时返回明确可重试错误码 `BUILD_QUEUE_TIMEOUT`（附带当前持有构建锁的工程路径、PID 与已运行时长），彻底消除 `9207` 碰撞。

### 3.3 高频 Trace 性能实测与针对性优化

1. **建立标准基准脚本 `scripts/benchmark_pvi_trace.py`**
   - 针对本机 ARsim 实测 `16 / 32 / 64 / 128` 变量在 `20 ms / 50 ms / 100 ms` 下的实际单轮耗时（P50 / P95 / P99）、`actual_interval_ms` 与 `dropped_samples`。
2. **评估并实施最优采样路径**
   - 对比 `pvipy==1.2.11` 的“同步轮询 `_read_many`”与“注册 `valueChanged` / `refresh` 异步事件回调后在内存快照采样”两种模式：
     - 若事件订阅模式在 128 变量下实测稳定且无内存泄漏/回调乱序，将 `TraceManager` 在 `interval_ms < 50` 时切换为订阅快照模式，并保留轮询模式作为降级开关；
     - 若 `pvipy` 底层事件机制受限，则在 `PviWorker._read_many` 内部优化对象查找与值序列化开销，并在 `plc_start_pvi_trace` 返回中增加实测吞吐预警字段（如 `estimated_min_interval_ms`）。

### 3.4 `plc_toolchain.ps1` 分步迁回 Python 与 `toolchain.py` 拆分

按“风险从低到高、每步独立可回滚”顺序推进，本阶段完成前两批迁移与模块拆分：

1. **第一批迁移（纯本地操作，零目标副作用）**：
   - `DescribePackage` → `src/br_plc_toolchain/services/ruc_package.py`（纯 Python `zipfile` + `xml.etree.ElementTree` 解析 RUC 元数据，完全脱离 PowerShell）；
   - `Build` → `src/br_plc_toolchain/services/as_build.py`（Python 直接 `subprocess` 调用 `BR.AS.Build.exe`，强制 UTF-8/兼容控制台编码解码、有界日志收集、精确解析 `Build: X error(s), Y warning(s)`，移除对 `plc_toolchain.ps1` `Invoke-Build` 的依赖）。
2. **`tools/mcp_server/toolchain.py` 模块化拆分**：
   - 将 1950 行单文件按职责拆分为 `tools/mcp_server/handlers/`：
     - `handlers/build.py`、`handlers/arsim.py`、`handlers/download.py`、`handlers/runtime.py`、`handlers/library.py`、`handlers/project.py`、`handlers/diagnostics.py`；
   - `tools/mcp_server/toolchain.py` 保留为轻量聚合入口（对外 `TOOLS` 字典与公共函数签名保持兼容，不破坏现有测试）。
3. **（可选延展）`Probe` 迁回 Python**：如前两项稳定且工期充裕，复用 `plc_logger_read.py` 已验证的直接调用 `PVITransfer.exe -silent` + Job Object 模式迁移 `Probe`；`Download` 仍保留并仅在充分回归后考虑迁移，不冒进破坏既有 50 次可靠性成果。

---

## 4. 自主开发测试与验收规程（必须全部执行）

### 4.1 自动化单元测试与故障注入（`pytest`）

新增并运行以下测试文件，确保全套回归 100% 通过：

1. **`tests/test_pvi_subprocess_worker.py`**
   - 子进程正常启动、RPC 读写、异常透传、正常 `close()` 退出码为 0；
   - **崩溃恢复测试**：外部强杀子进程后，下一次调用能准确报告 `PVI_CONNECTION_LOST` 或按策略重建新子进程，父进程无死锁、无僵尸进程；
   - **多家族隔离测试**：同进程内分别构造 `PVI4` 与 `PVI6` 两个 `PviTarget`，验证分配到两个独立子进程且互不干扰。
2. **`tests/test_build_queue_lock.py`**
   - 两个并发构建请求对不同工程发起调用时，第二个请求排队等待而非报冲突，第一个释放后第二个顺利执行；
   - 排队超过 `queue_timeout_seconds` 返回 `BUILD_QUEUE_TIMEOUT`（`retryable=True`）且包含当前持锁者信息。
3. **`tests/test_python_ruc_and_build.py`**
   - Python 版 `DescribePackage` 与原 PowerShell 版在真实/样例 RUC zip 上的输出字段 100% 等价；
   - Python 版 `Build` 对 0 error、编译失败、含非 ASCII 路径/中文警告、超长错误截断的解析测试。
4. **全套回归命令**：
   ```powershell
   cd C:\Users\BR\codex_ws\br_device_autodev
   .\.venv\Scripts\python.exe -m pytest -v > var\verification\phase3-YYYYMMDD\pytest.log 2>&1
   .\.venv\Scripts\python.exe scripts\maintenance\generate_mcp_docs.py --check
   ```

### 4.2 本机双版本（AS4 + AS6）端到端实测验收

使用本机真实 AS4 工程（`C:\Users\BR\codex_ws\p801_plc_debug_log`）与 AS6 工程（`C:\Users\BR\codex_ws\p106_at_auto_test_3` 或 `p103_test_pos_gen`）完成以下 5 项实测：

| Case ID | 验收项 | 操作步骤 | 通过标准 |
| :--- | :--- | :--- | :--- |
| **P3-E2E-01** | 同 MCP 会话双版本并存 | 启动**单个** MCP Server 进程，同时连接运行中的 AS4 ARsim（如 `127.0.0.2`）与 AS6 ARsim（如 `127.0.0.1`），交替读取两边变量 | 无需重启 Server，两个目标均返回有效变量值；进程列表可见两个独立 PVI Worker 子进程 |
| **P3-E2E-02** | PVI 子进程崩溃自隔离 | 在 P3-E2E-01 基础上强杀其中一个目标的 Worker 子进程，检查另一目标读写，再重新 `discover` 被杀目标 | 未被杀目标全程无影响；被杀目标重新连接后恢复正常，MCP Server 未退出 |
| **P3-E2E-03** | 跨工程并行构建排队 | 通过独立并发客户端同时向 AS4（`p801`）和 AS6（`p103`）发 `plc_build_project(build_ruc_package=true)` | 两者均成功构建（0 errors），无 `9207` 报错；日志证明串行排队执行且总耗时合理 |
| **P3-E2E-04** | Python 版 RUC 解析与构建等价性 | 对构建出的 AS4/AS6 RUC 包执行 `plc_describe_ruc_package` + `plc_check_download` + 至少 5 次连续 `plc_download_ruc` 冒烟 | 元数据完整，安全检查通过，5/5 下载与结果恢复正常 |
| **P3-E2E-05** | 高频 Trace 吞吐实测基准 | 运行 `scripts/benchmark_pvi_trace.py` 对本机 AS6 ARsim 跑 `32 / 64 / 128` 变量 × `20 ms / 50 ms` 矩阵（每档 10 秒） | 输出完整 P50/P95/P99 采样间隔与丢点率实测表，确认优化前后对比数据真实可复现 |

### 4.3 必须交付的完整验收报告

实施完成后，生成 `docs/verification/phase3-verification-YYYYMMDD.md`，并将原始日志与基准 JSON 存入 `var/verification/phase3-YYYYMMDD/`，报告必须包含：
1. **自动化测试统计**：总用例数、新增用例数、通过/失败数、`pytest.log` 路径、`generate_mcp_docs.py --check` 结果。
2. **P3-E2E-01 ~ P3-E2E-05 实测矩阵**：含双版本子进程 PID 证据、并行构建时间戳重叠与排队日志、5 次下载冒烟记录。
3. **128 变量 / 20 ms 性能基准实测表**：列出各档位（变量数 × 周期）的实测间隔、丢点数、CPU 占用，以及所选采样模式（订阅或轮询）的实测依据。
4. **孤儿进程与资源收尾核查**：关闭测试 MCP Server 后，核查无残留 `worker_main` Python 子进程、无残留 `ar000loader` / `PVITransfer` 进程。
