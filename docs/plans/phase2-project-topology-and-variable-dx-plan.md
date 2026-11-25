# Phase 2 修改计划：AS 工程拓扑解析、结构体变量展开与在线调试效率优化

状态：待实施。本文档仅描述拟议修改与验收标准，不代表相关能力已上线。  
前置依赖：建议在完成 [Phase 1](phase1-runtime-lifecycle-and-diagnostics-plan.md) 后实施。  
预计交付版本：`0.17.0a1`

---

## 1. 背景与改造目标

在复杂 Automation Studio 工程（如 `p106_at_auto_test_3` 这类多任务、多小车数组、嵌套结构体工程）中，AI 当前仍存在 4 类高频摩擦：
1. **读工程全靠手工翻 XML**：每次接手工程都要顺着 `.apj` → `Physical.pkg` → `Config.pkg` → `Cpu.pkg` → `Cpu.sw` → `Package.pkg` → `IEC.prg` 逐层读取七八个文件，耗费大量工具往返与上下文，且修改工程文件后缺少编译前的快速静态完整性自检。
2. **在线变量翻页重复全量扫描**：`plc_list_runtime_variables` 每翻一页都会重新扫描一次完整 PLC 变量表，大工程翻页延迟高。
3. **结构体与数组成员无法直接展开**：`plc_search_variables` 明确不展开结构体字段和数组元素，`pvipy` 不支持结构体整体写，AI 查复杂结构体时只能回去人工解析 `.typ` 拼变量路径。
4. **MCP 层缺少批量写入入口**：虽然 `PviClient.write_many` 已支持批量写，但在交互式调试中，AI 想一次性写 3~5 个参数时仍不得不串行多次调用 `plc_write_runtime_variable`（每次硬等 50 ms）或临时写 Python 脚本。

本阶段完成上述 **4 项开发体验与工程理解能力**（新增 2 个高内聚 MCP 工具 + 增强 2 个现有工具）。

---

## 2. 现网代码基线核对

| 模块 | 现有文件 | 现状与限制 |
| :--- | :--- | :--- |
| 工程与符号索引 | `tools/plc_symbol_index.py`<br>`tools/mcp_server/catalog_watch.py` | 仅做变量名目录索引与后台缓存刷新，不解析 `Cpu.sw` 任务拓扑、不校验 `.pkg`/`.prg` 悬空引用、不展开结构体成员 |
| PVI Worker | `src/br_plc_toolchain/backends/pvi/worker.py` | `_list_variables` 每次调用都执行 `_read_variable_names(parent)` 全量拉取；`_variable_info` 返回 `descriptor` 但未展开子字段；`_write_many` 已存在但未在 MCP 暴露 |
| 运行时服务与 SDK | `src/br_plc_toolchain/services/runtime_pvi.py`<br>`src/br_plc_toolchain/client.py` | `RuntimePviService` 仅暴露单点 `write`，未暴露 `write_many`（`PviClient.write_many` 是在客户端循环调 `service.write`） |
| 策略与权限 | `src/br_plc_toolchain/policy/runtime.py`<br>`tools/mcp_server/locks.py` | `RuntimePolicy.authorize_write` 已支持通配符与结构体前缀匹配（`name.`、`name[`） |

---

## 3. 详细实施方案

### 3.1 AS 工程拓扑只读解析与静态自检（`plc_inspect_project`）

1. **新建工程拓扑模块 `src/br_plc_toolchain/project/topology.py`**
   - 纯 Python 标准库（`xml.etree.ElementTree`）实现，不依赖 `BR.AS.Build.exe`，秒级返回：
     - **工程摘要**：`.apj` 路径、AS 主版本（AS4/AS6）、默认/指定 Config、全部可用 Config 列表；
     - **CPU 与硬件摘要**：解析 `Physical/<Config>/Config.pkg` → `<CPU>/Cpu.pkg` & `Hardware.hw`，提取 CPU 型号、AR 版本、仿真 IP（`SimulationIPAddress`，含是否缺省为 `127.0.0.1` 的标注）、是否包含 Safety 硬件/配置节点（`has_safety_hardware: bool`）；
     - **任务拓扑（`Cpu.sw`）**：按 `TaskClass`（Cyclic#1 ~ #8 等）列出全部 `TaskObject`，包含任务名、启用/禁用状态（`Memory` / `Language` / `Debugging` / `Disabled`）、`Source` 逻辑路径，并沿 `Logical/**/Package.pkg` 解析出实际物理源码目录与 `IEC.prg` 中列出的源码文件（`.st` / `.c` / `.cpp` / `.var` / `.typ`）；
     - **全局声明索引**：列出 `Logical/Global.var`、`Logical/Global.typ` 及各一级包的 `.var`/`.typ` 路径。
2. **内置静态完整性自检模式（`check_integrity: bool = True`）**
   - 检查以下常见人工/AI 改工程事故，输出结构化 `issues` 列表（`severity`, `file`, `code`, `message`）：
     - XML 格式损坏或无法解析的 `.apj` / `.pkg` / `.prg` / `.sw` / `.hw`；
     - `Package.pkg` / `IEC.prg` 中声明了但磁盘上不存在的**悬空引用**（`MISSING_REFERENCED_FILE`）；
     - `Cpu.sw` 中 `Source` 指向不存在的 Logical 对象（`BROKEN_TASK_SOURCE`）；
     - 同一 `Package.pkg` 内重复对象名（`DUPLICATE_PACKAGE_OBJECT`）；
     - 关键 XML 文件编码异常或异常 BOM 损坏检测。
3. **新增只读 MCP 工具 `plc_inspect_project`**
   - 参数：`project_path`、`config`（可选）、`include_files: bool = False`（默认返回任务级摘要控制输出体积，设为 `true` 返回每个任务的源码文件列表）、`check_integrity: bool = True`。
   - 风险级别：`readonly`。

### 3.2 在线变量扫描短时缓存与分页提速

1. **改造 `src/br_plc_toolchain/backends/pvi/worker.py`**
   - 在 `PviWorker` 中增加按 `(scope, task)` 索引的在线变量名列表缓存：`_var_list_cache: dict[tuple[str, str | None], tuple[float, list[str]]]`（默认 TTL = `30.0` 秒）。
   - `_list_variables(..., refresh: bool = False)`：
     - 命中有效缓存时直接做 `fnmatch` 过滤和切片分页，返回 `cache_hit: true`、`cached_at`、`cache_ttl_seconds`；
     - `refresh=True`、缓存过期、或目标发生重启/重连（`_on_cpu_error` / `_restart`）时自动失效缓存并重新全量扫描；
     - 返回中显式保留 `total_matched`、`offset`、`limit`、`has_more`，避免 AI 多翻空页。
2. **透传 `refresh` 参数**：在 `RuntimePviService.list_variables`、`PviClient.list_variables` 与 MCP 工具 `plc_list_runtime_variables` 中新增可选 `refresh: bool = False`。

### 3.3 结构体 / 数组叶子展开辅助（增强 `plc_get_runtime_variable_info` 与 `PviClient`）

1. **在线结构体展开（`src/br_plc_toolchain/backends/pvi/worker.py`）**
   - 在 `_variable_info(ref, expand: bool = False, max_depth: int = 3, max_fields: int = 128)` 中：
     - 当 `expand=True` 且变量为结构体（`is_structure=True`）或数组（`is_array=True`）时，利用 `pvipy` 变量描述符/子成员信息（或枚举其直接成员路径）递归展开至 `max_depth`，输出最多 `max_fields` 个可独立读写的叶子变量路径（`canonical`、`data_type`、`readable`、`writable`），超出时返回 `truncated: true` 和 `total_discovered`；
     - 若某版本 `pvipy` 对结构体 `descriptor` 不提供子字段清单，则优雅降级为结合工程 `.typ`/生成头信息的只读解析建议，并明确标注 `expansion_source: "pvi" | "project_type" | "unavailable"`，绝不伪造字段名。
2. **SDK 便利方法（`src/br_plc_toolchain/client.py`）**
   - 新增 `PviClient.expand_variable(variable, *, max_depth=3, max_fields=128)` 与 `PviClient.read_structure(variable, *, max_depth=2, max_fields=128)`（先展开叶子路径再走 `read_chunked` 返回字典/列表快照）。

### 3.4 MCP 受控批量写（`plc_write_pvi_batch`）

1. **服务层统一收口（`src/br_plc_toolchain/services/runtime_pvi.py`）**
   - 新增 `RuntimePviService.write_many(target_name, writes, *, execute, stop_on_error=True, readback_wait_ms=50)`：
     - 上限 `MAX_WRITE_BATCH = 20`（与 `config/defaults/base.json` 的 `runtime.max_write_batch` 对齐）；
     - **先全量预检，再执行写入**：逐项校验变量名解析、可写性、类型转换（拒绝结构体整体写）和 `RuntimePolicy.authorize_write`；任意一项预检不通过则**整批拒绝，不写入任何变量**（避免写一半被策略拦截留下半脏状态）；
     - 全部预检通过且 `execute=true` 后依次写入，并在整批写完后统一 `pump` 一次 + 逐项读回校验（避免 20 个变量硬睡 `20 * 50ms = 1s`），返回每项的 `before` / `requested` / `readback` / `verified` 以及 `atomic: false` 显式声明。
2. **暴露 MCP 工具 `plc_write_pvi_batch`**
   - 风险级别：`target_change`，受 `target:*` 锁、频率限制与审计记录保护，要求显式 `target` 与 `execute=true`。
   - `PviClient.write_many` 同步复用 `RuntimePviService.write_many`，消除重复逻辑。

### 3.5 文档与 Skill 同步

- 运行 `scripts/maintenance/generate_mcp_docs.py` 更新 `README.md`；
- 更新 `.agents/skills/br-plc-toolchain/SKILL.md`，明确“首次接手工程优先调用 `plc_inspect_project`；改完 `.pkg`/`.prg`/`.sw` 后先做静态校验再编译；多参数下发优先用 `plc_write_pvi_batch`”。

---

## 4. 自主开发测试与验收规程（必须全部执行）

### 4.1 自动化单元测试与故障注入（`pytest`）

新增并运行以下测试文件，确保全套回归 100% 通过：

1. **`tests/test_project_topology.py`**
   - 使用构造的 AS4 与 AS6 样例工程目录验证 `.apj`、多 Config、`Cpu.sw` 启用/禁用任务、`Hardware.hw` 的 `SimulationIPAddress` 与 Safety 节点识别；
   - **静态自检负面用例**：
     - 注入悬空 `Package.pkg` 引用 → 检出 `MISSING_REFERENCED_FILE`；
     - 注入 `Cpu.sw` 错误 `Source` → 检出 `BROKEN_TASK_SOURCE`；
     - 注入损坏 XML → 检出明确 XML 解析错误且不崩溃。
2. **`tests/test_runtime_variable_cache_and_expand.py`**
   - 验证 `list_variables` 连续翻页仅触发 1 次底层扫描（`cache_hit=True`），`refresh=True`、TTL 过期和重启事件正确触发刷新；
   - 验证结构体与数组 `expand=True` 的深度限制（`max_depth`）、数量截断（`max_fields`）及不可展开时的降级标记。
3. **`tests/test_pvi_write_batch.py`**
   - 验证 1~20 个变量正常批量写入与统一读回校验，第 21 个变量拒绝；
   - **预检全拒绝测试**：批量中第 3 个变量命中黑名单或为只读变量时，前 2 个合法变量**绝不能被写入**；
   - 验证 `execute=false` 与 `production` 角色拒绝；
   - 验证 `PviClient.write_many` 与 MCP `plc_write_pvi_batch` 行为一致。
4. **全套回归命令**：
   ```powershell
   cd C:\Users\BR\codex_ws\br_device_autodev
   .\.venv\Scripts\python.exe -m pytest -v > var\verification\phase2-YYYYMMDD\pytest.log 2>&1
   .\.venv\Scripts\python.exe scripts\maintenance\generate_mcp_docs.py --check
   ```

### 4.2 本机真实工程与 ARsim 端到端实测验收

使用本机真实 AS6 工程（`C:\Users\BR\codex_ws\p106_at_auto_test_3`）与 AS4 工程（`C:\Users\BR\codex_ws\p801_plc_debug_log`）执行以下 5 项实测：

| Case ID | 验收项 | 操作步骤 | 通过标准 |
| :--- | :--- | :--- | :--- |
| **P2-E2E-01** | AS6 复杂工程拓扑解析 | 对 `p106_at_auto_test_3` 调 `plc_inspect_project(config="SecPackTest", check_integrity=true)` | 正确识别 `X20CP3687X`、全部 TaskClass 任务及源码路径，耗时 < 2 秒，无误报 |
| **P2-E2E-02** | AS4 工程拓扑与仿真 IP 识别 | 对 `p801_plc_debug_log` 调 `plc_inspect_project(check_integrity=true)` | 正确识别 AS4 家族、`SimulationIPAddress` 与任务列表 |
| **P2-E2E-03** | 在线变量分页缓存性能对比 | 在运行中 ARsim 上对 `plc_list_runtime_variables` 连续读取第 1、2、3 页，并测一次 `refresh=true` | 第 2、3 页返回 `cache_hit=true`，响应耗时显著低于第 1 页（记录具体毫秒数） |
| **P2-E2E-04** | 结构体展开与批量读取 | 对 `p106` 中一个非空结构体/控制接口变量调 `plc_get_runtime_variable_info(expand=true)`，并将返回的叶子路径喂给 `plc_read_pvi_batch` | 正确展开叶子变量并全部读回有效值，记录 `expansion_source` |
| **P2-E2E-05** | MCP 受控批量写与黑名单拦截 | 在本机 ARsim 上：1) 批量写 2~3 个安全测试变量（先读再写同值或可逆测试值并还原）；2) 混入 1 个黑名单变量（如 `*Safety*` 或 `gIOCtrl*`）发起批量写 | 用例 1 全部写入并读回匹配且审计落盘；用例 2 整批预检拒绝，所有变量值未被改动 |

### 4.3 必须交付的完整验收报告

实施完成后，生成 `docs/verification/phase2-verification-YYYYMMDD.md`，并将原始输出保存到 `var/verification/phase2-YYYYMMDD/`，报告必须包含：
1. **自动化测试统计**：总用例数、新增用例数、通过/失败数、`pytest.log` 路径、`generate_mcp_docs.py --check` 结果。
2. **P2-E2E-01 ~ P2-E2E-05 实测矩阵**：含每项实测耗时（含分页缓存前后毫秒级对比数据）、返回关键字段摘要、审计路径与 PASS/FAIL 判定。
3. **结构体展开能力实测边界说明**：如实记录本机 `pvipy==1.2.11` 对不同嵌套层级/数组类型的展开实测表现与限制。
4. **环境收尾核查**：确认未改动 `p106`/`p801` 工程源码，验收用 ARsim 实例按规范停止或恢复原状。
