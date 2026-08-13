# PLC 自动构建、下载、反馈验证工具链计划

## 目标

建立一套可由人、Codex、CI 或 MCP 调用的贝加莱 B&R Automation Studio 自动化工具链，用于：

1. 修改或生成 PLC 工程代码后自动构建。
2. 生成并定位 RUC Package / Transfer.pil。
3. 在安全边界内下载到 ARsim 或白名单测试 PLC。
4. 通过 OPC UA 优先、PVI 其次读取 PLC 反馈。
5. 输出机器可读和人工可读的验证报告。

## 已验证事实（路径脱敏）

- 项目入口：由调用方或 environment 显式提供的 `<project-root>/<project>.apj`；仓库不内置机器相关工程路径。
  - AS 工程版本：`6.5.0.306`
  - 构建配置：`Config1`
- Automation Studio 构建工具和 PVITransfer：通过 `config/toolchains/toolchains.json` 或未跟踪的 `config/local/toolchains.json` 显式配置。
- 构建命令已验证：
  - `BR.AS.Build.exe <apj> -c <config> -buildRUCPackage`
  - 日志结果：`Build: 0 error(s), 2 warning(s)`
  - 注意：进程 exit code 曾返回 `1`，因此构建结果必须解析日志中的 error 数。
- 生成 RUC 包：`<project-root>/Binaries/<config>/<CPU>/RUCPackage/` 下的 `RUCPackage.zip` 和 `Transfer.pil`。
- PVITransfer 静默调用方式已验证：
  - 使用 `-silent`
  - 使用日志文件作为输出来源
  - 使用 `Start-Process -WindowStyle Hidden` 避免 GUI 窗口弹出
  - 当前包装脚本：`scripts/windows/invoke-pvitransfer-silent.ps1`
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

1. 默认只允许 ARsim 或 `config/targets/default-safe.json` 中白名单目标。
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
7. M9：把 ARsim 下载从“命令成功”提升为可诊断、可恢复的部署闭环：
   - 下载前比较 RUC 与目标的 CPU、OrderNumber、RuntimeType、ARVersion、分区布局和安装模式。
   - 对 ARsim/测试 PLC 的兼容性差异输出告警，继续使用完整 RUC；production 与跨运行时类型下载仍阻止。
   - 对超时、取消和异常清理 PVITransfer 进程树，保留最后一段传输日志。
   - 将 `process_started`、`runtime_reachable` 和 `application_ready` 分开验证。
   - 补充下载阶段事件、应用 readiness、Logger 和工作树产物的结构化证据。

## 当前状态

已完成：

- 构建工具定位。
- PVITransfer 定位。
- PVITransfer 静默隐藏执行验证。
- 测试 PLC 只读探针验证。
- 当前 RUC 包与测试 PLC 不匹配的风险识别。
- ARsim 目标启动、探针、安全检查和一条兼容 RUC 下载路径已验证；分区不兼容、超时残留和应用未就绪等失败路径仍待 M9 完成。
- OPC UA 白名单读取验证。
- PVI 协议读取 ARsim 变量验证。
- M1：`plc_toolchain.ps1` 核心命令已统一为 MCP 友好的 JSON 输出和退出码。
- M2：MCP Server 第一批 8 个工具已实现并验证。
- M3：`br-plc-toolchain` Skill 已创建。
- M4：Prompt 模板已创建于 `prompts/plc_toolchain/`。
- M5：统一验证报告已实现，输出到 `var/reports/*.json`。
- 第二批 MCP 工具已实现：`plc_run_arsim_closed_loop`、`plc_run_verification_suite`、`plc_get_target_config`、`plc_list_targets`。

当前状态：

- M6 已完成：白名单 PVI 写入、输入输出断言、恢复动作和统一报告均已实现。
- M7 已完成：PVITransfer Logger 读取已实现并完成实机验证。
- M8 已完成第一版：无源码 PVI 发现、持久多目标连接、运行时读取、测试 profile、临时会话写入和写后回读。
- 下一阶段是把旧 PVI CLI 缩减为新运行时服务的兼容适配器，并扩展连接恢复与兼容性测试。
- M9 尚未完成：需要补齐完整 RUC 下载进程生命周期、实时进度和应用 readiness。

## ARsim 下载闭环

ARsim 目标配置：

- 目标名：`arsim`
- IP：`127.0.0.1`
- Loader：
  - 必须由本地环境配置提供实际 `ar000loader.exe` 路径，不再使用已删除项目的硬编码默认值。

已实现命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command StartArsim -Target arsim
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command Probe -Target arsim
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command CheckDownload -Target arsim
powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command Download -Target arsim -Execute
```

兼容目标上的历史验证结果：

- `StartArsim`：复用已运行的 `ar000loader.exe`。
- `Probe`：
  - `CPUType=X20CP3687X`
  - `SSWVersion=6.5.1`
  - `PLCStatus=WarmStart`
- `CheckDownload`：通过。
- `Download`：`Transfer "RUCPackage.zip" ... SUCCESSFUL`。
- 下载后再次 `Probe`：仍为 `X20CP3687X / 6.5.1 / WarmStart`。

这条成功记录不能代表所有 ARsim 都可直接安装 RUC。近期实际部署记录表明：

- RUC 构建为 `0 error` 不等于当前 ARsim 的分区布局满足安装要求。
- `Minimum requirements of partition layout failed` 会导致下载被拒绝或长时间等待；反复切换安装限制还可能把 ARsim 留在 `Service`。
- `PVITransfer.exe` 在 MCP 超时后可能继续运行，调用方看到失败时目标状态仍可能被后台进程改变。
- ARsim 进程启动不等于应用已进入 RUN；必须继续验证 PLC 状态、`bAlive`、接口版本和阶段标识。

因此，后续验收必须区分以下三个状态：

1. `process_started`：Loader 进程已经启动或被复用；
2. `runtime_reachable`：PVI/Probe 能连接并返回 CPU、AR 版本和运行状态；
3. `application_ready`：应用处于可测试状态，`bAlive=true`，接口版本和阶段标识与本次构建一致。

## M9 ARsim 下载可靠性与部署闭环（新增）

### 目标

把“Build 成功、Download 命令返回成功”改成可验证的部署状态机。工具链必须能够区分：

- 包本身构建失败；
- 包与目标 CPU/Runtime/分区不兼容；
- 传输正在进行或等待目标重启；
- 传输超时但后台进程仍在修改目标；
- ARsim 已启动但应用尚未进入可测试状态；
- 已完成部署并且应用身份与本次构建一致。

### P0：阻止错误下载和不确定状态

1. **完整下载前置检查**
   - 比较 RUC 的 `CPUType`、`OrderNumber`、`RuntimeType`、`ARVersion` 与目标 Probe 结果。
   - 增加分区布局和安装模式检查；不能因为目标是 ARsim 就跳过 CPU/版本兼容性检查。
   - 对 `Minimum requirements of partition layout failed` 建立明确的结构化错误分类。
   - 不兼容时不得自动轮换多个安装限制反复尝试；可信调试目标记录告警后仍只执行一次完整 RUC 传输。

2. **超时、取消和异常清理**
   - 为每次 PVITransfer 建立独立进程组，记录 PID、命令、包路径和目标。
   - MCP 超时、取消或异常时终止对应进程树，而不是只取消等待 Future。
   - 返回 `cleanup_attempted`、`cleanup_succeeded`、残留 PID 和最后一段传输日志。
   - 清理后重新 Probe；若结果不确定，标记为 `deployment_state=unknown`，禁止直接进入测试。

3. **部署后 readiness 验证**
   - `plc_start_arsim` 不得仅以 Loader 启动作为成功。
   - 按顺序验证 `process_started`、`runtime_reachable`、`application_ready`。
   - `application_ready` 至少要求 PLC 状态可接受、`bAlive=true`、接口版本正确、阶段标识与本次构建一致。

### P1：提高诊断能力和自动恢复边界

1. **下载阶段事件和日志尾部**
   - 统一输出 `Connected`、`PackageValidated`、`TargetEnteringService`、`Installing`、`Restarting`、`WaitingForReconnection`、`RunVerified`、`Failed` 等阶段。
   - 轮询或读取 PVITransfer 日志时返回阶段、时间戳和最后 N 行，避免 180 秒无反馈后才一次性超时。

2. **完整 RUC 下载能力**
   - MCP 只构建并传输完整 `RUCPackage.zip`，不实现 Automation Studio 增量 Transfer。
   - 遇到 PVI 11156 时补充目标任务状态、完整 RUC、运行时类型和替换限制诊断，不尝试单模块下载。

3. **输入和输出诊断**
   - 工程路径不存在时，在仓库根目录搜索 `.apj`；唯一候选只给出建议，多候选不得自动选择。
   - PVI 对象不存在时返回相似变量候选；可信调试目标不再产生白名单拒绝。
   - PVI/Reset 默认返回紧凑摘要，完整变量级结果写入报告文件。
   - 修正 CSVX 的 `Severity`、`Time`、`ASCII Data`、`TaskName` 和 `ErrorCode` 解析，并支持按测试时间窗统计 Error/Fatal。

### P2：提高可重复性和仓库卫生

1. 所有生成的 `.pil` 固定使用 CRLF、明确编码、逐条命令校验，并在执行前报告脚本路径。
2. 构建、下载、Simulation 和 Logger 产物统一写入 `var/` 或明确的忽略目录；执行前后返回 `generated_artifacts`、新增文件和修改文件清单。
3. 不因下载自动改写无关 Physical、Diagnosis 或用户文件；报告中记录实际修改范围。
4. 下载错误、目标状态、清理结果和 readiness 证据全部写入统一报告，供 MCP、CI 和人工复核使用。

### M9 验收标准

- 构建成功但分区布局不兼容时，工具在下载前明确阻止或要求用户选择策略，不进入盲目重试。
- 下载超时或取消后，对应 PVITransfer 进程树不残留；若无法确认清理，返回 `unknown` 并阻止后续测试。
- 下载过程至少能区分连接、校验、安装、重启、重连和失败阶段。
- Loader 启动、Runtime 可达和应用就绪分别返回，不把 `Service` 或 `bAlive=false` 报告为应用成功。
- 成功部署后能验证 CPU/Runtime/接口版本/阶段标识与本次构建一致。
- 失败报告包含目标 Probe、包描述、安装策略、PVITransfer 日志、Logger 摘要和下一步建议。
- 整个流程不误修改或提交无关的 Physical、Diagnosis 和用户文件。

## OPC UA 反馈验证

安全原则：

- 不默认开放全部 PLC 变量。
- `config/targets/default-safe.json` 中 `opcua.auto_expose_all=false` 为默认策略。
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

- `config/targets/default-safe.json` 中 `pvi.enabled=true` 控制是否启用 PVI 读取。
- `pvi.verify_after_download=false` 默认不在下载后自动运行 PVI；当前下载后默认仍优先运行 OPC UA。
- `pvi.validation_variables` 仅提供下载后的默认抽样变量；显式请求可读取任意 PVI 变量。
- PVI DLL 目录由全局 `toolchains.<id>.pvi.dll_dir` 指定，脚本会传入 `PVIPY_PVIDLLPATH`；targets 文件不再保存本机 DLL 路径。

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

## M6 输入输出测试（已实现）

### 目标

`ReadPvi` 和 `VerifyOpcUa` 只能证明变量存在、可读、下载后程序仍在运行；M6 已新增以下自动输入输出测试闭环：

```text
写入测试输入
-> 等待 PLC 执行若干周期
-> 读取输出和状态
-> 与期望值/容差比较
-> 输出 pass/fail 报告
-> 恢复测试变量到安全状态
```

### 已实现本地脚本

已实现：

- `tools/pvi_write.py`
  - 通过 PVI 写入变量。
  - 只接受已经过白名单校验的变量和值。
  - 返回每个变量的写入结果和 readback。
- `tools/plc_io_test_runner.py`
  - 读取 `tests/plc/*.json` 测试套件。
  - 执行写入、等待、读取、断言、恢复。
  - 输出统一 JSON 报告。

### 已实现 CLI 命令

`tools/plc_toolchain.ps1` 已提供：

| 命令 | 用途 |
|---|---|
| `WritePvi` | 对可信调试目标的任意 PVI 可写变量执行写入，必须 `-Execute` |
| `RunIoTestCase` | 执行单个输入输出测试用例 |
| `RunTestSuite` | 执行 JSON 测试套件 |
| `ResetTestHarness` | 恢复测试 harness 到安全状态 |

### 已实现 MCP 工具

MCP Server 已提供：

| 工具 | 用途 |
|---|---|
| `plc_write_pvi` | ARsim/测试 PLC 全量 PVI 写入 |
| `plc_run_io_test_case` | 单个输入输出测试 |
| `plc_run_test_suite` | 批量测试套件 |
| `plc_reset_test_harness` | 测试前后恢复 |

### 已实现配置扩展

`config/targets/default-safe.json` 中 PVI 配置已经扩展为：

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

### 测试套件目录（已实现）

已新增：

```text
tests/plc/
  lqr_io_tests.json
```

单个 case 格式：

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
var/reports/*_io_test_<suite>.json
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

## M7 Logger 日志读取（已实现，2026-05-26）

### 目标

将现有构建、下载、PVITransfer 本地日志能力扩展为 PLC/AR Logger 模块读取能力，用于诊断：

- 下载失败或下载后启动异常。
- WarmStart / ColdStart / Software Reset 等运行状态变化。
- Automation Runtime 系统告警。
- Connectivity / OPC UA / 网络相关运行问题。

### 实现内容

已新增：

- `tools/plc_logger_read.py`
  - 生成 PVITransfer `.pil` 脚本。
  - 调用 `scripts/windows/invoke-pvitransfer-silent.ps1`。
  - 校验 logger 模块白名单和输出格式。
  - 返回 output 路径、PVITransfer log 路径和错误摘要。
  - 默认输出到 `var/logger/`。
  - 对 `.csvx` 输出做轻量摘要解析；解析失败只返回 `summary_parse_error`，不影响读取结果。
- `tools/plc_toolchain.ps1 -Command ReadLogger`
  - CLI 统一入口。
  - 支持 `-Target`、`-LoggerType`、`-LoggerName`、`-Format`、`-OutputPath`。
- MCP 工具 `plc_read_logger`
  - 对 Agent / CI 暴露结构化只读诊断能力。
  - 不直接返回 HTML/CSV 正文，只返回路径、摘要、日志和下一步建议。

输出目录：

```text
var/logger/
```

### PVITransfer 命令

已验证的 PVITransfer Logger 命令格式：

```text
Logger "Logger module type", "Logger module name", "Output format", "Name of the output file", "Language"
```

首批支持：

```text
Logger "System", "$arlogsys", ".html", "<output>", "en"
Logger "User", "$arlogusr", ".csvx", "<output>", "en"
Logger "Connectivity", "$arlogconn", ".csvx", "<output>", "en"
```

可选输出格式：

- `.html`：人工诊断优先。
- `.csvx`：后续机器解析优先。
- `.arl`：Automation Studio 查看。
- `.logpkg`：完整包，适合归档。

### 配置

`config/targets/default-safe.json` 已扩展：

```json
{
  "logger": {
    "enabled": true,
    "default_format": ".html",
    "allowed_modules": [
      { "type": "System", "name": "$arlogsys" },
      { "type": "User", "name": "$arlogusr" },
      { "type": "Connectivity", "name": "$arlogconn" }
    ],
    "blocked_modules": [
      { "type": "Safety", "name": "$safety" }
    ]
  }
}
```

### 安全边界

- Logger 读取是只读能力，不需要 `execute=true`。
- 只允许读取 `logger.allowed_modules` 中的模块。
- 不提供清空、删除、修改 Logger 的能力。
- Safety logger 默认禁用；如未来需要，必须单独设计显式确认和审计流程。
- 生产目标默认不自动读取；如需现场诊断，应先明确目标角色和授权方式。
- 输出文件必须写入 `var/logger/` 或调用方显式指定的仓库内路径。

### 验收标准

- ✅ `ReadLogger -Target test_plc -LoggerType System -LoggerName '$arlogsys' -Format .html` 可生成日志文件。
- ✅ MCP `plc_read_logger` 返回稳定 JSON，至少包含 `ok`、`target`、`logger_type`、`logger_name`、`output_path`、`log_path`。
- ✅ `Safety / $safety` 和不在白名单内的 logger 模块返回 `ok=false` 和清晰错误摘要。
- ✅ `.csvx` 输出可选解析为 JSON 摘要，包含日志条目、等级计数和最近时间戳；解析失败不导致读取失败。
- ✅ 任何实际 PVITransfer 调用都会保留 PVITransfer 日志，便于追溯。

### 验证记录

- 验证日期：2026-05-26
- 目标：`test_plc` (`192.168.50.222`)
- 读取模块：`System / $arlogsys`
- 输出格式：`.html`
- 结果：成功读取 26 条 System logger 记录。
- 严重等级统计：`Info=17`、`Warning=2`、`Success=7`
- 详细报告：`docs/PLC_LOGGER_READ_TEST_REPORT.md`
