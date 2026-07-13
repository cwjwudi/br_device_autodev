# PLC Skill / MCP 工具链下一阶段开发 PLAN

生成日期：2026-06-24

本文件用于指导本地开发 Agent 改进 `br_device_autodev` 中的 Skill、MCP Server、CLI 封装、配置、文档和测试。重点是工具链治理，不是修改 `PrintDemo` 示例工程。

## 总目标

把当前工具链从“可用的本地脚本集合”升级为“接口稳定、安全边界清晰、可测试、可审计、可团队部署的 PLC Agent 工具平台”。

## 最高优先级

1. 统一 MCP 工具契约。
2. 同步 Skill、AGENTS、README、Roadmap 文档。
3. MCP Server 增加服务端参数校验。
4. 统一安全策略实现，避免 Python 与 PowerShell 行为漂移。
5. 收紧默认配置，开放模式必须显式选择。
6. 对会改变工程或目标状态的工具增加锁、审计和报告。

## 推荐执行顺序

1. 增加 MCP contract 测试。
2. 生成或维护统一工具清单。
3. 精简 Skill 主文件，把完整工具表移入 reference。
4. 增加 MCP schema 服务端校验。
5. 拆分 dev / test / readonly 配置模板。
6. 统一默认 target 语义。
7. 统一 access_policy 权威实现。
8. 增加 target lock 与 audit log。
9. 改进变量 catalog 来源可信度。
10. 增加 doctor、environment validate、report summary 类诊断工具。

## 本地 Agent 执行提示

先阅读 `AGENTS.md`、`skills/br-plc-toolchain/SKILL.md`、`tools/mcp_server/server.py`、`tools/mcp_server/schemas.py`、`tools/mcp_server/toolchain.py`、`tools/plc_access_policy.py`、`tools/plc_toolchain.ps1`。每次只完成一个阶段，改完运行相关测试，并输出变更摘要、测试结果和下一步建议。

## Phase 1：MCP 工具契约一致性

目标：保证 `schemas.py` 中声明的工具和 `toolchain.py` 中注册的工具完全一致。

建议新增 `tests/test_mcp_contract.py`，至少检查：

1. `TOOL_DEFINITIONS` 的名称集合等于 `TOOLS.keys()`。
2. 每个工具都有 `inputSchema`。
3. 每个 `inputSchema` 都设置 `additionalProperties: false`。
4. 会改变工程或目标状态的工具必须有明确确认参数。
5. 新增工具时，如果只加实现、不加 schema，测试失败。

验收标准：运行测试后能自动发现工具清单漂移。

## Phase 2：统一工具清单文档

目标：不要在 Skill、README、AGENTS、Roadmap 中手动维护多份互相矛盾的工具表。

建议新增生成脚本：`tools/generate_mcp_docs.py`。

输出建议：

- `skills/br-plc-toolchain/references/mcp-tools.md`
- `tools/mcp_server/README_FOR_LOCAL.md` 中的工具表区域
- `docs/PLC_MCP_SKILL_PROMPT_ROADMAP.md` 中的当前工具状态区域

主 Skill 文件应保持短小，只写触发条件、安全边界和标准流程，完整工具表放入 reference。

## Phase 3：MCP 服务端参数校验

目标：MCP Server 不只把 schema 暴露给客户端，还要在工具调用前自行校验参数。

建议新增：`tools/mcp_server/validation.py`。

检查内容：

1. required 参数。
2. 参数类型。
3. enum 范围。
4. minimum / maximum。
5. unknown 参数。

错误返回应包含 `ok=false`、`tool`、`error`、`validation_errors`，让本地 Agent 能修正调用。

## Phase 4：配置分层

目标：默认配置保守，开发开放配置必须显式选择。

建议整理为：

- `plc_targets.local.json`：保守默认。
- `plc_targets.dev.example.json`：开发专用。
- `plc_targets.test.example.json`：专用测试目标。
- `plc_targets.readonly.example.json`：只读诊断模板。

同时更新 `plc_environments.json`，让环境名表达风险等级，例如 `default_safe`、`dev_agent_directed`、`test_whitelist`、`readonly_diagnostics`。

## Phase 5：统一默认 target 语义

目标：不显式选择目标时，不应作用于真实设备。

建议检查：

- `tools/mcp_server/toolchain.py` 中各工具的 `default_target`。
- `tools/mcp_server/schemas.py` 中暴露给 Agent 的默认值。
- `tools/plc_toolchain.ps1` 中 CLI 层默认值。
- `tools/plc_environments.json` 中 default 环境。

建议原则：

1. 默认环境优先指向仿真或安全只读目标。
2. 真实设备必须显式选择 target 或 environment。
3. 改变状态类工具若未明确 target，应返回清晰错误，或只执行规划/检查阶段。
4. 文档、schema、实现中的默认值必须一致。

验收标准：本地 Agent 不传 target 时，不会默认作用于真实设备。

## Phase 6：统一 access_policy 权威实现

目标：避免 Python 与 PowerShell 各自维护一套策略。

推荐以 `tools/plc_access_policy.py` 作为唯一权威策略引擎。

建议新增：

- `tools/plc_access_policy_cli.py`
- `tests/test_access_policy.py`

策略 CLI 应输出稳定 JSON，至少包含：

- `ok`
- `errors`
- `policy_mode`
- `target_role`
- `requested_items`
- `blocked_reason`

PowerShell 层应逐步减少重复判断逻辑，只负责调用策略 CLI 并根据返回值继续或停止。

验收标准：同一配置、同一请求，在 MCP、Python、PowerShell 路径下得到相同策略结论。

## Phase 7：锁和审计

目标：避免多个本地 Agent 同时改变同一目标或工程，并让关键动作可追溯。

建议新增：

- `tools/mcp_server/locks.py` 或 `tools/plc_target_lock.py`
- `tools/mcp_server/audit.py` 或 `tools/plc_audit.py`
- `tests/test_target_lock.py`
- `tests/test_audit_log.py`

锁文件建议放在：

```text
tools/.generated/locks/
```

审计文件建议放在：

```text
tools/.generated/audit/
```

需要纳入锁和审计的行为类型：

1. 修改工程结构。
2. 改变目标运行状态。
3. 改变目标变量状态。
4. 执行完整测试套件。
5. 同一 config 的构建过程。

审计记录至少包含：时间、工具名、目标名、目标角色、环境名、请求摘要、结果摘要、报告路径、日志路径。

验收标准：关键动作成功或失败都能留下审计记录；同一目标的关键动作不能并发冲突。

## Phase 8：测试夹具化

目标：自动测试不应直接依赖业务变量，而应逐步通过专门 Test Harness 进行。

建议长期引入 PLC 侧测试夹具概念：

```text
TestHarness/
  Inputs
  Outputs
  Command
  CaseId
  Execute
  Reset
  Busy
  Done
  Error
  ResultCode
```

工具层策略：

1. 底层变量访问工具保留，但只用于受控诊断。
2. 常规自动测试优先走测试套件工具。
3. 测试前后必须有 reset / restore 记录。
4. restore 失败时，测试整体失败，并在报告中提示人工检查。

验收标准：测试报告能区分参数校验失败、写入失败、读回失败、断言失败、恢复失败。

## Phase 9：变量 catalog 升级

目标：提高变量目录可信度。

当前 `plc_symbol_index.py` 主要基于源码正则扫描，建议先在 catalog 输出中增加来源信息：

- `catalog_source`
- `confidence`
- `generated_from`
- `warnings`

长期优先从 Automation Studio 构建产物生成变量目录；如果构建产物不存在，再降级到源码扫描。

验收标准：Agent 能知道变量目录来自源码扫描还是构建产物，避免把低可信 catalog 当作绝对真实。

## Phase 10：诊断和报告工具

目标：让 Agent 能判断本地环境是否配置正确，并能复盘历史结果。

建议新增 MCP 工具：

- `plc_doctor`
- `plc_validate_environment`
- `plc_list_reports`
- `plc_read_report_summary`

`plc_doctor` 检查项：Python、PowerShell、Automation Studio 路径、PVITransfer 路径、PVI Python 依赖、targets 配置、project 路径、config 名称、仿真 loader、`.generated` 写权限。

报告类工具只返回摘要和路径，不返回大型日志全文。

验收标准：本地 Agent 可以先运行 doctor 类工具定位环境问题，再决定是否继续后续流程。

## 新增 MCP 工具的标准模板

每新增一个工具，必须同时完成：

1. 底层实现或 CLI 封装。
2. `schemas.py` 中的 inputSchema。
3. `toolchain.py` 中的工具注册。
4. 服务端 schema 校验。
5. 风险等级说明。
6. access policy / target role 判断。
7. timeout 设置。
8. logs / report_path / warnings / next_actions。
9. 单元测试。
10. Skill / docs 同步。
11. 如果会改变工程或目标状态，必须接入 lock。
12. 如果会改变工程或目标状态，必须写 audit log。

工具风险等级建议分为：

```text
readonly       只读查询，不改变状态
local_write    只修改本地文件或报告
project_write  修改 AS 工程结构或配置
target_change  改变目标运行状态或变量状态
```

`project_write` 和 `target_change` 类工具必须有明确确认参数、审计记录、报告路径和失败处理策略。

## 不建议做的事

本阶段不要做：

1. 不要继续扩大默认动态访问范围。
2. 不要让真实设备成为默认目标。
3. 不要自动修改 Safety 工程。
4. 不要默认开放所有 OPC UA 节点。
5. 不要把 AS 样例项目作为主要重构对象。
6. 不要在 Skill 主文件中复制大量脚本实现细节。
7. 不要让文档工具清单继续手工漂移。

## 最终验收目标

完成本 PLAN 后，应满足：

1. Agent 读取 Skill 后能得到明确、安全、一致的流程。
2. MCP Server 能拒绝非法参数，而不是依赖客户端自觉。
3. 默认配置保守，开放模式必须显式选择。
4. Python / PowerShell 的 access_policy 结果一致。
5. 工具清单不再多处手工漂移。
6. 关键动作都有 lock 和 audit。
7. report / logger / audit 能被 Agent 复盘。
8. 新增工具有固定模板和测试约束。

## 给本地 AI 的建议任务入口

```markdown
请根据 `docs/PLC_SKILL_MCP_NEXT_DEVELOPMENT_PLAN.md` 改进本项目的 Skill / MCP 工具链。重点是 MCP Server、schemas、toolchain、access_policy、配置、Skill 文档和测试，不要优先修改 PrintDemo 的 AS 业务项目。

执行顺序：
1. 先完成 Phase 1：MCP 工具契约一致性测试。
2. 再完成 Phase 2：统一工具清单文档。
3. 每次只做一个小阶段。
4. 改完运行相关测试。
5. 输出变更摘要、测试结果、剩余风险和下一步建议。
```
