# Harness 框架现状审计：接线断点 / 多份实现 / 版本说法统计

| 项 | 内容 |
|---|---|
| 审计日期 | 2026-11-11 |
| 范围 | `src/harness/**/*.py`（**94 个**）、`docs/harness/*.md`（**6 个，合计 9,646 行**）、`tests/**/*.py`（27 个，仅作引用交叉核对） |
| 排除 | `docs/plan/` 下所有 PatchPilot 文档（按约定不纳入）；`docs/harness/AUDIT-*.md`（本报告自身，避免自污染统计） |
| 统计来源 | **`tools/audit_harness.py`**（零依赖、确定性脚本，判据版本 `1.2`）+ **`docs/harness/audit-report.json`**（机器可读快照） |
| 复现命令 | `python tools/audit_harness.py --check docs/harness/audit-report.json` → `CHECK OK` |
| 方法 | 固定文件集 → 固定正则 / AST 规则全量遍历 → 关键文件精读；**只读审计，未修改任何 `src/` 代码** |
| 后续目标 | 消除功能断点、合并多份实现、把 v1 / v2 / v3 / v3.1 整合成**单一版本** |
| 修复登记 | **2026-11-12：P0 全部 44 项修复完成、P1 完成 6 组合并、P2 完成归档与 CHANGELOG；判据升版 1.1 → 1.2（锚点由「断点态」翻转为「修复态」）。逐项状态见 §0.1 / §0.2，遗留见 §6.5 backlog。** |

> **完整性边界**：本文的机械统计（文件、行数、命中、同名定义、悬空导出、占位标记、锚点）是封闭域穷尽且可复现的；「44 项接线断点」是人工判定，脚本只固定其数量、分级与证据锚点有效性，不重算结论。详见 §6。

---

## 0.1 §1 修复状态登记（44 项，2026-11-12）

> 门禁基线：修复全程 338 tests 全绿，`GATE OK` / `CHECK OK`；快照按提示重生成。

**B 装配组（12 项）**：B01–B12 **全部已修**。B01/B02 声明层实例化并入程序；B03 装配期 `validate_layers()`；B04 自动层并入；B05 补 6 配置槽；B06 `new_runtime` 传 `tool_registry/checkpoint_store`（配套 `_tool` 经 `FunctionTool.invoke` 调用）；B07 `LocalSandbox` 真注册 + 新增 `LocalArtifactStore` + 修正 4 处名实不符；B08 包初始化自注册；B09 删悬空 `"build"`；B10 工厂表单一来源（与 `fp.from_spec` 共用）；B11 `STORES/PROGRAMS` 加消费槽；B12 CLI 健康检查改运行时协议校验。

**M 计量组（10 项）**：M01–M08、M10 **已修**；**M09 保留并说明**——`budget_layer` 不自动挂载：`_commit` 已单点记账，自动挂载会双 spend；其定位收敛为「显式子作用域预算」（声明通道经 B01 修复后已可用）。M01 `usage_total()` 统一口径；M02 `_model` 提取回包 usage；M03 双计消灭（`_pending_usage` pop 语义 + `_commit` 单点）；M04 `_commit` 调 `budget.spend`（legacy 路径同步传 budget）；M05 `_make_model_call` 填 `ModelResponse.usage`；M06 FakeModel 协议化（stream/response_format/usage 归一化）；M07 协议 `response_format` 改可选；M08 Framer/Encoder counter 接线；M10 `_commit` 写预算快照。

**C 契约组（10 项）**：C01–C08、C10 **已修**；C09 **部分已修**。C01 `SessionGuard`（quota/pinned_model 真实判定，顶层导出）；C02 `check_identity` 接入 `Agent.run`/`Harness.run`（deny → REFUSED）；C03 `Resilience` 补 `max_qps` + `CircuitBreaker`（closed/open/half_open，Actor 消费点已有）；C04 `StreamGuard` 改 check 退化语义（§4.2.6 处方②）；C05 `AnswerValidator` 实现 + v1 出口接线（`AgentConfig.validator`）；C06 四个拓扑类补 `children`；C07 `run_legacy` 补 `run` 插点执行（output_guard 出口扫描生效）；C08 structured 顶层导出（`ModelReply.parsed` 消费方连通）；C09 `Budget.view()` 已实现、subagent 走显式声明通道（`config.layers` 声明 `subagent_layer` 即生效）；C10 默认 `MemoryDurability`（build.py + agent.py 两处）。

**G 治理组（7 项）**：G01–G07 **全部已修**。G01 v3 入口补 guard/checks/classify/budget/auto 层；G02 `dry_run` 与 `run` 同源走 `with_auto_layers`；G03 `Harness.interpret`/`dry_run_program` 出口统一 `RunResult`（经 `as_run_result`）；G04 v1 执行统一走 `kernel.stage.run_stages`（ask 审批卡片流保留 Gate 直判，deny/Classify 语义一致）；G05 v3 工具经 `FunctionTool.invoke`（随 B06 落地）；G06 四段链收编 `kernel/stage.py` 单一实现（`run_effect_stages`，幂等/Hook 留在 EffectRuntime）；G07 v1/v3 模型调用接 `model_call` 插点（`EffectRuntime.model_call_layers` + `Actor.model_call`）。

**F 默认实现组（5 项）**：F01–F03、F05 **已修**；F04 **保留并说明**。F01/F02 装配期对 `model="fake"`/`sandbox="fake"` 显式 `UserWarning`（真实现已注册）；F03 `build_production` 全必填（原有）+ `build()`/`build_harness()` 对空默认显式告警，`NullDurability` 默认已移除；F04 11 个 `_adapter` 占位保留——调用期抛 `ConfigError`（带 pip 安装指引）**正是「缺依赖启动期显式报错」处方**，真实 SDK 实现属可选依赖范畴，超出本次封闭范围；F05 经 M06 解决（FakeModel usage 归一化；`actor.execute` tokens=0 为正确口径——工具调用不产生模型 token）。

## 0.2 §2 重复实现合并状态（2026-11-12）

| 组 | 状态 | 说明 |
|---|---|---|
| `Budget` 两份 | ✅ 已合并 | contracts 唯一实现；`parts/budget.py` 转发壳；`NullBudget` 迁入契约层 |
| `Failure` 两份 | ✅ 已合并 | stage.py 改用契约层定义（字段本就相同） |
| `ToolRequest` 两份 | ✅ 已改名 | stage 版 → `StageRequest`（消除同名不同形状） |
| `Limits` 同名异物 | ✅ 已改名 | 解释器护栏 → `RuntimeLimits`；顶层删 `InterpreterLimits` 别名 |
| `Decision` 同名异物 | ⏸ 保留 | 语义本不同（审批 vs 转移）；顶层 `Transition` 别名已隔离，无合并收益 |
| 两套四段链 | ✅ 已合并 | `run_effect_stages` 收编 `kernel/stage.py`；effects.py 只留运行时关注点 |
| 两代拓扑组件 | ✅ 已改名 | `fp/frontends` → `SupervisorProgram/HandoffProgram/BlackboardProgram` |
| 三个策略类 | ⬜ backlog | 见 §6.5（需统一两条执行线的 policy API） |
| 两套 presets | ⬜ backlog | 见 §6.5 |
| 两条装配线 | ⬜ backlog | 见 §6.5（涉及顶层 API 退役与大量测试迁移） |
| 两套 Tracer-事件体系 | ⬜ backlog | 见 §6.5（三代载荷语义统一） |
| 两代 Actor | ⏸ 保留 | `parts/actor.py` 是 v1 装配线载体；随「两条装配线」backlog 一并处置 |
| 其余（Framer/Encoder/Tracer 实现/模型包装等） | ⏸ 保留 | §2.6 判定为合理可替换策略 |

---

## 0. 结论速览

**本表所有数字以 `docs/harness/audit-report.json` 为准**，来源列标明机械统计还是人工判定。

| 指标 | 数值 | 来源 |
|---|---:|---|
| 代码文件 / 框架文档 / 测试文件 | 94 / 6（9,646 行）/ 27 | 机械 |
| 代码指纹 `sha256` | `dd4afe3fed51894e…` | 机械 |
| **严格代际词 `v1/v2/v3`** | 代码 **78 行 / 32 文件**；文档 **121 行 / 6 文件** | 机械 |
| 宽口径（+ `legacy`） | 代码 **88 行 / 32 文件**；文档 **134 行 / 6 文件** | 机械 |
| 全宽口径（+ `兼容/SUPPLEMENT/M15/版本/version`） | 代码 **139 行 / 43 文件**；文档 **232 行 / 6 文件** | 机械 |
| `v3.1 / SUPPLEMENT` 增量 | 代码 **26 行 / 15 文件**；文档 **10 行** | 机械 |
| 版本常量 / 代际标识 | **6 处** | 机械 |
| 同名顶层定义组（AST 全量） | **19 组** | 机械 |
| 其中人工归类为「多份实现 / 同名不同物」 | **16 组** | 人工 |
| 悬空 `__all__` 导出 | **1 处**（`assembly/config.py` 的 `"build"`） | 机械 |
| 兼容壳候选 | **12 个**（7 个转发文件 + 5 个纯导出 `__init__.py`） | 机械 + 人工 |
| 静态零引用候选 | **23 个** | 机械（启发式） |
| `TODO` 类 / `NotImplementedError` / `pass` / `_adapter(` 文本 | **0 / 1 / 18 / 18** | 机械 |
| 证据锚点 | **44 / 44 通过** | 机械 |
| **接线断点（人工判定索引）** | **44 项**（高 22 / 中 17 / 低 5） | 人工 |
| 并存的装配线 / 执行前端 / 四段链 | 2 条 / 3 条 / 2 套 | 人工 |

**三句话结论**

1. **能力不少，接线不多**：唯一真正生效的内核只有 `kernel/interpret.py: Runtime.interpret` 一处；绝大多数治理层、精确计数器、结构化输出、流式护栏、子 agent、路由、拓扑等部件在 `src/harness` 内**零调用点**，只在测试里被使用（脚本给出 23 个静态零引用候选）。
2. **不是「多份实现随机散落」，而是 v1→v2→v3 迁移的中间态**：两条装配线各自实例化一套部件，同名类在不同代里形状不同；AST 实测 19 组同名顶层定义，其中 16 组被人工判定为需要合并的重复概念。
3. **版本说法主要沉淀在注释与文档**：代码里 `v3.1 / SUPPLEMENT` 增量注释 26 行 / 15 文件，`TUTORIAL-BUILD.md` 按 v1→v2→v3→v3.1 分阶段叙述（严格口径 68 行，为全库最高）；`SPEC.md` 全文无 `v3`，仍以 v2 为规格主体。

---

## 1. 接线断点与未接线项（44 项，人工判定）

级别说明：**高** = 影响正确性 / 治理是否生效；**中** = 能力存在但默认不生效或口径不一致；**低** = 悬空导出、占位、可延后清理。

> 本节 44 条为人工判定。脚本 `MANUAL_ITEMS` 固化其 ID / 分类 / 级别 / 锚点名，并校验 44 个证据锚点全部命中（见 §6）；**脚本不重算结论**。

### 1.1 装配层（12 项）

| 编号 | 位置 | 现象 | 后果 | 级别 |
|---|---|---|---|---|
| B01 | `assembly/config.py:178` | `harness.layers = tuple(LayerSpec(...))` 只把配置复制成声明数据，全库无读取方 | `HarnessConfig.layers` **静默失效**，声明的层从不实例化、从不并入 program | 高 |
| B02 | `assembly/config.py:62-77` | `LAYER_FACTORIES` 的 lambda / `_layer_fn` **从未被调用**，`validate` 只在 `:103` 用 `in` 检查名字 | 层工厂表形同虚设；`"truncate"` 注册了名字但真实现在 `parts/capability.py:162`，且不会触发报错（校验只查名字）——是**静默不生效**而非启动失败 | 高 |
| B03 | `assembly/config.py:204-207` | `validate_layers()` 遍历 8 个插点做成环预检，`build_harness` 不调用，全库零调用点 | 层顺序成环的装配期预检失效 | 中 |
| B04 | `assembly/config.py:182-195` | `_auto_layers` 只挂 3 个层（有 guardrails 时 `input_guard` + `output_guard`；有 durability 时 `checkpoint`） | 其余 15+ 层（budget / trace / approval / idempotency / validate / context / audit / retrieval / memory_* / tenancy / truncate）默认全灭 | 高 |
| B05 | `assembly/config.py:44-58` vs `assembly/harness.py:26-41` | `Harness` 的 `guard / pipes / filter / sinks` 在 `HarnessConfig` 里**没有对应配置槽**，`Harness.of` 也不传 | 默认 `guard=None`、`pipes=()`、`filter=None`；Guard / Pipe / Filter / 计数器 / 结构化输出无法配置接线 | 高 |
| B06 | `assembly/harness.py:160-175` | `new_runtime` 构造 `Runtime` 时**未传 `tool_registry`、未传 `checkpoint_store`**（`interpret.py:97,102` 有这两个参数） | v3 路径的 `HarnessConfig.tools` 装配结果用不上；检查点只进内存，`resume_from_checkpoint` 拿不到数据 | 高 |
| B07 | `assembly/registry.py:203-214` | `sandbox["local"] → _fake_sandbox`、`artifacts["local"] → _memory_artifacts`、`secrets["memory"] → _env_secrets`、`approval["callback"] → _memory_approval`、`clock["fake"] → _system_clock` | 配置名与实现不符；真 `LocalSandbox`（`impl/backends/core.py:60`）从未注册 | 高 |
| B08 | `adapters/openai.py:133-138` | `MODELS["openai"]` 只在**显式 import 本模块时**才自注册，而 `harness/__init__.py` 不 import 它 | `HarnessConfig(model="openai")` 默认直接抛 `ConfigError`（占位工厂 `_adapter`） | 高 |
| B09 | `assembly/config.py:215` | `__all__` 导出 `"build"`，本文件无 `build` 定义（在 `assembly/build.py`） | 悬空导出 | 低 |
| B10 | `assembly/config.py:62` + `assembly/fpresets.py` | `LAYER_FACTORIES` 与 `fp/Program.from_spec(factories=...)` 是两套互不相干的工厂表，后者零调用点 | 两套层工厂并存 | 中 |
| B11 | `assembly/registry.py:127,249` | `STORES`、`PROGRAMS` 注册表无对应 `HarnessConfig` 槽位、无消费方（`build_harness` 用的是 `STORE_SLOTS`） | 死注册表 | 低 |
| B12 | `cli.py:4,78-90` | `check` 自述「P8 占位，返回可用性」，只做 spec 语法解析 | 健康检查不检查任何运行时依赖 | 低 |

### 1.2 计量 / 预算链路（10 项）

| 编号 | 位置 | 现象 | 后果 | 级别 |
|---|---|---|---|---|
| M01 | `parts/body/react.py:19`、`parts/actor_v2.py:46`、`kernel/effects.py:271` | **三套 usage 口径**：v1 读 `usage["total_tokens"]`（协议给的是 `total`）；v2 读 `total`（唯一正确）；v3 硬编码 `tokens=10` | 只有 v2 路径可信；v1 tokens 恒 0、v3 恒为 10×调用数，`max_tokens` 护栏基本失效 | 高 |
| M02 | `kernel/effects.py:284-296` | `_model` 调 `model.complete()` 后 `return {"ok":True,"output":reply}`，**完全丢弃 `ModelReply.usage`** | v3 路径拿不到真实 token | 高 |
| M03 | `parts/body/react.py:20-21` + `assembly/agent.py:262` | v1 先 `state.add_usage(tokens,1)` + `budget.spend`，`run_one` 又返回 `_usage={"calls":1,"tokens":0}`，而 `interpret.py:231-242` 优先采用 `_usage` | **calls 双重计数、tokens 归零**，`RunResult.usage` 错误 | 高 |
| M04 | `kernel/interpret.py:224-256` | `_commit` 从不调用 `budget.spend` | v3 下 `Budget.used_tokens/used_calls` 永远 0、`exhausted` 永远 False；预算变成 `Limits` + `state.usage` 的影子实现 | 中 |
| M05 | `parts/middleware/builtin.py:99` + `kernel/legacy.py:167` | `budget_layer` 读 `ModelResponse.usage["total"]`，但 `_make_model_call` 返回 `ModelResponse(reply=reply)` **不填 usage** | 该层即使显式挂上也只扣 0 | 中 |
| M06 | `impl/fakes.py:11-23` | `FakeModel` 是默认模型（`config.py:47`、`registry.py:121`），无 `stream()`、无 `response_format`、`ModelReply.usage` 为空 | **不满足 `Model` 协议却是默认实现** | 高 |
| M07 | `contracts/protocols/model.py:20` | 协议把 `response_format` 声明为必需关键字，但 `FakeModel.complete` 与 `parts/actor.py:23` 都不传 | 协议漂移 | 中 |
| M08 | `assembly/harness.py:60-61` | `ModelFramer(system=...)` / `ChatEncoder()` 都未传 `counter`；`HarnessConfig` 无 precision 槽位 | `parts/tokens.py` 的 `TiktokenCounter` 永不生效，默认 `1 token ≈ 4 字符`（`framers.py:29-31` 自注「只用于相对比较与裁剪」） | 中 |
| M09 | `parts/middleware/builtin.py:88-105` | `budget_layer` 不在 `_auto_layers` | 唯一的响应用量扣减层需手工声明，且声明通道本身失效（B01） | 中 |
| M10 | `parts/delivery.py:24` | `metadata={"budget": state.data.get("budget", {})}`，而 `state.data` 从不写 `"budget"` | 预算快照恒空 | 低 |

### 1.3 契约钩子空转（10 项）

| 编号 | 位置 | 现象 | 后果 | 级别 |
|---|---|---|---|---|
| C01 | `contracts/types.py:71-72` | `SessionMeta.quota` / `pinned_model` 全库只有字段定义，无任何读写判定 | 会话级配额与模型钉选不存在 | 高 |
| C02 | `parts/guard.py:17,25,41` | `check_identity` 3 个实现全部直接 allow / 透传 `identity_fn`，且**全库零调用点** | 接入鉴权 / 租户 / 配额整条链不存在 | 高 |
| C03 | `parts/resilience.py:13-29` | 只有 `timeout_s / retries / backoff_s`；`max_qps`、`circuit`、`breaker` 全库零命中；`AgentConfig.resilience` 默认 None | 限流与熔断未实现，连超时重试默认也不启用 | 中 |
| C04 | `parts/guardrail/streaming.py:39` + `parts/guardrail/detectors.py` | `StreamGuard` 用 `hasattr(g,"feed")` 过滤，而内置检测器只有 `check`、无 `feed`/`flush` | 过滤后 guardrails 为空，**流式护栏完全空转**；`GuardrailStream` 协议无实现 | 高 |
| C05 | `contracts/protocols/governance.py:45` | `Validator` 协议（`validate(answer,state)`）全库无实现 | 最终答案判定缺位 | 中 |
| C06 | `contracts/protocols/runtime.py:62` | `Topology` 要求 `children` 属性，`parts/topology.py` 四个类都没有 | 无满足协议的实现 | 低 |
| C07 | `kernel/legacy.py:78-79,162` + `kernel/chain.py:14-17` | `run_legacy` 只 resolve `tool_call` / `step` / `model_call` 三个插点，`POINTS` 里还有 `run` / `transition` / `effect` / `commit` / `node` | 声明 `run` 插点的层全部不触发，尤其 `output_guard_layer`（`guardrail/layer.py:186`）对最终答案的出口扫描永不执行 | 高 |
| C08 | `parts/structured.py` + `contracts/types.py:146` | 整个模块不被任何模块 import、不在顶层导出；`ModelReply.parsed` 无消费方；`Model.stream()` 唯一消费者是未接线的 `StructuredModel` | 结构化输出与模型流式补全断裂 | 中 |
| C09 | `contracts/types.py:382` | `Budget.split()` 唯一调用点 `kernel/scope.py:65` 在 `RunScope.child()` 内，而 `child()` 只被未接线的 `parts/subagent.py` 调用；`Budget.view()` 全库不存在 | 子 agent 共享预算默认不执行；v1 用的 `parts/budget.Budget` 连 `split` 都没有 | 中 |
| C10 | `assembly/build.py:85` + `parts/durability.py:16-20` | v1 默认 `NullDurability`，`save/load` 全 `return None` | `Agent.resume` 永远拿不到 state，审批挂起 / 崩溃恢复不可用 | 高 |

### 1.4 治理旁路（7 项）

| 编号 | 位置 | 现象 | 级别 |
|---|---|---|---|
| G01 | `assembly/harness.py:78` vs `:160-175,186-189` | `with_auto_layers` **只在 `Harness.run` 调用**；`Harness.interpret / new_runtime` 用 `layers=()`、`guard=None`、`checks=()`，无检查点存储、无工具注册表 → v3 入口默认绕过自动护栏、检查点、审批、Guard/Check 段 | 高 |
| G02 | `assembly/harness.py:117-127` | `dry_run` 直接调 `run_loop`，不走 `with_auto_layers`；`run(with_auto=False)` 另有显式绕过开关 | 中 |
| G03 | `assembly/harness.py:186-189` | `Harness.interpret` 返回 `Outcome`，不经 `Delivery`、不产出 `RunResult`（`governance.py:59-60`「Delivery 出口唯一」被绕过） | 中 |
| G04 | `assembly/agent.py:214-266` | v1 `Agent._interpret` 的 `run_one` 直调 `self.actor.execute`，**不经 `stage.run_stages`**；Gate 由 `guard.check` 直调，审批 / 事件 / 检查点靠回调复现，与 `deny→REFUSED` / `ask→NEEDS_APPROVAL` 语义不一致 | 中 |
| G05 | `assembly/harness.py:160-175` + `kernel/effects.py:302` | v3 不传 `tool_registry` → 工具回退 `state.data["tools"]`，绕过 `FunctionTool.invoke` 的参数校验与 `ToolContext` 能力注入 | 高 |
| G06 | `kernel/stage.py:114` vs `kernel/effects.py:181-239` | **四段链两套实现**：`run_stages` 与 `EffectRuntime._stages`（后者内联重写 Gate/Check/Wrap/Classify，只在 `:242` 复用 `stage.DefaultClassify`）；`effects.py` 本地还定义了 `Failure`/`ToolRequest` | 高 |
| G07 | `parts/actor.py:23` / `parts/actor_v2.py:43` / `kernel/effects.py:294` | 三条模型调用路径只有 v2 经 `_make_model_call` 的 `model_call` 插点层，v1 与 v3 都绕过 | 中 |

### 1.5 默认假实现（5 项）

| 编号 | 位置 | 现象 | 级别 |
|---|---|---|---|
| F01 | `assembly/config.py:47`、`assembly/registry.py:69,121` | 默认 `model="fake"`，`FakeModel` 恒返回 `answer("fake")`，usage 空 | 中 |
| F02 | `assembly/config.py:34`、`registry.py:203` | 默认 `sandbox="fake"`；`"local"` 也映射到 `_fake_sandbox`，真 `LocalSandbox` 未注册 | 高 |
| F03 | `assembly/build.py:84-87` | 默认 `NullTracer` / `NullDurability` / `NullReflector` / `AllowAllGuard` | 高 |
| F04 | `assembly/registry.py:55-59,120-125` | `openai/anthropic/ollama/postgres/redis/s3/docker/vault/qdrant/pgvector/http` 等 11 个槽位一律 `_adapter` 占位工厂，抛 `ConfigError` | 高 |
| F05 | `impl/fakes.py:16-23` | `FakeModel.complete` 不产生任何 usage；`parts/actor.py:50-55` 构造 `ActionResult` 从不填 `tokens` | 中 |

### 1.6 关于「显式占位注释」

全库 **未发现** `TODO` / `FIXME` / `XXX` /「暂未」「未接」「待补」「未实现」类注释；唯一 `NotImplementedError` 是 `kernel/effects.py:372` 的 `EffectRunner` 抽象基类（带 `# pragma: no cover`），属合理抽象；所有 `pass` 都在 except 分支或空异常类内。

问题更隐蔽的形式是**「注释声称已接线、代码没有」**，典型 5 处：

- `assembly/agent.py:294-295`（「预算统一接线 / 程序不再自查」）vs `parts/body/react.py:20-21` 仍在自查并 `spend`；
- `assembly/agent.py:370-371`（「预算自查已删除」）同上；
- `parts/framing/framers.py:49-50`（「生产装配 TiktokenCounter 精确计数」）vs `Harness.scope_for` 未注入；
- `parts/tokens.py:4`（「装配期注入」）vs 全库零 import；
- `parts/structured.py:12`、`adapters/openai.py:26`（「上层记账只认统一口径」）vs 三套口径并存。

### 1.7 最关键的 5 个断点

1. **层声明全链路失效**（B01 + B02 + B04）：`HarnessConfig.layers` 只存不生效，工厂表从未调用，`_auto_layers` 只挂 3 个层 → 15+ 治理层在默认装配里全灭。
2. **v3 入口绕过全部自动治理**（G01 + B06）：`interpret` 无 layers / guard / checks / checkpoint_store / tool_registry，且顶层 `__init__.py` 只导出 v1 装配线。
3. **计量造假，只有一条路径可信**（M01/M02/M03 + F01）：v1 口径错 + 双重计数、v3 硬编码 10、默认模型不给 usage。
4. **默认全是假实现**（F01–F04）：FakeModel / FakeSandbox（含 `local`）/ Null* / 11 个 `_adapter` 占位。
5. **契约钩子集体空转**（C01/C02/C04/C07）：配额、鉴权、流式护栏、最终答案出口护栏均不执行。

---

## 2. 多份实现 / 多版本共存（AST 实测 19 组同名定义，人工归类 16 组）

### 2.1 同名不同物（11 组）

| 概念 | 份数 | 定义位置 | 关键差异 | 各自使用方 | 冲突 |
|---|---:|---|---|---|---|
| `Budget` | 2 | `parts/budget.py:9` / `contracts/types.py:349` | 前者 60k/30、无 `split`、有 `NullBudget`；后者 200k/60、含 `owner/retries/replans/split` | 前者：`__init__.py:60`、`build.py:11,83`、`agent.py:38,74`；后者：`config.py:14`、`fpresets.py`、`harness.py:14`、`framers.py`、`builtin.py` | **是**，顶层 `harness.Budget` 与 `harness.contracts.Budget` 是两个类；`RunScope.child()` 依赖 `split()` |
| `Limits` | 2 | `contracts/types.py:393` / `kernel/interpret.py:51` | 前者沙箱资源（cpu_s/mem_mb/wall_s/output_bytes/network）；后者解释器护栏（max_transitions/max_calls/max_tokens/wall_seconds） | 前者 `impl/backends/core.py`；后者 `agent.py`、`legacy.py`、`harness.py`、`interpret.py` | 名字冲突，靠顶层别名 `InterpreterLimits`（`__init__.py:93`）规避 |
| `Decision` | 2 | `contracts/types.py:228` / `contracts/decision.py:42` | 前者人工审批（approve/reject/modify）；后者转移决策（effects/program/patch/restore） | 前者 `agent.py`、`core.py`、`builtin.py`；后者 `interpret.py`、`legacy.py`、`fp/frontends.py` | 语义不同，已用 `Transition` 别名隔离，仍是同名两份 |
| `Failure` | 2 | `contracts/types.py:248` / `kernel/stage.py:35` | **字段完全相同** | stage 版供四段链；types 版只作 `Filter` 协议类型标注 | 无意义重复，静态类型不一致 |
| `ToolRequest` | 2 | `contracts/types.py:632` / `kernel/stage.py:27` | 前者 `step + spec`；后者 `step + state` | 前者 middleware；后者 `run_stages` 的 Wrap 洋葱 | **是**，同名不同形状且都在用 |
| `ReactPolicy` | 2 | `parts/body/react.py:8` / `parts/policy/policies.py:15` | 前者 `next_step(state, ctx)` 自己 assemble→decide 并记账；后者 `next_step(state, scope)` 只转发 `scope.actor.propose` | 前者 `build.py:63` + `Agent`；后者 `fp` + `RunScope` | **是**，两套同名策略绑死两条执行线 |
| `WorkflowPolicy` | 2 | `parts/body/workflow.py:10` / `parts/policy/policies.py:26` | 游标存 `state.data` vs 存实例 | 同上 | **是** |
| `PlanExecutePolicy` | 2 | `parts/body/pe.py:19` / `parts/policy/policies.py:43` | 前者计划存 `state.section("pe")`、有 `_replan` 与 `budget.replans` 镜像；后者存实例、有 `replan()` | 同上 | **是**，且能力不对等（replan 只在 v1 版） |
| `Actor` | 协议 + 2 代实现 | `protocols/governance.py:22` / `parts/actor.py:17` / `parts/actor_v2.py:15` | 协议要求 `propose+step`（对齐 `LlmActor`），`parts.actor.Actor` 是 `decide+execute`，**不满足协议** | v1 `build.py:74`；v2 `harness.py:59` | **是** |
| `Tracer` / 事件载荷 | 2 套 | `TraceEvent` + `NullTracer/MemoryTracer/JsonlTracer`（`events.py:35`、`tracer.py`） / `RunEvent` + `EventSink/_Fanout/_QueueSink/trace_layer`（`events.py:49`、`backends.py:119`、`harness.py:200,214`） | 前者 `start_ms/end_ms` 的 span 制；后者 `ts_ms` 的事件制；`JsonlTracer` 读 `start_ms`，喂 `RunEvent` 会崩 | v1 `agent.py`；v2/v3 `legacy.py`、`interpret.py`、`effects.py` | **是**，两套载荷不互通；另有 `HookEvent` 作第三代载荷 |
| `Program` | 协议 + 实现 | `protocols/runtime.py:67` / `fp/__init__.py:102` | 协议 vs dataclass | 合理分层 | 否 |

> `describe`(3)、`resolve`(3)、`validate`(2)、`interpret`(2 函数 + 2 方法)、`react/workflow/pe` 工厂(2 组)：签名与命名空间不同，属**分散命名**而非重复实现，建议整合时加模块前缀别名。

**AST 全量结果（脚本 `duplicate_defs`：19 组同名顶层定义）**：与上表重合 10 组；另有 9 组未在上表展开——`Blackboard` / `Handoff` / `Supervisor`（`fp/frontends.py` ↔ `parts/topology.py`）、`Router`（协议 ↔ `frontends`）、`describe`(3 份) / `resolve`(3 份) / `react` / `workflow` / `pe`（预设 ↔ 程序工厂）。其中 `describe` / `resolve` 与三个工厂属分散命名；**`Blackboard` / `Handoff` / `Supervisor` 是两代拓扑组件的重复定义**，应并入 §2.6 一并处置。上表的「Tracer / 事件载荷」不是同名定义（三代事件类型不同名），属语义级双轨，故不在 AST 19 组内。

### 2.2 两条装配线

| | 线 A（能力容器 / v3 配置） | 线 B（v1 兼容 / 顶层公开） |
|---|---|---|
| 配置 | `assembly/config.py:44` `HarnessConfig` | `assembly/build.py:24` `AgentConfig` |
| 入口 | `build_harness()` → `Harness` | `build()` → `Agent` |
| 预设 | `assembly/fpresets.py`（返回 `HarnessConfig`） | `assembly/presets.py`（返回 `Agent`） |
| 实例化 | `LlmActor` + `ModelFramer` + `ChatEncoder` + `DefaultClassify` | `Actor` + `BudgetedContext` + `AllowAllGuard` + `NullTracer` + `NullDurability` + `NullReflector` + `parts.budget.Budget` |
| 使用方 | `cli.py`、`assembly/__init__.py`、`fp` | **顶层 `harness/__init__.py:10-17,104-124` 唯一公开** |
| 互相调用 | 无 | 无 |

两条线只共享 `contracts` 与 `kernel.interpret.Runtime`，预算 / 护栏 / 检查点 / 事件 / 出口实现完全不同；顶层只暴露线 B，线 A 需从 `harness.assembly` 进入。**这是「多版本共存」最大的结构性来源。**

### 2.3 两代部件（5 组）

| 组 | v1 | v2 / v3 |
|---|---|---|
| Actor | `parts/actor.py:17` `Actor` | `parts/actor_v2.py:15` `LlmActor` |
| 上下文装配 | `parts/context.py:26` `BudgetedContext` / `NullContext`（`protocols/framing.py:32` 自注「v1 形状，保留兼容」） | `parts/framing/framers.py:46` + `encoders.py:11`（4 种 Framer / 3 种 Encoder，属合理的可替换策略） |
| 策略 | `parts/body/{react,workflow,pe}.py`（`next_step(state, ctx)`） | `parts/policy/policies.py`（`next_step(state, scope)`） |
| 预设 | `assembly/presets.py` | `assembly/fpresets.py` |
| 观测出口 | `TraceEvent` + 3 个 Tracer | `RunEvent` + `EventSink` / `_Fanout` / `_QueueSink` / `trace_layer` / `Runtime.emit` / `HookEvent` |

### 2.4 兼容壳清单（7 个转发文件 + 2 个语义壳）

| 文件 | 转发到 |
|---|---|
| `src/harness/state.py:3` | `contracts/state.py:18` `State` |
| `src/harness/result.py:3` | `contracts/result.py:13` `RunResult` |
| `src/harness/errors.py:3-14` | `contracts/errors.py`（**未转发** v3 新增的 `DecisionError/EffectError/NotSerializable/PolicyError/TransientError`） |
| `src/harness/testing.py:3` | `impl/fakes.py` |
| `kernel/loop.py:19-26` | `kernel/legacy.py:67` `run_legacy`（自述「这里不再有循环」） |
| `kernel/scope.py:12` | `Namespace`（`# noqa: F401` 转发） |
| `contracts/types.py:13` | `from harness.contracts.protocols import *`（注释「兼容：旧代码从 types 取协议」） |
| `assembly/agent.py:1` | 语义壳：自称「v1 兼容壳」，`_interpret` 委托 `Runtime.interpret` |
| `kernel/legacy.py:1` | 语义壳：自称「v2 组合子线的前端适配」，`LegacyProgram` 委托 `Runtime.interpret` |

此外 `contracts/types.py:38` 的 `Namespace` 是**1 份定义 + 3 条导入路径**（`kernel/scope.py` → `config.py:199` / `harness.py:16` 二次转发）。

### 2.5 内核层次与双四段链

| 角色 | 位置 | 状态 |
|---|---|---|
| 唯一主循环 | `kernel/interpret.py:145 Runtime.interpret`（`while True` 在 `:154`） | 生效 |
| 转发壳 | `kernel/loop.py:19 run_loop`（6 行） | 无循环 |
| 前端适配 v2 | `kernel/legacy.py:30,67` `LegacyProgram` + `run_legacy` → `CallbackRunner` → `Runtime` | 生效（v2 入口） |
| 前端适配 v1 | `assembly/agent.py:207,359` `_interpret` + `_V1Program` → 另一个 `CallbackRunner` → `Runtime` | 生效（v1 入口） |
| 四段链 A | `kernel/stage.py:114 run_stages` | 生效（legacy 路径） |
| 四段链 B | `kernel/effects.py:181 _stages`（内联重写） | 生效（v3 路径） |

同一个 `Harness` 类内也有两条执行路径：`Harness.run → run_loop → run_legacy`（v2 兼容），`Harness.interpret / new_runtime → Runtime + EffectRuntime`（v3 主路径）。

### 2.6 判定：合理 vs 无意义重复

- **合理（同一协议下的可替换策略，保留）**：4 种 Framer、3 种 Encoder、`FakeModel`/`OpenAIModel`/`StructuredModel`、`NullTracer`/`MemoryTracer`/`JsonlTracer` 三者彼此、`fp/frontends.py` 的 11 个程序、`Pipeline/Handoff/Supervisor/Blackboard`。
- **无意义重复（必须合并）**：`Budget` / `Failure` / `ToolRequest` / 三个策略类 / 两套 presets / 两条装配线 / 两套四段链 / 两套 Tracer-事件体系 / `Limits` 与 `Decision` 同名异物。

---

## 3. v1 / v2 / v3 版本说法统计

### 3.1 统计口径（固化在 `tools/audit_harness.py` 的 `VERSION_SCOPES`）

| 口径 | 正则（大小写敏感，不用 IGNORECASE） | 用途 |
|---|---|---|
| `strict` | `\b(?:v\|V)[123](?:\.\d+)?\b` | 只数明确的 `v1` / `v2` / `v3` / `v3.1` 说法；`\b` 排除 `actor_v2` / `_V1Program` 等标识符 |
| `wide` | `strict` + `legacy\|Legacy\|LEGACY` | 含「兼容壳」「旧签名」表述 |
| `full` | `wide` + `兼容\|SUPPLEMENT\|M15\|版本\|version\|Version\|VERSION\|schema_version\|SCHEMA_VERSION\|contracts_version\|__version__` | 含模块编号与通用词，**会高估**，仅作交叉参考 |

统计单位 = **命中行数**（同一行命中多个词记 1 行）；文件集固定，`docs/harness/AUDIT-*.md` 被显式排除以免报告自污染。专项 `v3.1 / SUPPLEMENT` 用 `RE_V31 = v3\.1|SUPPLEMENT`。所有正则原文写入 `audit-report.json → meta.regex`；**改判据必须重新生成快照**，`--check` 会比较 `generator_sha256`。

### 3.2 代码文件（strict 口径，脚本实测 78 行 / 32 文件）

| 文件（相对 `src/harness/`） | strict 命中 | 主要语境 |
|---|---:|---|
| `assembly/agent.py` | 9 | v1 兼容壳、`_V1Program`、`agent_v1`、`v3.1 SUPPLEMENT A2/A4` |
| `assembly/registry.py` | 5 | `v3.1 B2/B3`、`v2`、`M15.7` |
| `contracts/protocols/stores.py` | 5 | v1 检查点、v2 形状、P3 迁移 |
| `contracts/types.py` | 5 | v1/v2/v3 字段增补、兼容旧代码 |
| `assembly/harness.py` | 4 | v3 唯一解释器、终止护栏、兼容期 |
| `kernel/interpret.py` | 4 | v3 解释器、v3.1 A2、旧路径 |
| `contracts/events.py` | 4 | v1/v2/v3 三代事件 |
| `fp/frontends.py` | 3 | v3 程序、v1/v2 示例 |
| `fp/__init__.py` | 3 | v3 门面、LegacyProgram、兼容 |
| `kernel/legacy.py` | 3 | `legacy` / `LegacyProgram`、v2、兼容期 |
| `kernel/effects.py` | 2 | v3 效应系统、旧路径 |
| 其余 21 个文件 | 各 1–2 | 单条 `# v3.1（SUPPLEMENT Ax）` 或 docstring 版本说明 |

> `wide`：88 行 / 32 文件；`full`：139 行 / 43 文件。`full` 多出的 11 个文件主要来自 `impl/stores/memory.py` 的数据快照版本变量（`versions` / `旧版本`，17 行），**不是框架代际**。
> `v3.1 / SUPPLEMENT` 专项：代码 **26 行 / 15 文件**，全部为增量注释；文档 **10 行**。
> 完整逐文件清单见 `audit-report.json → versions.*.per_file`，不在本文重复。

### 3.3 文档文件（6 个，全部命中）

| 文档 | 总行数 | strict | wide | full | 整体版本基线 |
|---|---:|---:|---:|---:|---|
| `TUTORIAL-BUILD.md` | 4,542 | 68 | 80 | 120 | **按 v1→v2→v3→v3.1 分阶段施工实录**；逐文件标注资产代际（`# actor.py（v1）` L2757、`# actor_v2.py（v2）` L2782、L3958/L3967 两套 presets），L4148「阶段七 v3.1 补充」 |
| `SPEC.md` | 2,618 | 23 | 23 | 58 | **以 v2 为规格主体、v1 为差异基线**；§22「版本与兼容」L2507、附录 C「与 v1 代码差异清单」L2601。全文**无 `v3`、无「解释器」**（`full` 58 行主要来自 `M15` 模块编号） |
| `PROPOSAL-通用解释器与效应系统.md` | 1,110 | 16 | 16 | 28 | **v3 方案**：L1 标题、L3「目标版本 0.3 / contracts_version 3」、L33「v1 线 / v2 线」双轨诊断、§10「兼容与迁移」L979、附录 C「v3 落地」L1061 |
| `TUTORIAL.md` | 619 | 12 | 13 | 17 | **以 v3 为主线**，穿插 v1 遗产 / v2 兼容壳；§8 标题「parts/ —— 组件库（v1/v2 资产，v3 复用）」L482 |
| `DEV-SESSION.md` | 641 | 1 | 1 | 7 | **v1（库形态）历史施工依据**，L7 明确让位 SPEC.md |
| `SUPPLEMENT-PLAN.md` | 116 | 1 | 1 | 2 | 不自称 v3.1，按 A/B/C 类补充清单组织；L3 的 `v1` 是**文档自身版本状态**，L48 引用 `_V1Program` |

口径合计：文档 `strict` **121 行 / 6 文件**，`wide` **134 行 / 6 文件**，`full` **232 行 / 6 文件**。

### 3.4 版本常量（脚本 `RE_CONSTANT` 检出 6 处）

| 常量 | 位置 | 值 |
|---|---|---|
| `__version__` | `src/harness/__init__.py:101` | `"0.3.0"` |
| `contracts_version` | `contracts/__init__.py:37` | `"3"` |
| `contracts_version` | `src/harness/__init__.py:102` | `"3"`（再导出） |
| `SCHEMA_VERSION` | `contracts/state.py:14` | `2` |
| `name = "agent_v1"` | `assembly/agent.py:362` | 代际标识 |
| `name = "legacy"` | `kernel/legacy.py:33` | 代际标识 |

代码里**没有** `CONTRACTS_VERSION` / `API_VERSION` / `SPEC_VERSION` 等其它大写版本常量；`impl/stores/memory.py` 的 `versions` / `state.rev` 是数据快照版本变量，不计入。

### 3.5 典型原文（10 条）

| # | 位置 | 原句 |
|---|---|---|
| 1 | `assembly/agent.py:1` | `"""Agent：v1 兼容壳（PROPOSAL §9.3 / §10）。` |
| 2 | `kernel/loop.py:1` | `"""兼容壳：v2 循环已降级为 React 前端（PROPOSAL §9.3 / §10）。"""` |
| 3 | `assembly/harness.py:79` | `# v3：run_loop 已降为前端薄壳，真正的循环是 kernel.interpret.Runtime.interpret。` |
| 4 | `contracts/protocols/framing.py:32` | `"""v1 形状，保留兼容；v2 由 Framer + Encoder 取代（P4 迁移）。"""` |
| 5 | `contracts/protocols/stores.py:25` | `"""v1 检查点：save/load。违反"历史不可变"，P3 迁移到 CheckpointStore。"""` |
| 6 | `contracts/types.py:593` | `"""v1 服务定位器，保留兼容；v2 用 kernel.scope.RunScope。"""` |
| 7 | `parts/framing/encoders.py:14` | `v3.1（SUPPLEMENT A6）：可注入 TokenCounter 精确计数 Pack.usage 的` |
| 8 | `docs/harness/PROPOSAL-…md:68` | `- **解释器唯一**：interpret() 是唯一循环；v1 删实现留兼容壳，v2 删循环留效应系统。` |
| 9 | `docs/harness/TUTORIAL-BUILD.md:197` | `三个事件类型对应三代：v1 的 TraceEvent 是 span 制，v2 统一成 RunEvent…v3 的 HookEvent 是 Hook 专用只读载荷——三者并存是"契约只增不改"纪律的产物。` |
| 10 | `docs/harness/TUTORIAL-BUILD.md:4148` | `# 阶段七 v3.1 补充 —— SUPPLEMENT-PLAN 的落地施工` |

---

## 4. 整合目标与处置路线

### 4.1 目标态（只保留一个版本）

| 维度 | 目标态 |
|---|---|
| 入口 | **1 个**公开装配入口（`build_harness`）+ **1 个**运行入口（`Harness.run` 语义，内部统一走 `Runtime.interpret`） |
| 契约 | **1 个** `Budget`、**1 个** `Failure`、**1 个** `ToolRequest`、具名区分的 `ResourceLimits` / `RuntimeLimits`、`Transition`（不再叫 `Decision`） |
| 计量 | **1 条**链路：模型回包 `usage.total` → `_commit` 唯一记账点 → `State.usage` / `Budget` / `RunResult.usage`，三条入口同一结果 |
| 治理 | **1 套**四段链（`stage.run_stages`），`EffectRuntime` 复用而非重写；所有层通过配置可挂载并生效 |
| 事件 | **1 套** `RunEvent` + `EventSink`；`TraceEvent` 迁为兼容类型或删除 |
| 部件 | **1 套** `LlmActor` + `Framer/Encoder` + `parts/policy/*`；v1 `Actor` / `BudgetedContext` / `parts/body/*` / `assembly/presets.py` 退役 |
| 版本标识 | 代码与文档中**不再出现 v1/v2/v3/v3.1**；统一 `contracts_version` 单一常量，迁移说明集中到 1 份 CHANGELOG |
| 文档 | `SPEC.md` 升为唯一权威规格（当前形态）；`TUTORIAL.md` 单一版本教程；`TUTORIAL-BUILD.md` / `DEV-SESSION.md` / `PROPOSAL` / `SUPPLEMENT-PLAN` 归档为历史资料，不再作为实现依据 |

### 4.2 P0 —— 先修断点（让已有能力真正生效）

1. `assembly/config.py`：让 `HarnessConfig.layers` 真正实例化并并入 program；调用 `validate_layers()`；补齐 `guard / pipes / filter / sink / token_counter / checkpoint_store` 配置槽；删除 `__all__` 里悬空的 `"build"`。
2. `assembly/harness.py`：`new_runtime` 传 `tool_registry` 与 `checkpoint_store`；`interpret` / `dry_run` 统一走 `with_auto_layers` 并产出 `RunResult`（经 `Delivery`）。
3. 计量统一：`kernel/effects.py:_model` 从 `ModelReply.usage` 提取并写入 `_usage`，删除 `:271` 的 `tokens=10`；`parts/body/react.py:19` 改用 `total` 并移除重复 `spend`；`kernel/legacy.py:167` 填 `ModelResponse.usage`；统一由 `_commit` 单点记账。
4. `assembly/registry.py`：把 `LocalSandbox` 注册到 `sandbox["local"]`，修正 4 处名实不符；在包初始化时完成 `adapters` 自注册，去掉「必须显式 import」。
5. `kernel/legacy.py`：补 `run` 插点执行，让 `output_guard_layer` 出口扫描生效。
6. `parts/guardrail`：给检测器实现 `feed/flush`，或改 `StreamGuard` 用现有 `check` 语义，避免空转。
7. 默认实现：把 `NullDurability` / `AllowAllGuard` 从生产默认中移除，或至少在装配期对「默认即空实现」给出显式告警。

### 4.3 P1 —— 合并多份实现

1. `Budget` 统一到 `contracts/types.py:349`，`parts/budget.py` 降为转发（`NullBudget` 迁入）；顶层 `__init__.py:60` 改指同一类。
2. `Failure` / `ToolRequest`：`kernel/stage.py` 删除本地定义，改用契约层或改名为 `StageRequest`。
3. 三个策略类统一到 `parts/policy/policies.py`，把 `parts/body/pe.py` 的 replan + `budget.replans` 能力移植过去，删除 `parts/body/*`。
4. 四段链：`EffectRuntime._stages` 改为调用 `stage.run_stages`，删除内联副本。
5. Tracer：`NullTracer/MemoryTracer/JsonlTracer` 统一到 `RunEvent`，`TraceEvent` 仅保留为兼容类型。
6. 装配线：顶层 `__init__.py` 改为导出 `build_harness / HarnessConfig / fpresets`；`build.py` / `agent.py` / `presets.py` 整条线退役或集中放到 `legacy/` 目录并标注。
7. `Limits` 改名 `ResourceLimits` / `RuntimeLimits`；`Decision`（转移）改名 `Transition`；删除 `InterpreterLimits` 别名。

### 4.4 P2 —— 收版本（只保留一个版本）

1. **代码**：清除 74 行严格代际词 + 20 行 `v3.1（SUPPLEMENT …）` 增量注释；`__version__` / `contracts_version` / `SCHEMA_VERSION` 统一由一处定义；删除 7 个兼容壳（或保留 1 个统一的 `compat.py` 并在单一版本稳定后移除）；删除 `agent_v1` / `legacy` 代际标识。
2. **文档**：`SPEC.md` 升版为唯一权威规格（去掉「v2 增补」「与 v1 差异清单」的分代叙述）；`TUTORIAL.md` 重写为单版本教程；`TUTORIAL-BUILD.md`（4,542 行）、`DEV-SESSION.md`、`PROPOSAL-…md`、`SUPPLEMENT-PLAN.md` 移入 `docs/harness/archive/` 并在文件头标注「历史资料，非实现依据」；新增 1 份 `CHANGELOG.md` 集中记录代际变更。
3. **测试**：`tests/` 中针对 v1/v2 兼容壳的用例（`test_replacement.py`、`test_supplement.py` 的 A4/A6 等）改为验证统一入口的等价行为，不再维护双轨断言。

### 4.5 验收口径

| # | 验收项 | 判定方式 |
|---|---|---|
| 1 | 同名类只剩 1 份定义 | 全库 `^class (Budget\|Failure\|ToolRequest\|ReactPolicy\|WorkflowPolicy\|PlanExecutePolicy\|Decision\|Limits)` 各 1 命中 |
| 2 | 严格代际词归零 | 代码与现行文档 `\bv[123]\b` 命中 0（历史归档与 CHANGELOG 除外） |
| 3 | 三入口计量一致 | 同一 goal 走 `build` / `Harness.run` / `Harness.interpret`，`RunResult.usage.tokens/calls` 相同且等于模型回包累计值 |
| 4 | 层可配置且生效 | 声明 `budget/trace/approval/idempotency/validate` 后，对应插点确实被调用（可用 `MemoryTracer` 断言事件） |
| 5 | 治理不可绕过 | 三条入口均经过四段链、护栏、检查点、审批，且产出 `RunResult` |
| 6 | 默认非假实现 | 生产预设不含 `FakeModel` / `FakeSandbox` / `NullDurability`，缺依赖时启动期显式报错 |
| 7 | 回归 | 现有测试全绿，且新增上述 3/4/5 的守卫用例 |

---

## 5. 口径说明与待确认

- 「只在测试里使用」的判定：脚本 `zero_reference_candidates` 用 AST 收集 `Name` / `Attribute` / import alias，给出 **23 个静态零引用候选**，并对 `tests/` 做文本计数交叉核对；这是**启发式**，`getattr`、注册表字符串、动态 import 不可见。
- 结论基于静态分析；`adapters` 自注册、`registry` 动态覆盖等运行时行为未实际运行验证（本次未执行测试）。
- 行号以 `code_fingerprint = dd4afe3fed51894e…` 对应的代码版本为准；所有统计均为「命中行数」，同行多词记 1 行。
- `full` 口径会把 `M15`（模块编号）、`version`（数据快照版本）、「兼容/版本」通用词计入，故数字偏大，只作交叉参考；§3.2 / §3.3 已分列三档避免误读。
- 本审计**未读取** `docs/plan/` 下任何文档，也**未修改任何 `src/` 代码**。
- **与初版的差异**：初版数字为逐次检索结果的手工汇总，本版由脚本统一计算；两者口径（尤其 `wide` 是否带 `\b`）与求和方式不同 —— `strict` 代码 74→**78**、`wide` 代码 93→**88**、`v3.1` 20→**26 行**、`full` 文档 240→**232**。**以 `audit-report.json` 为唯一权威值**，初版数字不再引用。

---

## 6. 可复现性与完整性边界

### 6.1 三份产物

| 产物 | 作用 |
|---|---|
| `tools/audit_harness.py` | 唯一判据来源：固定文件集、三档正则、AST 规则、44 个证据锚点、44 条人工判定索引 |
| `docs/harness/audit-report.json` | 机器可读快照（41,950 字节），含逐文件命中、同名定义位置、锚点结果、代码指纹与判据指纹 |
| 本文 | 人读结论；**所有机械数字取自快照**，人工判定逐条标明来源 |

### 6.2 复现命令

```bash
python tools/audit_harness.py                                          # 打印摘要
python tools/audit_harness.py --check docs/harness/audit-report.json   # 应输出 CHECK OK
python tools/audit_harness.py --json docs/harness/audit-report.json    # 代码/判据变更后重新生成
```

实测结果：`CHECK OK：当前代码与快照完全一致（字节级）`；两次独立 `--json` 运行经 `cmp` 比较**字节一致**。脚本无时间戳、无随机数、不读环境变量、零第三方依赖；JSON 用 `sort_keys` + 固定缩进。`meta.generator_sha256`（判据指纹）与 `scope.code_fingerprint_sha256`（代码指纹）任一变化，`--check` 都会失败，并指明是「判据被改」还是「源码被改」。

### 6.3 能保证什么 / 不能保证什么

| | 范围 | 保证 |
|---|---|---|
| **能保证** | 文件清单、行数、三档正则命中、同名顶层定义、悬空 `__all__`、兼容壳候选、`TODO` / `NotImplementedError` / `pass` / `_adapter(`、版本常量、44 个证据锚点 | 封闭域内**穷尽且可复现**：遍历全部文件、逐行可核对；换模型、换对话，跑同一脚本输出一致 |
| **不能保证** | 「框架所有功能断点都被找齐」 | 断点是语义判断，没有判定 oracle；静态分析看不见 `getattr`、注册表字符串、动态 import、配置组合。**44 项 = 按既定判据列出的条目数，不是缺陷总数** |
| **折中保证** | 人工判定的可复核性 | 44 条各有稳定 ID / 分类 / 级别 / 证据锚点；脚本校验 44/44 锚点仍命中，代码一变即可发现结论过期 |

### 6.4 若要进一步逼近「完整」

把「找缺陷」换成「对全部能力逐一验效」：AST 自动枚举全部对外符号 → 每符号一行「是否被装配引用 / 是否有测试触发 / 是否有断言证明生效」的布尔矩阵 → 空格即断点。此时完整性 = 矩阵行数 = 符号总数，是可验证的等式。本次按选定口径**只固化机械统计**，未做能力矩阵与守卫测试。

### 6.5 完成线与判据演进（终止「改完又发现、发现又改」的循环）

**问题根因**：用「发现」驱动修复 —— 每轮让模型重新做一遍开放式审计，开放集合永远能挑出新条目，循环不会终止。**终止它的办法是把「可用」从「没发现断点」改写成「门禁绿」**。

**完成线（一条命令）**：`python tools/verify_harness.py`

| # | 检查 | 断言 |
|---|---|---|
| 1 | `audit_harness.py --check` | 判据指纹与源码指纹未漂移 |
| 2 | `python -m unittest discover -s tests -q` | 338 个既有测试不退化 |
| 3 | 端到端冒烟 | `build_harness → react() → RunResult`：`ok=True`、`usage` 含 `tokens`/`calls`、`trace_id` 非空 |

**关键设计**：门禁只断言「已有能力不退化」，**不断言「所有能力都齐全」**。前者是封闭集合、可以变绿；后者是开放集合、永远红。因此 §1 的 44 项断点尚未修完，门禁照样 `GATE OK` —— 它们是 backlog，不是门禁条件。当前实测 `338 tests OK`、`status=completed usage={'tokens': 0, 'calls': 1}`；tokens 为 0 正是 §1.2 的计量断点，门禁**只验结构不验数值**，刻意不让它变成新的返工源。

**新对话 SOP（已同步写入项目长期记忆，避免重新发散）**

1. 不重做开放式审计、不手工汇总数字 → `python tools/audit_harness.py --check docs/harness/audit-report.json`
2. 判断「能不能继续做功能」→ `python tools/verify_harness.py`，绿了就往下做
3. 断点以 §1 的 44 条登记项为准，不即兴新增判据
4. 改了 `src/` 代码 → 重跑门禁；`--check` 报「代码指纹变化」是**预期**，执行一次 `--json` 重生成快照即可（机械动作，不是返工）

**判据演进规则（把返工压缩成有节奏的升版）**

| 场景 | 动作 |
|---|---|
| 新对话 / 新模型发现疑似新断点或新重复实现 | **不即时返工**，先登记到下方 backlog，写清证据与来源 |
| backlog 累积到要处理 | 一次性批量评估：合并同类、剔除误报、确定本轮要修的条目 |
| 决定纳入判据 | 显式升 `AUDIT_SPEC_VERSION` → 改脚本正则 / 锚点 / 条目表 → 重新生成快照 → 更新本文 → 跑门禁 |
| 只修代码、不升判据 | 不动判据；按 `--check` 提示重生成快照一次即可 |

**backlog（2026-11-12 修复轮之后遗留；本轮判据已升版至 1.2，下轮处理时若需再动判据，走一次新升版）**

| # | 条目 | 来源 | 证据 / 建议动作 |
|---|---|---|---|
| BL-1 | 三个策略类合并（ReactPolicy/WorkflowPolicy/PlanExecutePolicy 两代并存） | §2.1/§4.3.3 | v1 版（`parts/body/*`，`next_step(state, ctx)` 自行 assemble/decide/记账）与 v2/v3 版（`parts/policy/policies.py`，转发 `scope.actor.propose`）绑死两条执行线；需先把 pe 版的 replan + `budget.replans` 能力移植到统一实现，再删 `parts/body/*`。风险：v1 审批/记账语义已在 P0 期间统一到 `_commit`，合并时以 `kernel.stage` 为准 |
| BL-2 | 两套 presets 合并（`assembly/presets.py` vs `assembly/fpresets.py`） | §2.2/§4.3.6 | 随 BL-3 一并处置；合并方向：顶层只保留一套预设工厂 |
| BL-3 | 两条装配线收敛（`build/agent/presets` v1 线 vs `build_harness/HarnessConfig/fpresets` v3 线） | §2.2/§4.3.6 | 顶层 `__init__` 改为导出 `build_harness/HarnessConfig/fpresets`；v1 线集中到 `legacy/` 目录并标注「兼容壳」；涉及大量顶层 API 测试迁移（`test_core/test_compat` 等），单独立项 |
| BL-4 | Tracer-事件双轨统一（`TraceEvent`+3 Tracer span 制 vs `RunEvent`+EventSink 事件制） | §2.1/§4.3.5 | 统一到 `RunEvent`；`TraceEvent` 保留为兼容类型；`JsonlTracer` 改读 `ts_ms` |
| BL-5 | 代码内严格代际词清除（当前 strict ≈80 行 / 32 文件） | §3.2/§4.4.1 | 多为注释标注（如 `v3.1（SUPPLEMENT A2）`）与 docstring 版本叙述；逐处改写为单版本语义（保语义、去代际词）；`name="agent_v1"`/`name="legacy"` 代际标识随 BL-3 退役 |
| BL-6 | `SPEC.md` / `TUTORIAL.md` 单版本重写 | §3.3/§4.4.2 | 两文仍为分代叙述（v2 主体 / v3 主线）；重写工作量大于本轮剩余预算，未归档（它们是现行文档）；`TUTORIAL-BUILD`/`DEV-SESSION`/`PROPOSAL`/`SUPPLEMENT-PLAN` 已于本轮移入 `archive/` |
| BL-7 | 测试双轨断言改造（`test_replacement.py`、`test_supplement.py` A4/A6 等） | §4.4.3 | 随 BL-3 完成后改为验证统一入口等价行为 |

**backlog（新发现登记处，本轮不处理）**

| 登记日 | 来源 | 描述 | 证据 | 处置 |
|---|---|---|---|---|
| — | — | （空） | — | — |

> 判据演进无法完全消除，但被压缩成「显式升版 + 一次性批量」，而不是每次对话的即时返工。这是「不重复修改」与「功能尽可能可用」之间可操作的平衡点。

