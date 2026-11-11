> **历史资料，非实现依据。** 本文按框架代际（v1/v2/v3/v3.1）记录当时的设计与施工过程；
> 现行唯一权威是 `docs/harness/AUDIT-断点-重复实现-版本说法统计.md`（§6.5 完成线）与 `audit-report.json` 快照。
> 单一版本口径见根 `CHANGELOG.md`。

# SUPPLEMENT-PLAN：harness 框架补充与强化计划

> 状态：规划文档（v1，2026-11-10）
> 依据：`outline/20-副线封装推导.md`（九插点/十五组件/R1–R7/替换实验）、`DEV-SESSION.md`（未决问题 §11）、`SPEC.md`（非目标 §1.1）、`archive-all:docs/audit/AUDIT-CODE-GAPS.md`、对 harness-only 分支源码的逐文件核查（结论日期 2026-11-10）。
> 范围：除 MCP 与 RAG 之外的全部缺口。MCP 与 RAG（QdrantIndex）已单列，见 B 类。

---

## 0. 一句话定位

框架把**执行内核 + 治理不变量**（解释器/效应系统/唯一提交点/审批/预算/幂等）做扎实了；缺口集中在三处：①契约留了钩子但实现断在半路（A 类）；②"接口在核心、实现放 extras"的决策只兑现了 Skills 一半（B 类）；③SPEC 非目标区的生态层需要在项目层补齐（C 类）。

---

## 1. 边界纪律（补充工作不得违反）

| 纪律 | 出处 | 含义 |
|---|---|---|
| 内核零依赖 | pyproject `dependencies=[]` | A 类改动不引入任何第三方依赖 |
| R2 只依赖契约 / R4 构造只在装配层 | 推导 §5.4 | 新组件只依赖 Protocol/dataclass，实例化只进 `build()` |
| R6 每个组件可离线测 | 推导 §5.4 | 每个真实现必须配 fake，并进 `tests/conformance.py` 一致性基类 |
| 非目标清单 | SPEC §1.1 | 跨进程 A2A、队列/限流/鉴权网关、UI 平台**不进框架** |
| 三棵树分离 | 推导 §5.6 | 评测体系是独立树，不塞进框架包 |
| 替换实验验收 | 推导 §5.3 | 任何补充的验收 = "换掉它只消失一件事" |

---

## 2. A 类：框架核心——契约留了钩子没接线（优先级最高）

> 判定标准：契约、类型、槽位已存在但无消费方。属于"违宪缺口"，不补则推导文档的承诺落空。

### A1 重规划：接上 `Verdict.replan_all`
- **证据**：`contracts/types.py:178` 定义 `action: Literal["accept","retry","patch","replan_all"]`；`types.py:355` 有 `replans: int` 计数器；但全库无任何代码消费 `replan_all`，`parts/body/pe.py` 无 replan 逻辑。
- **要做**：`PlanExecutePolicy` 循环内，Reflector 返回 `replan_all` 时回到 Planner 重出计划（带上已完成步骤与失败原因）；重规划次数计入 `state.replans` 并受上限约束。
- **DoD**：替换实验——`Reflector` 返回 `replan_all` 的场景，计划被重出且 `replans` 递增；`NullReflector` 时该路径不存在。

### A2 解释器级检查点落盘 + 通用崩溃恢复
- **证据**：`kernel/interpret.py:178` 的 `self.checkpoints` 仅内存列表；`assembly/agent.py` 的 `resume()` 只覆盖审批挂起路径；`durability.py` 每步 `save` 有但"从任意检查点重放"无入口。
- **要做**：`Runtime` 接受可插拔 `CheckpointStore`（复用 `Durability` 协议）；`Agent.resume()` 扩展为按 `session_id + rev` 重放；序列化沿 `to_spec()` 语义，闭包程序显式降级（不假装时间旅行）。
- **DoD**：kill 掉跑到一半的运行，从最近检查点续跑且幂等键保证已生效副作用不重复（"恢复是重放结论不是重新推理"，SPEC M11）。

### A3 分派层补齐 LLMRouter / VectorRouter
- **证据**：DEV-SESSION §2 四层表列了 `RuleRouter / LLMRouter / VectorRouter / AlwaysRoute` 四种；源码只有后两者（`parts/dispatch.py`），LLM/Vector 零命中。
- **要做**：`LLMRouter`（小模型意图分类）、`VectorRouter`（嵌入+向量库做意图路由，依赖 B3 的 IndexBackend 真实现）；含 fallback 兜底率统计。
- **DoD**：路由替换实验——`RuleRouter ↔ VectorRouter` 互换，下游行为一致，只有分流质量变化。

### A4 Budget 与解释器 Limits 接线统一
- **证据**：`assembly/agent.py:249-255` 硬编码 `Limits(max_calls=10**9, max_tokens=10**9, wall_seconds=300)`，预算靠 `_V1Program.transition` 每轮自查 `budget.exhausted`；wall-clock/调用数护栏实际未接预算。
- **要做**：`AgentConfig` 增加 limits 透传；`Budget` 的 token/calls 计数与 `Runtime._guardrail` 的四项护栏合并为单一口径。
- **DoD**：预算耗尽由解释器护栏触发（status=degraded），而非程序自查；双重计数消失。

### A5 结构化输出闭环
- **证据**：`adapters/openai.py` 支持 `response_format: json_schema` 透传；但无"pydantic 契约 + 校验失败自动重试"回路；工具 schema 推导（`parts/tools.py`）与结构化输出是两套。
- **要做**：`structured(model, schema) -> Model` 包装器：输出经 pydantic 校验，失败把校验错误回灌重试（次数可配），最终返回强类型对象。
- **DoD**：缺字段/类型错的响应被自动修复或明确失败；替换实验——换底层模型只改一行。

### A6 真实 token 计数
- **证据**：framing 层按字符估算（审计 ch3/ch17 双标记 P0/P1）；推导 §5.5 约束 5 要求"装配的账（占用与丢弃项）随 Pack 返回"，字符估算使账不可信。
- **要做**：`Framing` 的计数器抽象成协议，默认实现接 tiktoken（extra），fake 用字符估算（离线测试用）。
- **DoD**：`Pack.usage` 与厂商 usage 偏差可量化；离线测试走 fake。

---

## 3. B 类：adapters 层——"接口在核心、实现放 extras"（DEV-SESSION §11.5 已定调，只兑现了 Skills 一半）

| # | 任务 | 现状证据 | extra 名 | DoD |
|---|---|---|---|---|
| B1 | **QdrantIndex / PGVectorIndex**：实现 `IndexBackend` 协议（过滤下推、Namespace 隔离） | `registry.py:196` 槽位指向抛错的 `_adapter`；`impl/backends/core.py:MemoryIndex` 只是二元组打分 | `qdrant` / `pgvector` | 真 embedding 检索召回对比 fake；conformance 一致性通过 |
| B2 | **OpenAIModel 接进 registry** | `adapters/openai.py` 类是真实完整实现，但 `registry.py:110` 的 `openai` 槽位仍指向抛错占位——半截工程 | 已有 `openai` | `build()` 配 `model=openai` 真跑通 |
| B3 | **嵌入函数抽象 + bge 实现**：`Document.vector` 字段存在但全库无人写入/消费 | `contracts/types.py:477` | `embeddings` | 嵌入→B1 入库→检索全链路真跑 |
| B4 | **OTel / Langfuse Tracer adapter** | `otel` extra 声明零实现；`parts/tracer.py` 只有 Null/Memory/Jsonl | `otel` / `langfuse` | 一次 run 的 trace 树在 LangFuse 可见；观测失败不影响运行（SPEC M10.1） |
| B5 | **Docker Sandbox backend**：实现 `Sandbox` 协议 | `capability.py` 有 exec/kill 工具（argv-only、timeout、scopes）；SPEC M12 只承诺 Subprocess/FakeSandbox | `docker` | 无网络 + 资源限额 + 挂载白名单三项全部可验证 |
| B6 | **MCP bridge**：MCP client → 工具发现 → 转 FunctionTool（转换时标注 scopes/side_effects） | 全库零命中 | `mcp` | 框架治理链对 MCP 工具零改动生效；conformance 通过 |

> B1–B3 合起来 = RAG 全链路（切块→嵌入→入库→混合检索→rerank 另行在检索层补 BM25/RRF/rerank，归 B1 扩展）。

---

## 4. C 类：项目层——SPEC 非目标区 + 三棵树纪律（不进框架）

| # | 事项 | 为什么在项目层 | 对应知识点 |
|---|---|---|---|
| C1 | **评测体系**（独立树）：评测集管理、组件/轨迹/端到端三层指标、RAGAS、LLM-as-judge、回归门禁 | 推导 §5.6 明文"评测是独立树"；`archive:code/eval/run_eval.py` 是前身 | 卷三.7、卷五.5 |
| C2 | **A2A**：AgentCard/task 生命周期/Artifact 最小往返 | SPEC 明文非目标"不做跨进程 A2A" | 卷五.6 |
| C3 | **服务化交付**：FastAPI+SSE 进度流、队列、限流、审批网关 | SPEC 明文非目标 | 卷五.7、卷二 Loop 调度 |
| C4 | **框架对照**：LangChain/LangGraph 重写同一套，"两版行为一致" | 推导 §5.3 第五种装配形态的验收本就指向框架卷 | 卷五 |
| C5 | **吸收 forms/ 实验代码**：`loop_engineering/loop_core.py`、`graph_engineering/fanout_speedup|write_conflict|back_edge_limit` → program 层实验 | 这些代码本就按 Loop/Graph 知识点写好，不必重写 | 卷二 Loop、卷五 Graph |

---

## 5. 实施顺序（与 PatchPilot 项目里程碑对齐）

| 顺序 | 任务 | 项目里程碑 | 理由 |
|---|---|---|---|
| 1 | A4 预算接线 + A6 token 计数 | M1/M2 | 基础计量先行，后面一切实验数据依赖它 |
| 2 | A1 重规划 + A2 检查点/崩溃恢复 | M2 | Loop 工程核心；PatchPilot 长任务需要 |
| 3 | A5 结构化输出 | M2 | Plan/补丁/校验全链路契约的地基 |
| 4 | B1–B3 RAG 真实现 + A3 路由 | M3 | 卷三知识落点 |
| 5 | B5 Docker 沙箱 + B6 MCP | M4 | 卷四 Harness 落点 |
| 6 | B4 Langfuse/OTel + C1 评测体系 | M5 | 卷五观测/评测落点 |
| 7 | C2 A2A + C3 服务化 + C4 框架对照 | M5 后 | 收尾与对照实验 |

---

## 6. 总验收（照抄推导文档的纪律）

1. **替换实验**：A/B 类每项交付必须配一次替换实验——"换掉它只消失一件事"。
2. **离线可测**：每个真实现配 fake，双双通过 `tests/conformance.py`。
3. **内核零改动**：B 类全部通过既有协议插槽接入，`kernel/` 与 `contracts/` 一行不改（A 类除外——A 类本就是接线性质的最小改动）。
4. **每项一页 API 说明**：沿用 DEV-SESSION 的 DoD 四件套（示例能跑 + 离线单测 + 替换实验 + API 文档）。

---

## 7. 与 PatchPilot 的关系

见 `docs/plan/PatchPilot-项目设计.md`。PatchPilot 是 C 类的载体：A/B 类的每一项补充都在它的某个里程碑里被真实业务场景消费，避免"为补而补"；项目的 M1–M5 反过来为 A/B 类提供验收场景与量化数据（自愈率、pass@1、检索命中率、成本归因）。
