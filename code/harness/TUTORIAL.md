# Harness 部件封装手册 —— 每个部件是怎么封装出来的

> 面向对象：想自己动手写部件（或写一个同类框架）的人。
> 每个部件统一按五段讲：**【问题】它回答什么问题 → 【签名】Protocol 怎么定、
> 为什么这么签 → 【最小实现】真实代码 → 【接线】挂在链路哪个位置、谁调用它
> → 【自制】自己写一个要满足什么**。
>
> 所有代码逐字来自 `code/harness/src/harness/`，标注了文件位置，可对照阅读。

---

## 0. 先掌握一个总配方：本框架所有部件共用同一套封装手法

读完后你会发现，每个部件都是同一配方的实例化：

```text
① Protocol 定签名（contracts/protocols/）     —— 接口与实现分离，签名里编码失败语义
② 声明是值，行为是纯函数（frozen dataclass）    —— 层/程序可比较、可复制、可进检查点
③ 最小实现 + Function 包装器（parts/）         —— AllowAll/Null 必须显式存在，不许"没有=放行"
④ 装配期接线（assembly/ + kernel/chain.py）    —— needs 缺失报错、顺序拓扑排序、环拒绝
⑤ fail-closed 兜底                             —— 未知异常归类 FAILED，观测异常一律吞掉
⑥ 每个部件配 Fake（impl/fakes.py, testing.py） —— 无模型无网络可测
```

先记住链路骨架（细节在后文逐一展开）：

```text
                 ①Gate        ②Check        ③Wrap(洋葱)      ④Classify
一条效应/一步 → [Guard 准入] → [Pipe 校验转换] → [Middleware 包裹] → 终端执行 → [Filter 归类异常]
                     │                                                    ↑
                     └── deny/ask 短路 ────────────── 异常统一送进 ──────────┘

插点（链挂在哪）：run · step · model_call · tool_call · transition · effect · commit · node
```

四段的失败语义不同，**这是不能合并成一条洋葱链的根本原因**：

| 段 | 部件 | 失败行为 | 为什么不能改成抛异常 |
|---|---|---|---|
| ① Gate | Guard | **返回判定** allow/deny/ask | 拒绝不是错误，是正常业务结局，不该走异常通道 |
| ② Check | Pipe | 抛 `ValidationError` | 参数错是程序 bug，必须炸出来统一归类 |
| ③ Wrap | Middleware | 异常原样穿透 | 中间件不该理解异常，只负责包裹 |
| ④ Classify | Filter | 唯一映射点，不吞异常 | 全框架只有这里允许"翻译"异常 |

---

# A. 四段链上的部件

## A1. Gate = Guard（准入）

**【问题】** 这个动作能不能做？做之前要不要人点头？

**【签名】** `contracts/protocols/guards.py`：

```python
@runtime_checkable
class Guard(Protocol):
    """段 Gate。返回判定、**不抛异常**、可短路。"""
    async def check_identity(self, goal: Any, ns: Any) -> "GuardDecision": ...
    async def check(self, step: "Step", state: "State") -> "GuardDecision": ...
```

签名里的三个设计决策：

1. **返回判定而非抛异常** —— `GuardDecision` 是 `allow / deny / ask` 三态
   值对象（`contracts/types.py`）。deny=拒绝（业务结局 refused），ask=转审批
   （needs_approval）。用异常表达"拒绝"会让调用方无法区分"拒绝"和"坏了"。
2. **两个方法不拆成两个部件** —— `check_identity`（这个人能不能发起这次运行）
   和 `check`（这个动作能不能执行）共享"不通过就拦"的语义，拆开会把拒绝逻辑
   写两遍（源码头注释原话，SPEC M8.1）。
3. **与 Guardrail 分离** —— `Guard` 管"动作能不能做"，`Guardrail` 管"内容能不能
   进出"（提示词注入检测等，五道闸）。一个是动作准入、一个是内容检测，
   输入形状完全不同（Step vs Content），合在一起签名就脏了。

**【最小实现】** `parts/guard.py`：

```python
class AllowAllGuard:
    async def check_identity(self, goal, ns=None): return GuardDecision.allow()
    async def check(self, step, state): return GuardDecision.allow()

class FunctionGuard:
    """把一个函数包成 Guard——大多数业务护栏只需要一个 if。"""
    def __init__(self, fn, identity_fn=None): ...
    async def check(self, step, state):
        decision = self.fn(step, state)
        if hasattr(decision, "__await__"):   # 同步异步函数都接受
            decision = await decision
        return decision
```

注意 `AllowAllGuard` **显式存在**：源码注释强调"不要用'没有 Guard'表示放行"——
缺省对象缺失会让"忘了配护栏"和"决定放行"不可区分。

**【接线】** 两处：
- v1/v2 四段链：`kernel/stage.py` 的 `run_stages(step, state, terminal=…, gate=…)`，
  第 ① 段 `await gate.check(step, state)`，deny/ask 直接短路返回 `StageResult(failure=…)`；
- v3 效应系统：`kernel/effects.py` 的 `_stages()`，先走各 `EffectLayer.gate`，
  再走注入的 `guard.check(step, state)`，效果相同。

**【自制清单】** 实现 `check(step, state) -> GuardDecision`（同步异步均可，
经 `FunctionGuard` 包装更省事）；绝不抛异常；deny 必须带 reason。

## A2. Check = Pipe（参数校验与转换）

**【问题】** 这一步的参数合法吗？要不要先规范化（trim、类型转换、默认值）？

**【签名】** `contracts/protocols/runtime.py`：

```python
@runtime_checkable
class Pipe(Protocol):
    """段 Check：参数校验与转换，失败抛 ValidationError。"""
    async def transform(self, step: "Step", state: "State") -> "Step": ...
```

签名设计：**输入 Step、返回 Step**（转换后的新 Step），失败唯一出口是
`ValidationError`。它和 Guard 最关键的区别：Guard 返回值、Pipe 抛异常——
参数错是调用方 bug，必须进入异常通道被 Classify 归一，而不是静默变成
一个业务结局。

**【最小实现】** 框架自带恒等件（`kernel/stage.py`）：

```python
class IdentityCheck:
    async def transform(self, step, state): return step
```

业务侧典型 Pipe（裁剪超长参数、注入 idem_key、单位换算）都是 10 行以内。

**【接线】** 四段链第 ② 段。v1 路径在 `run_stages`：

```python
try:
    for check in checks:
        step = await check.transform(step, state)
except Exception as exc:
    return StageResult(step, failure=await classify.classify(exc, phase="check", state=state))
```

注意这里 Check 的异常**当场**交给 Classify（phase="check"），不进 Wrap——
校验失败没有资格到达终端。

**【自制清单】** 实现 `transform`；失败抛 `ValidationError(field=…)`；
**返回新 Step 而不是原地改**（Step 是 frozen 值，用 `dataclasses.replace`）。

## A3. Wrap = Middleware / Layer（洋葱包裹）

**【问题】** 重试、超时、审计、记账、上下文装配……这些横切逻辑怎么不写死在循环里？

这是本框架封装密度最高的部件，分三层看。

### 3.1 协议层：Middleware

**【签名】** `contracts/protocols/runtime.py`：

```python
Handler = Callable[[Any], Awaitable[Any]]
"""(Request) -> Response。层签名统一为 (req, nxt) -> Response。"""

@runtime_checkable
class Middleware(Protocol):
    name: str
    points: frozenset[str]     # 在哪些插点生效
    needs: frozenset[str]      # 依赖哪些能力（缺则装配期报错，不降级）
    after: frozenset[str]      # 相对顺序声明
    before: frozenset[str]
    async def __call__(self, req: Any, nxt: Handler) -> Any: ...
```

四个声明字段各自回答一个问题：

| 字段 | 回答的问题 | 谁消费它 |
|---|---|---|
| `points` | 我挂在哪些插点上 | `kernel/chain.resolve` 筛选 |
| `needs` | 我需要哪些能力注入 | 装配期校验，缺失**报错**而非静默降级 |
| `after`/`before` | 我和谁谁先谁后 | `resolve` 做拓扑排序 |
| `__call__(req, nxt)` | 我怎么包裹 | `chain.execute` 洋葱组装 |

### 3.2 值层：Layer（layers.py 的核心封装决策）

**【签名】** `parts/middleware/base.py`：

```python
@dataclass(frozen=True)
class Layer:
    name: str
    points: frozenset[str]
    build: Callable[[Handler], Handler] = field(compare=False, repr=False)
    needs: frozenset[str] = frozenset()
    after: frozenset[str] = frozenset()
    before: frozenset[str] = frozenset()

    def wrap(self, nxt: Handler) -> Handler:
        return self.build(nxt)
```

**封装手法：层是值，不是对象。** 源码头注释原话："状态放在闭包里或作用域里，
不放在层实例上——否则层无法复用与比较。" `build` 是一个纯函数
`handler -> handler`，配置（如 budget 实例、sink）通过闭包捕获：

```python
def budget_layer(*, budget: Budget) -> Layer:      # 工厂函数 = 部件的惯用构造形态
    def build(nxt):
        async def handler(req):
            if budget.exhausted:
                raise BudgetExceeded(f"预算耗尽：{budget.snapshot()}")
            response = await nxt(req)
            if isinstance(response, ModelResponse):
                budget.spend(tokens=int(response.usage.get("total", 0)), calls=1)
            return response
        return handler
    return layer("budget", ["run", "model_call"], build, after=["tenancy"])
```

这就是"怎么封装一个中间件"的完整模板：**工厂函数收配置 → 内层 `build(nxt)`
闭包捕获配置 → 返回 `layer(name, points, build, needs=…, after=…)`**。
`layer()` 语法糖免得到处写 `frozenset`。

洋葱语义：`chain.execute(layers, request, terminal)` 从最内层（终端）向外
逐层包，**第一层最外**——即列表里第一个声明的层最后才碰到终端、最先看到请求。

### 3.3 内置层范例（挑四个代表，其余同理）

都在 `parts/middleware/builtin.py`，每个都值得当模板抄：

| 层 | 插点 | 包裹逻辑 |
|---|---|---|
| `trace_layer` | 全部 | `try: await nxt(req) finally: sink.emit(span.end)`——观测异常吞掉 |
| `budget_layer` | run + model_call | 前置检查 `exhausted` 抛 `BudgetExceeded`；后置按响应记账 |
| `checkpoint_layer` | step | **后置**：`store.put(ns, sid, state, expect_rev=state.rev)`（乐观锁，见 D3） |
| `approval_layer` | tool_call | 看 `spec.side_effects` 元数据（**不猜工具名**）决定是否走审批通道 |

`parts/layers.py` 还有五个薄层（tenancy/audit/retrieval/memory_recall/memory_write），
每个 20~40 行，是学习"业务横切怎么写成层"的最好教材。例：`retrieval_layer`
挂在 `model_call`，首轮把候选写进 `state.data["retrieved"]`，然后
`before=["context"]` 保证它排在取景层之前。

### 3.4 v3 的收拢：EffectLayer

v3 效应系统把四段打包成一个值对象（`kernel/effects.py`）：

```python
@dataclass(frozen=True)
class EffectLayer:
    name: str
    gate: Callable[[Effect, State], str] = _allow          # ① 返回判定
    check: Callable[[Effect, State], None] = _noop_check   # ② 抛异常
    wrap: Callable[[Effect, Callable], Callable] = _identity_wrap  # ③ 洋葱
    observe: Callable[[Effect, Any, State], None] = _noop_observe  # 只读观察
    points: frozenset[str] = frozenset({"effect", "commit"})
```

一个 `EffectLayer` 可同时提供四段中的任意几段，缺省段是恒等实现——
这样"只想加一个观察"的人不用理解整个洋葱。

**【自制清单】** 业务横切一律写工厂函数返回 `layer(...)`；
不改请求、只改响应时把 `await nxt(req)` 的结果加工后返回；
失败要么抛指定异常（走 Classify）要么返回值短路，**不要在层里吞业务异常**。

## A4. Classify = Filter（异常归类）

**【问题】** 全框架那么多部件都可能抛异常，谁来把它们统一"翻译"成调用方能
处理的六态结局？

**【签名】** `contracts/protocols/runtime.py`：

```python
@runtime_checkable
class Filter(Protocol):
    """段 Classify：异常 → Failure 的唯一映射点。"""
    async def classify(self, exc: BaseException, *, phase: str, state: "State") -> "Failure": ...
```

`Failure` 是三字段值对象：`status: RunStatus / reason: str / retryable: bool`。

**【最小实现】** `kernel/stage.py` 的 `DefaultClassify` 是一张异常→结局映射表，
值得整段背下来，因为它的排布就是 fail-closed 原则的落地：

```python
async def classify(self, exc, *, phase, state):
    if isinstance(exc, asyncio.CancelledError): return Failure(CANCELLED, "cancelled", False)
    if isinstance(exc, ApprovalRequired):       return Failure(NEEDS_APPROVAL, …, False)
    if isinstance(exc, (GuardDenied, PolicyError)): return Failure(REFUSED, f"policy:{exc}", False)
    if isinstance(exc, ValidationError):        return Failure(REFUSED, f"invalid_args:{…}", False)
    if isinstance(exc, TransientError):         return Failure(DEGRADED, "transient_exhausted", True)  # 可重试
    if isinstance(exc, BudgetExceeded):         return Failure(DEGRADED, "budget", False)
    if isinstance(exc, ToolError):              return Failure(DEGRADED, "tool", True)
    return Failure(FAILED, type(exc).__name__, False)   # 未知异常 fail-closed
```

要点：可重试的只有 `retryable=True` 的（Transient/Tool），拒绝和降级分得清清楚楚；
最后一行没有"猜"——**未知一律 FAILED**，宁可失败不可误放。

**【接线】** 四段链第 ④ 段 + 兜底双重身份：`run_stages` 里 Check 段和 Wrap 段的
异常都送进它；v3 效应系统里 `EffectRuntime._failed()` 调它，且连归类器自己
抛异常都防了（退化成 `status="failed", reason=str(exc)`）。

**【自制清单】** 实现一个 `classify`；先抄 DefaultClassify 再改映射；
永远给未知异常留 FAILED 出口。

## A5. Guardrail（内容检测，动作检测的姊妹件）

**【签名】** `contracts/protocols/guards.py`：

```python
@runtime_checkable
class Guardrail(Protocol):
    """五道闸的内容检测；检测与动作分离（SPEC M9.2）。"""
    name: str
    gates: frozenset[str]                                   # 挂在哪几道闸上
    async def check(self, content: "Content", scope: Any) -> "GuardrailVerdict": ...

@runtime_checkable
class GuardrailStream(Guardrail, Protocol):
    """流式增量检测：窗口缓冲 + 结尾 flush。"""
    async def feed(self, delta: str, st: "StreamState") -> "GuardrailVerdict": ...
    async def flush(self, st: "StreamState") -> "GuardrailVerdict": ...
```

封装要点：`gates` 声明自己检查哪几道闸（输入/输出/工具结果……），框架按闸
分发；流式版用 `feed/flush` 两段式——增量内容先攒窗口，流结束 flush 兜底，
因为敏感词可能被切成两个 delta。实现见 `parts/guardrail/`
（detectors/layer/streaming 三件）。

---

# B. 链本身的封装

部件只解决"单件怎么写"，链解决"多件怎么排"。

## B1. 插点（POINTS）：链的坐标系

**【问题】** 层说"我挂在 model_call"，框架怎么知道有哪些合法位置？

**【实现】** `kernel/chain.py`：

```python
POINTS = (
    "run", "step", "model_call", "tool_call",     # v1/v2 四点：运行/步/问模型/调工具
    "transition", "effect", "commit", "node",     # v3 新增：解释器/效应/提交/图节点
)
```

封装手法：**插点是字符串常量集，不是枚举类**——为了可扩展（PROPOSAL §9.2：
新增插点不动旧契约），`resolve()` 只校验"在集合里"，未知插点抛 `ConfigError`。

## B2. 顺序解析：拓扑排序

**【问题】** 十个层都挂在 model_call，谁先谁后？写死顺序则加层要改内核。

**【实现】** `kernel/chain.py` 的 `resolve(layers, point)`：

```python
def resolve(layers, point):
    picked = [lay for lay in layers if point in _points_of(lay)]   # 按插点筛选
    # after/before 声明 → 边 → Kahn 拓扑排序
    ready = [n for n in names if n in pending and not pending[n]]
    if not ready:
        raise ConfigError(f"插点 {point} 的层顺序成环：{sorted(pending)}")
```

三个封装决策：
1. **声明式顺序**（`after={"trace"}`）而非列表顺序——层之间不 import 对方也能表达依赖；
2. **环 = 装配期失败**（ConfigError），绝不带病运行；
3. **无约束层保持注册顺序**（稳定排序），保证行为可复现。
重名层同样装配期报错——层按名字排序，重名即排序歧义。

## B3. 四段编排：run_stages

**【实现】** `kernel/stage.py`：

```python
async def run_stages(step, state, *, terminal, gate=None, checks=(), layers=(), classify=None):
    gate = gate or AllowAllGate()          # 缺省件显式构造
    classify = classify or DefaultClassify()
    # ① Gate：返回判定，不抛异常 → deny/ask 直接构造失败结局短路
    # ② Check：逐个 transform，异常当场 classify(phase="check")
    # ③ Wrap：reversed 遍历逐层包 terminal（第一层最外）
    # ④ Classify：wrap 段异常 classify(phase="wrap")
    return StageResult(step, result=result)   # 要么 result 要么 failure，二选一
```

源码注释一句硬话："**按固定顺序走四段；顺序不可调、不可合并、不可省略**。"
封装成"不可配置的固定管线"是有意的——四段失败语义不同（见 §0 表），
允许用户调顺序就等于允许他们破坏语义。

`StageResult` 是出口的值形状：`step + (result | failure)`，调用方用
`result.ok` 属性判断，失败不再需要 try/except。

## B4. v3 收拢：EffectRuntime._stages

v3 把效应的执行也编排成同样的四段（`kernel/effects.py`），新增了两个封装点：

- **幂等前置**：进四段链之前先查 `effect.idem_key in self.seen`，命中直接回放
  缓存结果且 `_usage={"calls":0,"tokens":0}`（不重复计量）；
- **Hook 后置**：四段走完统一 `_fire_hooks(effect, result, state)`。

`Effect → Step` 的对接是薄适配器 `to_step()`：按 `_KIND_TO_STEP` 映射表
把效应翻译成旧四段链认识的 Step——**适配而不是重写**，让 v1 的治理资产
零改动复用。

---

# C. 观测部件

## C1. Hook（纯观察）

**【问题】** 有些逻辑只想"看"不想"改"——指标、日志、告警。用 Middleware 写
太重（要理解 req/nxt）。

**【签名】** `contracts/protocols/runtime.py`：

```python
@runtime_checkable
class Hook(Protocol):
    """纯观察：只读事件，返回值被忽略（= 不调 nxt 的层）。"""
    point: str
    async def __call__(self, event: "HookEvent") -> None: ...
```

**封装手法一句话：Hook 就是不调 `nxt` 的层。** 这一行注释把两个部件的关系
讲透了——Middleware 的权力是"改写或短路"，Hook 自愿放弃这个权力，换取
签名更简单（收一个事件、不返回任何东西）。

`HookEvent`（`contracts/events.py`）是只读载荷：`point / state_id / fields`。
v3 的落点在 `EffectRuntime._fire_hooks`：point 格式 `effect.<kind>`，
hook 用**前缀匹配**订阅（`point in getattr(hook, "point", point)`），
`effect.` 前缀 = 订阅所有效应。hook 抛异常只发 `hook.error` 事件，绝不影响运行。

**【接线】** `Runtime(hooks=…)` → `EffectRuntime._fire_hooks`（每条效应结束后）。

**【自制清单】** 一个带 `point` 属性的可调用对象即可；
把它当只读的，别指望它改流程——要改流程请写 Layer。

## C2. Tracer（事件出口）

**【签名】** `contracts/protocols/governance.py`：

```python
@runtime_checkable
class Tracer(Protocol):
    """带 span 语义的事件出口；异常不得影响请求（SPEC M10.1）。"""
    async def emit(self, event: "RunEvent") -> None: ...
```

**【最小实现】** `parts/tracer.py` 三件套，展示了同一协议的三档实现成本：

```python
class NullTracer:      # 测试：什么都不做
    async def emit(self, event): return None
class MemoryTracer:    # 测试/断言：收进列表
    async def emit(self, event): self.events.append(event)
class JsonlTracer:     # 生产：追加一行 JSON
    async def emit(self, event): …fh.write(json.dumps(row, …) + "\n")
```

封装要点：协议只有一个方法 `emit`，且**"异常不得影响请求"写进了协议文档**——
实现方可以自己吞，框架侧调用处也会兜（`Runtime.emit` 里 `try/except: pass`）。
事件统一是 `RunEvent` 值对象（name/trace_id/span_id/parent_id/ts_ms/fields），
`parent_id` 必须真实填写才能串出跨 agent 的 trace 树。

## C3. 事件名表

`contracts/events.py` 的 `EVENT_NAMES` 元组是全框架的观测面清单：
`run.start/end、step.start/end、model.start/delta/end、tool.start/end、
guardrail、approval.required/resolved、checkpoint、error、hook.error、
transition、effect、commit、node`。封装手法：**事件名即契约**——名字进
EVENT_NAMES 才算稳定 API，消费方按名字过滤，加事件不破坏旧消费者。

---

# D. 治理部件

## D1. Budget（预算）

**【实现】** `parts/budget.py`：

```python
@dataclass
class Budget:
    tokens: int = 60_000
    calls: int = 30
    used_tokens: int = 0
    used_calls: int = 0
    @property
    def exhausted(self) -> bool: …
    def spend(self, tokens=0, calls=1) -> None: …
    def snapshot(self) -> dict[str, int]: …   # 异常信息里的弹药
```

封装决策：
- **预算是共享资源**（头注释原话），所以它是独立值对象、由层/内核引用记账，
  不藏在模型适配器里；
- 记账分两处：`budget_layer`（v1 路径，模型响应后按 usage 扣）与
  `State.add_usage`（v3 路径，提交点统一扣）；
- **子代理切分**：`RunScope.child(name, budget_fraction=0.3)` 调
  `budget.split(0.3)`——父作用域预算的 30% 划给子作用域，资源"单一所有者、
  单向继承"；
- `NullBudget`（上限设成天文数字）让测试不用关心预算。

## D2. Limits（全局终止护栏）

**【实现】** `kernel/interpret.py`：

```python
@dataclass(frozen=True)
class Limits:
    max_transitions: int = 64
    max_calls: int = 100
    max_tokens: int = 200_000
    wall_seconds: float = 30.0
```

封装决策：这是 v3 框架**新增的唯一不变量**——"任何程序都必须能停下来"。
控制流交给程序后，程序可以无限返回自己空转，所以上限必须收拢到框架。
四个维度（转移数/调用数/token 数/墙钟）每轮循环开头检查，超限返回
`Halt(..., "degraded")`——**护栏触发也是正常结局（degraded），不是异常**。
注意它和 Budget 的分工：Budget 是消费侧记账（部件级），Limits 是运行侧
硬停（框架级），v3 里 `Harness.new_runtime` 把 `Budget.calls/tokens` 映射进
`Limits`，两个概念一处汇合。

## D3. Durability / CheckpointStore（持久化）

**【签名】** `contracts/protocols/stores.py`，两代并存、各有深意：

```python
@runtime_checkable
class Durability(Protocol):
    """v1 检查点：save/load。违反"历史不可变"，P3 迁移到 CheckpointStore。"""
    async def save(self, state: "State") -> None: ...
    async def load(self, session_id: str) -> "State | None": ...

@runtime_checkable
class CheckpointStore(Protocol):
    """v2 多版本快照：追加新 rev，旧版本永不修改（不变量 1）。"""
    async def put(self, ns, sid, state, *, expect_rev: int | None) -> int: ...
    async def get(self, ns, sid, rev=None) -> "Checkpoint | None": ...
    async def history(self, ns, sid, *, limit=50) -> list[int]: ...
```

对比读出封装手法的演进：v1 `save/load` 是"覆盖式存档"，会把历史改掉；
v2 改成 `put/get/history`——**put 带 `expect_rev`（乐观锁：期望的旧版本号，
不匹配即冲突拒绝）**，每次落盘追加新 rev，回溯才能"读历史快照"而不是
"恢复被覆盖的存档"。这个签名差异就是"检查点 vs 存档"的语义差别。
另外所有 v2 存储协议第一个参数都是 `Namespace`——多租户隔离在**签名里**强制，
实现想忘都忘不掉。

**【最小实现】** `parts/durability.py` 的 `SQLiteDurability`：标准库 sqlite3、
UPSERT 语句、单文件，约 40 行——"生产可用"的最小成本示范。

## D4. Idempotency（幂等）

**【签名】** `stores.py`：

```python
@runtime_checkable
class Idempotency(Protocol):
    async def begin(self, ns: "Namespace", key: str) -> Any: ...
    async def commit(self, ns: "Namespace", key: str, value: Any) -> None: ...
```

两段式（begin 占位 → commit 落值）而非单方法，因为副作用执行是异步的：
begin 拿到占位符，别的并发请求撞同一个 key 时能识别"已在执行"。
v3 进程内的简化版是 `EffectRuntime.seen: dict[str, Any]` + `Effect.idem_key`：
命中即回放结果且零计量。场景：审批通过后重放、断点续跑重执行——
**审批通过不等于副作用只发生一次**（DEV-SESSION §8 原话），幂等键是唯一的保险。

---

# E. 执行部件

## E1. Tool（唯一有副作用的执行原语）

**【签名】** `contracts/protocols/tools.py`：

```python
@runtime_checkable
class Tool(Protocol):
    spec: "ToolSpec"                                   # 元数据：名字/schema/side_effects
    async def invoke(self, args: dict, ctx: "ToolContext") -> "ToolResult": ...
```

两个签名决策：
1. **spec 与 invoke 分离**——模型需要的元数据（schema、副作用级别）和执行体
   分开，approval_layer 才能只看元数据判审批，不用真调工具；
2. **invoke 收 `ToolContext`**——文件系统、沙箱、密钥、取消信号都是**注入**的
   （来自 RunScope），工具自己不 import 全局资源。能力最小权限落在这里。

**【封装最精彩的一段：schema 推导定死不许猜】** `parts/tools.py` 头注释：

> 推导规则（定死，不许猜）：无标注一律报 `ConfigError`，不默认 `string`——
> 否则 `amount: int` 会被当成字符串传给下游，错误发生在最远的地方。

```python
def schema_for_type(annotation, *, name="") -> dict:
    if annotation in _PRIMITIVES: return {"type": _PRIMITIVES[annotation]}
    if origin is Literal: return {"enum": list(args)}
    if dataclasses.is_dataclass(annotation): …递归展开字段…
    if annotation is Any:
        raise ConfigError(f"参数 {name} 标注为 Any，无法推导 schema；请给出具体类型")
    raise ConfigError(f"参数 {name} 的类型不受支持：{annotation!r}")
```

**宁可在装配期报错，不在运行期猜类型**——这是整份代码库里最值得学的封装
态度。配合 `_docstring_parts()` 拆 docstring（首段=工具描述，`Args:` 段=
逐参数说明），`@tool` 装饰器就能从"带类型标注的普通函数"零成本生成
ToolSpec。`ToolRegistry` 负责 add/get/schemas 的集中管理。

## E2. Actor（决策 + 执行）

**【签名】** `contracts/protocols/governance.py`：

```python
@runtime_checkable
class Actor(Protocol):
    """插点 ④ 决策 + ⑥ 执行。只做执行，不做评估（SPEC M3.1）。"""
    async def propose(self, state, scope) -> Any: ...    # 产出 Step | Done
    async def step(self, step, state, scope) -> "ActionResult": ...
```

**【最小实现】** `parts/actor_v2.py` 的 `LlmActor.propose`，演示了"部件怎么
在不知道链存在的情况下被治理"：

```python
frame = await scope.framer.frame(state, budget=scope.budget)   # 取景：选哪些内容
pack = await scope.encoder.encode(frame)                       # 编码：Frame → 载荷
request = ModelRequest(state=state, messages=…, tools=…, budget=…, frame=frame)
model_call = getattr(scope, "model_call", None)                # ← 关键
if model_call is not None:
    reply = (await model_call(request)).reply                  # 经链调用（护栏/记账/重试全在里面）
else:
    reply = await self.model.complete(pack.messages, schemas)  # 直连（仅测试兜底）
```

封装要点：**Actor 不 import kernel、不知道层存在，它只调 `scope.model_call`**
——链是内核注入 scope 的能力。这是"部件与链解耦"的标准手法。
职责边界同样值得抄：propose 只解析 tool_call 产出 Step（一轮只取第一个，
不支持并行工具——ADR 12 明说）；step 失败**不重试不评估**，包装成
`ok=False` 的 ActionResult 回灌模型，由下一轮修正——评估是 Reflector 的事。

## E3. Model（模型后端）

**【签名】** `contracts/protocols/model.py`：

```python
@runtime_checkable
class Model(Protocol):
    """一次补全 + 一次流式补全。usage 必须归一化成 {input, output, total}。"""
    async def complete(self, messages, tools=None, *, response_format) -> "ModelReply": ...
    def stream(self, messages, tools=None) -> AsyncIterator["ModelDelta"]: ...
```

协议只有两个方法，但文档把 **usage 归一化**写成义务——各家 SDK 的 token
统计五花八门，归一化责任压给适配器（`adapters/openai.py`），内核只认
`{input, output, total}`。封装手法：**格式噪音挡在协议边界外**。

## E4. Framer / Encoder（数据视图两段分离）

**【签名】** `contracts/protocols/framing.py`：

```python
@runtime_checkable
class Framer(Protocol):
    """取景：选哪些、怎么排、超预算丢谁。不拼字符串、不决定格式。"""
    kind: str
    async def frame(self, state, *, budget) -> "Frame": ...

@runtime_checkable
class Encoder(Protocol):
    """编码：Frame → 载荷。不决定留哪条。"""
    fmt: str
    async def encode(self, frame) -> Any: ...
```

这是"一个职责拆成两个部件"的教科书案例，两个 Protocol 文档各有一句
"不做对方的事"：Framer 不拼字符串（决定**留什么**），Encoder 不决定留哪条
（决定**长什么样**）。上下文策略 = 任选 Framer × 任选 Encoder，2×3 组合
零新代码。v1 的 `Context.assemble(state, budget)` 把两件事捏在一起，
v2 拆开——拆的动机写在协议注释里（"v1 形状保留兼容；v2 由 Framer+Encoder
取代"）。

---

# F. 组装部件

## F1. RunScope（能力作用域）

**【实现】** `kernel/scope.py`：

```python
@dataclass(frozen=True)
class RunScope:
    namespace: Namespace          # 谁在跑（tenant/user/session/agent）
    budget: Any
    model / fs / sandbox / artifacts / secrets / memory / …   # 能力引用，缺省 None
    depth: int = 0
    max_depth: int = 2
    child_slots: Any = None       # 子 agent 并发槽位

    def child(self, name, *, budget_fraction=0.3) -> "RunScope":
        if self.depth + 1 > self.max_depth:
            raise ConfigError(f"子 agent 深度超过上限 …")
        child_budget = self.budget.split(budget_fraction) if self.budget …
        return replace(self, namespace=replace(self.namespace, agent=name),
                       budget=child_budget, depth=self.depth + 1)
```

三个封装决策（都有事故出处）：
1. **frozen 值对象**：能力集合不可变，派生用 `replace()`——作用域不会被
   运行时偷偷改权柄；
2. **缺省 None、用时明确报错**：新字段必须带默认值（契约只增不改纪律），
   但"缺省为 None 时策略会明确报错"（字段注释原话）——降级可以，假装可以不行；
3. **child_slots 挂在 scope 不挂层**：源码注释记了教训——"层是值、会被复制，
   挂在层上会导致每层各造一个信号量，总量失控（SPEC M13.7）"。
   **有并发语义的资源必须挂在单例作用域上。**

## F2. Harness（能力容器）

**【定位】** `assembly/harness.py` 头注释："模型、工具、存储、后端。
**不持有任何策略。**" 能力归 Harness，策略归程序与层——这句话就是容器和
策略的分界线。核心接线方法是 `new_runtime()`：

```python
return Runtime(
    layers=tuple(layers),
    limits=limits or Limits(max_transitions=self.max_transitions,
                            max_calls=self.budget.calls,      # ← Budget 映射进 Limits
                            max_tokens=self.budget.tokens),
    record_only=record_only,
    extra_handlers=extra_handlers,
    emit=emit,                # 事件出口：scope.events 扇出，异常吞掉
    model=self.model,
    guard=self.guard,
    checks=tuple(self.pipes),     # Pipe 列表 → Check 段
    classify=self.filter,         # Filter → Classify 段
    hooks=tuple(hooks),
)
```

读这段代码就能看懂全部部件的汇合点：**容器持有的每一类能力，对应内核
Runtime 的一个构造参数**。封装手法：容器只做"搬运工"，不做任何策略判断；
流式出口 `astream()` 也只是"多挂一个队列 sink"，不是另一条执行路径。

## F3. Registry（注册表）

**【实现】** `assembly/registry.py` 的 `PROGRAMS` + `register_program(name, factory)`。
配套手法见 `fp/frontends.py` 末尾的**自注册**：

```python
def _register_frontends() -> None:
    for name, cls in {"leaf": Leaf, "graph": Graph, …}.items():
        if name not in PROGRAMS:
            register_program(name, _program_factory(name, cls))
_register_frontends()     # import 即注册
```

封装决策：前端库**自己**注册，装配层不反向 import fp——既保持依赖单向，
又实现"新增一种形态只需一行"。`program_from_spec()` 按名字查工厂编译
JSON 声明，**无白名单**（注册即用）。这和 EffectRuntime 的
`handlers.update(extra_handlers)` 是同一手法：**注册代替 if 分支**。

---

# G. 部件速查表

| 想做的事 | 该封装的部件 | Protocol 位置 | 最小实现模板 |
|---|---|---|---|
| 拦动作（权限/审批/预算闸门） | Guard | contracts/protocols/guards.py | FunctionGuard 包一个 if |
| 拦内容（注入检测/敏感词） | Guardrail / GuardrailStream | 同上 | parts/guardrail/ |
| 校验转换参数 | Pipe | contracts/protocols/runtime.py | transform + ValidationError |
| 重试/超时/审计/记账/上下文 | Layer（工厂函数） | parts/middleware/base.py | budget_layer 模板 |
| 只看不改（指标/日志） | Hook | 同上 | point 属性 + async __call__ |
| 异常→结局映射 | Filter | 同上 | 抄 DefaultClassify |
| 跨会话长期记忆 | Memory / MemoryStore / MemoryPolicy | contracts/protocols/stores.py | recall + write（策略另拆） |
| 断点续跑/检查点 | Durability / CheckpointStore | 同上 | SQLiteDurability 模板 |
| 副作用去重 | Idempotency / Effect.idem_key | 同上 | begin/commit 两段式 |
| 新工具 | Tool（或 @tool 装饰器） | contracts/protocols/tools.py | 带类型标注的函数即可 |
| 换模型 | Model | contracts/protocols/model.py | complete + usage 归一化 |
| 换上下文策略 | Framer × Encoder | contracts/protocols/framing.py | 各实现一个纯函数 |
| 自定义执行体 | Actor | contracts/protocols/governance.py | propose + step，经 scope.model_call |
| 事件落盘 | Tracer | 同上 | emit 一个方法；JsonlTracer 30 行 |
| 出口加工 | Delivery | 同上 | finish(state, status) -> RunResult |
| 新架构/新编排 | Program（transition） | contracts/protocols/runtime.py | 裸函数 + FnProgram 就行 |
| 新效应类型 | handler 注册 | kernel/effects.py | extra_handlers={"kind": fn} |

---

# H. 验收你的部件：每件配一个 Fake

封装的最后一环（DEV-SESSION §9 DoD：示例能跑 + 离线单测 + 替换实验 +
一页文档）。框架自带假件体系（`impl/fakes.py`、`testing.py`）：
`FakeModel`（按脚本回放回复）、`FakeTool`、`MemoryTracer`、`MemoryDurability`、
`NullBudget`。写部件时的标准动作：

```python
# 1. Protocol 先行：签名进 contracts/protocols/
# 2. 最小实现：AllowAll/Null 显式存在，不做"没有=放行"
# 3. Fake：MemoryTracer 风格的三行假件，让测试零网络
# 4. 替换实验：真实现 vs Fake 跑同一用例，结果一致才算封装成功
#    —— "换掉一个组件只消失一件事"是封装正确的唯一判据
```

**替换实验**是这套方法论的核心验收：把 JsonlTracer 换成 MemoryTracer、
把真模型换成 FakeModel，运行结果应当完全一致（除观测产物外）。
做不到，说明有部件偷偷越界了。
