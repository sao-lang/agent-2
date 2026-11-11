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

### P2 · 版本收敛（本轮完成部分）

- 历史文档 `TUTORIAL-BUILD.md` / `DEV-SESSION.md` /
  `PROPOSAL-通用解释器与效应系统.md` / `SUPPLEMENT-PLAN.md` 移入
  `docs/harness/archive/`，文件头标注「历史资料，非实现依据」。
- 本 CHANGELOG 建立，作为代际变更的集中记录。

### 已知遗留（见 AUDIT §6.5 backlog）

- §1 无遗留断点；§2 剩余 4 组结构性合并（三策略类 / 两套 presets /
  两条装配线 / Tracer-事件双轨）。
- 代码内 78 行严格代际词注释改写；`SPEC.md` / `TUTORIAL.md` 单版本重写。
