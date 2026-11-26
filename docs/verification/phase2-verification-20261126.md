# Phase 2 阶段验收报告（AS 工程拓扑解析、在线变量缓存、结构体展开与 MCP 受控批量写）

交付版本：`0.17.0a1`  
验收日期：`2026-11-26`  
对应计划：[phase2-project-topology-and-variable-dx-plan.md](../plans/phase2-project-topology-and-variable-dx-plan.md)

---

## 1. 验收范围与环境基线

- **仓库路径**：`C:\Users\BR\codex_ws\br_device_autodev`
- **基线 Git Commit**：`a0fdb00`（`0.16.0a1` → `0.17.0a1`）
- **Python 解释器**：`C:\Users\BR\codex_ws\br_device_autodev\.venv\Scripts\python.exe`（Python 3.14.6，pytest 9.2.0，pvipy 1.2.11）
- **工具链**：`as6_default`（AS6 / PVI6，`Pvi6Com64.dll`）
- **端到端测试工程**：
  - AS6 工程：`C:\Users\BR\codex_ws\p106_at_auto_test_3`（`ACOPOStrak_API_V6.apj`，Config `SecPackTest`，CPU `X20CP3687X`，AR `6.7.8`）
  - AS4 工程：`C:\Users\BR\codex_ws\p801_plc_debug_log\as-project`（`StdLibs.apj`，Config `3586X`，CPU `X20CP3586`，AR `J4.93`）
- **端到端测试目标 IP**：`127.0.0.9`（`p105_queue`，独立空闲回环地址，测完自动停止并清理目录）
- **验收范围**：
  1. 只读 AS 工程拓扑解析与静态完整性自检：`src/br_plc_toolchain/project/topology.py` + MCP 工具 `plc_inspect_project`；
  2. 在线变量列表 30 秒短时缓存与分页提速：`PviWorker._list_variables(..., refresh=False)` + `plc_list_runtime_variables(refresh=...)`；
  3. 结构体 / 数组叶子展开辅助：`PviWorker._variable_info(..., expand=True, max_depth=3, max_fields=128)` + `plc_get_runtime_variable_info(expand=...)` + `PviClient.expand_variable` / `PviClient.read_structure`；
  4. MCP 受控批量写：`RuntimePviService.write_many`（全量预检、最多 20 变量、统一单次 `pump` 读回校验、`atomic=false`）+ `plc_write_pvi_batch` + `PviClient.write_many` 统一收口。

---

## 2. 自动化测试结果汇总

- **回归命令**：
  ```powershell
  cd C:\Users\BR\codex_ws\br_device_autodev
  .\.venv\Scripts\python.exe -m pytest -v > var\verification\phase2-20261126\pytest.log 2>&1
  .\.venv\Scripts\python.exe scripts\maintenance\generate_mcp_docs.py --check
  ```
- **测试统计**：
  - 基线用例数：248 passed（231 subtests）
  - 新增 Phase 2 专项用例：11 个（覆盖 `tests/test_project_topology.py`、`tests/test_runtime_variable_cache_and_expand.py`、`tests/test_pvi_write_batch.py`）
  - 最终全套回归结果：**259 passed, 0 failed, 0 skipped, 240 subtests passed**（耗时 `27.37s`，退出码 `0`）
- **MCP 文档同步检查**：`scripts/maintenance/generate_mcp_docs.py --check` 退出码 `0`（`README.md` 与 `schemas.py` 一致）。
- **原始日志路径**：`var/verification/phase2-20261126/pytest.log`

---

## 3. 端到端实测用例矩阵（本机真实工程 + 真实 ARsim）

所有 5 项实测均通过 `server.handle_tools_call` 走完整 MCP Schema 校验、锁控制与审计链路，原始结构化结果保存于 `var/verification/phase2-20261126/e2e_results.json`。

| Case ID | 验收项 | 操作步骤与关键参数 | 预期结果 | 实测结果摘要 | 耗时 | 判定 |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **P2-E2E-01** | AS6 复杂工程拓扑解析 | `plc_inspect_project(project_path=p106_at_auto_test_3, config="SecPackTest", include_files=true, check_integrity=true)` | 识别 `X20CP3687X`、全部 TaskClass 任务及源码路径，耗时 < 2s，无误报 | `family="AS6"`, `as_version="6.5.0.306"`, `cpu_type="X20CP3687X"`, `ar_version="6.7.8"`, `total_tasks=16`（8 enabled / 8 disabled）, `integrity.ok=true`（0 error / 0 warning） | 0.238 s | **PASS** |
| **P2-E2E-02** | AS4 工程拓扑与仿真 IP 识别 | `plc_inspect_project(project_path=p801_plc_debug_log/as-project, check_integrity=true)` | 识别 AS4 家族、`SimulationIPAddress` 与任务列表 | `family="AS4"`, `as_version="4.12.6.106"`, `cpu_type="X20CP3586"`, `simulation_ip="127.0.0.2"`（`is_default=false`）, `total_tasks=3`, `integrity.ok=true` | 0.123 s | **PASS** |
| **P2-E2E-03** | 在线变量分页缓存性能对比 | 在 `p106` ARsim（`127.0.0.9`）上对 `scope="global"` 连续读第 1、2、3 页（`limit=25`），再调 `refresh=true` | 第 2、3 页 `cache_hit=true` 且耗时低于第 1 页；`refresh=true` 触发重扫 | `total_matched=85`；Page 1: **5.01 ms** (`cache_hit=false`) → Page 2: **3.62 ms** (`cache_hit=true`) → Page 3: **3.56 ms** (`cache_hit=true`) → Refresh: **3.75 ms** (`cache_hit=false`)，`ttl=30.0s` | 15.94 ms | **PASS** |
| **P2-E2E-04** | 结构体展开与批量读取 | 对 `gAssembly`（`Assembly_typ`）调 `plc_get_runtime_variable_info(expand=true, max_depth=3, max_fields=64)`，取 16 个叶子喂给 `plc_read_pvi_batch`，并用 `PviClient.read_structure` 复测 | 正确展开叶子路径并全部读回有效值，标注 `expansion_source` | `expansion_source="pvi"`, `total_discovered=856`, `returned_fields=64`, `truncated=true`, 展开耗时 `258.24 ms`；`plc_read_pvi_batch` 16/16 读回 `ok=true`；`PviClient.read_structure` 32/32 `ok=true` | 4.46 s | **PASS** |
| **P2-E2E-05** | MCP 受控批量写与黑名单拦截 | 1) 批量写 `gAssembly.Ref` + `gAssembly.EnableSctrl`（写原值校验读回）；2) 混入黑名单变量 `IOModule:Index` 发起批量写并给第一个安全变量传变更值；3) `execute=false` | 用例 1 写入并读回 `verified=true` 且审计落盘；用例 2 整批预检拒绝且首变量值未变动；用例 3 拒绝 | 用例 1：`ok=true`, `atomic=false`, `verified=[true, true]`, 审计落盘（`728.21 ms`）；用例 2：`POLICY_DENIED`（`Variable matches the PVI write blacklist`），回读确认 `gAssembly.Ref` **未被修改**；用例 3：`POLICY_DENIED` | 1.03 s | **PASS** |

---

## 4. 故障注入与安全护栏验证结果

| 负面/安全场景 | 验证层级 | 实测结果 / 错误码 | 判定 |
| :--- | :--- | :--- | :---: |
| `Package.pkg` 悬空文件引用与重复对象 | 单测故障注入 | 检出 `MISSING_REFERENCED_FILE` 与 `DUPLICATE_PACKAGE_OBJECT` | **PASS** |
| `Cpu.sw` 指向不存在的 Logical 任务源 | 单测故障注入 | 检出 `BROKEN_TASK_SOURCE` | **PASS** |
| 损坏 XML（未闭合标签） | 单测故障注入 | 检出 `MALFORMED_XML` 且工具不崩溃 | **PASS** |
| `plc_write_pvi_batch` 超过 20 个变量（21 个） | 单测 | 拒绝写入（`ValueError: writes may contain at most 20 items`） | **PASS** |
| 批量写混入黑名单变量（`IOModule:Index` / `*Safety*`） | 实测 + 单测 | `POLICY_DENIED` 整批预检拒绝，前置合法变量零写入 | **PASS** |
| 批量写混入只读变量或结构体整体写（`dict`） | 单测故障注入 | 整批预检拒绝，前置合法变量零写入 | **PASS** |
| `plc_write_pvi_batch` 传 `execute=false` | 实测 + 单测 | `POLICY_DENIED`（拒绝写入） | **PASS** |
| `plc_write_pvi_batch` 指向 `role="production"` 目标 | 单测 | `PermissionError` 永久拒绝 | **PASS** |

---

## 5. 结构体展开能力实测边界说明（`pvipy==1.2.11`）

在真实 AS6 工程 `p106_at_auto_test_3`（`AR 6.7.8`、`pvipy==1.2.11`）上实测确认：
1. **已支持**：`pvipy` 在首次读取 `variable.dataType` / `isStructure` / `isArray` 时通过 `POBJ_ACC_TYPE_EXTERN` + `POBJ_ACC_TYPE_INTERN` 自动解析并展开结构体及其内部嵌套结构体/结构体数组，填充 `variable._struct_members`（例如 `gAssembly` 实测发现 `856` 个叶子字段），`max_depth` 与 `max_fields` 可有效截断超深/超大结构体，展开出的 `canonical` 路径可直接用于 `plc_read_pvi_batch` 与 `PviClient.read_structure`。
2. **已知边界**：
   - 对于 3 维及以上数组或 `pvipy` 未提供 `_struct_members` / `get_array_indices()` 的特殊/外部指针类型，返回 `expansion_source="unavailable"` 与明确提示 `expansion_note`，绝不伪造字段名；
   - 大型结构体首次批量读回时（如 16 个从未链接过的叶子变量）会逐个建立 PVI 链接并等待 `variable_link_wait_s`（约 `4.2 s`），后续重复读取复用已缓存变量句柄则明显更快。

---

## 6. 原始证据索引与环境收尾核查

- **自动化测试日志**：`var/verification/phase2-20261126/pytest.log`
- **端到端实测脚本与输出**：
  - `var/verification/phase2-20261126/run_phase2_e2e.py`
  - `var/verification/phase2-20261126/e2e_results.json`
  - `var/verification/phase2-20261126/e2e_stdout.log`
- **环境收尾核查日志**：`var/verification/phase2-20261126/cleanup_check.log`
- **关键审计记录（`var/audit/2026-11-26/`）**：
  - 安全批量写成功：`014116_722217_plc_write_pvi_batch_started_03c507c4.json`、`014117_161899_plc_write_pvi_batch_succeeded_420c4cc9.json`
  - 黑名单拦截拒绝：`014118_009972_plc_write_pvi_batch_started_171011db.json`、`014118_302372_plc_write_pvi_batch_failed_ec247895.json`
  - ARsim 停止与目录清理：`014122_930322_plc_manage_arsim_succeeded_baf9aa25.json`、`014123_845043_plc_manage_arsim_succeeded_b92916c2.json`
- **环境收尾核查结果**（见 `var/verification/phase2-20261126/cleanup_check.log`）：
  ```text
  === Get-Process ar000loader, ar000, PVITransfer ===
  (none)
  ```
  本次验收释放的 ARsim 实例（`d31ed63c...`）与临时运行目录均已通过 `plc_manage_arsim(stop/clean)` 彻底停止与删除，端口 `127.0.0.9:11169` 状态为 `free`，未修改 `p106_at_auto_test_3` 或 `p801_plc_debug_log` 的任何源码文件。
