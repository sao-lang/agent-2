# 《Agent 与 Harness 工程》知识体系大纲（v3）

> 旧稿 00–62 章**全部作废**。旧稿只作为**知识点清单**的来源，不作结构来源。
>
> **v3 相对 v2 的修正**：
> 1. v2 按"章"合并，吞掉了十几个知识点（意图识别、槽位填充、语义缓存、SSE、限流、reducer、误杀率、SQL 守卫、索引类型、查询改写、置信区间、红队）。v3 改为**按知识点保真**：先列全 94 条知识点，再排章。
> 2. v2 没有说清**最终交付物的形态**。v3 立起全书的核心交付物：**一个零耦合、可组合的 Harness**。
> 3. v3 的组件划分**不是从任何现有代码推导的**，而是**从 Agent 的结构和一次 loop 的执行顺序推导**：Agent 本质是一个循环，循环上每个「必须做决定/必须查素材/必须防出错」的位置都需要一个组件，**挂不到具体插点的就不是组件**（见第五节）。

---

## 一、这本书交付什么

**读完能独立设计、实现、交付一个可组合的 Agent + Harness，并能解释每一个设计决定的取舍。**

| # | 交付物 | 怎么证明 |
|---|---|---|
| 1 | 能讲清机器 | 说得出"它为什么编 / 为什么忘 / 为什么停不下来" |
| 2 | **能装配运行时** | 不看代码，把 14 个组件按 loop 插点**组合**出一个 Harness；任意替换一个不影响其他 |
| 3 | 能判断取舍 | 拿到需求能说出走哪条路、为什么、成本上界 |
| 4 | 能交付并证明 | 系统可部署、可观测、可评测，出过事故能复盘 |

第 2 项是分水岭。现在这本书的问题是"读完能复述，但不能从零写出来"；而**写出来**的标准不是"能跑"，是"**换掉一个组件不影响其他组件**"。

---

## 二、四个同心层

```
④ 交付层   能部署 · 能观测 · 能评测 · 能复盘
③ 约束层   预算 · 护栏 · 沙箱 · 审批 · 幂等
② 运行层   循环 · 状态 · 工具 · 编排 · 记忆 · 路由
① 模型层   调用 · token · 提示 · 依据
```

Agent 的每个坏法都能追到内层：停不下来 → 模型不知道停（①）；上下文爆 → token 是硬约束（①）；状态丢 → 循环本身无记忆（②）；上线被绕过 → 约束不在模型里（③）。所以学习顺序必须由内向外。

---

## 三、七条主线能力

| # | 主线 | 学完的标志 |
|---|---|---|
| S1 | **模型心智** | 能预判一段提示词会怎么被带偏 |
| S2 | **上下文经济学** | 能对任意一次调用报出 token / 成本 / 延迟三个数并解释来源 |
| S3 | **循环与终止** | 能写出一个不会跑飞的循环 |
| S4 | **知识供给** | 能设计从文档到回答的完整链路，并对坏回答做归因 |
| S5 | **编排与范式** | 能对需求给出范式判断并说明代价 |
| S6 | **边界与耐久** | 能设计出"撞得住"的系统 |
| S7 | **度量与交付** | 能用一个数字证明某次改动变好或变坏 |

---

## 四、知识点全表

**每一行是一个不可替代的知识点，章只是它们的容器。**

### ① 模型层

| # | 知识点 | 必讲的内容 |
|---|---|---|
| A1 | 一次调用的完整生命周期 | messages→模型→usage→finish_reason→content；每步谁负责、哪里会坏 |
| A2 | `finish_reason` 决定一切 | `stop`/`length`/`tool_calls`/`content_filter` 各意味着什么，怎么分支 |
| A3 | 续写机制与幻觉 | 三种依据强度（有依据/弱依据/无依据）与对应策略 |
| A4 | token 计量与口径 | 汉字/英文/代码的估算偏差；必须用厂商 usage 校准 |
| A5 | 成本结构 | 输入 vs 输出定价差；缓存命中；按环节归因的前提 |
| A6 | 上下文窗口溢出 | 溢出时丢的是什么、丢在哪；预留 output token |
| A7 | 采样参数 | temperature/top_p 对稳定性的影响；结构化输出为什么要低温度 |
| A8 | 提示词六要素 | 角色/任务/约束/示例/输出格式/反例；哪些真正起作用 |
| A9 | 提示词回归测试 | 改一句怎么知道变好变坏；版本化与门禁 |

### ② 运行层

| # | 知识点 | 必讲的内容 |
|---|---|---|
| B1 | 工具定义与 `tool_calls` 解析 | 模型只输出"意图"，不执行函数；参数是 JSON 字符串 |
| B2 | 最小循环与终止条件 | while + 终止三态（答完/超步/空转） |
| B3 | 四种失控 | 无限循环/重复调用/上下文爆炸/成本击穿，各自的信号 |
| B4 | 重复检测（指纹） | 为什么 `sort_keys` 必需；15 行换最大收益 |
| B5 | 循环内上下文裁剪 | 单条消息级截断，不是整段丢弃 |
| B6 | 三种编排范式 | 固定工作流/ReAct/Plan-and-Execute 的判据、成本、边界 |
| B7 | 计划依赖与并发 | DAG 决定谁能并发；P&E 的计划审查价值 |
| B8 | 反思必须有外部裁判 | 纯自评为什么无效；裁判的三种来源 |
| B9 | 分级重规划 | retry/patch/replan_all 的触发条件 |
| B10 | State 设计 | 放什么不放什么；字段生命周期；schema 演进 |
| B11 | reducer 与并发写 | 并行分支为什么丢数据；累加 vs 覆盖 |
| B12 | 持久化与恢复语义 | checkpoint 存什么；恢复从哪一步继续 |
| B13 | 幂等与副作用重放 | 为什么恢复会发两封邮件；幂等键放哪 |
| B14 | MCP 三角色与治理 | Host/Client/Server；命名空间前缀；默认拒绝 |
| B15 | Skill 的完整构成 | `SKILL.md` + references/ + scripts/ + templates/ + tests/；不是只有一个 md |
| B16 | Skill 三级加载 | L1 元数据常驻/L2 正文命中才读/L3 资源执行时才读 |
| B17 | 触发判定 | description 三段式；召回 vs 误触发；留出集 |
| B18 | 能力编排与冲突 | 四类能力（RAG/工具/Skill/记忆）的边界；两个都能答时谁优先 |
| B19 | 工具收窄 | `allowed-tools` 怎么把可见工具数降下来 |
| B20 | 意图识别与路由 | 三级路由（规则→小模型→大模型）；置信度不是概率；幂等路由 |
| B21 | 兜底不是失败 | 兜底率监控；"该转人工却没转"的三种写法 |

### ③ 知识层

| # | 知识点 | 必讲的内容 |
|---|---|---|
| C1 | RAG 四环节 | 检索/拼装/生成/引用，各在哪一步坏 |
| C2 | 分块策略与混杂度 | 定长/标题/语义/父子；一个块混几个主题 |
| C3 | 混合检索与 RRF | 向量+BM25 为什么互补；融合公式 |
| C4 | 重排 | 只能重排"已召回的"；成本与收益 |
| C5 | 查询改写 | HyDE/多查询扩展；什么时候得不偿失 |
| C6 | 向量索引类型 | 暴力/HNSW/IVF 的取舍；过滤为什么必须在检索前 |
| C7 | 嵌入质量评估 | 用一个数字判断嵌入模型适不适合你的语料 |
| C8 | 上下文四槽位 | 系统/任务/记忆/检索的预算分配；压缩与丢弃顺序 |
| C9 | 短期记忆≠聊天记录 | 槽位（任务状态）与滑窗（对话）的区别；槽位误捕获 |
| C10 | 长期记忆三层 | 语义/情景/程序；租户隔离；软删除 |
| C11 | 文档生命周期 | 改/删/版本共存；索引重建时机 |
| C12 | 知识治理与 wiki | 条目结构（要点/例外/来源）；矛盾检测；可溯源率 |

### ④ 约束层

| # | 知识点 | 必讲的内容 |
|---|---|---|
| D1 | 沙箱四条边界 | 路径/网络/资源/时间；`resolve()` 与元数据地址 |
| D2 | 护栏必须是代码 | 为什么 prompt 里的"不要"不算护栏 |
| D3 | SQL 守卫 | `WITH ... DELETE` 这类绕过；白名单而非黑名单 |
| D4 | PII 与顺序 | 正则顺序错一个就漏（身份证在手机号前） |
| D5 | 误杀率与拦截率 | 两个数必须一起报；只报拦截率等于自欺 |
| D6 | 间接注入 | 检索文档里的"忽略之前的指令"；最容易忽略的缝 |
| D7 | 攻击面地图 | 绕过不发生在你以为的那一层；红队怎么打 |
| D8 | 分级审批 | 哪一步要人点头；审批卡片写什么；有效期 |
| D9 | 中断与恢复 | 关页面再回来继续；审批状态机 |
| D10 | 多 Agent 判据 | 什么时候拆划算；拆了成本怎么算 |
| D11 | 对外三种形态 | 同步 API/异步队列/流式；各自适用 |
| D12 | SSE 六件套 | 关缓冲（应用层+nginx）、心跳、断线、错误帧 |
| D13 | 队列/幂等/限流/鉴权 | 上线前四件套，每件的失败形态 |
| D14 | 优雅关闭 | `docker stop` 时手上的活；SIGTERM 直达（exec 形式） |
| D15 | 镜像分层与体积 | 多阶段构建；什么绝不能进镜像 |

### ⑤ 度量层

| # | 知识点 | 必讲的内容 |
|---|---|---|
| E1 | 计量 | 记什么（input/output/缓存/延迟）；`run_id` 还原调用树 |
| E2 | span 树 | trace_id/parent_id；为什么要落盘 |
| E3 | OTel 约定 | 语义化字段；接平台时对不上的根因 |
| E4 | RAG 评测 | 检索层与生成层分开评；三类样本；锚点映射 |
| E5 | RAGAS 四个指标 | faithfulness/answer relevancy/context precision/recall；怎么算出来的 |
| E6 | Agent 评测 | 四层（结果/轨迹/稳定/成本）；轨迹的四条硬判据 |
| E7 | LLM 裁判 | 怎么证明裁判可信；偏差与校准 |
| E8 | 多轮与 HITL 评测 | 单轮测不到的两类 |
| E9 | 置信区间与统计功效 | "95% 通过"是真的吗；多少次重复才够 |
| E10 | 门禁阈值 | 比率类看绝对差，其余看相对变化 |
| E11 | 成本归因与三级预算 | 钱花在哪；语义缓存的三条红线 |
| E12 | 延迟瀑布 | TTFT vs 总延迟；并行化；降级链 |
| E13 | 故障复盘 | 五问法；失败分类决定修复方向；MTTD/MTTR |
| E14 | 事故→回归用例 | 一次事故变成一条永不回归的测试 |

### ⑥ 框架层（独立成卷，逐 API 讲解）

| # | 知识点 | 必讲的内容 |
|---|---|---|
| F1 | 包结构与模型接入 | `init_chat_model` 参数矩阵；厂商包拆分；网关兼容；`with_structured_output` 三种策略 |
| F2 | 消息与内容块 | 四种消息类型；`content` vs `content_blocks`；`additional_kwargs`/`response_metadata`/`usage_metadata` |
| F3 | Runnable 协议与组合子 | `invoke`/`batch`/`stream`/`astream_events`；`|`/`Parallel`/`Passthrough`/`Lambda`/`Branch`/`WithFallbacks` |
| F4 | 输出解析与自愈 | 四个解析器 + `OutputFixingParser`/`RetryOutputParser` |
| F5 | 提示词模板 | `ChatPromptTemplate`/`MessagesPlaceholder`/`FewShotChatMessagePromptTemplate` |
| F6 | 工具定义与注入 | `@tool`/`BaseTool`/`StructuredTool`；`InjectedState`/`InjectedStore`/`ToolRuntime`；`bind_tools` |
| F7 | 检索组件 | `VectorStore` 接口；`as_retriever` 三种 `search_type`；`MultiQuery`/`ContextualCompression`/`Ensemble` |
| F8 | `create_agent` 全参数 | 12+ 个参数各管什么；`state_schema`/`context_schema`/`checkpointer`/`store` |
| F9 | 中间件机制 | 六个钩子；洋葱顺序；短路规则；自定义中间件的三个限制 |
| F10 | 19 个内置中间件 | 逐个讲参数与适用场景（限流、重试、摘要、HITL、PII、选工具、子代理、rubric…） |
| F11 | LangGraph 状态与 reducer | `Annotated[list, add]`；`MessagesState`；reducer 与并发写（接 B11） |
| F12 | 图与边 | `add_node`/`add_edge`/`add_conditional_edges`；`Send` 动态扇出；`Command` 跳转 + 更新 |
| F13 | 编译与运行时 | `compile(checkpointer=, store=, interrupt_before=)`；`Pregel` 超步；`Runtime`/`context_schema` |
| F14 | 函数式 API | `@entrypoint`/`@task`；与图 API 的取舍 |
| F15 | 持久化与时间旅行 | `Checkpointer` 家族；`thread_id`/`checkpoint_ns`；`get_state_history`/`update_state` |
| F16 | 流式 | 5 种 `stream_mode`；`astream_events` v2 字段 |
| F17 | Deep Agents | 内建的 9 个组件；subagents；permissions；sandboxes；skills；fault-tolerance |
| F18 | LlamaIndex 与其他框架 | `IngestionPipeline`/索引类型/`QueryEngine`/`Workflow`；pydantic-ai/AutoGen/CrewAI/OpenAI Agents SDK；平台化编排 |

### ⑦ 可选深水区

| # | 知识点 | 必讲的内容 |
|---|---|---|
| G1 | 何时该微调 | 判据；四个隐形代价；数据格式与对话模板 |
| G2 | LoRA/QLoRA | 改的是什么；三种"loss 好看但模型坏了" |
| G3 | 微调的评测与上线 | 合并导出、灰度、回归 |
| G4 | GraphRAG | 三类问题的判据；二部图 PPR；成本是普通 RAG 的 5–20 倍 |
| G5 | Harness 成熟度 | L1–L5；22 项能力自评 |

**知识点总数：A9 + B21 + C12 + D15 + E14 + F18 + G5 = 94 条。**

---

## 五、Harness 组件清单（从 Agent 结构推导）

**这一节不参考任何现有代码。组件从 Agent 的结构和一次 loop 的执行顺序长出来。**

### 5.0 推导起点：Agent 的四个结构事实

| # | 事实 | 推出什么 |
|---|---|---|
| **①** | Agent 的本质是**一个循环**：模型输出 →（可能）调用工具 → 结果回灌 → 再问模型 | Loop 是最小骨架，没有它就是一次性的单次调用 |
| **②** | 循环的每一步都在**做决定**（要不要调工具、调哪个、算不算完成） | 需要「决策」类组件 |
| **③** | 决定需要**素材**（工具清单、检索结果、历史、记忆） | 需要「供给」类组件 |
| **④** | 循环里每件事都**可能出错且不可逆**（跑飞、超预算、越权、断电） | 需要「治理」类组件 |

所以组件清单 = **循环骨架 + 三类插件**。这是自上而下的分类，但下面会自下而上验证：**每个组件必须挂到 loop 的一个具体位置。**

---

### 5.1 一次 loop 的执行顺序（组件的插点）

```
                        ┌─────────────────────────────────────────────┐
   请求进来 ──────────▶ │  ① 入口：这是什么请求？要做什么？             │
                        └──────────────────┬──────────────────────────┘
                                           ▼
                        ┌─────────────────────────────────────────────┐
                        │  ② 装配上下文：这一轮该让模型看见什么         │
                        └──────────────────┬──────────────────────────┘
                                           ▼
              ┌────────────────────────────┴────────────────────────────┐
              │                    Loop（循环体，反复执行）                │
              │  ┌──────────────────────────────────────────────────┐   │
              │  │ ③ 判断：够不够？要不要先拆成计划？                 │   │
              │  └──────────────────┬───────────────────────────────┘   │
              │                     ▼                                   │
              │  ┌──────────────────────────────────────────────────┐   │
              │  │ ④ 决策：下一步做什么？（回答 / 调工具 / 继续想）    │   │
              │  └──────────────────┬───────────────────────────────┘   │
              │                     ▼                                   │
              │  ┌──────────────────────────────────────────────────┐   │
              │  │ ⑤ 准入：这个动作允许吗？要不要人点头？             │   │
              │  └──────────────────┬───────────────────────────────┘   │
              │                     ▼                                   │
              │  ┌──────────────────────────────────────────────────┐   │
              │  │ ⑥ 执行：真的去调工具 / 真的去问模型                │   │
              │  │    ┌──────────────────────────────────────────┐  │   │
              │  │    │ Resilience：超时 → 重试 → 限流 → 熔断 → 降级 │  │   │
              │  │    └──────────────────────────────────────────┘  │   │
              │  └──────────────────┬───────────────────────────────┘   │
              │                     ▼                                   │
              │  ┌──────────────────────────────────────────────────┐   │
              │  │ ⑦ 校验：这一步做对了吗？整体达标了吗？             │   │
              │  └──────────────────┬───────────────────────────────┘   │
              │                     ▼                                   │
              │  ┌──────────────────────────────────────────────────┐   │
              │  │ ⑧ 记账：花了多少？走到了第几步？存档了吗？         │   │
              │  └──────────────────┬───────────────────────────────┘   │
              │                     ▼                                   │
              │              回到 ②（下一轮）或退出                      │
              └─────────────────────────────────────────────────────────┘
                                           ▼
                        ┌─────────────────────────────────────────────┐
                        │  ⑨ 出口：整理结果、留痕、交回               │
                        └─────────────────────────────────────────────┘
```

**这就是组件清单的来源**。每一个编号位置都需要一个组件，**位置之间不能共享代码，否则位置的概念就消失了**。

---

### 5.2 九个插点 → 十四个组件

| 插点 | 要回答的问题 | 组件 | 为什么必须独立 |
|---|---|---|---|
| ① 入口 | 这是什么请求？走哪条路？ | **Router** | 分流决策与执行分离，才能对简单请求跳过高成本路径 |
| ② 装配 | 这一轮让模型看见什么？ | **Context** | 窗口预算与召回质量是两件事，混在一起就无法归因 |
| ③ 判断 | 要不要先拆计划？ | **Planner** | 计划是「可审查、可修改的数据」；塞进决策里就无法 HITL |
| ④ 决策 | 下一步做什么？ | **Actor** | 唯一必需的组件；它只做执行，不做评估 |
| ⑤ 准入 | 允许吗？要人点头吗？ | **Guard** | 必须独立于决策：模型被说服了，Guard 不被说服 |
| ⑥ 执行 | 有哪些动作？怎么调？ | **Tools** | 能力注册与调用分离；执行后端（本地/沙箱/MCP）可替换 |
| ⑥ 执行 | 单次调用挂了怎么办？ | **Resilience** | 超时/重试/限流/熔断/降级共享同一份失败计数；拆开就要跨组件共享状态 |
| ⑦ 校验 | 做对了吗？没达标怎么办？ | **Reflector** | 必须能拿到**外部**证据；写在 Actor 里就只能自评。判定与修复共用同一个 `Verdict` |
| ⑧ 记账 | 还能继续吗？ | **Budget** | 被 ③④② 三处读取，任何一处持有都会造成反向依赖 |
| ⑧ 记账 | 发生过什么？ | **Tracer** | 跨全部插点，且必须能离线工作 |
| ⑧ 记账 | 崩了怎么续？ | **Durability** | 恢复是"重放结论"不是"重新推理"，不能被 State 承担 |
| 循环外 | 它记得住什么？ | **Memory** | 跨会话；与单次 loop 的 State 是不同生命周期 |
| 循环外 | 它凭什么知道？ | **Knowledge** | 召回质量独立于窗口预算 |
| 循环外 | 正确的流程是什么？ | **Skills** | 给流程；Tools 给能力。两者数量级与加载时机都不同 |

**共 14 个组件**。下表说明它们的归属与状态载体：

| 组件 | 归属 | 随 loop 变化？ | 需要持久化？ |
|---|---|---|---|
| Router | 入口 | 否（每次请求一次） | 否 |
| Context | 每轮 | **是** | 否（可重建） |
| Planner | 循环内 | 是（可重规划） | **是** |
| Actor | 循环内 | 是 | 否（结论进 State） |
| Guard | 循环内 | 否（无状态优先） | 否（决策留痕进 Tracer） |
| Tools | 循环外 | 否 | 否 |
| Resilience | 循环内（包住每次调用） | 是（失败计数、熔断档位） | 否（重启后归零可接受） |
| Reflector | 循环内 | 是 | **是**（改后的 Plan） |
| Budget | 横切 | **是**（累减） | **是** |
| Tracer | 横切 | 是（追加） | **是** |
| Durability | 横切 | 是 | **是**（它自己就是） |
| Memory | 循环外 | 否（跨请求） | **是** |
| Knowledge | 循环外 | 否 | 是（索引） |
| Skills | 循环外 | 命中时才读 | 否 |

**State 不是第 15 个组件**，它是"随 loop 变化且需要持久化"的那一列的**容器**。这是它最容易出错的地方：任何不属于上表"需要持久化=是"的东西，都不该进 State。

#### 为什么 Resilience 是一个组件而不是五个

超时、重试、限流、熔断、降级，五个机制共享同一份状态（最近失败了几次、当前档位、冷却到什么时候），且都只在**一次调用的局部**做决策，不改变 loop 走向。拆成五个组件，计数器就要跨组件共享——这正是耦合的来源。

主流框架把它们做成了三个平级中间件（`ModelRetryMiddleware` / `ModelFallbackMiddleware` / `ToolRetryMiddleware`），因为框架是"积木"思路；本书按**共享状态**归并，讲起来才有一条主线。

**顺序是有讲究的**（必须按这个顺序串）：

```
调用 ──▶ 超时 ──▶ 重试 ──▶ 限流 ──▶ 熔断 ──▶ 降级 ──▶ 真正发出
         (多久算挂) (挂了再试) (别打太快) (别打了)  (换一个打)
```

顺序错了会出真 bug：
- 熔断放在重试**外侧** → 每次重试都被重新判断，熔断永远触发不了；
- 降级放在重试**内侧** → 一失败就换 provider，重试形同虚设。

#### 一个必须区分清楚的重名

| 词 | 在哪 | 含义 |
|---|---|---|
| `retry`（Resilience） | 插点 ⑥ | **同一次调用**再试一次，参数不变 |
| `retry`（Reflector 的策略） | 插点 ⑦ | **这一步**重做，参数可能改 |

这是两个不同层级，也正是它们必须分属两个组件的理由。混淆会导致"重试了 3 次"到底是 3 次 HTTP 还是 3 次工具调用说不清。

---

### 5.3 能力 → 范式 → 部件（三层选择）

**Agent 的能力不是靠加组件获得的，而是靠三种选择。** 组件是固定的，能力是组合出来的。

#### 第一层：能力（会什么）

| 能力 | 由哪些组件共同提供 | 缺了它会怎样 |
|---|---|---|
| 会回答 | Actor + Context | 只能复述用户原话 |
| 会执行 | Actor + Tools | 只会说不会做 |
| 会查资料 | Knowledge → Context | 编造事实 |
| 会记住 | Memory → Context | 每次都从零开始 |
| 会守规矩 | Skills + Guard | 每次流程都不一样 / 会做不该做的事 |
| 会自己发现错 | Reflector（含修复策略） | "做完了"就是做完了 |
| 会拆解复杂任务 | Planner | 长任务走一步看一步 |
| 会分流 | Router | 所有请求付最贵的成本 |
| 会停下来 | Budget + 终止条件 | 跑飞 |

#### 第二层：范式（怎么组织这些能力）

| 范式 | 用的组件组合 | 适用判据 | 代价 |
|---|---|---|---|
| **单次调用** | Actor +(Context) | 一次问答能解决 | 无法多步 |
| **固定工作流** | 预定义顺序 + Tools + Guard | 步骤在设计期确定，运行时无分支 | 无法应对输入多样性 |
| **ReAct** | Actor + Tools + Budget + Context | 步数未知、需要边看结果边决定 | 成本不可预测 |
| **Plan-and-Execute** | Planner + Actor + Reflector | 多步、步骤间有依赖、需要先审查 | 计划可能不适用 |
| **Workflow Agent** | 图的节点/边 + 局部 ReAct | 大部分确定、少数地方需要灵活 | 需要写图 |
| **多 Agent** | 多个 Actor 实例 + 编排 | 子任务可独立、上下文需要隔离 | 通信与协调成本 |

> **关键**：范式不是组件，**是组件的接线方式**。装配同一个组件清单，换接线就是换范式。这就是为什么第 8 章能把三种范式放在一起讲——读者手上已经有全部零件。

#### 第三层：部件（每个组件的内部可选实现）

| 组件 | 可选实现（部件） | 选择依据 |
|---|---|---|
| Actor | **Provider 后端**：OpenAI / Anthropic / 自建网关 / 本地 Ollama / Fake（离线测试） | 成本、能力、合规 |
| Actor | **调用方式**：原生 tool_calls / 文本 ReAct 解析 | 模型是否支持原生工具调用 |
| Planner | 隐式（不拆）/ 显式 LLM 计划 / 模板计划 | 任务是否需要可审查 |
| Reflector | 空 / 规则裁判 / 测试裁判 / LLM 裁判；修复策略 retry / patch / replan_all | 有没有外部信号 |
| Context | 全量 / 滑窗 / 四槽位 / 摘要压缩 | 窗口够不够 |
| Knowledge | 向量 / BM25 / 混合 / 图 | 查询类型 |
| Tools | **Executor 后端**：本地函数 / 沙箱命令 / MCP 服务 | 副作用等级 |
| Resilience | 各机制的开关与阈值（见 5.2） | 哪一种失败最先发生 |
| Guard | 静态规则 / 动态策略 / 人工审批 | 后果可逆性 |
| Budget | 步数 / token / 金额 / 时间；**含缓存**（精确 / 语义） | 哪一种最先被击穿 |
| Durability | 无 / 文件 / 数据库 / 框架 checkpointer | 任务时长 |

**关于 Provider（换模型厂商）**：它属于 `Actor` 的部件，不是顶层组件。换 Provider 会改变四件事，必须在卷 1 第 3 章讲清：

| 会变的东西 | 后果 |
|---|---|
| token 口径 | 同一段中文，两家算出不同的数，成本报表全错 |
| `finish_reason` 取值 | 截断的判断逻辑要按家写映射 |
| 工具调用格式 | 参数是 JSON 字符串还是对象、并行调用怎么表达 |
| 缓存命中规则 | 输入前缀匹配的粒度不同，命中率差异巨大 |

**关于缓存**：它属于 `Budget` 的实现策略，不单列组件。理由：缓存唯一的作用是"少花一次钱、少等一次"，它不改变任何决策，也不被任何决策读取。单列会让 `Budget` 的定义变模糊；而"语义缓存的三条红线"本来就是成本问题。

**三层的关系**：

```
部件（怎么实现一个组件）
   ↑ 选
范式（怎么接这些组件）
   ↑ 选
能力（要做到什么）
```

**读者学完应该能回答**：我要的能力 → 需要哪些组件 → 用哪个范式接线 → 每个组件选哪个部件。**这就是"能自己写一个 Agent"的完整含义。**

---

### 5.4 依赖规则（"不耦合"的可操作定义）

| 规则 | 表述 | 违反的样子 |
|---|---|---|
| **R1 按插点分层** | 位置靠后的组件不 import 位置靠前的组件 | Guard import Actor 来判断"它要干什么" |
| **R2 只依赖契约** | 组件之间只依赖 Protocol / dataclass | `isinstance(x, LLMJudgeReflector)` |
| **R3 数据只走 State** | 跨组件传数据走 State，不做参数层层透传 | `actor.run(plan, ctx, mem, kb, budget, tracer)` |
| **R4 构造只在装配层** | 所有实例化集中在一个 `build(config)` | 组件内部 `Planner()` |
| **R5 治理不可选** | 一旦装配，任何路径都不能跳过 Guard/Budget/Tracer | "内部调用"绕过 Guard |
| **R6 每个组件可离线测** | 无模型、无网络能单测 | 测不了 = 耦合了 |

**契约集合**（6 个数据类型 + 8 个 Protocol）：

```
Goal  Route  Plan  Step  ActionResult  Verdict
──────────────────────────────────────────────
Router  : route(Goal) -> Route
Planner : plan(Goal, State) -> Plan
Actor   : step(Step, State) -> ActionResult
Reflector: review(ActionResult, Plan) -> Verdict | Plan   # Verdict 含 retry/patch/replan_all
Context : assemble(State, Budget) -> Messages
Guard   : allow(Step) -> Decision
Tool    : invoke(args) -> Result
```

---

### 5.5 组合证明：三种装配形态

| 形态 | 装哪些组件 | 获得的能力 | 对应章 |
|---|---|---|---|
| **A 最小** | Actor + Tools | 能调一次工具并回答 | 5 |
| **B ReAct** | A + Context + Budget + Tracer | 多步、不跑飞、可排查 | 6 |
| **C 完整** | 全部 14 个 | 生产形态 | 11 起 |

**验收方式**：第 5 章不是第 12 章的删减版，而是**同一骨架装了更少的组件**。

**替换实验**（每章必做一项）：
- `Reflector` → `NullReflector`：只有"自我纠错"消失；
- `Router` → `AlwaysRoute`：只有"分流"消失；
- `Knowledge` → `NullKnowledge`：只有"查资料"消失，退化成纯对话；
- `Planner` → `ImplicitPlanner`：从 P&E 退化成 ReAct。

**任何一次替换导致别的组件报错，就是耦合。**

---

### 5.6 组件清单的验收：它必须能生成一个真实系统

把清单拿去对照一个成熟的开源 harness（如 Deep Agents / Claude Code），检查是否一一对应。**对不上的地方，要么是本清单缺组件，要么是那个系统有冗余。**

| 本清单 | 成熟框架对应物 | 状态 |
|---|---|---|
| Router | 无内建（需自写） | 本清单更细 |
| Context | 自动压缩 / context editing 中间件 | 一致 |
| Planner | todo list 中间件 / 计划文件 | 一致 |
| Actor | 模型调用 + 工具节点 | 一致 |
| Guard | 权限 / HITL 中间件 | 一致 |
| Tools | 工具注册与执行 | 一致 |
| Reflector | rubric grading（Beta） | 一致 |
| Resilience | `ToolRetryMiddleware`/`ModelRetryMiddleware`/`ModelFallbackMiddleware` | 一致 |
| Budget | model/tool call limit 中间件 | 一致 |
| Tracer | 平台追踪 | 一致 |
| Durability | checkpointer | 一致 |
| Memory | 长期记忆存储 | 一致 |
| Knowledge | retriever | 一致 |
| Skills | skills 目录约定 | 一致 |

**结论**：14 个组件与主流 harness 的构成吻合。其中 `Router` 与 `Resilience` 在多数框架里**没有独立组件**（散落在中间件里或干脆没有），恰好是线上出问题最多的两个位置。

---

## 六、卷与章（94 个知识点装进 41 章）

> **每一卷都对应"把 loop 上的某些插点填满"**。章的顺序 = 组件的装配顺序。

### 卷 0 · 起点（第 0 章）
- 0.1 四个同心层｜0.2 七条主线｜0.3 **一次 loop 的九个插点与 14 个组件**｜0.4 能力→范式→部件三层选择｜0.5 结业项目与阶段｜0.6 三条阅读路径｜0.7 环境与代码约定

> 第 0 章就要给出 5.1 那张 loop 插点图和 5.2 的组件表。读者从第一页就知道自己在造什么、造到第几步。

### 卷 1 · 模型底座（第 1–4 章）→ A1–A9
**本卷产出**：`llm/`（调用与计量）+ **Provider 抽象层**——所有组件的共同地基，但它本身不是组件。

> 第 3 章必须讲透"换 Provider 会变哪四件事"：token 口径、`finish_reason` 取值、工具调用格式、缓存命中规则。这四件事不同步，成本报表和截断判断全错。

| 章 | 标题 | 知识点 |
|---|---|---|
| 1 | 一次调用的完整生命周期 | A1 A2 |
| 2 | 续写机器：它为什么编 | A3 A7 |
| 3 | token、窗口与成本 | A4 A5 A6 |
| 4 | 提示词：把要求变成可检查的约束 | A8 A9 |

### 卷 2 · 决策与执行：填满 loop 的插点 ③–⑧（第 5–12 章）→ B1–B19

**本卷产出**：Actor / Tools / Resilience / Budget / Tracer / Planner / Reflector / Durability / Skills

| 章 | 标题 | 知识点 | 新装的组件（插点） |
|---|---|---|---|
| 5 | 让它有手：Actor 与最小循环 | B1 B2 | **Actor**(④) + **Tools**(⑥) + State |
| 6 | 第一次调用就挂了：超时、重试与韧性 | B3（局部） | **Resilience**(⑥) |
| 7 | 停不下来：四道刹车 | B3 B4 B5 | **Budget**(⑧) + **Tracer**(⑧) ＋ Resilience 补全（限流/熔断/降级） |
| 8 | 路径该由谁定：三种编排范式 | B6 B7 | **Planner**(③)（含 `ImplicitPlanner`） |
| 9 | 错了怎么自己发现：裁判与修复 | B8 B9 | **Reflector**(⑦)（含 retry/patch/replan_all） |
| 10 | State：放什么、怎么写不坏 | B10 B11 | State 的契约与 reducer |
| 11 | 断了怎么办：持久化与幂等 | B12 B13 | **Durability**(⑧) |
| 12 | 工具生态：MCP、Skill 与能力编排 | B14 B15 B16 B17 B18 B19 | **Skills** + 工具收窄 + 冲突裁决 |

> 第 12 章偏重（6 个知识点），见第十一节。

**卷 2 结束时已装 9 个组件，能跑生产任务**，但只能处理"不需要外部知识、不需要查边界"的任务。

### 卷 3 · 素材与分流：填满插点 ①② 与循环外的供给（第 13–18 章）→ B20 B21 C1–C12

**本卷产出**：Router / Knowledge / Context / Memory

| 章 | 标题 | 知识点 | 新装的组件（插点） |
|---|---|---|---|
| 13 | 意图识别与路由 | B20 B21 | **Router**(①) |
| 14 | RAG 最小闭环 | C1 | **Knowledge**(循环外) |
| 15 | 分块与向量检索 | C2 C6 C7 | Knowledge 内部实现 |
| 16 | 检索质量：混合、重排、改写 | C3 C4 C5 | Knowledge 内部实现 |
| 17 | 上下文工程与短期记忆 | C8 C9 | **Context**(②) |
| 18 | 长期记忆与知识治理 | C10 C11 C12 | **Memory**(循环外) |

> **意图识别单独成章**：它是**请求进入系统后的第一个决策**（Router 组件），既不属于检索也不属于记忆，且含兜底率监控、幂等路由、置信度陷阱这些极易被吞掉的细节。
>
> **Knowledge 与 Context 分开两章**：召回质量与窗口预算分开归因，是卷 3 验收方式（对坏回答做归因）的结构前提。


### 卷 4 · 边界：填满插点 ⑤ 与执行后端（第 19–24 章）→ D1–D15

**本卷产出**：Guard + Tools 的执行后端 + 部署层

| 章 | 标题 | 知识点 | 新装的组件 / 层 |
|---|---|---|---|
| 19 | 沙箱：它能碰什么 | D1 | Tools 的执行后端 |
| 20 | 护栏：把"不要"写成代码 | D2 D3 D4 D5 | **Guard**(⑤) |
| 21 | 防绕过：用户和文档都会骗它 | D6 D7 | Guard 的输入面 |
| 22 | 人机协作：哪一步必须有人点头 | D8 D9 | Guard 的审批态 + Durability 的中断态 |
| 23 | 多 Agent：拆了为什么更慢更贵 | D10 | 认知族的多实例装配 |
| 24 | 交付：从能跑到能上线 | D11 D12 D13 D14 D15 | 部署层（不属于组件） |

> 卷 4 是**唯一"只加约束、不加能力"**的卷。装配完，Harness 从"能跑"变成"撞得住"。

### 卷 5 · 度量：验证插点 ⑧ 是否真的生效（第 25–29 章）→ E1–E14

**本卷产出**：Tracer 完整实现 + `eval/`

| 章 | 标题 | 知识点 | 对应的组件 |
|---|---|---|---|
| 25 | 计量与可观测 | E1 E2 E3 | **Tracer**(⑧) 完整实现 |
| 26 | RAG 评测与 RAGAS | E4 E5 | Knowledge 的外部验证 |
| 27 | Agent 评测 | E6 E7 E8 | 整个 Harness 的外部验证 |
| 28 | 统计与门禁 | E9 E10 | 评测的方法论 |
| 29 | 成本、延迟与故障复盘 | E11 E12 E13 E14 | Budget 的报表侧 + 复盘方法 |

> 评测按你的要求拆三章：RAG 评测（含 RAGAS）、Agent 评测、统计与门禁。
>
> **卷 5 的特殊地位**：它不是加组件，而是**验证前四卷装的组件是否真的生效**。Tracer 是唯一在本卷才写完实现的组件（卷 2 只是骨架）。

### 卷 6 · 框架与平台（第 30–37 章）→ F1–F18

> **这一卷的定位**：前五卷你手写了一个 14 组件的 Harness。这一卷回答"**生产项目里为什么通常直接用框架**"，并且**逐个 API 讲到位**。
>
> 写法要求：每个 API 必须给出 **① 签名/参数表 ② 最小可跑例子 ③ 它替掉了你手写的哪个组件 ④ 它的边界（做不到什么）**。不允许出现"某某框架很好用"这种句子。

| 章 | 标题 | 讲哪些 API（逐项） |
|---|---|---|
| **30** | LangChain 基础：包结构、模型与消息 | `init_chat_model` 的参数矩阵（`model`/`model_provider`/`temperature`/`max_tokens`/`timeout`/`max_retries`）｜各厂商包拆分（`langchain-openai`/`-anthropic`/`-ollama`/网关兼容写法）｜消息类型（`SystemMessage`/`HumanMessage`/`AIMessage`/`ToolMessage`、`content_blocks` vs `content`、`additional_kwargs`/`response_metadata`/`usage_metadata`）｜`invoke`/`stream`/`batch`/`ainvoke` 四件套｜结构化输出 `with_structured_output` 的三种策略 |
| **31** | LangChain 组合：LCEL 与输出解析 | Runnable 协议（`invoke`/`batch`/`stream`/`astream_events`）｜组合子 `|`、`RunnableParallel`、`RunnablePassthrough`、`RunnableLambda`、`RunnableBranch`、`RunnableWithFallbacks`｜`assign`/`pick`/`bind`｜解析器 `StrOutputParser`/`JsonOutputParser`/`PydanticOutputParser`/`XMLOutputParser` + `OutputFixingParser`/`RetryOutputParser`｜`PromptTemplate`/`ChatPromptTemplate`/`MessagesPlaceholder`/`FewShotChatMessagePromptTemplate` |
| **32** | LangChain 工具与检索 | `@tool` 装饰器（docstring→description、类型注解→schema、`args_schema`）｜`BaseTool` 与 `StructuredTool`｜`InjectedState`/`InjectedStore`/`ToolRuntime` 注入｜工具错误处理与 `return_direct`｜`bind_tools`/`tool_choice`｜检索侧：`Document`/`DocumentLoader`、`RecursiveCharacterTextSplitter` 参数、`VectorStore` 接口、`as_retriever` 的 `search_type`（similarity/mmr/similarity_score_threshold）、`MultiQueryRetriever`/`ContextualCompressionRetriever`/`EnsembleRetriever` |
| **33** | LangChain Agent：`create_agent` 与中间件（最重的一章） | `create_agent` 全部参数（`model`/`tools`/`system_prompt`/`middleware`/`response_format`/`state_schema`/`context_schema`/`checkpointer`/`store`/`interrupt_*`/`name`/`debug`）｜**中间件机制**：`before_model`/`after_model`/`wrap_model_call`/`wrap_tool_call`/`before_agent`/`after_agent`，洋葱顺序与短路规则｜**19 个内置中间件逐个讲**：`ToolErrorMiddleware`、`ToolRetryMiddleware`（`on_failure` 三档）、`ModelRetryMiddleware`、`ModelFallbackMiddleware`、`SummarizationMiddleware`、`HumanInTheLoopMiddleware`、`ModelCallLimitMiddleware`、`ToolCallLimitMiddleware`（`exit_behavior` 三档）、`PIIDetectionMiddleware`、`TodoListMiddleware`、`LLMToolSelectorMiddleware`、`ProviderToolSearchMiddleware`、`ShellToolMiddleware`、`FilesystemMiddleware`、`SubagentMiddleware`、`RubricGradingMiddleware`、`FileSearchMiddleware`、`ContextEditingMiddleware`、`LLMToolEmulatorMiddleware`｜自定义中间件的三个限制 |
| **34** | LangGraph 基础：状态、图与边 | `StateGraph`/`MessagesState`｜`State` 的类型注解与 `Annotated[list, operator.add]` reducer（`add_messages`/`add`/自定义）｜`add_node`/`add_edge`/`add_conditional_edges`/`START`/`END`｜`compile()` 与 `compile(checkpointer=, store=, interrupt_before=, interrupt_after=)`｜`Pregel` 超步语义｜`Send`（动态扇出）、`Command`（节点内跳转 + 更新状态）｜`Runtime` 与 `context_schema`｜函数式 API `@entrypoint`/`@task`（与图 API 的取舍）｜`create_react_agent` 已废弃 → 迁移到 `create_agent` |
| **35** | LangGraph 进阶：持久化、流式与 HITL | `Checkpointer` 家族（`InMemorySaver`/`SqliteSaver`/`PostgresSaver`）｜`thread_id`/`checkpoint_id`/`checkpoint_ns`｜`get_state`/`get_state_history`/`update_state`（时间旅行与分叉）｜`interrupt()` + `Command(resume=...)` 做审批｜`Store`（`put`/`get`/`search`，跨 thread 长期记忆）｜流式 5 种 `stream_mode`（`values`/`updates`/`custom`/`messages`/`debug`）+ `astream_events` v2 字段｜子图与 `Subgraph` 命名空间｜多 Agent 三种拓扑（supervisor/swarm/handoff） |
| **36** | Deep Agents 与 LlamaIndex | **Deep Agents**：`create_deep_agent` 的 `middleware` 定制面｜todo list、虚拟文件系统、subagents（同步/异步/动态）、`permissions`、`sandboxes`、`backends`、`Skills`、`Memory`、`context-engineering`、`fault-tolerance`、`rubric`｜它能直接替掉本书的哪 9 个组件｜**LlamaIndex**：`IngestionPipeline`（transformation 链）、`SentenceSplitter`/`SemanticSplitterNodeParser`、`VectorStoreIndex`/`SummaryIndex`/`KeywordTableIndex`、`QueryEngine` 与 `Retriever` 的区别、`NodePostprocessor`、`Workflow`（事件驱动）｜两条路线的选择依据 |
| **37** | 其他框架与平台化编排 | pydantic-ai（依赖注入 `RunContext`、`output_type`、`@agent.tool`）｜AutoGen（`AssistantAgent`/`GroupChat`/speaker selection）｜CrewAI（`Agent`/`Task`/`Crew`/`Process`）｜OpenAI Agents SDK（`Agent`/`Runner`/`handoff`/`guardrail`/`session`）｜MCP 官方 SDK｜**平台化**：Coze/Dify 的节点类型、界面上看不见的三类状态（上下文窗口、索引版本、节点级计量）、成本上界 |

**卷 6 的验收**：给你一个真实需求（例如"支持 30 个工具的客服 Agent，需要审批和断点续跑"），你能说出**用框架的话每个组件对应哪个类、还需要自己写哪些**。

**框架卷与手写组件的对照表**（附录 E 的正文版，每章都要填一行）：

| 手写组件 | LangChain | LangGraph | Deep Agents | LlamaIndex |
|---|---|---|---|---|
| Router | 无 | 条件边 | 无 | RouterRetriever |
| Context | `SummarizationMiddleware`/`ContextEditingMiddleware` | 自定义节点 | 自动压缩 | `ChatMemoryBuffer` |
| Planner | `TodoListMiddleware` | 图结构 | todo list | 无 |
| Actor | `create_agent` 的 model node | `add_node(agent)` | 内建 | `Workflow` 步骤 |
| Guard | `HumanInTheLoopMiddleware`/`PIIDetectionMiddleware` | `interrupt()` | `permissions` | 无 |
| Tools | `@tool`/`BaseTool` | `ToolNode` | `tools` | `FunctionTool` |
| Reflector | `RubricGradingMiddleware` | 自定义节点 | `rubric` | 无 |
| Resilience | 三个重试/降级中间件 | 自定义 | 部分内建 | 无 |
| Budget | `ModelCallLimitMiddleware`/`ToolCallLimitMiddleware` | 自定义 | 无 | 无 |
| Tracer | LangSmith | LangSmith | 内建 | 无 |
| Durability | checkpointer | `Checkpointer` 家族 | `fault-tolerance` | 无 |
| Memory | `BaseStore` | `Store` | `Memory` | `ChatMemoryBuffer` |
| Knowledge | Retriever 链 | `ToolNode` 包装 | `retrieval` | `QueryEngine` |
| Skills | 无（约定） | 无 | `Skills` | 无 |

### 卷 7 · 可选深水区（第 38–41 章）

| 章 | 标题 | 知识点 |
|---|---|---|
| 38 | 何时该微调 | G1 |
| 39 | LoRA / QLoRA 与上线 | G2 G3 |
| 40 | GraphRAG | G4 |
| 41 | Harness 成熟度自评 | G5 |

**合计：41 章（含第 0 章）。**

### 章节 → 组件的最终对照

| 卷 | 主题 | 本卷装上的组件 | 累计 |
|---|---|---|---|
| 1 | 模型底座 | 无（地基 `llm/`） | 0 |
| 2 | 决策与执行（第 5–12 章） | Actor、Tools、Resilience、Budget、Tracer(骨架)、Planner、Reflector、Durability、Skills | 9 |
| 3 | 素材与分流（第 13–18 章） | Router、Knowledge、Context、Memory | 13 |
| 4 | 边界（第 19–24 章） | Guard | 14（+ 部署层） |
| 5 | 度量（第 25–29 章） | Tracer 完整实现 | 14 |
| 6 | 框架（第 30–37 章） | 不新增（逐 API 对照） | 14 |
| 7 | 可选（第 38–41 章） | 不新增 | 14 |

> 组件数 14。第 0 章那张 loop 图必须与本表一致。
>
> **每章开头必须写清两件事**：① 覆盖 A–G 里哪几条知识点 ② 装上 loop 的第几个插点的哪个组件。


---

## 七、知识依赖图

```
卷0 地图（含 14 组件总图）
  │
  ▼
卷1 模型底座(A1–A9)                     ← 地基 llm/
  │
  ▼
卷2 认知族(B1–B19)                       ← 装 Actor 等 9 个组件
  │
  ▼
卷3 供给族(B20–C12)                      ← 装 Router/Knowledge/Context/Memory
  │
  ▼
卷4 治理族(D1–D15)                       ← 装 Guard + 部署层
  │
  ▼
卷5 度量(E1–E14)                         ← 验证前四卷，补完 Tracer
  │
  ▼
卷6 框架(F1–F18)                         ← 逐 API 对照：你写的 X 在框架里是 Y
  │
  ▼
卷7 可选(G1–G5)
```

三条不可颠倒的边：
1. 卷 1 必须在卷 2 前——不理解"它会编"，看不懂第 9 章为什么要裁判。
2. 卷 2 必须在卷 3 前——记忆是往 State 里写，没有 State 就没地方放。
3. 卷 5 必须在卷 4 后——先有可观的量，再谈"证明变好了"。

卷 6 放在卷 4/5 之后：框架的持久化、中间件、reducer 只有手写过才看得懂。

---

## 八、结业项目（社区主流方向）

我查了 GitHub topic 星标与 Trending（数据见第十一节）。当前主流不是"售后问答"，而是三类：

| 方向 | 证据 | 能覆盖的主线 |
|---|---|---|
| **Coding Agent / Harness** | `openinterpreter` 68.7k、`Codewhale` 41.1k、`DeepSeek-Reasonix` 36.0k、`qwen-code` 28.7k、`planning-with-files` 27.7k、`jcode` 21.2k；周榜前十有 `opencode`、`orca`、`security-audit-skill` | **最全**：循环、工具、状态、Skill、沙箱、审批、评测、trace 全用得上；且**有天然裁判（测试）** |
| **Deep Research Agent** | `deer-flow` 84.4k、`BettaFish` 42.5k、`DeepResearch` 20.1k、`deep-searcher` 8.3k | RAG + 多 Agent + 长任务 + 引用溯源 + 成本 |
| **Computer Use / Browser Agent** | `browser-use` 119.2k、`UI-TARS-desktop` 39.4k、`cua` 31.0k、`Agent-S` 12.8k | 沙箱 + 视觉接地 + HITL + 失败恢复 |

### 主项目：Coding Agent（仓库级改造）

- 输入：一句话需求 + 一个真实仓库
- 流程：定位代码 → 改 → 跑测试 → 修失败 → 出 diff
- 为什么是它：
  - **有天然裁判**（测试），正好落地 B8「反思必须有外部裁判」
  - **有天然副作用**（改文件、跑命令），沙箱与审批是必需品而非装饰
  - **是天然长任务**（几分钟到几十分钟），逼你实现 B12/B13
  - **天然可评测**（pass@k、diff 质量、步数、成本）
  - 当前就业面最宽

### 对照实验（成本很低，必须做）

同一个 Harness，只换工具集和提示词，变成 Deep Research 与 Browser Agent。用来证明"Harness 是可复用骨架"，这正是本书核心论点。

### 分阶段交付（与卷、组件对应）

| 阶段 | 对应卷 | 新增组件 | 交付物 | 验收 |
|---|---|---|---|---|
| P1 | 卷 1 | —（地基 `llm/`） | 能算成本、能稳定解析的一次调用 | 报出任意请求的三个数 |
| P2 | 卷 2 | Actor·Tools·Resilience·Budget·Tracer·Planner·Reflector·Durability·Skills | **自己写的** Agent 运行时（无框架） | 四种失控各被拦一次 |
| P3 | 卷 3 | Router·Knowledge·Context·Memory | 接上仓库检索、Skill 与记忆 | 对失败 patch 能归因到具体组件 |
| P4 | 卷 4 | Guard + 部署层 | 沙箱 + 护栏 + 审批 + 容器化 | 一次越权被拦 + 一次中断恢复 |
| P5 | 卷 5 | Tracer 完整实现 + `eval/` | trace + 评测（含 RAGAS 与 Agent 四层） | 一份带置信区间的对比报告 |
| P6 | 卷 6 | 不新增 | 用 LangGraph 重写 P2→P4 的同一套 | 两版行为一致，代码量对比 |
| P7 | — | — | **3 份失败复盘** | 做错 → 定位 → 修好 → 回归验证 |

P7 是毕业线。

**结业项目必须体现可组合**：答辩时要能当场做一次**替换实验**——把 `Reflector` 换成 `NullReflector`、把 `Knowledge` 换成 `NullKnowledge`，系统仍能运行，只有对应能力消失。

---

## 九、每章统一写法（五段）

| 段 | 回答 | 不合格的样子 |
|---|---|---|
| 1. 缺了它会怎样 | 没有这个机制，系统会怎么坏 | "某某技术非常重要" |
| 2. 机制 | 为什么坏 | 直接贴代码不给因果 |
| 3. **装哪个组件** | 这一节结束时，骨架里多了什么 | 独立脚本，接不上上一章 |
| 4. 边界 | 什么时候别这么做 | 没有反例 |
| 5. 弄坏它 | 自己动手复现一次失败 | 只有"练习题" |

**删掉**：章首术语表（术语就地解释，汇总进附录）、"本章产出/验收标准/遗留问题"三节、标题里的 ★ 与一串顿号、重复 30 次的"先看一个具体的坏事 / 为什么现有手段不够"。

---

## 十、写作规则

| 规则 | 手段 |
|---|---|
| 数字必须有出处 | 正文数字要么由 `code/` 跑出，要么删掉改成判断依据 |
| 模拟必须标注 | 规则模拟的"模型表现"首次出现处写明"机制演示，不是实测" |
| **代码只往上加** | 全书一条连续的骨架；每章只在 loop 上**新增一个组件**，不改已有组件 |
| **每个组件必带单测** | 没有模型、没有网络的离线测试；测不了说明耦合了 |
| 引用永远有效 | `第 N 章` / `code/` 路径 / 相对链接由脚本校验 |
| **知识点可追溯** | 每章开头标注它覆盖 A1–G5 中的哪几条、装配了哪个组件 |

后三条是这个大纲的防复发机制：知识点能查漏（防"漏掉意图识别"）、组件能单测（防"写成一坨"）、代码只往上加（防"每章一个孤立脚本"）。

---

## 十一、已确认的设计决定

| # | 决定 | 理由 |
|---|---|---|
| 1 | **14 个组件**，按 loop 插点划分 | 挂不到具体插点的就不是组件 |
| 2 | `Tools` 与 `Skills` 分开 | 能力清单 vs 流程说明书；数量级与加载时机都不同 |
| 3 | `Knowledge` 与 `Context` 分开 | 召回质量 vs 窗口预算；合并后无法归因"答错" |
| 4 | `Budget`/`Guard`/`Tracer` 放插点 ⑤⑧，不塞进 Actor | 治理不可被决策绕过 |
| 5 | **`Resilience` 独立成组件** | 超时/重试/限流/熔断/降级共享同一份失败计数，拆开必然跨组件共享状态 |
| 6 | **`Replanner` 合回 `Reflector`** | 两者只隔一个 `Verdict`，三种修复策略就是 `Verdict` 的三个取值 |
| 7 | **`Provider` 是部件不是组件** | 它是 Actor 的执行后端；但它会改变 token 口径等四件事，单独在第 3 章讲 |
| 8 | **`Cache` 归入 `Budget`** | 只影响"少花一次钱"，不改变任何决策 |
| 9 | 第 12 章不拆 | 6 个知识点同属"工具生态"，拆开反而割裂 |
| 10 | 框架卷拆 8 章（第 30–37 章） | 逐 API 讲解需要篇幅；第 33 章中间件最重 |
| 11 | 主项目 Coding Agent，另两个作对照实验 | 有天然裁判、天然副作用、天然长任务 |

---

## 十二、附录

| 附录 | 内容 |
|---|---|
| A | 术语表（全书唯一定义处） |
| B | **Harness 组件清单与契约定义**（14 个组件的 Protocol + 插点图，可直接抄） |
| C | 故障速查：症状 → 最可能出问题的组件 → 查哪章 |
| D | 结业答辩题库（含"你为什么不这么做"、替换实验） |
| E | 手写组件 ↔ 框架对应物（卷 6 索引） |
| F | 94 条知识点 × 章节 × 组件 三向覆盖矩阵（自查用） |

### 主流方向调研数据（2026-10 采集）

| 仓库 | Stars | 方向 |
|---|---|---|
| browser-use/browser-use | 119,211 | browser agent |
| bytedance/deer-flow | 84,449 | deep research harness |
| openinterpreter/openinterpreter | 68,681 | coding agent |
| codewhale-hq/Codewhale | 41,121 | terminal coding agent |
| bytedance/UI-TARS-desktop | 39,395 | computer use |
| esengine/DeepSeek-Reasonix | 35,973 | coding agent |
| trycua/cua | 31,030 | computer use sandbox |
| QwenLM/qwen-code | 28,737 | coding agent |
| OthmanAdi/planning-with-files | 27,672 | 长任务规划（持久化） |
| 1jehuang/jcode | 21,223 | 多 Agent harness |
| Alibaba-NLP/DeepResearch | 20,081 | deep research |
| simular-ai/Agent-S | 12,753 | computer use |
| zilliztech/deep-searcher | 8,349 | deep research |
