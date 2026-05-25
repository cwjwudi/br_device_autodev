# PLC 自动构建、下载、反馈验证工具链计划

## 目标

建立一套可由人、Codex、CI 或 MCP 调用的贝加莱 B&R Automation Studio 自动化工具链，用于：

1. 修改或生成 PLC 工程代码后自动构建。
2. 生成并定位 RUC Package / Transfer.pil。
3. 在安全边界内下载到 ARsim 或白名单测试 PLC。
4. 通过 OPC UA 优先、PVI 其次读取 PLC 反馈。
5. 输出机器可读和人工可读的验证报告。

## 已验证事实

- 项目入口：
  - `PrintDemo/Huitong_FrontEval.apj`
  - AS 工程版本：`6.5.0.306`
  - 构建配置：`Config1`
- Automation Studio 构建工具存在：
  - `D:\BRAutomation\AS65\AS6\bin-en\BR.AS.Build.exe`
- AS6.5 对应 PVITransfer 存在：
  - `D:\BRAutomation\AS65\PVI6\PVI\Tools\PVITransfer\PVITransfer.exe`
- 构建命令已验证：
  - `BR.AS.Build.exe <apj> -c Config1 -buildRUCPackage`
  - 日志结果：`Build: 0 error(s), 2 warning(s)`
  - 注意：进程 exit code 曾返回 `1`，因此构建结果必须解析日志中的 error 数。
- 生成 RUC 包：
  - `PrintDemo/Binaries/Config1/X20CP3687X/RUCPackage/RUCPackage.zip`
  - `PrintDemo/Binaries/Config1/X20CP3687X/RUCPackage/Transfer.pil`
- PVITransfer 静默调用方式已验证：
  - 使用 `-silent`
  - 使用日志文件作为输出来源
  - 使用 `Start-Process -WindowStyle Hidden` 避免 GUI 窗口弹出
  - 当前包装脚本：`tools/invoke_pvitransfer_silent.ps1`
- PVITransfer `.pil` 文件需要 Windows CRLF 换行；否则多行命令可能被当成一条指令。
- `-Conn:"'device', 'cpu', 'WT=...', 'IGNORE'"` 可覆盖 `.pil` 内部 `Connection` 指令。
- 只读探针已验证历史测试 PLC：
  - IP：`192.168.50.233`
  - CPU：`X20CP1586`
  - AR：`J4.93`
  - 状态：`WarmStart`
- 当前配置的测试 PLC：
  - IP：`192.168.50.222`
  - 目标名：`test_plc`
  - 角色：`dedicated_test_plc`
  - 只读探针已验证：`X20CP1685 / 6.5.1 / WarmStart`
- 当前构建出的 RUC 包是 ARsim 包：
  - `CPUType=AR000`
  - `RuntimeType=AR Simulation`
  - `ARVersion=6.5.1`
  - `OrderNumber=X20CP3687X`
- 因此当前 RUC 包不能直接下载到 `192.168.50.233`，需要先生成匹配测试 PLC 的真实目标包，或仅下载到 ARsim。

## 安全边界

1. 默认只允许 ARsim 或 `tools/plc_targets.local.json` 中白名单目标。
2. 即使目标配置 `allow_auto_download=true`，下载前也必须执行只读探针。
3. 下载前必须比较：
   - RUC 包 `CPUType` / `OrderNumber` / `RuntimeType` / `ARVersion`
   - 目标 PLC `CPUType` / `SSWVersion` / `PLCStatus`
4. 生产 PLC 一律禁止自动下载，除非用户明确确认并提供目标名。
5. 不自动修改 Safety 工程、安全任务、安全 I/O。
6. 自动化下载必须保留日志与报告。

## 分层方案

MCP / Skill / Prompt 的详细落地路线见：

- `docs/PLC_MCP_SKILL_PROMPT_ROADMAP.md`

### 第 1 层：本地 CLI / 脚本

核心能力应先做成本地脚本，便于人工、Codex、CI 和 MCP 复用。

计划入口：

- `tools/plc_toolchain.ps1`

计划命令：

- `Build`：调用 `BR.AS.Build.exe` 构建并解析错误数。
- `Probe`：生成临时 `.pil` 并用 PVITransfer 只读读取 CPU/AR/状态。
- `DescribePackage`：读取 RUC 包中的 `ProjectInformation.xml`。
- `CheckDownload`：比较 RUC 包与目标 PLC，输出安全判定。
- `Download`：在安全判定通过后执行 RUC 下载。
- `VerifyOpcUa`：读取 OPC UA 白名单节点，作为首选反馈验证。
- `ReadPvi`：通过 hilch/Pvi.py 读取 PVI 变量，作为 OPC UA 的补充或备用反馈验证。

### 第 2 层：Skill

Skill 用来写 Agent 工作规范，不承载复杂执行逻辑。

内容包括：

- 处理构建/下载/验证前必须阅读上下文文档。
- 下载前必须先 `Probe` 和 `CheckDownload`。
- PVITransfer 必须使用 hidden wrapper。
- 构建结果按日志 error 数判定，不只看 exit code。
- 生产 PLC 必须人工确认。

### 第 3 层：MCP Server

MCP 用于把本地 CLI 封装成结构化工具：

- `plc_build_project`
- `plc_probe_target`
- `plc_describe_ruc_package`
- `plc_check_download`
- `plc_download_ruc`
- `plc_read_opcua_nodes`
- `plc_read_pvi_variables`
- `plc_run_verification_suite`

MCP 只做结构化参数、调用 CLI、返回 JSON；核心逻辑仍放在本地脚本/库。

### 第 4 层：提示词

提示词仅作为临时操作指导或 Skill 的补充，不作为工具链主体。

## 执行计划

1. 创建计划文档。
2. 实现 `tools/plc_toolchain.ps1` 第一版：
   - `Build`
   - `Probe`
   - `DescribePackage`
   - `CheckDownload`
3. 用当前工程执行本地构建验证。
4. 对 `test_plc` 执行只读探针。
5. 对当前 RUC 包执行描述与下载安全检查。
6. 根据检查结果决定下一步：
   - 若目标为 ARsim，则继续完善 ARsim 下载与 OPC UA 验证。
   - 若目标为测试 PLC，则先生成匹配 `X20CP1586 / J4.93` 的工程配置和 RUC 包。

## 当前状态

已完成：

- 构建工具定位。
- PVITransfer 定位。
- PVITransfer 静默隐藏执行验证。
- 测试 PLC 只读探针验证。
- 当前 RUC 包与测试 PLC 不匹配的风险识别。
- ARsim 目标启动、探针、安全检查和 RUC 下载闭环验证。
- OPC UA 白名单读取验证。
- PVI 协议读取 ARsim 变量验证。
- M1：`plc_toolchain.ps1` 核心命令已统一为 MCP 友好的 JSON 输出和退出码。
- M2：MCP Server 第一批 8 个工具已实现并验证。
- M3：`br-plc-toolchain` Skill 已创建。
- M4：Prompt 模板已创建于 `prompts/plc_toolchain/`。
- M5：统一验证报告已实现，输出到 `tools/.generated/reports/*.json`。
- 第二批 MCP 工具已实现：`plc_run_arsim_closed_loop`、`plc_run_verification_suite`、`plc_get_target_config`、`plc_list_targets`。

下一步：

- M6：实现输入输出测试闭环，让工具链能证明 PLC 程序行为正确，而不仅是变量可读。
- 对 LQR 等控制程序，使用 PVI 白名单写入测试输入，等待 PLC 周期执行，再读取输出并做容差断言。
- 所有写入只允许测试 harness 白名单变量，不写 Safety、物理 I/O、系统变量或生产 PLC。

## ARsim 下载闭环

ARsim 目标配置：

- 目标名：`arsim`
- IP：`127.0.0.1`
- Loader：
  - `PrintDemo/Temp/Simulation/Config1/X20CP3687X/ar000loader.exe`

已实现命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command StartArsim -Target arsim
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command Probe -Target arsim
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command CheckDownload -Target arsim
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command Download -Target arsim -Execute
```

最新验证结果：

- `StartArsim`：复用已运行的 `ar000loader.exe`。
- `Probe`：
  - `CPUType=X20CP3687X`
  - `SSWVersion=6.5.1`
  - `PLCStatus=WarmStart`
- `CheckDownload`：通过。
- `Download`：`Transfer "RUCPackage.zip" ... SUCCESSFUL`。
- 下载后再次 `Probe`：仍为 `X20CP3687X / 6.5.1 / WarmStart`。

## OPC UA 反馈验证

安全原则：

- 不默认开放全部 PLC 变量。
- `tools/plc_targets.local.json` 中 `opcua.auto_expose_all=false` 为默认策略。
- 推荐使用 `opcua.exposure_mode=whitelist`，只暴露验证所需变量。
- 下载后自动验证由 `opcua.verify_after_download=true` 控制。

当前已验证的 OPC UA endpoint：

- `opc.tcp://127.0.0.1:4840`

当前白名单验证节点：

- `ns=5;s=::AsGlobalPV:gstHmi.stOutputs.diSImage`
- `ns=5;s=::AsGlobalPV:gstHmi.stOutputs.diPuWindowIntervalmm`
- `ns=5;s=::AsGlobalPV:gstHmi.stConfig.strPuChartAdr`
- `ns=5;s=::AsGlobalPV:gstMainInface.stFromMain.diSImage`
- `ns=5;s=::AsGlobalPV:gstMainInface.stToMain.usiActivePU`
- `ns=5;s=::SVG:strTransform`

已实现命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command VerifyOpcUa -Target arsim
```

验证结果：

- 所有白名单节点读取成功。
- `gstHmi.stOutputs.diSImage=600`
- `gstHmi.stConfig.strPuChartAdr=http://127.0.0.1`
- `SVG:strTransform` 可读并返回 SVG 指令 JSON 字符串。

当前 `Download -Execute` 在下载成功后会根据配置自动运行 OPC UA 验证。

## PVI 反馈验证

使用场景：

- PVI 作为 OPC UA 后备通道；当客户设备不允许开放 OPC UA 变量时，仍可读取必要验证变量。
- PVI 也适合读取 CPU 状态、任务变量、全局变量等 Automation Runtime 诊断信息。

实现方式：

- Python 包：`pvipy`，导入名为 `pvi`。
- 本地脚本：`tools/pvi_read.py`
- 工具链命令：`tools/plc_toolchain.ps1 -Command ReadPvi`
- PVI 对象链路：`Connection -> Line(LNANSL) -> Device(TCP) -> Cpu -> Variable/Task -> Variable`

安全与配置：

- `tools/plc_targets.local.json` 中 `pvi.enabled=true` 控制是否启用 PVI 读取。
- `pvi.verify_after_download=false` 默认不在下载后自动运行 PVI；当前下载后默认仍优先运行 OPC UA。
- `pvi.validation_variables` 使用白名单变量，不做“读取全部变量”的默认行为。
- 如需指定 PVI DLL 目录，可设置 `pvi.pvi_dll_dir`，脚本会传入 `PVIPY_PVIDLLPATH`。

当前已验证的 PVI 读取：

- 目标：`arsim`
- IP：`127.0.0.1`
- CPU 状态：`WarmStart / RUN`
- 全局变量：
  - `gstHmi.stOutputs.diSImage=600`
  - `gstHmi.stConfig.strPuChartAdr=http://127.0.0.1`
  - `gstMainInface.stToMain.usiActivePU=88`
- 任务变量：
  - `SVG:strTransform` 可读并返回 SVG 指令 JSON 字符串。

已实现命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command ReadPvi -Target arsim
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command ReadPvi -Target arsim -PviVariable 'gstHmi.stOutputs.diSImage,SVG:strTransform'
```

## M6 输入输出测试计划

### 目标

当前 `ReadPvi` 和 `VerifyOpcUa` 只能证明变量存在、可读、下载后程序仍在运行。下一步需要新增自动输入输出测试能力：

```text
写入测试输入
-> 等待 PLC 执行若干周期
-> 读取输出和状态
-> 与期望值/容差比较
-> 输出 pass/fail 报告
-> 恢复测试变量到安全状态
```

### 新增本地脚本

建议新增：

- `tools/pvi_write.py`
  - 通过 PVI 写入变量。
  - 只接受已经过白名单校验的变量和值。
  - 返回每个变量的写入结果和 readback。
- `tools/plc_io_test_runner.py`
  - 读取 `tests/plc/*.json` 测试套件。
  - 执行写入、等待、读取、断言、恢复。
  - 输出统一 JSON 报告。

### 新增 CLI 命令

建议在 `tools/plc_toolchain.ps1` 中新增：

| 命令 | 用途 |
|---|---|
| `WritePvi` | 对白名单变量执行 PVI 写入，必须 `-Execute` |
| `RunIoTestCase` | 执行单个输入输出测试用例 |
| `RunTestSuite` | 执行 JSON 测试套件 |
| `ResetTestHarness` | 恢复测试 harness 到安全状态 |

### 新增 MCP 工具

建议在 MCP Server 中新增：

| 工具 | 用途 |
|---|---|
| `plc_write_pvi` | 白名单 PVI 写入 |
| `plc_run_io_test_case` | 单个输入输出测试 |
| `plc_run_test_suite` | 批量测试套件 |
| `plc_reset_test_harness` | 测试前后恢复 |

### 配置扩展

建议把 `tools/plc_targets.local.json` 中 PVI 配置扩展为：

```json
{
  "pvi": {
    "enabled": true,
    "read_whitelist": [],
    "write_whitelist": [],
    "restore_writes": []
  }
}
```

写入白名单只放测试 harness 输入变量，例如 LQR：

- `LQR:bLqrEnable`
- `LQR:bLqrReset`
- `LQR:arLqrX`
- `LQR:arLqrXRef`
- `LQR:arLqrK`
- `LQR:rLqrMaxAbsU`

输出变量只读，不写：

- `LQR:arLqrU`
- `LQR:arLqrError`
- `LQR:stLqrStatus`

### 测试套件目录

建议新增：

```text
tests/plc/
  lqr_io_tests.json
```

单个 case 建议格式：

```json
{
  "name": "nominal_tracking_error",
  "target": "test_plc",
  "settle_ms": 100,
  "writes": [
    { "variable": "LQR:bLqrEnable", "value": true },
    { "variable": "LQR:arLqrX", "value": [1.0, 0.0, -2.0, 0.5] },
    { "variable": "LQR:arLqrXRef", "value": [0.0, 0.0, 0.0, 0.0] },
    { "variable": "LQR:arLqrK", "value": [2.0, 0.4, 0.0, 0.0, 0.0, 0.0, 2.0, 0.4] }
  ],
  "readback": [
    "LQR:arLqrU",
    "LQR:arLqrError",
    "LQR:stLqrStatus"
  ],
  "checks": [
    { "variable": "LQR:arLqrU[0]", "expected": -2.0, "tolerance": 0.001 },
    { "variable": "LQR:arLqrU[1]", "expected": 3.8, "tolerance": 0.001 },
    { "variable": "LQR:stLqrStatus.usiErrorCode", "expected": 0 }
  ]
}
```

### LQR 首批测试场景

1. `zero_state_zero_output`
   - 零状态、零参考、启用控制。
   - 期望 `arLqrU=[0,0]`，`bValid=true`。
2. `nominal_tracking_error`
   - 给定非零状态和增益。
   - 期望 `u = -K * (x - x_ref)`。
3. `saturation_limit`
   - 设置较小 `rLqrMaxAbsU`。
   - 期望输出被限幅，`bSaturated=true`，`usiErrorCode=2`。
4. `disabled_zero_output`
   - `bLqrEnable=false`。
   - 期望输出清零，`bValid=false`。
5. `reset_clears_output`
   - `bLqrReset=true`。
   - 期望输出和误差清零。

### 报告

报告路径：

```text
tools/.generated/reports/*_io_test_<suite>.json
```

报告必须包含：

- 构建结果和 RUC 包信息。
- 目标探针和下载安全检查。
- 每个 case 的写入值、readback、实际值、期望值、容差、pass/fail。
- restore/reset 是否成功。
- 失败原因和下一步建议。

### M6 验收标准

- `plc_run_test_suite(target="test_plc", suite="tests/plc/lqr_io_tests.json", execute=true)` 可完整运行。
- 所有写变量都来自 `pvi.write_whitelist`。
- 任一 case 失败时套件返回 `ok=false`，同时保留完整报告。
- 测试结束后执行 restore/reset。
- 禁止写生产 PLC、Safety、物理 I/O 和系统变量。
