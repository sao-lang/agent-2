# CHANGELOG

单一版本口径：框架只有一个版本（`__version__` / `contracts_version` /
`SCHEMA_VERSION` 的唯一权威定义在 `src/harness` 内；代际不再作为对外口径）。
历史施工实录与分代方案见 `docs/harness/archive/`（历史资料，非实现依据）。

## 0.3.x — 单版本收敛（2026-11-12）

依据：`docs/harness/AUDIT-断点-重复实现-版本说法统计.md`（§4 路线 P0 → P1 → P2）。

### P0 · 接线断点修复（44 项）

- **B 装配组（B01–B12）**：声明层真实实例化并入程序 + 装配期 `validate_layers()`；
  补齐 6 个配置槽（guard/pipes/filter/sink/token_counter/checkpoint_store）；
  `new_runtime` 传 `tool_registry/checkpoint_store`；注册真 `LocalSandbox` 与新增
  `LocalArtifactStore`，修正 secrets/approval/clock 名实不符；包初始化完成
  adapters 自注册；CLI 健康检查改为运行时协议校验；删除悬空 `"build"` 导出。
- **M 计量组（M01–M10）**：`usage_total()` 统一三套 usage 口径；`_commit` 成为
  唯一记账点（State.usage + Budget.spend + `state.data["budget"]` 快照）；
  删除 `tokens=10` 硬编码；`ModelResponse.usage` / `_pending_usage` 链路补全；
  FakeModel 协议化（stream/response_format/usage 归一化）；Framer/Encoder
  counter 接线。
- **C 契约组（C01–C10）**：`SessionGuard`（quota/pinned_model 真实判定）+
  三入口 `check_identity` 接线（deny → REFUSED）；`Resilience` 补 `max_qps`
  与 `CircuitBreaker`；`StreamGuard` 改用 check 退化语义（不再空转）；
  `AnswerValidator` 实现 + 出口接线；四个拓扑类补 `children`；
  `run_legacy` 补 `run` 插点（output_guard 出口扫描生效）；
  structured 顶层导出；`Budget.view()` 实现；默认 `MemoryDurability`。
- **G 治理组（G01–G07）**：v3 入口补 guard/checks/classify/budget/auto 层；
  `dry_run` 与 `run` 同源；`Harness.interpret` 出口统一 `RunResult`；
  v1 执行统一走 `kernel.stage.run_stages`；四段链收编 `kernel/stage.py`
  单一实现；v1/v3 模型调用接 `model_call` 插点。
- **F 默认实现组（F01–F05）**：假实现默认在装配期显式告警；
  `build_production` 保持全必填；缺依赖的适配器槽位调用期显式
  `ConfigError`（带安装指引）。

### P1 · 重复实现合并（§2.6 无意义重复）

- `Budget` 统一到 `contracts.types.Budget`；`parts/budget.py` 降为转发壳；
  `NullBudget` 迁入契约层。
- `Failure`：`kernel/stage.py` 改用契约层定义（字段本就相同）。
- `ToolRequest`（stage 版）改名 `StageRequest`，消除与契约层同名不同形状。
- 解释器护栏 `Limits` 改名 `RuntimeLimits`；顶层删除 `InterpreterLimits` 别名。
- 两套四段链：`EffectRuntime._stages` 委托 `kernel.stage.run_effect_stages`，
  四段语义单一实现。
- 两代拓扑：`fp/frontends` 的 `Supervisor/Handoff/Blackboard`（transition 程序
  代）改名 `SupervisorProgram/HandoffProgram/BlackboardProgram`，
  与 `parts/topology`（Runnable 代）不再同名。

### P2 · 版本收敛

- 历史文档 `TUTORIAL-BUILD.md` / `DEV-SESSION.md` /
  `PROPOSAL-通用解释器与效应系统.md` / `SUPPLEMENT-PLAN.md` 移入
  `docs/harness/archive/`，文件头标注「历史资料，非实现依据」。
- 本 CHANGELOG 建立，作为代际变更的集中记录。

### 收敛轮 · 多版本残留清零（2026-11-12，判据 1.2 → 1.3）

全部 7 项残留（AUDIT §6.5 BL-1~BL-5、BL-7）完成；每阶段 `GATE OK`：

- **Actor 双实现**：`parts/actor_v2.py` 并入 `parts/actor.py`；`LlmActor`
  吸收 resilience / model_call 插点成为唯一执行终端。
- **策略两代**：`parts/policy/policies.py` 唯一实现；`PlanExecutePolicy`
  吸收原 PE 的 section 记账 / `replan_all` / `budget.replans` 镜像全部语义；
  `ScriptedPlanner`/`FunctionPlanner` 移至 `parts/policy/planners.py`；
  `parts/body/*` 整包退役。
- **legacy 桥**：`kernel/legacy.py` 删除；`Harness.run`/`dry_run` 直连
  `kernel.interpret.Runtime`（`CallbackRunner` + `run_stages` 四段链保留）；
  `Program.transition` 内联 `next_step → Decision|Halt` 翻译；
  `kernel/loop.py` 降为无循环空壳。
- **装配线两条**：`assembly/agent.py`/`build.py`/`presets.py` 退役；
  审批/恢复闭环（SUPPLEMENT A2）并入 `Harness.resume`（approve/reject/modify
  + 崩溃恢复，持久化统一走 CheckpointStore 协议）；顶层 `__init__.py`
  只导出门面入口（`Harness`/`build_harness`/`HarnessConfig`/fp 组合子）。
- **Tracer-事件双轨**：`parts/tracer.py` 退役，`parts/sinks.py`
  （`Null/Memory/Jsonl` Sink，`emit(RunEvent)`）成为唯一观测面；
  `TraceEvent`/`Span` 从契约层退役；JSONL 行形状对齐 `RunEvent`。
- **代际标识**：代码内 strict/wide 口径代际词 **0 行**（原 88 行/32 文件）；
  `name="agent_v1"`/`name="legacy"`/`LegacyProgram`/`_run_legacy` 随退役清除。
- **顺带修复**：`MemoryCheckpointStore.get` 对齐 `state.rev == store 版本索引`；
  `checkpoint_layer` 的 `expect_rev` 改为 `state.rev - 1`（与 interpret 同口径）——
  多 commit 运行的乐观并发误报被消除。
- **测试与示例**：9 个测试文件迁移至统一入口等价断言（341 tests，零删减）；
  8 个示例脚本全部改写 v3 且端到端可运行。

### 收敛轮 · 测试替身出包（2026-11-12，判据 1.3 → 1.4）

框架包内不再存在"用于场景测试或实验"的代码：

- **移出 src/harness**：`FakeModel`/`answer`/`tool_call`（删 `impl/fakes.py` 与
  `harness/testing.py` 兼容壳）、`FakeSandbox`（剧本沙箱）、`FakeClock`——
  统一迁入 `tests/support.py`；examples 侧共用 `examples/demo_model.py`。
- **kernel 剧本通路删除**：`effects._model` 的 `state.data["script"]` 回放分支
  移入 `tests/support.py` 的 `script_model_handler`（经 `extra_handlers={"model": …}`
  覆盖内置 model 效应；journal cursor 语义原样保留）。
- **registry 收紧**：`fake` 三个槽位（model/sandbox/clock）删除；
  `HarnessConfig.model=None` 为合法装配（不注入模型的程序）；
  `BackendSpec.sandbox` 默认 `"local"`，`LocalSandbox` 改为
  **空白名单 = 全拒绝**（fail-closed）；F01/F02 假实现告警随之删除。
- **文档**：`README.md` / `TUTORIAL.md` 按单版本口径重写更新（`TUTORIAL-BUILD.md`
  历史资料更新文头状态）；`harness check` 探活不再要求默认装配携带模型。

### 已知遗留（见 AUDIT §6.5 backlog）

- BL-6：`SPEC.md` 单版本重写（文档叙述口径，独立立项；TUTORIAL.md 已随本轮更新）。
- 代码侧无遗留；判据 v1.4 锚点 44/44 通过。
