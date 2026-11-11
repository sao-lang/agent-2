# 从零重建 Harness —— 全框架逐文件封装实录

> 本教程按真实依赖顺序，把 `src/harness/` 里**每一个文件**从空目录
> 开始重建一遍：先给这个文件的真实代码（逐字来自仓库，个别超长处用 `…` 标注省略），
> 再讲它是怎么封装出来的。全文没有总览，只有施工。
>
> 总览见 `TUTORIAL.md`；设计规格见 `docs/harness/SPEC.md` 与 `PROPOSAL-通用解释器与效应系统.md`；
> 阶段七的施工依据是 `docs/harness/SUPPLEMENT-PLAN.md`。

## 施工顺序（依赖决定，不可乱）

```text
阶段一 contracts/   status → errors → events → types → state → result → protocols/×9 → decision
阶段二 kernel/      stage → chain → scope → effects → interpret → legacy(+loop 壳)
阶段三 parts/       budget/tracer/durability/resilience → guard+guardrail → middleware+layers
                    → framing → tools → actor → body → knowledge/memory/retrieval/skills
                    → context/delivery/reflector/dispatch/topology → subagent/capability
阶段四 impl/+adapters/  stores/memory → fakes/testing → backends → openai
阶段五 fp/+assembly/    frontends → fp 门面 → registry → build+config → harness+agent → presets
阶段六 门面与验收       __init__ → cli → examples → tests
阶段七 v3.1 补充       A6 tokens → A1 replan → A2 checkpoint → A4 预算接线
                       → A5 structured → A3 路由 → B2/B3 注册表与向量检索
                       → conformance 基类 + test_supplement 验收
```

---

# 阶段一 contracts/ —— 先冻结语言

## 1.1 `contracts/status.py`：枚举与状态机

```python
"""枚举与状态机（SPEC M1.2、M16.2）。零依赖。"""
from enum import StrEnum

class RunStatus(StrEnum):
    """运行终态的七种取值。RUNNING 只存在于内存态，禁止出现在 RunResult。"""
    RUNNING = "running"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    REFUSED = "refused"
    FAILED = "failed"
    NEEDS_APPROVAL = "needs_approval"
    CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset(RunStatus) - {RunStatus.RUNNING}

class Phase(StrEnum):
    """失败发生在哪一段（供 Filter.classify 使用）。"""
    RUN = "run"; STEP = "step"; GATE = "gate"; CHECK = "check"; WRAP = "wrap"
    CLASSIFY = "classify"; MODEL = "model"; TOOL = "tool"; EXPORT = "export"

class Point(StrEnum):       # 四个可包裹插点（v1/v2）
    RUN = "run"; STEP = "step"; MODEL_CALL = "model_call"; TOOL_CALL = "tool_call"

class FrameKind(StrEnum):   # 四种帧（M6.1）
    MODEL = "model"; HUMAN = "human"; APPROVAL = "approval"; TRACE = "trace"

class Gate5(StrEnum):       # 护栏五道闸（M9.1）
    INBOUND = "inbound"; CONTEXT = "context"; MODEL_OUT = "model_out"
    TOOL_OUT = "tool_out"; OUTBOUND = "outbound"

class SideEffect(StrEnum):  # 工具副作用等级：驱动审批分级、幂等要求、沙箱路由
    PURE = "pure"; READ = "read"; WRITE = "write"; NET = "net"; SHELL = "shell"

class GuardAction(StrEnum):
    ALLOW = "allow"; DENY = "deny"; ASK = "ask"

class GuardrailAction(StrEnum):   # 动作强度递增，仲裁取最严（M9.3）
    ALLOW = "allow"; WARN = "warn"; REDACT = "redact"
    REWRITE = "rewrite"; ASK = "ask"; BLOCK = "block"
```

**封装手法**：
1. 用 `StrEnum` 不用 int 枚举——落库、日志、跨机传输时值就是可读字符串。
2. `SideEffect` 是压在**工具元数据**上的小状态机：`approval_layer` 看 `side in ("write","shell")` 判审批，幂等层按 `idempotent` 判去重，沙箱路由看 `sandbox`——**一个字段驱动三套治理**，所以它必须进 contracts 而不是任何部件。
3. `GuardAction`（动作三态）和 `GuardrailAction`（内容六态）分开定义——动作判定只有过/不过/问人，没有 warn/redact 这种"中间动作"。
4. `RunStatus` 七态里 RUNNING 是唯一非终态，`TERMINAL_STATUSES` 把这个区分做成常量。

## 1.2 `contracts/errors.py` + `approval_errors.py`：异常树

```python
"""基座异常。调用方按类型区分失败，不要一律 except Exception。"""

class HarnessError(Exception):
    """所有基座异常的根。"""

class ConfigError(HarnessError):
    """配置组合非法，例如 mode=workflow 却传了 planner。"""

class BudgetExceeded(HarnessError): pass
class GuardDenied(HarnessError): pass
class ToolError(HarnessError): pass
class ReflectorReject(HarnessError): pass
class ApprovalExpired(HarnessError): pass
class MaxStepsExceeded(HarnessError): pass
class ContractError(HarnessError):
    """组件返回的类型不符合契约。"""

# ---- SPEC M16.1.1 的错误分类（映射在 kernel.stage.DefaultClassify）

class ValidationError(HarnessError):
    """参数不合法（Check 段的产物）。携带字段路径，便于模型自愈。"""
    def __init__(self, message: str, *, field: str = "") -> None:
        super().__init__(f"{field}: {message}" if field else message)
        self.field = field

class ConcurrencyError(HarnessError):
    """乐观并发冲突（expect_rev 不匹配）。"""

class TransientError(HarnessError):
    """可重试失败：超时、限流、5xx。"""

class PolicyError(HarnessError):
    """准入或护栏拒绝。"""

# ---- v3：纯新增

class DecisionError(ContractError):
    """transition 返回了不符合契约的东西。"""

class EffectError(HarnessError):
    """效应请求无法执行（未注册 kind、参数缺失等）。"""

class NotSerializable(ConfigError, TypeError):
    """闭包程序/层不提供 to_spec()：显式降级，不假装可序列化。
    同时继承 TypeError 以兼容「to_spec 抛 NotSerializable」的旧调用点。"""

BudgetError = BudgetExceeded   # SPEC 里叫 BudgetError；保留旧名兼容
```

`approval_errors.py`：

```python
class ApprovalRequired(HarnessError):
    """准入层判定"需要人点头"：由 Classify 映射为 NEEDS_APPROVAL。
    携带的信息足够重建一张审批卡片，且不含任何执行结果——此刻还没有结果。"""
    def __init__(self, step_id: str, *, reason: str = "", card: dict | None = None,
                 tool: str = "") -> None:
        super().__init__(f"需要审批：{tool or step_id} ({reason})")
        self.step_id = step_id
        self.reason = reason
        self.card = card or {}
        self.tool = tool
```

**封装手法**：
1. **异常即分类**：每个异常类对应 DefaultClassify 的一行映射（见 2.1），部件只需要抛对类型，不需要知道会被归成什么终态。
2. `ValidationError.field` 是给**模型自愈**用的——错误回灌给模型时，"哪个字段错"比错误文本更有用。
3. `NotSerializable(ConfigError, TypeError)` 双继承是迁移期技巧：新语义是"配置不可序列化"，旧调用点写的是 `except TypeError`——一个类同时满足两边，旧代码零改动。
4. `ApprovalRequired` 只带审批卡片信息、**不带结果**——抛它的时刻工具还没执行，用类型设计堵住"审批通过后才补结果"这类逻辑漏洞。

## 1.3 `contracts/events.py`：事件类型

```python
"""事件类型（SPEC M1.4、M10.1）。零依赖。"""

EVENT_NAMES = (
    "run.start", "run.end", "step.start", "step.end",
    "model.start", "model.delta", "model.end",
    "tool.start", "tool.end", "guardrail",
    "approval.required", "approval.resolved",
    "checkpoint", "error", "hook.error", "guardrail_error",
    # v3：解释器与效应系统的新插点
    "transition", "effect", "commit", "node",
)

@dataclass(frozen=True)
class TraceEvent:
    """v1 形状，保留兼容。"""
    trace_id: str; span_id: str; name: str; kind: str = "span"
    parent_id: str | None = None; start_ms: int = 0; end_ms: int = 0
    fields: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class RunEvent:
    """v2 统一事件（唯一对外观察面）。"""
    name: str; trace_id: str = ""; span_id: str = ""; parent_id: str | None = None
    kind: str = "span"; ts_ms: int = 0
    fields: dict[str, Any] = field(default_factory=dict); id: str = ""

@dataclass(frozen=True)
class HookEvent:
    """hook 的载荷：只读，返回值被忽略（SPEC M13.6）。"""
    point: str; state_id: str = ""; fields: dict[str, Any] = field(default_factory=dict)

@dataclass
class Span:
    """一次插点的起止。parent_id 必须真实填写（SPEC M11.4）。"""
    trace_id: str; span_id: str; name: str; parent_id: str | None = None
    start_ms: int = 0; end_ms: int | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    def end(self, **fields: Any) -> None:
        self.fields.update(fields)
```

**封装手法**：`EVENT_NAMES` 是元组不是枚举——加事件名不破坏任何消费者（按名字过滤），名字进了这个元组才算**稳定 API**。三个事件类型对应三代：v1 的 TraceEvent 是 span 制，v2 统一成 RunEvent（唯一观察面），v3 的 HookEvent 是 Hook 专用只读载荷——三者并存是"契约只增不改"纪律的产物。

## 1.4 `contracts/types.py`：全部值类型（693 行）

```python
"""契约数据类型（SPEC M1.2 / M1.4）。
规则：进契约的 dataclass 一律 frozen=True（State、Step、Plan、RunContext、
Budget 与流式累积态除外，它们跨层演进）。只增不改：新增字段必须有默认值。"""

# ---------- 标识 ----------
@dataclass(frozen=True)
class Namespace:
    """四段元组而非字符串：任何一层隔离都不能靠拼字符串（SPEC M1.11）。"""
    tenant: str = "default"; user: str = "anonymous"
    session: str = "default"; agent: str = "agent"
    def as_tuple(self): return (self.tenant, self.user, self.session, self.agent)
    def child(self, agent: str) -> "Namespace":
        return Namespace(self.tenant, self.user, self.session, agent)

@dataclass(frozen=True)
class SessionRef:
    """持久化单位（一个键），横跨多次 loop，挂不到任何插点。"""
    session_id: str; tenant: str = "default"; started_at: str = ""

@dataclass(frozen=True)
class SessionMeta:
    id: str; tenant: str = "default"; user_id: str = "anonymous"; title: str = ""
    status: str = "active"; created_at: float = 0.0; last_active: float = 0.0
    quota: dict[str, int] = field(default_factory=dict); pinned_model: str | None = None

# ---------- 输入 ----------
@dataclass(frozen=True)
class Goal:
    text: str; user_id: str = "anonymous"; session_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Brief:
    """子 agent 的交接单：必须带原始依据，不许只带结论（SPEC M14.3）。"""
    goal: Goal; context_refs: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    deadline: float | None = None

@dataclass(frozen=True)
class TaskSpec:
    description: str; agent_type: str = "default"
    expected_schema: dict[str, Any] | None = None; max_steps: int | None = None

# ---------- 过程 ----------
@dataclass
class Step:   # 唯一的跨层可变过程类型
    id: str; instruction: str = ""; tool_name: str | None = None
    args: dict[str, Any] = field(default_factory=dict); idem_key: str | None = None
    kind: Literal["tool", "llm", "agent", "human"] = "tool"
    index: int = 0; plan_id: str = ""

@dataclass(frozen=True)
class ToolCall:
    name: str; args: dict[str, Any] = field(default_factory=dict); id: str = ""

@dataclass(frozen=True)
class Done:
    """BodyPolicy 的"下不去了"信号。"""
    answer: str = ""; reason: str = "completed"

@dataclass
class Plan:
    id: str; steps: list[Step] = field(default_factory=list); rev: int = 0

@dataclass(frozen=True)
class ModelReply:
    content: str = ""; tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict); finish_reason: str = "stop"

@dataclass(frozen=True)
class ModelDelta:
    kind: Literal["text", "tool_call", "usage"] = "text"
    text: str = ""; index: int = 0; usage: dict[str, int] = field(default_factory=dict)

@dataclass(frozen=True)
class ResponseFormat:
    kind: Literal["text", "json_schema"] = "text"; schema: dict[str, Any] | None = None

@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]; content: str = ""
    tool_calls: tuple[dict[str, Any], ...] = (); tool_call_id: str = ""; name: str = ""

# ---------- 判定 ----------
@dataclass(frozen=True)
class Verdict:
    passed: bool; reason: str = ""
    action: Literal["accept", "retry", "patch", "replan_all"] = "accept"

@dataclass(frozen=True)
class GuardDecision:
    action: Literal["allow", "deny", "ask"]; reason: str = ""
    card: dict[str, Any] = field(default_factory=dict); expires_in: int | None = None
    @classmethod
    def allow(cls): return cls("allow")
    @classmethod
    def deny(cls, reason): return cls("deny", reason=reason)
    @classmethod
    def ask(cls, reason, card=None, expires_in=None):
        return cls("ask", reason=reason, card=card or {}, expires_in=expires_in)

@dataclass(frozen=True)
class Content:
    """护栏的输入：文本 + 种类 + 来源引用（SPEC M9.2）。"""
    text: str; kind: str = "model"; ref: str = ""

@dataclass(frozen=True)
class GuardrailVerdict:
    """检测与动作分离：检测器只报风险，动作由策略定（SPEC M9.2）。"""
    risk: float = 0.0; labels: tuple[str, ...] = ()
    action: Literal["allow", "warn", "redact", "rewrite", "ask", "block"] = "allow"
    spans: tuple[tuple[int, int], ...] = (); replacement: str | None = None

@dataclass(frozen=True)
class Decision:      # ★ 这是"人工审批结果"——与 v3 转移决策 Decision 同名不同物
    action: Literal["approve", "reject", "modify"]; by: str = "human"; reason: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    @classmethod
    def approve(cls, by="human", comment=""): return cls("approve", by=by, reason=comment)
    @classmethod
    def reject(cls, by="human", reason=""): return cls("reject", by=by, reason=reason)
    @classmethod
    def modify(cls, args, by="human"): return cls("modify", by=by, args=args)

@dataclass(frozen=True)
class Failure:
    """Filter 的唯一产物（SPEC M16.1.1）。"""
    status: RunStatus; reason: str; retryable: bool = False

# ---------- 结果 ----------
@dataclass(frozen=True)
class ActionResult:
    step_id: str; ok: bool; output: str = ""; error: str | None = None
    tokens: int = 0; tool_name: str | None = None
    citations: list[str] = field(default_factory=list)
    artifacts: list["ArtifactRef"] = field(default_factory=list)

@dataclass(frozen=True)
class ToolResult:
    step_id: str; tool: str = ""; ok: bool = True; output: str = ""
    error: str | None = None; tokens: int = 0
    artifacts: list["ArtifactRef"] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ExecResult:
    exit: int = 0; stdout: str = ""; stderr: str = ""
    artifacts: list["ArtifactRef"] = field(default_factory=list)
    truncated: bool = False; timed_out: bool = False

@dataclass(frozen=True)
class Pack:
    messages: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    frame: "Frame | None" = None

@dataclass(frozen=True)
class Recalled:
    text: str; layer: Literal["semantic", "episodic", "procedural"] = "semantic"
    score: float = 0.0; source: str = ""; age_days: int = 0
    dedup_key: str = ""; id: str = ""; superseded_by: str = ""

# ---------- 视图 ----------
@dataclass(frozen=True)
class Section:
    """取景产物的一个槽位。ephemeral = 只本轮可见（SPEC M6.1）。"""
    name: str; priority: int = 0; source: str = ""; text: str = ""
    tokens_est: int = 0; ephemeral: bool = False

@dataclass(frozen=True)
class Frame:
    kind: FrameKind = FrameKind.MODEL
    sections: tuple[Section, ...] = (); dropped: tuple[str, ...] = ()
    tokens_est: int = 0; meta: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Card:
    title: str = ""; body: str = ""
    fields: dict[str, str] = field(default_factory=dict); actions: tuple[str, ...] = ()

# ---------- 治理 ----------
@dataclass
class Budget:    # 可变：消耗计数
    tokens: int = 200_000; calls: int = 60
    used_tokens: int = 0; used_calls: int = 0
    owner: str = "run"; retries: int = 0; replans: int = 0
    @property
    def remaining_tokens(self): return max(0, self.tokens - self.used_tokens)
    @property
    def remaining_calls(self): return max(0, self.calls - self.used_calls)
    @property
    def exhausted(self): return self.remaining_tokens <= 0 or self.remaining_calls <= 0
    def spend(self, tokens=0, calls=1):
        self.used_tokens += max(0, tokens); self.used_calls += max(0, calls)
    def snapshot(self):
        return {"tokens": self.tokens, "calls": self.calls,
                "used_tokens": self.used_tokens, "used_calls": self.used_calls}
    def split(self, fraction: float = 0.3) -> "Budget":
        """给子 agent：额度按比例切分，消耗仍计入父（不变量 2）。"""
        ratio = max(0.0, min(1.0, fraction))
        return Budget(tokens=int(self.remaining_tokens * ratio),
                      calls=max(1, int(self.remaining_calls * ratio)),
                      owner=f"child:{self.owner}")

@dataclass(frozen=True)
class Limits:    # 沙箱资源上限（不是 v3 解释器的 Limits，那个在 kernel）
    cpu_s: float = 10.0; mem_mb: int = 512; wall_s: float = 30.0
    output_bytes: int = 1_000_000; network: bool = False

@dataclass(frozen=True)
class Mount:
    target: str; source: str | None = None; mode: Literal["ro", "rw"] = "ro"

@dataclass(frozen=True)
class ApprovalRequest:
    id: str; step: Step; reason: str = ""
    card: dict[str, Any] = field(default_factory=dict)
    expires_at: str = ""; session_id: str = ""

@dataclass(frozen=True)
class Checkpoint:
    session_id: str; rev: int; state: Any = None; created_at: float = 0.0

@dataclass(frozen=True)
class Recorded:
    key: str; value: Any = None; at: float = 0.0

@dataclass(frozen=True)
class Page:
    items: tuple[Any, ...] = (); cursor: str | None = None

# ---------- 工具元数据 ----------
@dataclass(frozen=True)
class ToolSpec:
    """工具元数据：驱动审批分级、幂等要求、沙箱路由（SPEC M3.5）。"""
    name: str; description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    side_effects: SideEffect = SideEffect.PURE
    scopes: frozenset[str] = frozenset()
    timeout_s: float | None = None; idempotent: bool = False
    max_output_bytes: int = 32_000; needs_approval: bool = False; sandbox: bool = False

@dataclass(frozen=True)
class ToolContext:
    """能力按 spec.scopes 注入；工具只能拿到声明过的能力。"""
    fs: Any = None; sandbox: Any = None; artifacts: Any = None
    secrets: Any = None; state: Any = None; signal: Any = None

# ---------- 后端数据 ----------
@dataclass(frozen=True)
class Document:
    id: str; text: str; metadata: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None

@dataclass(frozen=True)
class Job:
    id: str; kind: str; payload: dict[str, Any] = field(default_factory=dict)
    not_before: float = 0.0; attempts: int = 0; dedup_key: str = ""

@dataclass(frozen=True)
class Match:
    path: str; line: int = 0; text: str = ""

@dataclass(frozen=True)
class Stat:
    path: str; size: int = 0; mtime: float = 0.0; mode: int = 0; is_dir: bool = False

@dataclass(frozen=True)
class ArtifactRef:
    uri: str; bytes: int = 0; sha256: str = ""; content_type: str = ""

@dataclass(frozen=True)
class ArtifactMeta:
    ref: ArtifactRef; created_at: float = 0.0; expires_at: float | None = None

@dataclass
class StreamState:
    """流式护栏的累积态（可变的契约类型）。"""
    buffer: str = ""; blocks: int = 0; resumed: bool = False

@dataclass(frozen=True)
class Effect:
    """效应请求：想对外部世界做的一件事的描述，不是立刻做。

    v1 里它只是 dry_run 的产物；v3 起它是解释器的唯一 I/O 载体。
    遵守「只增不改」纪律：旧字段与位置不变，spec 放宽为 Any，新增字段
    全部带默认值，kind 由字面量放宽为 str——新增 kind 只需注册一个
    handler，不改内核。
    """
    kind: str = "tool"
    step: Step | None = None
    spec: Any = None
    est_tokens: int = 0
    key: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    child: Any = None        # child 效应携带的子程序
    idem_key: str = ""       # 幂等键：同键同结果（PROPOSAL §12）
    index: int = 0           # 批内序号，供事件与日志定位

@dataclass(frozen=True)
class LayerSpec:
    """层的声明形态（可序列化）；Layer 的运行形态含闭包，不可序列化。"""
    name: str; config: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ProgramSpec:
    body: str = "react"; max_steps: int = 24
    workflow: tuple[dict[str, Any], ...] = ()
    layers: tuple[LayerSpec, ...] = ()

# ---------- 拓扑 ----------
@dataclass(frozen=True)
class Route:
    name: str; accepts: list[str] = field(default_factory=list); fallback: bool = False

@dataclass
class Board:
    state: "State"; rev: int = 0; owner: str | None = None

# ---------- v1 运行时上下文（兼容） ----------
@dataclass
class RunContext:
    """v1 服务定位器，保留兼容；v2 用 kernel.scope.RunScope。"""
    state: "State"; actor: Any; context: Any; budget: Any; tracer: Any
    knowledge: Any = None; memory: Any = None; skills: Any = None; config: Any = None

# ---------- 层请求/响应（SPEC M1.7）----------
@dataclass(frozen=True)
class RunRequest:
    goal: Goal; ns: Namespace = field(default_factory=Namespace); state: Any = None

@dataclass(frozen=True)
class StepRequest:
    state: "State"; step: Step | Done

@dataclass(frozen=True)
class ModelRequest:
    state: Any = None; messages: tuple[Message, ...] = ()
    tools: tuple[dict[str, Any], ...] = ()
    budget: Budget | None = None; frame: Frame | None = None

@dataclass(frozen=True)
class ToolRequest:
    step: Step; spec: ToolSpec | None = None

@dataclass(frozen=True)
class RunResponse:
    result: Any = None

@dataclass(frozen=True)
class StepResponse:
    step: Step | None = None

@dataclass(frozen=True)
class ModelResponse:
    reply: ModelReply | None = None; usage: dict[str, int] = field(default_factory=dict)

@dataclass(frozen=True)
class ToolResponse:
    result: ToolResult | None = None

Request = RunRequest | StepRequest | ModelRequest | ToolRequest
Response = RunResponse | StepResponse | ModelResponse | ToolResponse
```

**封装手法**：
1. **frozen 是默认，可变是例外**——文件头一句话写明例外清单（State/Step/Plan/RunContext/Budget/StreamState）。判据：这个值"跨层演进"（会被谁改写）吗？会被改的才准可变。
2. **同名不同物的坑**：这里有一个 `Decision`（人工审批结果），v3 又有 `contracts/decision.py` 的 `Decision`（转移决策）。v3 的解法不是改旧名（会破坏兼容），而是给新类型加顶层别名 `Transition`、旧类型保持 `harness.Decision`——用命名空间隔离代替重命名。
3. `GuardDecision` 带 `card/expires_in`：ask 的那一刻就把审批卡片和有效期定好，下游（审批通道、Durability）不再需要理解"为什么要审批"。
4. `ToolSpec.scopes` + `ToolContext`：**能力注入的最小单位**。工具声明要什么能力（scopes），框架按声明给（ToolContext 字段）——没有声明就拿不到，这是最小权限的类型级实现。
5. 四对 Request/Response（run/step/model/tool）是**层的统一请求形状**：层不知道自己在哪个插点，只看 `isinstance(req, ToolRequest)` 决定管不管。
6. `LayerSpec` 与 `Layer` 分离：声明形态可序列化（进配置文件），运行形态含闭包不可序列化——不分开就无法"配置声明层"。

## 1.5 `contracts/state.py`：State 信封

```python
"""State 信封：公共字段 + 命名空间 data。"""

SCHEMA_VERSION = 2   # to_dict() 的落库版本；读取时走迁移函数链（SPEC §22）

@dataclass
class State:
    goal: Goal
    session: SessionRef
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    data: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    step_index: int = 0
    status: RunStatus = RunStatus.RUNNING
    usage: dict[str, int] = field(default_factory=lambda: {"tokens": 0, "calls": 0})
    last_error: str | None = None
    rev: int = 0                      # 最近一次落盘的版本号（不变量 1）

    # ---- v3 通用解释器：只增字段，全部带默认值 ----
    results: dict[str, Any] = field(default_factory=dict)  # 效应结果；__batch__ = 本批
    journal: dict[str, Any] = field(default_factory=dict)  # 观测/消费进度，不随回溯回滚

    def snapshot(self) -> dict[str, Any]:
        """只备份可回滚的业务状态。
        journal（观测进度）与 usage（计量）是既成事实，不随回溯回滚——
        否则回溯会把"已经问过模型"这件事也撤销，脚本会被重复消费。"""
        return copy.deepcopy({
            "goal": self.goal, "data": self.data, "results": self.results,
            "messages": self.messages, "step_index": self.step_index,
            "status": self.status, "last_error": self.last_error, "rev": self.rev,
        })

    def restore(self, snap: dict[str, Any]) -> None:
        """由解释器在 Decision.restore 时调用；不碰 journal/usage。"""
        for key in ("goal", "data", "results", "messages", "step_index",
                    "status", "last_error", "rev"):
            if key in snap:
                setattr(self, key, copy.deepcopy(snap[key]))

    def section(self, name: str) -> dict[str, Any]:
        """取一个策略自己的命名空间，不存在就建。"""
        value = self.data.get(name)
        if not isinstance(value, dict):
            value = {}
            self.data[name] = value
        return value

    def add_usage(self, tokens=0, calls=0):
        self.usage["tokens"] += max(0, tokens)
        self.usage["calls"] += max(0, calls)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION,
                "goal": {"text": self.goal.text, "user_id": self.goal.user_id,
                         "session_id": self.goal.session_id, "metadata": self.goal.metadata},
                "session": {"session_id": self.session.session_id,
                            "tenant": self.session.tenant,
                            "started_at": self.session.started_at},
                "trace_id": self.trace_id,
                "data": _jsonable(self.data), "messages": _jsonable(self.messages),
                "step_index": self.step_index, "status": str(self.status),
                "usage": dict(self.usage), "last_error": self.last_error,
                "rev": self.rev}

    @classmethod
    def from_dict(cls, raw) -> "State":
        """镜像 to_dict；trace_id 缺省重生成；status 容错缺省 running。"""

def _jsonable(value: Any) -> Any:
    """只允许 JSON 能表达的东西进 State；其余类型报错。"""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=_default))
    except TypeError as exc:
        raise TypeError(f"State 只能保存可序列化数据：{exc}") from exc

def _default(value: Any) -> Any:
    if dataclasses.is_dataclass(value): return dataclasses.asdict(value)
    if hasattr(value, "isoformat"): return value.isoformat()
    raise TypeError(f"不可序列化类型：{type(value).__name__}")
```

**封装手法**：
1. **信封 + 命名空间**，不是字段并集：所有策略共用一个 State 类，各自的字段放 `data["react"]`、`data["pe"]`、`section("tasks")`——否则 15 个组件的字段并集会把 State 撑爆，且组件之间会互相踩字段。
2. `snapshot/restore` 的分区是**踩坑的产物**（v3 样张第一次跑回溯时把模型脚本的消费游标也回滚了，脚本被重复消费）：可回滚（业务状态）与不可回滚（journal/usage，外部世界的既成事实）物理分成两组字段，restore 的 key 列表里根本没有 journal。
3. `_jsonable` 在写入口拦：连接、锁、客户端进 State 直接 TypeError。可序列化不是靠自觉，是靠入口检查。
4. `SCHEMA_VERSION` 进落库字典：旧 run 读不出时显式拒绝而不是猜。

## 1.6 `contracts/result.py`：RunResult

```python
@dataclass
class RunResult:
    status: RunStatus
    answer: str = ""
    state: State | None = None
    usage: dict[str, int] = field(default_factory=lambda: {"tokens": 0, "calls": 0})
    citations: list[str] = field(default_factory=list)
    pending: ApprovalRequest | None = None
    error: str | None = None
    trace_id: str = ""
    rev: int = 0                      # 指向最终检查点，供 resume / 时间旅行
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (RunStatus.COMPLETED, RunStatus.DEGRADED)
```

**封装手法**：`pending` 字段让 `NEEDS_APPROVAL` 成为"带附件的结局"——调用方拿 `result.pending` 走审批，`agent.resume(id, decision)` 回来；`rev` 指向最终检查点，是时间旅行的入口。运行中间态（RUNNING）永远不会出现在这里。

## 1.7 `contracts/protocols/`：九个协议文件（部件的接口层）

### `guards.py` —— 准入与内容

```python
@runtime_checkable
class Guard(Protocol):
    """段 Gate。返回判定、不抛异常、可短路。"""
    async def check_identity(self, goal: Any, ns: Any) -> "GuardDecision": ...
    async def check(self, step: "Step", state: "State") -> "GuardDecision": ...

@runtime_checkable
class Guardrail(Protocol):
    """五道闸的内容检测；检测与动作分离（SPEC M9.2）。"""
    name: str
    gates: frozenset[str]
    async def check(self, content: "Content", scope: Any) -> "GuardrailVerdict": ...

@runtime_checkable
class GuardrailStream(Guardrail, Protocol):
    """流式增量检测（SPEC M9.4）：窗口缓冲 + 结尾 flush。"""
    async def feed(self, delta: str, st: "StreamState") -> "GuardrailVerdict": ...
    async def flush(self, st: "StreamState") -> "GuardrailVerdict": ...
```

### `governance.py` —— 决策、路由、校验、观测、出口

```python
@runtime_checkable
class Actor(Protocol):
    """插点 ④ 决策 + ⑥ 执行。只做执行，不做评估（SPEC M3.1）。"""
    async def propose(self, state: "State", scope: Any) -> Any: ...
    async def step(self, step: Any, state: "State", scope: Any) -> "ActionResult": ...

@runtime_checkable
class Router(Protocol):
    """分派层：不解决问题，只决定谁来解决（SPEC M4.1）。"""
    async def route(self, goal: "Goal", state: "State | None" = None) -> "Route": ...

@runtime_checkable
class Reflector(Protocol):
    """单步结果质量判定（SPEC M5.1）。"""
    async def review(self, result: "ActionResult", state: "State") -> "Verdict": ...

@runtime_checkable
class Validator(Protocol):
    """最终答案判定。"""
    async def validate(self, answer: str, state: "State") -> "Verdict": ...

@runtime_checkable
class Tracer(Protocol):
    """带 span 语义的事件出口；异常不得影响请求（SPEC M10.1）。"""
    async def emit(self, event: "RunEvent") -> None: ...

@runtime_checkable
class Delivery(Protocol):
    """出口唯一：只有它能产出 RunResult（SPEC M10.3）。"""
    async def finish(self, state, status, *, answer="", reason="",
                     pending=None) -> "RunResult": ...
```

### `tools.py` / `model.py` / `framing.py`

```python
@runtime_checkable
class Tool(Protocol):
    """唯一有副作用的执行原语。spec 携带元数据，invoke 接收能力注入的 ToolContext。"""
    spec: "ToolSpec"
    async def invoke(self, args: dict[str, Any], ctx: "ToolContext") -> "ToolResult": ...

@runtime_checkable
class Model(Protocol):
    """一次补全 + 一次流式补全。usage 必须归一化成 {input, output, total}。"""
    async def complete(self, messages, tools=None, *, response_format) -> "ModelReply": ...
    def stream(self, messages, tools=None) -> AsyncIterator["ModelDelta"]: ...

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

@runtime_checkable
class Context(Protocol):
    """v1 形状，保留兼容；v2 由 Framer + Encoder 取代（P4 迁移）。"""
    async def assemble(self, state, budget_tokens) -> "Pack": ...
```

### `runtime.py` —— 运行时扩展点（四段链的部件全在这）

```python
Handler = Callable[[Any], Awaitable[Any]]
"""(Request) -> Response。层签名统一为 (req, nxt) -> Response。"""

@runtime_checkable
class Middleware(Protocol):
    """段 Wrap：插点上的包裹。"""
    name: str
    points: frozenset[str]     # 在哪些插点生效
    needs: frozenset[str]      # 依赖哪些能力（缺则在装配期报错，不降级）
    after: frozenset[str]
    before: frozenset[str]
    async def __call__(self, req: Any, nxt: Handler) -> Any: ...

@runtime_checkable
class Hook(Protocol):
    """纯观察：只读事件，返回值被忽略（= 不调 nxt 的层）。"""
    point: str
    async def __call__(self, event: "HookEvent") -> None: ...

@runtime_checkable
class Pipe(Protocol):
    """段 Check：参数校验与转换，失败抛 ValidationError。"""
    async def transform(self, step: "Step", state: "State") -> "Step": ...

@runtime_checkable
class Filter(Protocol):
    """段 Classify：异常 → Failure 的唯一映射点。"""
    async def classify(self, exc: BaseException, *, phase: str, state: "State") -> "Failure": ...

@runtime_checkable
class Runnable(Protocol):
    """可运行单元；拓扑可嵌套（Agent 与 Topology 同签名）。"""
    name: str
    async def run(self, goal: "Goal", *, scope: Any) -> "RunResult": ...

@runtime_checkable
class Topology(Runnable, Protocol):
    children: tuple["Runnable", ...]

@runtime_checkable
class Program(Protocol):
    """v3 唯一契约：transition(state) -> Decision | Halt（PROPOSAL §4）。
    返回类型用 Any 以避免契约层内部循环导入；具体判定在 kernel.interpret
    用 isinstance 完成。"""
    name: str
    def transition(self, state: "State") -> Any: ...
```

### `stores.py` —— 存储协议（两代并存）

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

@runtime_checkable
class SessionStore(Protocol):
    async def create(self, ns, meta) -> "SessionMeta": ...
    async def get(self, ns, sid) -> "SessionMeta | None": ...
    async def list(self, ns, *, cursor=None, limit=50) -> Any: ...
    async def update(self, ns, sid, patch) -> "SessionMeta": ...

@runtime_checkable
class MessageLog(Protocol):
    async def append(self, ns, sid, msgs) -> int: ...
    async def tail(self, ns, sid, *, max_tokens) -> list[dict]: ...

@runtime_checkable
class Memory(Protocol):
    """v1 形状，保留兼容。"""
    async def recall(self, query, *, scope, layers, k) -> list["Recalled"]: ...
    async def write(self, items) -> int: ...

@runtime_checkable
class MemoryStore(Protocol):
    """v2 形状：命名空间强制、可遗忘、可过期、去重键（SPEC M7.2）。"""
    async def recall(self, ns, query, *, layers, k) -> list["Recalled"]: ...
    async def upsert(self, ns, items) -> int: ...
    async def forget(self, ns, ids) -> int: ...
    async def expire(self, ns, now) -> int: ...

@runtime_checkable
class Idempotency(Protocol):
    async def begin(self, ns, key) -> Any: ...
    async def commit(self, ns, key, value) -> None: ...

@runtime_checkable
class MemoryPolicy(Protocol):
    """写入策略与存取分离（SPEC M7.2）：该不该写、写成什么、何时合并失效。"""
    async def should_write(self, state, result) -> bool: ...
    async def extract(self, state) -> list["Recalled"]: ...
    async def merge(self, old, new) -> list["Recalled"]: ...
    async def decay(self, items, now) -> list["Recalled"]: ...
```

### `backends.py` —— 外部世界边界

```python
@runtime_checkable
class FileSystem(Protocol):
    """虚拟路径 + 挂载表；resolve() 是唯一 jail 点（SPEC M12.3）。"""
    mounts: tuple["Mount", ...]
    async def read(self, path: str) -> bytes: ...
    async def write(self, path: str, data: bytes) -> None: ...
    async def edit(self, path, old, new, *, count=1) -> int: ...
    async def glob(self, pattern) -> list[str]: ...
    async def grep(self, pattern, *, glob="**/*", max_hits=200) -> list["Match"]: ...
    async def stat(self, path) -> "Stat": ...

@runtime_checkable
class Sandbox(Protocol):
    """执行边界。exec 只收 argv 列表，不给 shell 解析留口子（SPEC M12.4）。"""
    async def exec(self, argv, *, cwd="/work", env=None, stdin=None,
                   limits=None, timeout_s=None) -> "ExecResult": ...
    async def kill(self, exec_id: str) -> None: ...

@runtime_checkable
class ArtifactStore(Protocol):
    async def put(self, name, data) -> "ArtifactRef": ...
    async def get(self, ref) -> bytes: ...
    async def stat(self, ref) -> "ArtifactMeta": ...

@runtime_checkable
class SecretBroker(Protocol):
    """只按名取；永不明文进 prompt（SPEC M12.2）。"""
    async def get(self, name) -> str: ...
    async def list(self) -> list[str]: ...

@runtime_checkable
class IndexBackend(Protocol):
    """过滤必须下推到后端，否则租户泄漏（SPEC M12.2）。"""
    async def search(self, ns, query, *, k, filters=None) -> list["Recalled"]: ...
    async def upsert(self, ns, docs) -> int: ...

@runtime_checkable
class Skills(Protocol):
    """给流程不给能力；三段式渐进披露（SPEC M7.3）。"""
    def catalog(self) -> list[Any]: ...
    async def load(self, name) -> Any: ...
    async def resource(self, name, path) -> str: ...

@runtime_checkable
class EventSink(Protocol):
    async def emit(self, event: "RunEvent") -> None: ...

@runtime_checkable
class Queue(Protocol):
    async def enqueue(self, job, *, delay_s=0) -> str: ...
    async def dequeue(self, *, timeout_s) -> Any: ...
    async def ack(self, job_id) -> None: ...

@runtime_checkable
class ApprovalChannel(Protocol):
    async def request(self, req) -> str: ...
    async def wait(self, approval_id, *, timeout_s) -> "Decision | None": ...
    async def respond(self, approval_id, decision) -> None: ...

@runtime_checkable
class Clock(Protocol):
    """可注入时间，测试与回放必须能控制（SPEC M12.2）。"""
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...
```

### `body.py` —— 主体策略缝

```python
@runtime_checkable
class BodyPolicy(Protocol):
    """唯一策略缝：内核只问"下一步是什么"，不问"怎么想出来的"。"""
    name: str
    async def next_step(self, state: "State", scope: Any) -> "Step | Done": ...

@runtime_checkable
class Planner(Protocol):
    """只在 Plan-and-Execute 里出现（ReAct / Workflow 不持有 Planner）。"""
    async def plan(self, goal: "Goal", state: "State") -> "Plan": ...
```

**协议层封装手法汇总**：
1. `@runtime_checkable Protocol`：结构化类型——部件不需要继承任何基类，"长得像"就算实现。装配期可以做 `isinstance(x, Guard)` 检查而不引入继承耦合。
2. **失败语义编码在签名里**：Guard 返回判定、Pipe 抛异常、Filter 只收异常——读签名就知道部件在四段链的哪一段。
3. **职责边界写在 docstring**："只做执行，不做评估"、"不解决问题，只决定谁解决"、"不拼字符串、不决定格式"——每个协议的"不做清单"和"做清单"同样精确。
4. **两代并存**（Durability/CheckpointStore、Memory/MemoryStore、Context/Framer+Encoder）不是没清理，是迁移纪律：旧形状签名不变，新形状在旁边，工厂慢慢迁。
5. `stores` 全部收 `Namespace` 第一参：多租户隔离在签名里强制。

## 1.8 `contracts/decision.py`：唯一契约（v3）

```python
"""通用解释器的唯一契约（v3 / PROPOSAL §4）。

框架不提供任何架构，只提供这套最小执行契约：
    Program.transition(state) -> Decision | Halt

命名说明：本模块里的 Decision 是「转移决策」。现有
harness.contracts.types.Decision 是「人工审批结果」，语义不同且被
ApprovalChannel / Agent.resume 依赖，因此两者保持命名空间隔离：
顶层 harness.Decision 仍是审批类型，本类型通过
harness.contracts.decision.Decision 使用，顶层别名为 Transition。
"""

@dataclass(frozen=True)
class Decision:
    """一次转移。"""
    effects: tuple[Effect, ...] = ()   # 一批效应请求：0 个=纯决策步，多个=并行
    program: Any = None                # 下一个程序；None=保持当前（自己=循环）
    patch: dict[str, Any] = field(default_factory=dict)   # 显式状态增量
    restore: dict[str, Any] | None = None  # 回溯：先恢复历史快照再执行
    note: str = ""                     # 人类可读备注，进 trace
    meta: dict[str, Any] = field(default_factory=dict)    # 内核不解释的透传

@dataclass(frozen=True)
class Halt:
    """终止。status 用字符串，允许前端自定义状态而不改内核。"""
    answer: str = ""; status: str = "completed"
    extra: dict[str, Any] = field(default_factory=dict)

class FnProgram:
    """零封装入口：把一个裸函数（可同步可异步）变成 Program。"""
    def __init__(self, fn, name: str = "fn") -> None:
        self.fn = fn; self.name = name
    def transition(self, state: State) -> Decision | Halt:
        return self.fn(state)

CAPABILITIES = ("describe", "to_spec", "static_check")

def capabilities(program) -> dict[str, bool]:
    """程序声明自己支持哪些静态能力，框架不假装全能。"""
    return {name: callable(getattr(program, name, None)) for name in CAPABILITIES}

def describe(program) -> str:
    fn = getattr(program, "describe", None)
    return fn() if callable(fn) else f"<opaque:{getattr(program, 'name', type(program).__name__)}>"

def to_spec(program) -> dict[str, Any]:
    """检查点序列化。闭包程序显式降级，不假装支持时间旅行。"""
    fn = getattr(program, "to_spec", None)
    if not callable(fn):
        raise NotSerializable("NotSerializable: 闭包程序不提供 to_spec()")
    return fn()

def static_problems(program) -> list[str]:
    """装配期可查的都查；不透明程序返回空列表（运行时治理）。"""
    check = getattr(program, "static_check", None)
    return list(check()) if callable(check) else []
```

**封装手法**：
1. `Decision.program=None` 是语义最密的一个字段：**保持当前=循环、换成历史程序=回溯、换成新组合=改图**——控制流三件事被一个"下一个程序指针"全覆盖。
2. `Halt.status` 用 `str` 不用枚举：前端自定义终止态（"refused_by_policy"之类）不用改内核。
3. 治理分级做成**能力探测**而不是接口继承：`getattr(program, "to_spec", None)`——程序实现了就用，没实现显式降级 `<opaque>`，框架不假装全能。

---

# 阶段二 kernel/ —— 先造循环，再装治理

## 2.1 `kernel/stage.py`：四段执行链

```python
"""L0 内核：四段执行链（Gate → Check → Wrap → Classify）。
四段的失败语义不同，所以不能合并成一条洋葱（SPEC M2.2）：

    Gate     动作准入，返回判定，不抛异常，可短路
    Check    参数校验与转换，抛 ValidationError
    Wrap     包裹执行，异常原样穿透
    Classify 异常 → Failure 的唯一映射点，不吞异常"""

Terminal = Callable[[Step, State], Awaitable[ActionResult]]

@dataclass(frozen=True)
class ToolRequest:
    """Wrap 段的请求形状（SPEC M1.7）。层拿它构造新 Response，不原地改。"""
    step: Step; state: State

@dataclass(frozen=True)
class Failure:
    """异常归类结果。Filter 的唯一产物（SPEC M16.1.1）。"""
    status: RunStatus; reason: str; retryable: bool = False

@dataclass(frozen=True)
class StageResult:
    """一段链走完的结局：要么有动作结果，要么有失败分类。"""
    step: Step; result: ActionResult | None = None; failure: Failure | None = None
    @property
    def ok(self) -> bool:
        return self.result is not None and self.failure is None

class AllowAllGate:
    async def check(self, step, state) -> GuardDecision: return GuardDecision.allow()

class DenyAllGate:
    async def check(self, step, state) -> GuardDecision:
        return GuardDecision.deny("DenyAllGate")

class IdentityCheck:
    async def transform(self, step, state) -> Step: return step

class DefaultClassify:
    """异常 → Failure 的默认映射（SPEC M16.1.1）；未知异常 fail-closed。"""
    async def classify(self, exc, *, phase, state) -> Failure:
        if isinstance(exc, asyncio.CancelledError):
            return Failure(RunStatus.CANCELLED, "cancelled", False)
        if isinstance(exc, ApprovalRequired):
            return Failure(RunStatus.NEEDS_APPROVAL, exc.reason or "approval_required", False)
        if isinstance(exc, (GuardDenied, PolicyError)):
            return Failure(RunStatus.REFUSED, f"policy:{exc}", False)
        if isinstance(exc, ApprovalExpired):
            return Failure(RunStatus.REFUSED, "approval:expired", False)
        if isinstance(exc, ConcurrencyError):
            return Failure(RunStatus.REFUSED, "concurrency_conflict", False)
        if isinstance(exc, ValidationError):
            return Failure(RunStatus.REFUSED, f"invalid_args:{exc.field}", False)
        if isinstance(exc, TransientError):
            return Failure(RunStatus.DEGRADED, "transient_exhausted", True)
        if isinstance(exc, BudgetExceeded):
            return Failure(RunStatus.DEGRADED, "budget", False)
        if isinstance(exc, ToolError):
            return Failure(RunStatus.DEGRADED, "tool", True)
        if isinstance(exc, (ConfigError, ContractError)):
            return Failure(RunStatus.FAILED, type(exc).__name__, False)
        return Failure(RunStatus.FAILED, type(exc).__name__, False)

async def run_stages(step, state, *, terminal, gate=None, checks=(),
                     layers=(), classify=None) -> StageResult:
    """按固定顺序走四段；顺序不可调、不可合并、不可省略。"""
    gate = gate or AllowAllGate()
    classify = classify or DefaultClassify()

    # ① Gate：返回判定，不抛异常
    decision: GuardDecision = await gate.check(step, state)
    if decision.action == "deny":
        return StageResult(step, failure=Failure(RunStatus.REFUSED,
                           f"policy:{decision.reason}", False))
    if decision.action == "ask":
        return StageResult(step, failure=Failure(RunStatus.NEEDS_APPROVAL,
                           decision.reason, False))

    # ② Check：校验与转换
    try:
        for check in checks:
            step = await check.transform(step, state)
    except Exception as exc:
        return StageResult(step, failure=await classify.classify(exc, phase="check", state=state))

    # ③ Wrap：洋葱包住终端（层签名是 (ToolRequest, nxt) -> ActionResult）
    async def base(req: ToolRequest) -> ActionResult:
        return await terminal(req.step, req.state)

    handler: Callable[[ToolRequest], Awaitable[ActionResult]] = base
    for layer in reversed(list(layers)):
        inner, lay = handler, layer
        async def handler(req: ToolRequest, *, _inner=inner, _lay=lay) -> ActionResult:
            return await _lay(req, _inner)

    # ④ Classify：异常 → Failure 的唯一映射点
    try:
        result = await handler(ToolRequest(step=step, state=state))
    except Exception as exc:
        return StageResult(step, failure=await classify.classify(exc, phase="wrap", state=state))
    return StageResult(step, result=result)
```

**封装手法**：
1. 四段顺序写死在一个函数里且注释声明"不可调、不可合并、不可省略"——这不是不灵活，是把**语义正确性**锁进实现：Gate 返回值短路、Check 异常当场归类（没有资格到终端）、Wrap 穿透、Classify 独占翻译权。
2. 洋葱构造用默认参数闭包 `_inner=inner, _lay=lay` 防循环变量 late-binding 的经典 bug——自己写洋葱链必抄。
3. `StageResult` 把"成功"与"失败"统一成一个值：调用方永远 `sr.ok` 判断，不再 try/except。
4. `AllowAllGate/DenyAllGate/IdentityCheck/DefaultClassify` 四个缺省件显式存在——"没有配"和"决定放行"必须可区分。

## 2.2 `kernel/chain.py`：插点、拓扑排序、洋葱执行

```python
"""L0 内核：链执行器（拓扑排序 + 洋葱）。
只对同一插点内的层排序；环 → ConfigError；洋葱只在 Wrap 段使用。"""

POINTS = (
    "run", "step", "model_call", "tool_call",     # 旧四点
    "transition", "effect", "commit", "node",     # v3 新增：解释器事件插点
)

def _points_of(layer) -> frozenset[str]:
    raw = getattr(layer, "points", frozenset())
    if isinstance(raw, str):
        raw = {raw}                 # 容错：单个字符串也接受
    return frozenset(raw)

def resolve(layers, point) -> list[Any]:
    """筛出该插点的层并按 after/before 拓扑排序。
    无约束的层保持注册顺序（稳定排序），保证可复现。"""
    if point not in POINTS:
        raise ConfigError(f"未知插点：{point!r}，合法值 {POINTS}")

    picked = [lay for lay in layers if point in _points_of(lay)]
    names = [getattr(lay, "name", f"layer{i}") for i, lay in enumerate(picked)]
    if len(set(names)) != len(names):
        raise ConfigError(f"插点 {point} 上存在重名层：{names}")

    edges: dict[str, set[str]] = {n: set() for n in names}
    for lay, name in zip(picked, names):
        for dep in getattr(lay, "after", frozenset()):
            if dep in edges:
                edges[name].add(dep)
        for dep in getattr(lay, "before", frozenset()):
            edges[dep].add(name)

    ordered: list[str] = []
    pending: dict[str, set[str]] = {n: set(d) for n, d in edges.items()}
    while pending:
        ready = [n for n in names if n in pending and not pending[n]]
        if not ready:
            raise ConfigError(f"插点 {point} 的层顺序成环：{sorted(pending)}")
        for n in ready:
            ordered.append(n)
            del pending[n]
        for deps in pending.values():
            deps.difference_update(ready)

    by_name = dict(zip(names, picked))
    return [by_name[n] for n in ordered]

def describe(layers, point) -> str:
    return " > ".join(getattr(lay, "name", "?") for lay in resolve(layers, point))

async def execute(layers, request, terminal) -> Any:
    """洋葱执行：第一层最外，最后一层最内，逐层包裹终端。
    层可以是 Layer（有 wrap）或普通 (req, nxt) 可调用对象。"""
    def _wrap(lay, nxt):
        if hasattr(lay, "wrap"):
            return lay.wrap(nxt)
        async def call(req, *, _lay=lay, _nxt=nxt):
            return await _lay(req, _nxt)
        return call

    handler = terminal
    for lay in reversed(list(layers)):
        handler = _wrap(lay, handler)
    return await handler(request)
```

**封装手法**：
1. `POINTS` 是字符串元组不是枚举——v3 加四个新插点没动旧代码。
2. 顺序是**声明式**（after/before），层之间不 import 对方也能表达依赖；环在装配期爆 `ConfigError`，绝不带病运行。
3. 重名校验：排序按名字，重名即歧义，直接拒绝。
4. `execute` 兼容两种层形态（有 `wrap` 方法的 Layer 值对象、裸 `(req, nxt)` 函数）——层的定义不垄断在一处。

## 2.3 `kernel/scope.py`：能力作用域

```python
"""L0 内核：运行作用域。
作用域只持有不可变的能力引用；可变状态只有 State（见 SPEC M2.4）。
子 agent 通过 child() 派生：新命名空间、切分预算、独立沙箱、span 挂父。"""

@dataclass(frozen=True)
class RunScope:
    namespace: Namespace = field(default_factory=Namespace)
    budget: Any = None
    tracer: Any = None
    delivery: Any = None
    guard: Any = None
    actor: Any = None          # 执行原语（P5 接入；缺省 None 时策略明确报错）
    framer: Any = None
    encoder: Any = None
    model: Any = None; fs: Any = None; sandbox: Any = None
    artifacts: Any = None; secrets: Any = None; index: Any = None
    memory: Any = None
    guardrails: tuple[Any, ...] = ()
    events: Any = None         # EventSink：唯一对外观察面
    model_call: Any = None     # 由内核注入：经 model_call 链的模型调用
    pipes: tuple[Any, ...] = ()
    layers: tuple[Any, ...] = ()
    filter: Any = None
    clock: Any = None; config: Any = None
    depth: int = 0
    max_depth: int = 2
    #: 子 agent 并发槽位。挂在这里而不是挂在层上：层是值、会被复制，
    #: 挂在层上会导致"每层各造一个信号量"，总量失控（SPEC M13.7）。
    child_slots: Any = None
    capacity: dict[str, Any] = field(default_factory=dict)

    def child(self, name: str, *, budget_fraction: float = 0.3) -> "RunScope":
        """派生子作用域：实现"资源单一所有者"不变量（单向继承）。"""
        if self.depth + 1 > self.max_depth:
            raise ConfigError(
                f"子 agent 深度超过上限 {self.max_depth}：{self.namespace.agent} -> {name}")
        child_budget = self.budget
        if self.budget is not None and hasattr(self.budget, "split"):
            child_budget = self.budget.split(budget_fraction)
        return replace(self, namespace=replace(self.namespace, agent=name),
                       budget=child_budget, depth=self.depth + 1)
```

**封装手法**：
1. frozen 值对象 + `replace()` 派生：作用域在运行期不可能被偷改权柄。
2. 缺省 None 但"用时明确报错"：新字段必须带默认值（契约只增不改），可降级不可假装。
3. `child_slots` 挂 scope 的教训要记住：**有并发语义的资源挂单例作用域，不挂可复制的值**。
4. `model_call` 是内核注入的"经链调用"——Actor 等部件调它就自动过全部层，不需要 import kernel。

## 2.4 `kernel/effects.py`：效应系统（401 行）

```python
"""效应系统（v3 / PROPOSAL §5、§9.1）。
所有 I/O 必须先表达成 Effect，由这里批量执行，走四段链
Gate → Check → Wrap → Classify；之后才由解释器在唯一提交点写状态。
三件事在这里定死：
* kind 可扩展：新增效应类型只需注册一个 handler，内核零改动；
* 一批效应并发执行（asyncio.gather），并行不需要框架算子；
* record_only=True 就是 dry_run：四段链照走，终端只记账不执行。"""

#: Effect.kind → 既有 Step.kind（PROPOSAL §6 的薄适配器）
_KIND_TO_STEP = {
    "tool": "tool", "model": "llm", "child": "agent", "ask": "human",
    "skill": "tool", "wait": "human", "compute": "tool",
}

async def maybe_await(value):     # 层与 handler 允许同步或异步
    return await value if inspect.isawaitable(value) else value

def to_step(effect: Effect) -> Step:
    """Effect → Step 薄适配器：让 kernel/stage.py 的四段链一行不改被效应喂入。"""
    if effect.step is not None:
        return effect.step
    args = effect.args or {}
    raw_args = args.get("args", {}) or {}
    step_args = dict(raw_args) if isinstance(raw_args, dict) else {}
    return Step(
        id=effect.key or effect.kind,
        instruction=str(args.get("instruction", "")),
        tool_name=args.get("name"),
        args=step_args,
        idem_key=effect.idem_key or None,
        kind=_KIND_TO_STEP.get(effect.kind, "tool"),
    )

def as_result_dict(value) -> dict:
    """把任意 handler 产物归一成 dict；兼容既有 ActionResult。"""
    if isinstance(value, dict):
        return dict(value)
    return {"ok": bool(getattr(value, "ok", True)),
            "output": getattr(value, "output", ""),
            "error": getattr(value, "error", "") or "",
            "tokens": int(getattr(value, "tokens", 0) or 0),
            "raw": value}

# ---- 横切层：v3 四段打包成一个值对象 ----
def _allow(effect, state): return "allow"
def _noop_check(effect, state): return None
def _identity_wrap(effect, nxt): return nxt
def _noop_observe(effect, result, state): return None

@dataclass(frozen=True)
class EffectLayer:
    """效应层的四段 + 观察。与既有 Layer/Middleware/Hook 协议一一对应。
    gate    Gate，返回 allow / deny / ask；不抛异常、可短路
    check   Check，抛异常即归类为参数非法
    wrap    Wrap，wrap(effect, nxt) -> handler(effect, state)，洋葱包裹
    observe Hook，只读观察；异常被吞掉，不影响运行"""
    name: str
    gate: Callable = _allow
    check: Callable = _noop_check
    wrap: Callable = _identity_wrap
    observe: Callable = _noop_observe
    points: frozenset[str] = frozenset({"effect", "commit"})

@dataclass
class EffectRuntime:
    """可扩展的效应运行时。
    handlers 是一张 kind → fn(effect, state) 表；新增 kind 只需
    extra_handlers 注册一个函数，不改内核、不加 if kind == ...。"""
    layers: tuple[EffectLayer, ...] = ()
    record_only: bool = False
    extra_handlers: dict[str, Callable] = field(default_factory=dict)
    guard: Any = None
    checks: tuple[Any, ...] = ()
    classify: Any = None
    hooks: tuple[Any, ...] = ()
    emit: Callable | None = None
    model: Any = None
    tool_registry: Any = None
    child_runner: Callable | None = None
    effects_log: list[Effect] = field(default_factory=list)   # dry_run 用
    seen: dict[str, Any] = field(default_factory=dict)        # 幂等键 → 结果

    def __post_init__(self) -> None:
        self.layers = tuple(self.layers)
        self.handlers: dict[str, Callable] = {
            "model": self._model, "tool": self._tool, "skill": self._skill,
            "ask": self._ask, "wait": self._wait, "compute": self._compute,
            "child": self._child,
        }
        self.handlers.update(self.extra_handlers or {})       # 注册代替分支

    async def execute(self, effects, state) -> list[Any]:
        """批量并发执行；0 个效应就是纯决策步，不落盘不记账。"""
        if not effects:
            return []
        self.effects_log.extend(effects)
        indexed = [replace(e, index=i) for i, e in enumerate(effects)]
        return list(await asyncio.gather(*(self._stages(e, state) for e in indexed)))

    # ---- 四段链 ----
    async def _stages(self, effect: Effect, state) -> dict:
        step = to_step(effect)

        async def finish(result):
            for layer in self.layers:                        # Hook：只读观察
                try:
                    await maybe_await(layer.observe(effect, result, state))
                except Exception:
                    pass                                      # 观测不得影响运行
            await self._fire_hooks(effect, result, state)
            return result

        # 幂等：同键命中直接回放，不重复产生副作用、也不重复计量
        if effect.idem_key and effect.idem_key in self.seen:
            cached = dict(self.seen[effect.idem_key])
            cached["_usage"] = {"calls": 0, "tokens": 0}
            return await finish(cached)

        # ① Gate：返回判定，不抛异常，可短路
        for layer in self.layers:
            verdict = await maybe_await(layer.gate(effect, state))
            if verdict in ("deny", "ask"):
                return await finish({
                    "ok": False,
                    "error": f"{'gate' if verdict == 'deny' else 'approval'}:{layer.name}",
                    "status": "refused" if verdict == "deny" else "needs_approval",
                })
        if self.guard is not None:
            verdict = await self.guard.check(step, state)
            if getattr(verdict, "action", "allow") in ("deny", "ask"):
                return await finish({
                    "ok": False, "error": f"policy:{getattr(verdict, 'reason', '')}",
                    "status": "refused" if verdict.action == "deny" else "needs_approval",
                })

        # ② Check：参数校验与转换
        try:
            for layer in self.layers:
                await maybe_await(layer.check(effect, state))
            for pipe in self.checks:
                step = await maybe_await(pipe.transform(step, state))
        except Exception as exc:
            return await finish(await self._failed(exc, state, phase="check"))

        # ③ Wrap：洋葱，外层在最外
        handler: Callable = self._terminal
        for layer in reversed(self.layers):
            handler = layer.wrap(effect, handler) or handler

        # ④ Classify：异常 → 失败归类的唯一映射点
        try:
            out = await maybe_await(handler(effect, state))
            result = as_result_dict(out)
        except Exception as exc:
            result = await self._failed(exc, state, phase="wrap")

        if effect.idem_key:
            self.seen[effect.idem_key] = dict(result)
        return await finish(result)

    async def _failed(self, exc, state, *, phase) -> dict:
        classifier = self.classify or stage.DefaultClassify()
        try:
            failure = await classifier.classify(exc, phase=phase, state=state)
            status = str(getattr(failure, "status", "failed"))
            reason = getattr(failure, "reason", str(exc))
        except Exception:                       # 归类器本身坏了也不能吞掉结果
            status, reason = "failed", str(exc)
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}",
                "status": status, "reason": reason}

    async def _fire_hooks(self, effect, result, state) -> None:
        """v3 首次给 Hook 协议接上真正落点；hook 报错只发 hook.error。"""
        point = f"effect.{effect.kind}"
        event = HookEvent(point=point, state_id=state.trace_id,
                          fields={"key": effect.key, "ok": bool(result.get("ok", True))})
        for hook in self.hooks:
            if point not in getattr(hook, "point", point):   # 前缀匹配订阅
                continue
            try:
                await maybe_await(hook(event))
            except Exception as exc:
                if self.emit is not None:
                    await self.emit("hook.error", error=str(exc), point=point)
        if self.emit is not None:
            await self.emit("effect", kind=effect.kind, key=effect.key,
                            ok=bool(result.get("ok", True)), rev=state.rev)

    async def _terminal(self, effect, state) -> dict:
        """终端：只记账不写业务状态（状态单一所有者由 commit 保证）。"""
        usage = {"calls": 1, "tokens": 10 if effect.kind == "model" else 0}
        if self.record_only:
            return {"ok": True, "output": f"[dry-run:{effect.kind}]", "_usage": usage}
        handler = self.handlers.get(effect.kind)
        if handler is None:
            raise EffectError(f"未注册的效应类型：{effect.kind}")
        out = await maybe_await(handler(effect, state))
        result = as_result_dict(out)
        result.setdefault("_usage", usage)
        return result

    # ---- 内置 handler ----
    async def _model(self, effect, state) -> dict:
        script = state.data.get("script")
        if script is not None:                    # 脚本回放：测试零网络
            cursor = int(state.journal.get("cursor", 0))
            reply = script[cursor] if cursor < len(script) else {"content": "done"}
            # journal 是"外部世界的既成事实"，必须即时推进；它不参与回溯。
            state.journal["cursor"] = cursor + 1
            return {"ok": True, "output": reply}
        if self.model is not None:
            messages = list(effect.args.get("messages", ()))
            reply = await maybe_await(self.model.complete(messages, None))
            return {"ok": True, "output": reply}
        raise EffectError("model 效应需要 state.data['script'] 或注入 model")

    async def _tool(self, effect, state) -> dict:
        name = effect.args.get("name")
        if not name:
            raise EffectError("tool 效应缺少 args['name']")
        tools = self.tool_registry if self.tool_registry is not None \
            else state.data.get("tools", {})
        fn = tools[name] if isinstance(tools, dict) else tools.get(name)
        if fn is None:
            raise EffectError(f"未注册的工具：{name}")
        out = await maybe_await(fn(**(effect.args.get("args", {}) or {})))
        return {"ok": True, "output": out}

    async def _skill(self, effect, state) -> dict:
        """渐进披露三段：catalog 常驻 / body 按需 / resource 按需。"""
        catalog = state.data.get("skills", {})
        name = effect.args.get("name", ""); part = effect.args.get("part", "body")
        if part == "catalog":
            out = {k: v.get("description", "") for k, v in catalog.items()}
        elif part == "resource":
            out = catalog[name]["resources"].get(effect.args.get("path", ""), "")
        else:
            out = catalog.get(name, {}).get("body", "")
        return {"ok": True, "output": out}

    async def _ask(self, effect, state) -> dict:
        return {"ok": True, "output": {"approved": True}}

    async def _wait(self, effect, state) -> dict:
        queue = state.data["external_queue"]      # 控制权交给外部系统
        return {"ok": True, "output": await queue.get()}

    async def _compute(self, effect, state) -> dict:
        op = effect.args.get("op"); args = effect.args.get("args", [])
        ops = {"concat": lambda: "".join(map(str, args)),
               "upper": lambda: str(args[0]).upper(),
               "sum": lambda: sum(args),
               "join": lambda: " | ".join(map(str, args))}
        if op not in ops:
            raise EffectError(f"未知 compute 操作：{op}")
        return {"ok": True, "output": ops[op]()}

    async def _child(self, effect, state) -> dict:
        """嵌套子运行：能力作用域由新 State 隔离，预算由父解释器统一护栏。"""
        from harness.contracts.types import Goal
        from harness.kernel.interpret import interpret
        program = effect.child or effect.args.get("program")
        if program is None:
            raise EffectError("child 效应缺少 program")
        raw_goal = effect.args.get("goal", state.goal)
        goal = Goal(raw_goal) if isinstance(raw_goal, str) else raw_goal
        child_state = State(goal=goal, session=state.session)
        child_state.data = copy.deepcopy(effect.args.get("data", {}))
        runner = self.child_runner or interpret
        out = await maybe_await(runner(program, child_state))
        status = getattr(out, "status", "completed")
        return {"ok": status in ("completed", "degraded"),
                "output": getattr(out, "answer", ""), "_child": out}

# ---- runner 协议 ----
class EffectRunner:
    """Runtime 只认识这个接口：execute(effects, state) -> list[result]。
    换掉它就能把效应喂给既有 stage.run_stages 或任何执行后端。"""
    async def execute(self, effects, state): raise NotImplementedError

class CallbackRunner(EffectRunner):
    """把一个 run_one(effect, state) 回调包成批量 runner（旧路径兼容用）。"""
    def __init__(self, run_one, *, effects_log=None):
        self.run_one = run_one
        self.effects_log = effects_log if effects_log is not None else []

    async def execute(self, effects, state):
        if not effects:
            return []
        self.effects_log.extend(effects)
        return list(await asyncio.gather(
            *(self.run_one(replace(e, index=i), state) for i, e in enumerate(effects))))

async def execute_effects(effects, state, *, runtime=None, **kwargs):
    """便捷入口：没有 runtime 就按 kwargs 造一个。"""
    rt = runtime or EffectRuntime(**kwargs)
    return await rt.execute(tuple(effects), state)
```

**封装手法**：
1. `handlers` 注册表 + `extra_handlers.update()`：**注册代替 if 分支**。内核查无此 kind 就抛 EffectError，永不内置新类型判断。
2. `record_only` 只换终端不换链——dry_run 的门禁/校验/归类全部真实走过，只有最后一步"假装执行"。
3. `_model` 优先查 `state.data["script"]`（脚本回放）再查注入 model：304 个测试全部离线跑，靠的就是这个顺序。
4. `_child` 复用 `child_runner`（指向解释器自己）：嵌套运行的层/护栏/预算不因嵌套而丢失。
5. 幂等前置 → Gate → Check → Wrap → Classify → 记幂等 → Hook 后置的编排顺序是唯一执行顺序，写死在 `_stages`。
6. `EffectRunner` 协议是**执行后端的插头**：旧路径（CallbackRunner）与新效应系统（EffectRuntime）都在这个插头上，解释器不知道自己背后是谁。

## 2.5 `kernel/interpret.py`：唯一解释器（277 行）

```python
"""通用解释器（v3 / PROPOSAL §3、§5）—— 全框架唯一的循环。

    program = 初始程序
    while True:
        d = await program.transition(state)     # 架构在这里，框架不问
        if d is Halt: return Outcome
        results = await runner.execute(d.effects, state)   # 批量 → 四段链
        commit(state, d.patch, results)         # 唯一提交点
        emit(state); checkpoint(state, program)
        program = d.program or program          # 自=循环 / 历史=回溯 / 新组合=改图

框架只守不变量：状态单一所有者、能力作用域、预算、四段链、审批、
事件、检查点、全局终止护栏。内核里没有 if kind == ...。"""

class ValidationFailed(Exception):
    """装配期校验失败：能静态查的都查，不透明程序明确降级。"""

@dataclass(frozen=True)
class Limits:
    """框架新增的唯一不变量：任何程序都必须能停下来。"""
    max_transitions: int = 64
    max_calls: int = 100
    max_tokens: int = 200_000
    wall_seconds: float = 30.0

@dataclass
class Outcome:
    """一次运行的产物。state 与 extra 供兼容层组装 RunResult。"""
    answer: str; status: str; transitions: int; usage: dict[str, int]
    checkpoints: int
    trace: list[str] = field(default_factory=list)
    state: State | None = None
    extra: dict[str, Any] = field(default_factory=dict)

class Runtime:
    """解释器 = 一个循环 + 一个效应运行时。
    runner 可整体替换：默认走 v3 效应系统，旧路径注入 CallbackRunner，
    内核自身一行不改。"""
    def __init__(self, *, layers=(), limits=None, record_only=False,
                 extra_handlers=None, runner=None, emit=None, hooks=(),
                 model=None, tool_registry=None, guard=None, checks=(),
                 classify=None, after_commit=None) -> None:
        self.layers = tuple(layers)
        self.limits = limits or Limits()
        self.record_only = record_only
        self.emit_fn = emit
        self.after_commit = after_commit
        self.checkpoints: list[dict] = []
        self.events: list[str] = []
        self.runner: EffectRunner = runner or EffectRuntime(
            layers=self.layers, record_only=record_only,
            extra_handlers=extra_handlers, hooks=tuple(hooks), emit=self.emit,
            model=model, tool_registry=tool_registry, guard=guard,
            checks=tuple(checks), classify=classify)
        # child 效应复用同一运行时：层、检查点、预算护栏不因嵌套而丢失。
        if isinstance(self.runner, EffectRuntime) and self.runner.child_runner is None:
            self.runner.child_runner = self.interpret

    @staticmethod
    def validate(program) -> list[str]:
        """能查的都查；闭包程序只保证能跑（治理分级）。"""
        problems: list[str] = []
        if not callable(getattr(program, "transition", None)):
            problems.append("程序缺少 transition()")
        else:
            problems.extend(static_problems(program))
        return problems

    async def interpret(self, program, state) -> Outcome:
        problems = self.validate(program)
        if problems:
            raise ValidationFailed("; ".join(problems))

        trace = [f"run.start:{describe(program)}"]
        await self.emit("run.start", goal=_goal_text(state), program=describe(program))
        started = time.monotonic()
        n = 0
        while True:
            halt = self._guardrail(state, n, started)
            if halt is not None:
                return await self._finish(state, halt, n, trace)

            decision = await maybe_await(program.transition(state))
            if isinstance(decision, Halt):
                return await self._finish(state, decision, n, trace)
            if not isinstance(decision, Decision):
                raise DecisionError(
                    f"transition 必须返回 Decision | Halt，收到 {type(decision)!r}")

            if decision.restore is not None:
                state.restore(decision.restore)      # journal/usage 不回滚

            results = await self.runner.execute(decision.effects, state)
            kinds = ",".join(e.kind for e in decision.effects) or "pure"
            await self.emit("transition", program=getattr(program, "name", "?"),
                            kinds=kinds, note=decision.note, index=n)
            forced = self._commit(state, decision, results)
            await self.emit("commit", rev=state.rev, effects=len(decision.effects))
            if self.after_commit is not None:
                await self.after_commit(state, decision, results)

            spec: Any = "<opaque>"
            try:
                spec = to_spec(program)
            except (TypeError, NotSerializable):
                pass                                  # 不透明程序明确降级
            self.checkpoints.append({
                "rev": state.rev, "program": spec, "state": state.snapshot(),
            })
            await self.emit("checkpoint", rev=state.rev, serializable=spec != "<opaque>")
            trace.append(f"{n}:{getattr(program, 'name', '?')}:[{kinds}]"
                         + (f":{decision.note}" if decision.note else ""))

            program = decision.program if decision.program is not None else program
            n += 1
            if forced is not None:
                return await self._finish(state, forced, n, trace)

    def _guardrail(self, state, n, started) -> Halt | None:
        """全局终止护栏：控制流可以任意，但必须能停下来。"""
        if n >= self.limits.max_transitions:
            return Halt("max_transitions", "degraded")
        if state.usage.get("calls", 0) >= self.limits.max_calls:
            return Halt("max_calls", "degraded")
        if state.usage.get("tokens", 0) >= self.limits.max_tokens:
            return Halt("max_tokens", "degraded")
        if time.monotonic() - started > self.limits.wall_seconds:
            return Halt("wall_clock", "degraded")
        return None

    @staticmethod
    def _commit(state, decision, results) -> Halt | None:
        """唯一提交点。程序只读 State，效应只返回结果；写只发生在这里。"""
        batch: dict[str, Any] = {}
        forced: Halt | None = None
        for effect, raw in zip(decision.effects, results):
            result = as_result_dict(raw)
            usage = result.pop("_usage", None) or {
                "calls": 1, "tokens": int(result.get("tokens", 0) or 0)}
            messages = result.pop("_messages", ())
            halt_spec = result.pop("_halt", None)
            key = effect.key or "last"
            state.results[key] = result
            batch[key] = result
            if "output" in result:
                state.data["last_output"] = result["output"]
                state.data["last_result"] = result.get("raw", result)
            state.add_usage(tokens=int(usage.get("tokens", 0)),
                            calls=int(usage.get("calls", 0)))
            for message in messages:
                state.messages.append(message)
            if isinstance(halt_spec, dict) and forced is None:
                forced = Halt(str(halt_spec.get("answer", "")),
                              str(halt_spec.get("status", "failed")),
                              dict(halt_spec.get("extra", {})))
        state.results["__batch__"] = batch    # 每轮覆盖，程序只读"本批新结果"
        state.data.update(decision.patch)
        if decision.meta.get("bump_step"):
            state.step_index += 1
        state.rev += 1
        return forced

    async def _finish(self, state, halt, n, trace) -> Outcome:
        trace.append(f"run.end:{halt.status}")
        await self.emit("run.end", status=halt.status, steps=n, answer=halt.answer)
        return Outcome(answer=halt.answer, status=halt.status, transitions=n,
                       usage=dict(state.usage), checkpoints=len(self.checkpoints),
                       trace=trace, state=state, extra=dict(halt.extra))

    async def emit(self, name, **fields) -> None:
        """观测失败不得影响运行（SPEC M10.1）。"""
        self.events.append(name)
        if self.emit_fn is None:
            return
        try:
            await self.emit_fn(name, **fields)
        except Exception:
            pass

async def interpret(program, state, **kwargs) -> Outcome:
    """模块级便捷入口：await interpret(program, state)。"""
    return await Runtime(**kwargs).interpret(program, state)
```

**封装手法**：
1. 循环体六行对应六项职责，**每行一个事件插点**（transition/commit/checkpoint）——这就是 POINTS 后四个插点的来源。
2. `_commit` 用结果字典里的私有键 `_usage/_messages/_halt` 传带外信息——handler 返回值归一成 dict 后，计量、回灌消息、强制终止都走**数据**而不是异常，终端"只记账不写状态"的约束因此成立。
3. 检查点三分量：rev + program spec（不可序列化则 `<opaque>`）+ state.snapshot——时间旅行的全部素材。
4. 护栏四个维度在循环开头检查且返回 `Halt(..., "degraded")`：**超限是结局不是异常**。
5. `child_runner = self.interpret`：嵌套运行的效应共享同一运行时，护栏/层/事件不丢失。
6. `forced` 逻辑：效应可以携带 `_halt` 强制终止——审批拒绝、外部叫停都从这里来。

## 2.6 `kernel/legacy.py` + `kernel/loop.py`：兼容壳的手法

```python
"""v2 组合子线的前端适配（PROPOSAL §9.3 / §10）。
原来的 kernel/loop.run_loop 是第二个独立循环；现在它只是一个前端：
把 Program = body + layers 编译成唯一协议 transition(state)，
四段链、step 插点、事件、dry_run 记录由注入的 CallbackRunner 与
after_commit 钩子复现，循环本身交给 kernel.interpret.Runtime。"""

class LegacyProgram:
    """body.next_step → transition；鸭子类型满足新 Program 协议。"""
    name = "legacy"
    def __init__(self, program, scope) -> None:
        self.program = program; self.scope = scope

    async def transition(self, state) -> Decision | Halt:
        if self.scope.budget is not None and self.scope.budget.exhausted:
            return Halt("", "degraded", {"reason": "budget"})
        if state.step_index >= self.program.max_steps:
            return Halt("", "degraded", {"reason": "max_steps"})
        try:
            decision = await self.program.body.next_step(state, self.scope)
        except Exception as exc:
            failure = (await self.scope.filter.classify(exc, phase="step", state=state)
                       if self.scope.filter is not None else None)
            if failure is None:
                state.last_error = str(exc)
                return Halt("", "failed", {"reason": str(exc)})
            state.last_error = failure.reason
            return Halt("", str(failure.status), {"reason": failure.reason})

        if isinstance(decision, Done):
            return Halt(decision.answer, "completed")
        if not isinstance(decision, Step):
            raise HarnessError(f"BodyPolicy 返回非法类型：{type(decision)!r}")
        return Decision(
            effects=(Effect(kind="tool", step=decision, key=decision.id),),
            program=self, meta={"bump_step": True}, note=f"step:{decision.id}",
        )

async def run_legacy(*, program, state, scope, record_effects=None,
                     max_transitions=None) -> RunResult:
    """旧签名、旧行为；循环在 Runtime.interpret 里，且全框架仅此一处。"""
    scope = replace(scope, layers=tuple(program.layers),
                    model_call=_make_model_call(program, scope))
    tool_layers = chain.resolve(program.layers, "tool_call")
    step_layers = chain.resolve(program.layers, "step")

    async def terminal(step, st):
        if record_effects is not None:      # dry_run：记账不执行
            record_effects.append(Effect(kind="tool", step=step))
            return ActionResult(step_id=step.id, ok=True, output="[dry-run]")
        return await scope.actor.step(step, st, scope)

    async def run_one(effect, st) -> dict:
        step = effect.step
        await _emit(scope, st, "step.start", step=step.id, tool=step.tool_name or "")
        sr = await stage.run_stages(step, st, terminal=terminal, gate=scope.guard,
                                    checks=tuple(scope.pipes), layers=tool_layers,
                                    classify=scope.filter)
        if sr.failure is not None:
            return {"ok": False,
                    "_halt": {"status": str(sr.failure.status), "answer": "",
                              "extra": {"reason": sr.failure.reason}},
                    "_usage": {"calls": 0, "tokens": 0}}
        ar = sr.result
        return {"ok": bool(getattr(ar, "ok", False)),
                "output": getattr(ar, "output", "") if ar is not None else "",
                "raw": ar,
                # LlmActor.propose() 已经记过模型调用，这里不能重复计量。
                "_usage": {"calls": 0, "tokens": 0}}

    async def after_commit(st, decision, results) -> None:
        step = decision.effects[0].step if decision.effects else None
        ok = bool(results and isinstance(results[0], dict) and results[0].get("ok", False))
        if step is not None:
            await _emit(scope, st, "step.end", step=step.id, ok=ok)
        if step_layers:
            await chain.execute(step_layers, StepRequest(state=st, step=step), _identity)

    await _emit(scope, state, "run.start", goal=state.goal.text)
    ceiling = min(max_transitions or program.max_steps + 2, program.max_steps + 2)
    runtime = Runtime(
        limits=Limits(max_transitions=ceiling, max_calls=10**9,
                      max_tokens=10**9, wall_seconds=300.0),
        runner=CallbackRunner(run_one), after_commit=after_commit, emit=None)
    out = await runtime.interpret(LegacyProgram(program, scope), state)
    result = as_run_result(out, state)
    await _emit(scope, state, "run.end", status=str(result.status), steps=state.step_index)
    return result

def as_run_result(out: Outcome, state) -> RunResult:
    """新内核的字符串状态 → 既有 RunResult（七态枚举）。"""
    try:
        status = RunStatus(out.status)
    except ValueError:
        status = RunStatus.FAILED
    state.status = status
    reason = str(out.extra.get("reason", ""))
    return RunResult(status=status, answer=out.answer, state=state,
                     usage=dict(state.usage),
                     error=(reason or None) if status is not RunStatus.COMPLETED else None,
                     trace_id=state.trace_id, rev=state.rev)

def _make_model_call(program, scope):
    """把 model_call 点上的层封成可调用对象交给 Actor（SPEC M2.2）。"""
    layers = chain.resolve(program.layers, "model_call")
    async def call(request: ModelRequest) -> ModelResponse:
        async def terminal(req):
            reply = await scope.model.complete(list(req.messages), list(req.tools) or None)
            return ModelResponse(reply=reply)
        if layers:
            return await chain.execute(layers, request, terminal)
        return await terminal(request)
    return call

async def _emit(scope, state, name, **fields) -> None:
    """事件是唯一对外观察面；观测失败不得影响运行。"""
    sink = getattr(scope, "events", None)
    if sink is None:
        return
    try:
        await sink.emit(RunEvent(name=name, trace_id=state.trace_id, fields=fields))
    except Exception:
        pass
```

`kernel/loop.py`（26 行纯转发）：

```python
"""兼容壳：v2 循环已降级为 React 前端。这里不再有循环。"""
async def run_loop(*, program, state, scope, record_effects=None,
                   max_transitions=None) -> RunResult:
    from harness.kernel.legacy import run_legacy
    return await run_legacy(program=program, state=state, scope=scope,
                            record_effects=record_effects,
                            max_transitions=max_transitions)
```

**封装手法（兼容迁移的教科书）**：
1. **旧名字保留、旧行为转发**：`run_loop`/`Agent` 的签名与语义原样，循环体删除、转发到新解释器——调用方零感知。
2. `LegacyProgram` 是**翻译器**：把 `body.next_step → Step|Done` 翻译成 `transition → Decision|Halt`。Done→Halt、Step→单效应 Decision（`meta={"bump_step": True}` 让内核推进 step_index）。
3. 旧路径的逐步语义用三样东西在新内核上复现：`CallbackRunner(run_one)`（效应喂旧四段链）、`after_commit`（step 插点层）、`_make_model_call`（model_call 插点层封成可调用给 Actor）。
4. topology 里 `_call` 的教训写在源码里：按签名显式分流，**不再用 `try/except TypeError` 兜底**——那会吞掉子节点内部抛出的 TypeError，把真实故障伪装成签名不匹配。

---

# 阶段三 parts/ —— 组件库

## 3.1 治理小组件四件（budget / tracer / durability / resilience）

`parts/budget.py`（contracts/types.py 里另有契约版 Budget，字段一致、多 `owner/retries/replans/split`）：

```python
"""预算：token 与调用次数。预算是共享资源，不是某个组件的私有财产。"""
@dataclass
class Budget:
    tokens: int = 60_000; calls: int = 30
    used_tokens: int = 0; used_calls: int = 0
    # remaining_tokens / remaining_calls / exhausted 属性、spend()、snapshot() 同 types 版

class NullBudget(Budget):
    """测试用：永不耗尽。"""
    def __init__(self) -> None:
        super().__init__(tokens=10**12, calls=10**9)
```

`parts/tracer.py`：

```python
"""Tracer：唯一的外部事件出口。只记录结构化事件，不参与决策；
处理异常只记日志、不影响请求。"""
class NullTracer:
    async def emit(self, event: TraceEvent) -> None: return None

class MemoryTracer:
    def __init__(self): self.events: list[TraceEvent] = []
    async def emit(self, event): self.events.append(event)

class JsonlTracer:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
    async def emit(self, event):
        row = {"trace_id": event.trace_id, "span_id": event.span_id,
               "parent_id": event.parent_id, "name": event.name,
               "kind": event.kind, "start_ms": event.start_ms,
               "end_ms": event.end_ms, "fields": event.fields}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

def new_event(trace_id, name, *, kind="span", parent_id=None, fields=None,
              start_ms=None, end_ms=None) -> TraceEvent:
    """span_id 在这里生成；start/end 缺省都是 now。"""
    now = int(time.time() * 1000)
    return TraceEvent(trace_id=trace_id, span_id=uuid.uuid4().hex[:12],
                      parent_id=parent_id, name=name, kind=kind,
                      start_ms=start_ms if start_ms is not None else now,
                      end_ms=end_ms if end_ms is not None else now, fields=fields or {})
```

`parts/durability.py`：

```python
"""Durability：一次运行的检查点。默认内存实现只用于测试；生产用 SQLite（仍是标准库）。"""
class NullDurability:
    async def save(self, state): return None
    async def load(self, session_id): return None

class MemoryDurability:
    def __init__(self): self._states = {}
    async def save(self, state): self._states[state.session.session_id] = state.to_dict()
    async def load(self, session_id):
        raw = self._states.get(session_id)
        return State.from_dict(raw) if raw else None

class SQLiteDurability:
    """单文件检查点；适合单机、桌面应用、示例。"""
    def __init__(self, path="harness-runs.db"):
        self.path = str(path)
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS runs ("
                         "session_id TEXT PRIMARY KEY, state TEXT NOT NULL, "
                         "updated_at TEXT NOT NULL)")
    def _connect(self): return sqlite3.connect(self.path)
    async def save(self, state):
        payload = json.dumps(state.to_dict(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute("INSERT INTO runs(session_id, state, updated_at) "
                         "VALUES (?, ?, datetime('now')) "
                         "ON CONFLICT(session_id) DO UPDATE SET state=excluded.state, "
                         "updated_at=excluded.updated_at",
                         (state.session.session_id, payload))
    async def load(self, session_id):
        with self._connect() as conn:
            row = conn.execute("SELECT state FROM runs WHERE session_id = ?",
                               (session_id,)).fetchone()
        return State.from_dict(json.loads(row[0])) if row else None
```

`parts/resilience.py`：

```python
"""Resilience：包住一次模型/工具调用，而不是整个循环。"""
@dataclass
class Resilience:
    timeout_s: float = 30.0; retries: int = 0; backoff_s: float = 0.0

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return await asyncio.wait_for(fn(), timeout=self.timeout_s)
            except Exception as exc:
                last = exc
                if attempt >= self.retries:
                    raise
                if self.backoff_s:
                    await asyncio.sleep(self.backoff_s * (attempt + 1))
        raise last
```

**封装手法**：重试只包**单次调用**不包循环（循环重试会放大错误 + 绕过护栏）；`backoff_s * (attempt+1)` 线性退避一行实现；Tracer/Durability 都是"三档实现"（Null 测试 / Memory 断言 / 生产持久化）共享一个协议。

## 3.2 `parts/guard.py` + `parts/guardrail/`

`guard.py` 全文：

```python
"""Guard：动作之前的准入层（插点 ⑤ + 接入阶段）。
默认 AllowAll 也要显式存在；不要用"没有 Guard"表示放行。
两个方法共享"不通过就拦"的语义，拆成两套组件会把同一条拒绝逻辑写两遍。"""

class AllowAllGuard:
    async def check_identity(self, goal, ns=None): return GuardDecision.allow()
    async def check(self, step, state): return GuardDecision.allow()

class DenyAllGuard:
    async def check_identity(self, goal, ns=None): return GuardDecision.deny("DenyAllGuard")
    async def check(self, step, state): return GuardDecision.deny("DenyAllGuard")

class FunctionGuard:
    def __init__(self, fn, identity_fn=None) -> None:
        self.fn = fn; self.identity_fn = identity_fn
    async def check_identity(self, goal, ns=None):
        if self.identity_fn is None:
            return GuardDecision.allow()
        decision = self.identity_fn(goal, ns)
        if hasattr(decision, "__await__"):
            decision = await decision
        return decision
    async def check(self, step, state):
        decision = self.fn(step, state)
        if hasattr(decision, "__await__"):
            decision = await decision
        return decision
```

`guardrail/detectors.py` 核心（检测器 + 仲裁）：

```python
"""护栏的检测器与仲裁（SPEC M9）。
检测与动作分离：检测器只报"哪一段、什么风险"，动作由策略层按环境决定。
仲裁规则定死：取最严动作；同级取最高 risk；rewrite 与 redact 冲突取 redact。"""

ACTION_ORDER = (ALLOW, WARN, REDACT, REWRITE, ASK, BLOCK)   # 强度递增

def _rank(action): return ACTION_ORDER.index(action) if action in ACTION_ORDER else 0

def arbitrate(verdicts) -> GuardrailVerdict:
    """多个检测器的仲裁：最严动作胜出，同级取最高 risk。"""
    if not verdicts:
        return GuardrailVerdict()
    winner = max(verdicts, key=lambda v: (_rank(v.action), v.risk))
    labels, spans = [], []
    for v in verdicts:
        labels.extend(v.labels); spans.extend(v.spans)
    action = winner.action
    if action == REWRITE and any(v.action == REDACT for v in verdicts):
        action = REDACT          # 改写可能引入新风险，脱敏更保守
    return GuardrailVerdict(risk=max(v.risk for v in verdicts),
                            labels=tuple(dict.fromkeys(labels)), action=action,
                            spans=tuple(spans), replacement=winner.replacement)

def apply_verdict(text, verdict) -> str:
    """按仲裁结果改写文本（只有 redact/rewrite 会改内容）。"""
    if verdict.action not in (REDACT, REWRITE): return text
    if verdict.replacement is not None: return verdict.replacement
    out = text
    for start, end in sorted(verdict.spans, reverse=True):   # 从后往前替换，区间不失效
        out = out[:start] + "[已脱敏]" + out[end:]
    return out

class PatternGuardrail:
    """正则检测器基类：命中即报风险与区间，不动文本。"""
    name = "pattern"
    gates = frozenset({Gate5.INBOUND})
    action = GuardrailAction.WARN; risk = 0.5
    def __init__(self, rules):   # rules: (label, pattern)
        self.rules = [(label, re.compile(pattern, re.IGNORECASE))
                      for label, pattern in rules]
    async def check(self, content, scope=None) -> GuardrailVerdict:
        labels, spans = [], []
        for label, rx in self.rules:
            for match in rx.finditer(content.text):
                labels.append(label); spans.append((match.start(), match.end()))
        if not labels:
            return GuardrailVerdict()
        return GuardrailVerdict(risk=self.risk, labels=tuple(labels),
                                action=self.action, spans=tuple(spans))

class InjectionGuardrail(PatternGuardrail):
    """间接注入的主战场：入站与入上下文两道闸（SPEC M9.1 ①②）。"""
    name = "injection"
    gates = frozenset({Gate5.INBOUND, Gate5.CONTEXT, Gate5.TOOL_OUT})
    action = GuardrailAction.BLOCK; risk = 0.9
    def __init__(self):
        super().__init__([
            ("ignore-instructions", r"ignore (all )?(previous|prior|above) instructions"),
            ("role-override", r"(you are now|act as|从现在起你是|你现在是)"),
            ("system-prompt", r"(system prompt|系统提示词|上面的指令)"),
            ("ignore-zh", r"(忽略|无视)(之前|以上|前面)的?(指令|要求)"),
        ])
# PIIGuardrail / SecretLeakGuardrail 同构；builtin_detectors() 返回三件套
```

`guardrail/layer.py` 的扫描函数（层只是薄包装）：

```python
INPUT_GATES = (Gate5.INBOUND, Gate5.CONTEXT)
OUTPUT_GATES = (Gate5.MODEL_OUT, Gate5.OUTBOUND)

async def _scan(guardrails, content, *, gates, sink=None, fail_open=False) -> GuardrailVerdict:
    """逐个检测器扫描并仲裁；检测器自身失败默认 fail-closed。"""
    verdicts = []
    for rule in guardrails:
        rule_gates = {str(g) for g in getattr(rule, "gates", ())}
        if not rule_gates & {str(g) for g in gates}:
            continue
        try:
            verdicts.append(await rule.check(content, None))
        except Exception as exc:      # 检测器故障
            verdicts.append(GuardrailVerdict(
                risk=1.0, labels=(f"detector_error:{getattr(rule, 'name', '?')}",),
                action=("warn" if fail_open else "block")))
            _ = exc
    verdict = arbitrate(verdicts)
    if verdict.action != ALLOW and sink is not None:
        try:
            await sink.emit(RunEvent(name="guardrail", fields={…}))
        except Exception: pass        # 审计不得影响请求
    return verdict

def input_guard_layer(*, guardrails, sink=None, fail_open=False) -> Layer:
    """插点 model_call：扫入站消息与入上下文的检索/记忆/skill（闸 ①②）。"""
    # build(nxt) → 扫 ModelRequest.messages → BLOCK 抛 PolicyError / REDACT 改写消息
def output_guard_layer(*, guardrails, sink=None, fail_open=False) -> Layer:
    """插点 model_call：扫模型输出（闸 ③）；插点 run 扫最终出口（闸 ⑤）。"""
```

`guardrail/streaming.py` 三条规则：

```python
"""流式护栏（SPEC M9.4）：窗口缓冲 + 增量检测。
1 窗口缓冲：最近 64 字符不立即下发（防跨块敏感串）
2 已下发不可撤回：命中只能"中断 + 说明"
3 块级降级：检测器不支持增量时每 256 字符整块检测"""
WINDOW = 64; BLOCK_SIZE = 256

@dataclass
class StreamOutcome:
    text: str = ""; blocked: bool = False; labels: tuple[str, ...] = ()
    blocks: int = 0; degraded: bool = False; reason: str = ""

class StreamGuard:
    """包住一个文本增量流，边收边判。"""
    def __init__(self, guardrails, *, window=WINDOW, block_size=BLOCK_SIZE):
        self.guardrails = [g for g in guardrails if hasattr(g, "feed")]  # 只收支持增量的
    async def run(self, deltas) -> AsyncIterator[str]:
        """产出可直接下发的文本块；命中 block 时停止产出。"""
        # pending += delta → feed 检测 → BLOCK 则 return（中断）
        # 非 BLOCK 下发 pending[:-WINDOW]（留窗口）→ flush 时下发余量并做终检
```

**封装手法**：
1. Guard（动作）与 Guardrail（内容）是**平行体系**不是父子体系——检测器只报 `GuardrailVerdict`（风险值+区间+建议动作），改不改文本、拦不拦，由 `_scan` 的调用方（环境）决定：同一个 PII 检测器在测试环境 fail_open、生产 fail_closed。
2. 仲裁是**多检测器合并**的唯一算法且定死：最严动作、同级最高 risk、REWRITE+REDACT 冲突取 REDACT（改写可能引入新风险）。
3. 流式的物理约束（已下发不可撤回）直接决定接口形状：`feed/flush` 两段 + 64 字符窗口。
4. 检测器自身故障也生成 verdict（risk=1.0），而不是让异常穿透——护栏的失败也是一次"判定"。

## 3.3 `parts/middleware/` + `parts/layers.py`

`middleware/base.py` 全文：

```python
"""层机制（SPEC M13.1）：可组合的包裹单元。
层是值：Layer 只装声明与一个纯函数 build(handler) -> handler。
状态放在闭包里或作用域里，不放在层实例上——否则层无法复用与比较。"""
Handler = Callable[[Any], Awaitable[Any]]

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

def layer(name, points, build, *, needs=(), after=(), before=()) -> Layer:
    """构造一个层（语法糖，避免到处写 frozenset）。"""
    return Layer(name=name, points=frozenset(points), build=build,
                 needs=frozenset(needs), after=frozenset(after),
                 before=frozenset(before))

def compose_layers(*layers) -> list[Layer]:
    """只做保留顺序的扁平化；真正的排序交给 kernel.chain.resolve。"""
    return list(layers)
```

`middleware/builtin.py` 八个内置层（每个都值得当模板抄）：

```python
def context_layer(*, system="", encoder=None) -> Layer:
    """插点 model_call：取景 → 编码，替换请求里的消息（SPEC M6）。"""
    framer = ModelFramer(system=system); enc = encoder or ChatEncoder()
    def build(nxt):
        async def handler(req):
            if not isinstance(req, ModelRequest) or req.state is None:
                return await nxt(req)
            frame = await framer.frame(req.state, budget=req.budget or Budget())
            pack = await enc.encode(frame)
            return await nxt(replace(req, messages=tuple(pack.messages), frame=frame))
        return handler
    return layer("context", ["model_call"], build, before=["input_guard"])

def checkpoint_layer(*, store, cap="store") -> Layer:
    """插点 step：每步落盘，rev 递增（不变量 1）。"""
    def build(nxt):
        async def handler(req):
            response = await nxt(req)
            state = getattr(req, "state", None)
            if state is not None and isinstance(response, StepResponse):
                await store.put(getattr(req, "ns", None) or state_namespace(state),
                                state.session.session_id, state, expect_rev=state.rev)
            return response
        return handler
    return layer("checkpoint", ["step"], build, needs=[cap], after=["validate"])

def budget_layer(*, budget: Budget) -> Layer:
    """插点 run + model_call：记账；超限抛 BudgetExceeded（SPEC M8.2）。"""
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

def trace_layer(*, sink, clock=None) -> Layer:
    """全部插点：开/闭 span 并发事件（SPEC M10.1）。异常不得影响请求。"""
    def build(nxt):
        async def handler(req):
            name = type(req).__name__
            start = int((clock.now().timestamp() if clock else time.time()) * 1000)
            try:
                response = await nxt(req)
            finally:
                end = int((clock.now().timestamp() if clock else time.time()) * 1000)
                try:
                    await sink.emit(RunEvent(name="span.end", ts_ms=end,
                                             fields={"request": name, "start_ms": start,
                                                     "end_ms": end}))
                except Exception: pass    # 观测不得影响请求
            return response
        return handler
    return layer("trace", ["run", "step", "model_call", "tool_call"], build,
                 needs=["events"], before=["audit"])

def approval_layer(*, channel=None, when=("write", "shell"), always=(),
                   timeout_s=0.0) -> Layer:
    """插点 tool_call：按 side_effects 判定是否需要人点头（SPEC M8.3）。
    判定为"需要"且拿不到既有决定时抛 ApprovalRequired；由 Classify 映射成
    NEEDS_APPROVAL，运行层据此落盘挂起。不猜工具名，只看元数据。"""
    def build(nxt):
        async def handler(req):
            if not isinstance(req, ToolRequest): return await nxt(req)
            spec = req.spec
            side = str(getattr(spec, "side_effects", "pure"))
            name = getattr(spec, "name", "")
            needed = bool(getattr(spec, "needs_approval", False)) \
                or side in when or name in always
            if not needed:
                return await nxt(req)
            card = {"title": f"需要批准：{name}", "tool": name,
                    "side_effects": side, "args": dict(req.step.args)}
            if channel is not None:
                approval_id = await channel.request(ApprovalRequest(
                    id="", step=req.step, reason=f"side_effects={side}", card=card))
                decision = await channel.wait(approval_id, timeout_s=timeout_s)
                if decision is not None:
                    if decision.action == "reject":
                        raise PolicyError(f"人工驳回：{decision.reason or name}")
                    step = req.step
                    if decision.action == "modify":
                        step = replace(step, args={**step.args, **decision.args})
                    return await nxt(replace(req, step=step))
            raise ApprovalRequired(req.step.id, reason=f"side_effects={side}",
                                   card=card, tool=name)
        return handler
    return layer("approval", ["tool_call"], build, after=["idempotency"])

def default_idem_key(req, ns=None) -> str:
    """幂等键统一在工具层派生（SPEC M3.5）。"""
    ns_key = tuple(ns.as_tuple()) if ns is not None and hasattr(ns, "as_tuple") else ("",)
    payload = json.dumps(req.step.args, sort_keys=True, ensure_ascii=False, default=str)
    raw = f"{ns_key}:{req.step.index}:{req.step.tool_name}:{payload}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

def idempotency_layer(*, store, key_fn=None, ns=None) -> Layer:
    """插点 tool_call：命中幂等表直接回旧结果，不执行任何副作用（SPEC M7.2 C7）。"""
    derive = key_fn or default_idem_key
    def build(nxt):
        async def handler(req):
            if not isinstance(req, ToolRequest): return await nxt(req)
            key = derive(req, ns)
            hit = await store.begin(ns, key)
            if hit is not None:
                return ToolResponse(result=hit.value)
            response = await nxt(req)
            if isinstance(response, ToolResponse) and response.result is not None:
                await store.commit(ns, key, Recorded(key=key, value=response.result))
            return response
        return handler
    return layer("idempotency", ["tool_call"], build, needs=["idempotency"],
                 after=["approval"])

def validate_layer(*, reflector, max_retries=2, budget=None) -> Layer:
    """插点 step：结果质量判定，按 Verdict 决定重跑还是采纳（SPEC M5.3）。
    修复计数落在 Budget.retries，不落在 State（不变量 2）。"""
    def build(nxt):
        async def handler(req):
            response = await nxt(req)
            if not isinstance(response, StepResponse) or reflector is None:
                return response
            state = getattr(req, "state", None)
            if state is None: return response
            for _ in range(max_retries + 1):
                result = state.data.get("last_result")
                verdict = await reflector.review(result, state)
                if verdict.action != "retry":
                    return response
                if budget is not None:
                    if budget.retries >= max_retries: break
                    budget.retries += 1
                response = await nxt(req)      # 重跑同一 step
            return response
        return handler
    return layer("validate", ["step"], build)

def taskboard_layer() -> Layer:
    """插点 step + model_call：任务清单注入 + 状态推进（SPEC M13.4.1）。
    清单落在 state.section("tasks")，由 ModelFramer 取成 task 槽（ephemeral）。"""
    def build(nxt):
        async def handler(req):
            state = getattr(req, "state", None)
            if state is not None:
                board = state.section("tasks")
                board.setdefault("items", [])
                board["updated_at"] = time.time()
            return await nxt(req)
        return handler
    return layer("taskboard", ["step", "model_call"], build, after=["context"])

def add_task(state, text, *, owner="") -> dict:
    """三件套之一：建任务（上限 50，防模型无限建）。"""
    board = state.section("tasks")
    items = board.setdefault("items", [])
    if len(items) >= 50:
        raise ValueError("任务数已达上限 50")
    task = {"id": f"t{len(items) + 1}", "text": text, "status": "todo", "owner": owner}
    items.append(task)
    return task

def update_task(state, task_id, status, *, reason="") -> dict:
    """三件套之二：改状态（todo → doing → done / blocked）。"""
    allowed = {"todo", "doing", "done", "blocked"}
    if status not in allowed:
        raise ValueError(f"非法状态：{status}")
    for task in state.section("tasks").get("items", []):
        if task["id"] == task_id:
            task["status"] = status
            if status == "blocked":
                task["reason"] = reason
            return task
    raise KeyError(f"未知任务：{task_id}")

def list_tasks(state) -> list[dict]:
    """三件套之三：列任务。"""
    return list(state.section("tasks").get("items", []))
```

`layers.py` 五个薄层（结构同上，全部 20-40 行）：

```python
def tenancy_layer(*, expected_tenant=None) -> Layer:
    """插点 run：绑定命名空间，拒绝越权会话（SPEC M13.4 #1）。"""
    # build(nxt)：req.ns.tenant != expected_tenant → raise PolicyError
    #           → 把 ns.tenant 写回 state.session（绑定）
    return layer("tenancy", ["run"], build)

def audit_layer(*, sink) -> Layer:
    """全部插点：结构化审计（谁、做了什么、结果摘要、用量）（SPEC M13.4 #4）。"""
    # build(nxt)：记录 started → await nxt → sink.emit(RunEvent("audit", …))
    #           → 全程 try/except 吞掉（审计不得影响请求）
    return layer("audit", ["run", "step", "model_call", "tool_call"], build,
                 needs=["events"], after=["trace"])

def retrieval_layer(*, knowledge, ns=None, k=6) -> Layer:
    """插点 model_call：召回候选写进 state.data["retrieved"]（SPEC M13.4 #9）。
    只给候选、不决定条数以外的裁剪——裁剪在取景器里（Memory 不感知预算）。"""
    # build(nxt)：首轮 if not state.data.get("retrieved") 才检索（一轮一次）
    return layer("retrieval", ["model_call"], build, needs=["index"], before=["context"])

def memory_recall_layer(*, memory, layers=("semantic", "episodic"), k=6) -> Layer:
    """插点 model_call：跨会话召回写进 state.data["memory"]（SPEC M13.4 #10）。"""
    return layer("memory_recall", ["model_call"], build, needs=["memory"],
                 before=["context"])

def memory_write_layer(*, memory, policy) -> Layer:
    """插点 run：出口后按 MemoryPolicy 写入（SPEC M13.4 #11）。"""
    # build(nxt)：await nxt 之后 → policy.should_write / extract / memory.write
    #           → 全程 try/except（记忆写入失败不影响主流程）
    return layer("memory_write", ["run"], build, needs=["memory"], after=["delivery"])
```

**封装手法**：
1. 层的**声明顺序有讲究**且全写在 after/before 里：`idempotency` 在 `approval` 前（先查幂等再问人，重复请求不该浪费一次审批）、`context` 在 `input_guard` 前（先取景再扫内容）、`retrieval/memory_recall` 在 `context` 前（先召回再取景）、`memory_write` 在 `delivery` 后（出口收尾后才写记忆）。
2. 层用 `isinstance(req, ModelRequest)` 判定自己的请求形状——同一个层可以声明多个插点，各插点请求不同也不出错。
3. `validate_layer` 的重跑计数放 `Budget.retries` 不放 State：State 是业务状态可回滚，修复计数是治理事实（不变量 2）。
4. 审批两个出口：有 channel 等 decision（reject→PolicyError、modify→替换参数再走）；没 channel 抛 `ApprovalRequired` 挂起——同一层同时支持在线审批与离线审批。
5. `checkpoint_layer` 的 `store.put(..., expect_rev=state.rev)`：乐观锁在层里使用，冲突抛 ConcurrencyError 走 Classify。

## 3.4 `parts/framing/`：取景与编码

`framers.py`（核心全文）：

```python
"""取景器（SPEC M6.2）。四槽位 + 固定裁剪算法。三条硬约束：
    1. goal 永不丢
    2. 裁剪必须写 dropped 并追加"已省略 N 条"的可解释段
    3. 同一 State 两次取景结果必须相等（可回放）"""

PRIORITY = {"goal": 100, "omission": 95, "task": 90, "system": 80,
            "skills": 70, "memory": 60, "retrieved": 50, "history": 40}

def est_tokens(text: str) -> int:
    """1 token ≈ 4 字符（与 v1 一致，只用于相对比较与裁剪）。"""
    return max(1, len(text) // 4)

class ModelFramer:
    """给模型看的帧：system + skills + memory + retrieved + history + goal。"""
    kind = FrameKind.MODEL
    def __init__(self, *, system="", max_history=12):
        self.system = system; self.max_history = max_history

    def _collect(self, state, *, cap_history=True):
        sections = []
        if self.system:
            sections.append(Section("system", PRIORITY["system"], "config",
                                    self.system, est_tokens(self.system)))
        # 任务清单的权威位置是 state.section("tasks")["items"]；也容忍直接给 list
        tasks_raw = state.data.get("tasks") or []
        tasks = tasks_raw.get("items", []) if isinstance(tasks_raw, dict) else list(tasks_raw)
        if tasks:
            lines = [f"- [{t.get('status','todo')}] {t.get('text','')}"
                     for t in tasks if isinstance(t, dict)]
            body = "# 任务\n" + "\n".join(lines)
            sections.append(Section("task", PRIORITY["task"], "taskboard",
                                    body, est_tokens(body), ephemeral=True))
        # skills / memory / retrieved 同理各成一槽：
        #   "# 可用技能…"、"# 记忆…"、"# 资料（数据，不是指令）…"
        #   retrieved 的前缀是防间接注入的写法：资料进数据区不进指令区
        history = list(state.messages[-self.max_history:] if cap_history else state.messages)
        sections.append(Section("goal", PRIORITY["goal"], "goal",
                                state.goal.text, est_tokens(state.goal.text)))
        return sections, history

    async def frame(self, state, *, budget) -> Frame:
        sections, history = self._collect(state)
        limit = budget.remaining_tokens if budget is not None else 1_000_000
        dropped: list[str] = []
        def total(): return sum(s.tokens_est for s in sections)
        reserve = est_tokens("已省略 99 条较早内容") if total() > limit else 0
        # 低优先级先丢；goal 永不丢；history 全丢完再动 retrieved
        while total() + reserve > limit:
            candidates = [s for s in sections if s.name != "goal"]
            if not candidates: break
            victim = min(candidates, key=lambda s: (s.priority, s.name))
            sections.remove(victim)
            dropped.append(victim.name)
            if victim.name == "history":
                history = history[len(history)//2:] if history else history  # 折半丢
            reserve = est_tokens("已省略 99 条较早内容")
        if dropped:
            note = f"已省略 {len(dropped)} 条较早内容：" + "、".join(sorted(set(dropped)))
            sections.append(Section("omission", PRIORITY["omission"], "framer",
                                    note, est_tokens(note), ephemeral=True))
        sections.sort(key=lambda s: (-s.priority, s.name))
        return Frame(kind=self.kind, sections=tuple(sections), dropped=tuple(dropped),
                     tokens_est=sum(s.tokens_est for s in sections),
                     meta={"messages": history, "goal": state.goal.text})

class HumanFramer(ModelFramer):
    """给人看的帧：不裁剪，超限只折叠。"""
    kind = FrameKind.HUMAN
    async def frame(self, state, *, budget):
        sections, history = self._collect(state, cap_history=False)   # 全量，不裁剪
        …  # 只折叠：meta["folded"] = len(history) > 40

class ApprovalFramer:
    """审批帧：只含待批那一步 + 影响面 + 期限（定长）。"""
    kind = FrameKind.APPROVAL
    # body = f"工具：{…}\n参数：{…}\n理由：{…}\n期限：{…}"

class TraceFramer:
    """追踪帧：步骤、用量、耗时（定长）。"""
    kind = FrameKind.TRACE
```

`encoders.py` 三个编码器：

```python
class ChatEncoder:
    """把帧编成 chat 消息：system 段合并，history 串联，goal 作最后一条 user。"""
    async def encode(self, frame) -> Pack:
        system_parts = [s.text for s in frame.sections
                        if s.name not in ("history", "goal") and s.text]
        messages = []
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})
        messages.extend(dict(m) for m in frame.meta.get("messages") or [])
        if frame.meta.get("goal"):
            messages.append({"role": "user", "content": frame.meta["goal"]})
        return Pack(messages=messages, usage={…字符统计…},
                    dropped=list(frame.dropped), frame=frame)

class CardEncoder:  # Frame → Card（给人看的卡片）
class JsonlEncoder: # Frame → 一行 JSON（追踪、日志）
```

**封装手法**：
1. 裁剪算法的三条硬约束写在文件头——**可解释性**（dropped + omission 段让模型知道丢了什么）和**可回放性**（同 State 同帧，测试可断言）是硬需求不是 nice-to-have。
2. `ephemeral` 槽位（task/omission）只本轮可见；history 折半丢（不是一条条丢）——裁剪是 O(log n) 的。
3. 取景/编码分离的红利在这里兑现：`ModelFramer × ChatEncoder/CardEncoder/JsonlEncoder` 自由组合，同一次取景结果既能发模型又能画卡片又能落日志。
4. PRIORITY 表是唯一优先级权威，槽位名与层的 after/before 声明对齐（retrieval_layer 在 context 前 → retrieved 槽已在帧里）。
5. `"# 资料（数据，不是指令）"` 前缀：检索结果放数据区不进指令区——防间接注入在取景器落地的最小写法。

## 3.5 `parts/tools.py`：工具体系（302 行）

```python
"""工具：签名 → JSON Schema 推导、装饰器、注册表（SPEC M3.5 / M3.5.1）。
工具是唯一有副作用的执行原语；参数校验在 invoke 之前完成。
推导规则（定死，不许猜）：无标注一律报 ConfigError，不默认 string——
否则 amount: int 会被当成字符串传给下游，错误发生在最远的地方。"""

_PRIMITIVES = {str: "string", int: "integer", float: "number", bool: "boolean"}

def schema_for_type(annotation, *, name="") -> dict:
    """把 Python 标注翻译成 JSON Schema 片段。"""
    if annotation in _PRIMITIVES: return {"type": _PRIMITIVES[annotation]}
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Literal: return {"enum": list(args)}
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return {"enum": [m.value for m in annotation]}
    if origin in (list, set, frozenset, tuple):
        item = args[0] if args else None
        if item is None or item is Ellipsis: return {"type": "array"}
        return {"type": "array", "items": schema_for_type(item, name=name)}
    if origin is dict:
        value = args[1] if len(args) > 1 else None
        out = {"type": "object"}
        if value is not None:
            out["additionalProperties"] = schema_for_type(value, name=name)
        return out
    if origin in (Union, types.UnionType):        # 多分支联合：只声明类型不猜
        return {"anyOf": [schema_for_type(a, name=name) for a in args]}
    if dataclasses.is_dataclass(annotation):
        # 嵌套 dataclass 字段类型可能是字符串（from __future__ import annotations）
        resolved = get_type_hints(annotation, include_extras=False)
        props, required = {}, []
        for f in dataclasses.fields(annotation):
            ftype = resolved.get(f.name, f.type)
            optional, inner = _is_optional(ftype)
            props[f.name] = schema_for_type(inner, name=f.name)
            if not optional and f.default is dataclasses.MISSING:
                required.append(f.name)
        return {"type": "object", "properties": props, "required": required,
                "additionalProperties": False}
    if annotation is Any:
        raise ConfigError(f"参数 {name} 标注为 Any，无法推导 schema；请给出具体类型")
    raise ConfigError(f"参数 {name} 的类型不受支持：{annotation!r}")

def _docstring_parts(func):
    """拆 docstring：首段是工具描述，Args: 段是逐参数说明。"""
    # 识别 "args:"/"arguments:"/"参数:" 段落，按 "key: value" 拆参数说明

def derive_schema(func):
    """返回 (parameters, description, param_descriptions)。"""
    # 遍历签名参数：跳过 self/cls/*args；
    # **kwargs → {"type": "object", "additionalProperties": True}
    # 首参标注为 ToolContext → 能力注入参数，不进 schema
    # 缺标注 → ConfigError（不默认 string）
    # Optional[X] → piece 加 "nullable": True；docstring 说明写进 description
    # 无默认值且非 Optional → required

@dataclass
class FunctionTool:
    """既满足 v1 形状（name/description/parameters/invoke），也带 spec 元数据。"""
    spec: ToolSpec
    func: Callable
    is_async: bool = False
    # name/description/parameters 三个 property 转发到 spec

    @property
    def _takes_ctx(self) -> bool:
        """工具的首参若标注为 ToolContext，调用时注入能力。"""
        hints = get_type_hints(self.func, include_extras=False)
        return any(h is ToolContext for h in hints.values())

    async def invoke(self, args, ctx=None) -> str:
        try:
            if self._takes_ctx and ctx is not None:
                value = self.func(**{**args, "ctx": ctx})
            else:
                value = self.func(**args)
            if inspect.isawaitable(value):
                value = await value
        except TypeError as exc:
            raise ToolError(f"{self.name}: 参数不匹配：{exc}") from exc
        except PermissionError:
            # 路径越界 / 权限拒绝：原样抛出，交给 Classify 归为 REFUSED。
            # 包成 ToolError 会被当作"可重试的工具失败"回灌给模型，错误归因就丢了。
            raise
        except Exception as exc:
            raise ToolError(f"{self.name}: {exc}") from exc
        return value if isinstance(value, str) \
            else json.dumps(value, ensure_ascii=False, default=str)

    async def call(self, args, ctx=None) -> ToolResult:
        """v2 形状：返回结构化结果，供 Wrap 段截断/脱敏。"""
        out = await self.invoke(args, ctx)
        return ToolResult(step_id="", tool=self.name, ok=True, output=out)

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.spec.name,
                "description": self.spec.description,
                "parameters": self.spec.parameters}}

def tool(func=None, *, name=None, description=None,
         side_effects=SideEffect.PURE, scopes=(), timeout_s=None,
         idempotent=False, max_output_bytes=32_000,
         needs_approval=False, sandbox=False):
    """把一个函数变成 FunctionTool；支持 @tool 与 @tool(...)。"""
    def wrap(fn):
        parameters, doc, _ = derive_schema(fn)
        spec = ToolSpec(name=name or fn.__name__,
                        description=description or doc or (inspect.getdoc(fn) or "").strip(),
                        parameters=parameters, side_effects=SideEffect(side_effects),
                        scopes=frozenset(scopes), timeout_s=timeout_s,
                        idempotent=idempotent, max_output_bytes=max_output_bytes,
                        needs_approval=needs_approval, sandbox=sandbox)
        return FunctionTool(spec=spec, func=fn, is_async=inspect.iscoroutinefunction(fn))
    return wrap if func is None else wrap(func)    # 两种装饰器形态

@dataclass
class ToolRegistry:
    tools: dict[str, FunctionTool] = field(default_factory=dict)
    def add(self, *tools):
        for item in tools:
            item = as_tool(item)
            if item.name in self.tools:
                raise ToolError(f"工具重名：{item.name}")
            self.tools[item.name] = item
        return self
    def get(self, name):
        if name not in self.tools:
            raise ToolError(f"未知工具：{name}")
        return self.tools[name]
    def schemas(self, *, allow=None) -> list[dict]:
        items = self.tools.values()
        if allow is not None:               # skill 的 allowed_tools 在这里生效
            items = [t for t in items if t.name in allow]
        return [item.schema() for item in items]
    def specs(self, *, allow=None) -> list[ToolSpec]: …
    def names(self): return sorted(self.tools)
    async def invoke(self, call: ToolCall, ctx=None):
        return await self.get(call.name).invoke(call.args, ctx)

def as_tool(value) -> FunctionTool:
    """裸函数也能直接进注册表。"""
    if isinstance(value, FunctionTool): return value
    if callable(value): return tool(value)
    raise ToolError(f"无法作为工具：{value!r}")
```

**封装手法**：
1. **装配期报错优于运行期猜**贯穿整个 schema 推导：缺标注、Any、不支持的类型全部 ConfigError。`amount: int` 被当字符串传下游的错误发生在"最远的地方"，所以宁可在注册时就炸。
2. `PermissionError` 单独原样穿透是**错误归因**的细节：包成 ToolError 会被 Classify 归为"可重试"回灌模型，权限拒绝（REFUSED）就变成"模型反复重试被拒"。
3. `@tool` 与 `@tool(...)` 双形态是 `func is None` 一个判断实现的装饰器标准写法。
4. `ToolContext` 注入按**类型标注探测**（`_takes_ctx`）：工具作者声明 `ctx: ToolContext` 就拿到能力，不声明就纯函数——能力注入零配置。
5. `schemas(allow=...)` 是 Skill 收窄工具面的落点：工具收窄靠交集不靠提示词。

## 3.6 `parts/actor.py` + `parts/actor_v2.py`

```python
# actor.py（v1）
"""Actor：一次决策 + 一次执行。
它不评估结果，也不决定下一步；这两件事分别归 Reflector 与 BodyPolicy。"""
@dataclass
class Actor:
    model: Model; tools: ToolRegistry; resilience: object | None = None

    async def decide(self, state, pack) -> ModelReply:
        call = lambda: self.model.complete(pack.messages, self.tools.schemas())
        if self.resilience is not None:
            return await self.resilience.call(call)    # 重试只包一次调用
        return await call()

    async def execute(self, step, state) -> ActionResult:
        if not step.tool_name:   # 没有工具名 = 纯指令步，直接当成功输出
            return ActionResult(step_id=step.id, ok=True, output=step.instruction)
        try:
            call = lambda: self.tools.invoke(ToolCall(step.tool_name, step.args))
            output = await (self.resilience.call(call) if self.resilience else call())
        except ToolError as exc:
            return ActionResult(step_id=step.id, ok=False, error=str(exc),
                                tool_name=step.tool_name)   # 失败回灌，不抛
        return ActionResult(step_id=step.id, ok=True, output=output,
                            tool_name=step.tool_name)

# actor_v2.py（v2）
"""LlmActor（插点 ④ 决策 + ⑥ 执行）。只做执行，不做评估；
取景/编码/记账都在这里完成，不泄漏给策略。"""
@dataclass
class LlmActor:
    model: Any; tools: Any = None; name: str = "actor"

    async def propose(self, state, scope) -> Step | Done:
        """决定下一步：取景 → 编码 → （经 model_call 链）问模型 → 解析 tool_call。
        取景永远在这里做；scope.model_call 由内核提供（内含护栏/缓存等层），
        所以本类不需要知道链的存在，也不需要 import kernel。"""
        schemas = self.tools.schemas() if self.tools is not None else None
        frame = await scope.framer.frame(state, budget=scope.budget)
        pack = await scope.encoder.encode(frame)
        request = ModelRequest(state=state, messages=tuple(pack.messages),
                               tools=tuple(schemas or ()), budget=scope.budget,
                               frame=frame)
        model_call = getattr(scope, "model_call", None)
        if model_call is not None:
            reply = (await model_call(request)).reply     # 经链调用
        else:
            reply = await self.model.complete(pack.messages, schemas)   # 直连兜底
        usage = dict(getattr(reply, "usage", {}) or {})
        tokens = int(usage.get("total", usage.get("tokens", 0)) or 0)
        state.add_usage(tokens=tokens, calls=1)
        if scope.budget is not None:
            scope.budget.spend(tokens=tokens, calls=1)
        calls = list(getattr(reply, "tool_calls", []) or [])
        if not calls:
            return Done(answer=str(getattr(reply, "content", "")))
        call = calls[0]          # 一轮只取第一个：并行工具不支持（ADR 12）
        return Step(id=f"s{state.step_index + 1}",
                    instruction=str(getattr(reply, "content", "") or ""),
                    tool_name=call.name, args=dict(call.args), index=state.step_index)

    async def step(self, step, state, scope) -> ActionResult:
        """执行一次工具调用。失败回灌模型，由下一轮修正。"""
        if not step.tool_name:
            return ActionResult(step_id=step.id, ok=True, output=step.instruction)
        try:
            tool = self.tools.get(step.tool_name)
            ctx = ToolContext(fs=scope.fs, sandbox=scope.sandbox,
                              artifacts=scope.artifacts, secrets=scope.secrets,
                              state=state, signal=getattr(scope, "signal", None))
            output = await tool.invoke(step.args, ctx)
        except Exception as exc:      # 工具失败回灌
            return ActionResult(step_id=step.id, ok=False, error=str(exc),
                                tool_name=step.tool_name)
        return ActionResult(step_id=step.id, ok=True, output=output,
                            tool_name=step.tool_name)
```

**封装手法**：Actor 的职责边界"只执行不评估"用代码结构强制——propose 返回 `Step|Done`（决策）、step 返回 `ActionResult`（执行），**没有**任何重试/评估逻辑；失败返回 `ok=False` 的值而不是抛异常，把"失败也是数据"落到 Actor 这一层。v2 的 LlmActor 通过 `scope.model_call` 被治理而不知道链存在（见 2.6）。

## 3.7 `parts/body/`：三种主体策略 + Planner

```python
# workflow.py
"""Workflow：步骤由开发者写死；模型不决定顺序。"""
class WorkflowPolicy:
    def __init__(self, steps): self.steps = list(steps)
    async def next_step(self, state, ctx) -> Step | Done:
        index = int(state.data.get("workflow_index", 0))
        if index >= len(self.steps):
            return Done(answer=state.data.get("last_output", ""))
        step = replace(self.steps[index], id=self.steps[index].id or f"w{index + 1}")
        state.data["workflow_index"] = index + 1
        return step

# react.py
"""ReAct：每轮由模型决定下一步；没有显式 Plan。"""
class ReactPolicy:
    def __init__(self, max_steps=8): self.max_steps = max_steps
    async def next_step(self, state, ctx) -> Step | Done:
        if state.step_index >= self.max_steps:
            return Done(answer=state.data.get("last_output", ""), reason="max_steps")
        pack = await ctx.context.assemble(state, ctx.budget.remaining_tokens)
        reply = await ctx.actor.decide(state, pack)
        state.data["last_model_usage"] = dict(reply.usage)
        tokens = int(reply.usage.get("total_tokens", 0))
        state.add_usage(tokens=tokens, calls=1)
        ctx.budget.spend(tokens=tokens, calls=1)
        if reply.tool_calls:
            call = reply.tool_calls[0]
            step_id = f"s{state.step_index + 1}"
            state.data["_react_tool_call_id"] = step_id
            return Step(id=step_id, instruction=reply.content,
                        tool_name=call.name, args=call.args)
        return Done(answer=reply.content)

# pe.py
"""Plan-and-Execute：先产出一份可审查的 Plan，再逐步执行。"""
class PlanExecutePolicy:
    def __init__(self, planner, max_steps=20):
        self.planner = planner; self.max_steps = max_steps
    async def next_step(self, state, ctx) -> Step | Done:
        section = state.section("pe")            # 自己的命名空间，不踩别人
        if "plan" not in section:
            plan = await self.planner.plan(state.goal, state)
            if not isinstance(plan, Plan):
                raise TypeError("Planner.plan 必须返回 Plan")
            section["plan"] = asdict(plan)       # 存成 dict：可序列化、可回滚
            section["index"] = 0
        raw = section["plan"]
        plan = Plan(id=raw["id"], steps=[Step(**item) for item in raw["steps"]],
                    rev=int(raw.get("rev", 0)))
        index = int(section.get("index", 0))
        if index >= len(plan.steps) or index >= self.max_steps:
            return Done(answer=state.data.get("last_output", ""), reason="plan_done")
        step = plan.steps[index]
        section["index"] = index + 1
        return step

# planner.py
"""Planner：只属于 Plan-and-Execute。"""
@dataclass
class ScriptedPlanner:
    """固定计划；示例与测试用。"""
    plan_obj: Plan
    async def plan(self, goal, state) -> Plan: return self.plan_obj

class FunctionPlanner:
    def __init__(self, fn): self.fn = fn
    async def plan(self, goal, state) -> Plan:
        value = self.fn(goal, state)
        if hasattr(value, "__await__"): value = await value
        return value
```

**封装手法**：三种策略同签名 `next_step → Step|Done`，内核对它们一无所知——这就是 BodyPolicy"唯一策略缝"。P&E 的 Plan 存 `section("pe")` 且转成 dict：进 State 就必须可序列化（回滚/检查点），策略自己保证。ScriptedPlanner/FunctionPlanner 是"最小实现 + Function 包装器"配方的又一次出现。

## 3.8 知识/记忆/检索/技能

```python
# knowledge.py
"""Knowledge：取哪几条。只负责检索，不负责预算与拼装。"""
def _bigrams(text): …          # 清洗后字符二元组
def _score(query, text): …     # 二元组重合率

class InMemoryKnowledge:
    """最小实现：字符二元组重合打分，够离线测试与示例。"""
    async def retrieve(self, query, *, k, filters=None) -> list[Recalled]:
        # filters 以 "key=value" 匹配 item.source（多租户过滤的最小实现）
        # score > 0 才收；按分排序取前 k

# memory.py
"""Memory：跨会话的长期数据；不负责一次运行的检查点。"""
class InMemoryMemory:
    async def recall(self, query, *, scope, layers, k):
        rows = [item for item in self.items if item.layer in layers]  # 分层召回
        # 同样的 _score 打分取前 k
    async def write(self, items) -> int:
        self.items.extend(items); return len(items)

# retrieval.py
"""RetrievalPolicy：什么时候取、拿什么 query 去取。"""
class AutoRetrieval:
    def __init__(self, k=6, when="first_step"): …
    async def retrieve(self, goal, knowledge, tenant="default") -> list[Recalled]:
        return await knowledge.retrieve(goal.text, k=self.k,
                                        filters={"tenant": tenant} if tenant else None)
class NoRetrieval:
    async def retrieve(self, goal, knowledge, tenant="default"): return []
```

```python
# skills.py
"""Skills：给流程，不给能力。
目录约定：skills/<name>/SKILL.md + 可选 workflow.json（有它才能 as_workflow）"""
@dataclass(frozen=True)
class SkillMeta:
    name: str; description: str
    allowed_tools: list[str] = field(default_factory=list); path: str = ""

@dataclass
class Skill:
    meta: SkillMeta; body: str
    resources: dict[str, str] = field(default_factory=dict)

class SkillRegistry:
    @classmethod
    def from_dir(cls, root) -> "SkillRegistry":
        # 扫目录 → 解析 SKILL.md 的 YAML front matter（name/description/allowed-tools）
        #   无 front matter 时正文首个非空行当 description
        # → references/ 下所有文件收进 resources
    def catalog(self) -> list[SkillMeta]: …      # 常驻：只有元数据
    def load(self, name) -> Skill: …             # 按需：正文
    def as_workflow(self, name) -> WorkflowPolicy:
        skill = self.load(name)
        manifest = Path(skill.meta.path) / "workflow.json"
        if not manifest.exists():
            raise ValueError(f"Skill {name} 只有说明，不能编译成 Workflow")
        rows = json.loads(manifest.read_text(encoding="utf-8"))
        steps = [Step(**row) for row in rows["steps"]]
        return WorkflowPolicy(steps)             # 固定流程不被模型改序
```

**封装手法**：Memory/Knowledge/Retrieval 是三个**不同的问题**（跨会话长期数据 / 取哪几条 / 什么时候取），分三个部件而不是捏成一个"RAG 组件"。Knowledge 只按分数返回候选、Context/Framer 决定放几条、Retrieval 决定时机——预算感知只在取景器。Skills 的"catalog 常驻 / body 按需 / resource 按需"三段对应 `Effect("skill", part=…)` 三个取值（见 2.4 `_skill` handler）；"只有 SKILL.md 的 Skill 不能 as_workflow"——不能把散文假装编译成步骤。

## 3.9 Context / Delivery / Reflector / Dispatch / Topology

```python
# context.py（v1）
"""Context：装配这一轮模型看见什么。
Knowledge 决定"取哪几条"，Context 决定"放几条、放哪个槽位"。"""
class BudgetedContext:
    """按字符预算装配；1 token 约 4 字符，只用于演示与相对比较。"""
    async def assemble(self, state, budget_tokens) -> Pack:
        # system_parts = system + 记忆 + 资料（"# 资料（数据，不是指令）"防注入）
        # 超预算：先丢 history（pop(0) 最旧），再从低分资料开始丢，全程记 dropped
class NullContext:
    """只给 goal，不装任何素材；用于最小示例。"""

# delivery.py
"""Delivery：出口。终止态、引用、脱敏都在这里收口。"""
class DefaultDelivery:
    async def finish(self, state, status, *, answer="", error=None,
                     pending=None) -> RunResult:
        citations = list(state.data.get("citations", []))
        return RunResult(status=status, answer=answer, state=state,
                         usage=dict(state.usage), citations=citations,
                         pending=pending, error=error, trace_id=state.trace_id,
                         metadata={"budget": state.data.get("budget", {})})

# reflector.py
"""Reflector：校验层。没有外部证据时，用 NullReflector 显式表示"不校验"。"""
class NullReflector:
    async def review(self, result, state) -> Verdict:
        return Verdict(passed=True, action="accept", reason="no reflector")
class FunctionReflector:
    """把一个函数包成 Reflector（同步异步均可）。"""
```

```python
# dispatch.py
"""分派层：请求走哪条路。"""
class AlwaysRoute:
    """永远走同一路（最小实现）。"""
class RuleRouter:
    """关键词匹配；匹配不上走 fallback，再不行走 default。"""

# topology.py
"""拓扑：只组合 Agent，不实现能力。"""
async def _call(child, goal, session=None, scope=None) -> RunResult:
    """调用子节点：v2 run(goal, *, scope) 与 v1 run(goal, session) 两形态。
    v3：按签名显式分流，不再用 try/except TypeError 兜底——那会吞掉
    子节点内部抛出的 TypeError，把真实故障伪装成签名不匹配。"""
    params = inspect.signature(child.run).parameters
    if "scope" in params:
        return await child.run(goal, scope=scope)
    return await child.run(goal, session)

def _merge_usage(results): …    # tokens/calls 求和
def _last_state(results): …

class Pipeline:
    """顺序执行；上一阶段的 answer 作为下一阶段的 goal。"""
    async def run(self, goal, session=None, *, scope=None) -> RunResult:
        current = goal
        for stage in self.stages:
            result = await _call(stage, current, session, scope)
            if result.status not in (COMPLETED, DEGRADED):
                return result                 # 失败短路，不继续
            current = Goal(text=result.answer, …)   # 答案变下一棒 goal

class Handoff:
    """按 Router 把控制权交给一个 agent。"""
    # route = await self.router.route(goal) → agents.get(route.name)
    # → 找不到则找 is_fallback 的 → 都没有则 failed

class Supervisor:
    """拆任务并发跑多个 worker，最后 synth 合并。"""
    # planner 产出任务 → 各 worker 并发（asyncio.gather）→ 任一失败短路返回
    # → self.synth(results) 或 answer 拼接

class Blackboard:
    """共享看板；顺序写入，reducer 合并。"""
    # board[f"{agent.name}-{index}"] = result.answer；trigger 命中提前结束
```

**封装手法**：拓扑四个类**全部实现 Runnable 签名**（`run(goal, session, *, scope)`）——拓扑可嵌套（Supervisor 里套 Pipeline 套 Handoff）的原因。Pipeline 失败短路、Supervisor 失败也短路、Blackboard 顺序写不并发写（并发写要 Board 增量回写，是另一套机制）。合并 usage 是拓扑的固定义务。

## 3.10 `parts/subagent.py` + `parts/capability.py`

```python
# subagent.py
"""子 agent 层（SPEC M13.5）。五条必须做全，缺一条就是玩具：
    1 独立作用域：新 Namespace、新 State、span 挂父
    2 共享预算：child = parent.split(0.3)，消耗仍计入父
    3 上限：深度、并发、子树步数
    4 返回摘要：只回 answer + 引用 + 用量，不回灌 messages
    5 取消传播：父取消 → 子全停"""

def subagent_layer(*, scope, agent_factory, tool_name="task",
                   concurrency=4, budget_fraction=0.3, max_summary_chars=2000) -> Layer:
    """插点 tool_call：把 task 工具变成一次子运行。
    agent_factory(child_scope, task) 返回一个带 run(goal, scope) 的 Runnable。"""
    slots = scope.child_slots or asyncio.Semaphore(max(1, concurrency))
    if scope.child_slots is None:
        # 第一次构造时把槽位钉进作用域，后续所有子层共用同一份（不变量 2）
        scope = replace(scope, child_slots=slots)

    def build(nxt):
        async def handler(req):
            if not isinstance(req, ToolRequest) or req.step.tool_name != tool_name:
                return await nxt(req)
            args = dict(req.step.args or {})
            task = TaskSpec(description=str(args.get("description",
                                    req.step.instruction or "")),
                            agent_type=str(args.get("agent_type", "default")),
                            expected_schema=args.get("expected_schema"))
            if not task.description.strip():
                return ToolResponse(result=ToolResult(step_id=req.step.id,
                    tool=tool_name, ok=False, error="缺少 description"))
            child_scope = scope.child(task.agent_type, budget_fraction=budget_fraction)
            async with slots:                              # ③ 并发上限
                child = agent_factory(child_scope, task)
                try:
                    result = await child.run(
                        Goal(task.description, session_id=req.step.id),
                        scope=child_scope)
                except asyncio.CancelledError:              # ⑤ 取消传播
                    raise
            summary = (result.answer or "")[:max_summary_chars]
            return ToolResponse(result=ToolResult(          # ④ 只回摘要
                step_id=req.step.id, tool=tool_name,
                ok=result.status in ("completed", "degraded"),
                output=summary, error=result.error,
                tokens=int(result.usage.get("tokens", 0)),
                meta={"depth": child_scope.depth,
                      "agent": child_scope.namespace.agent,
                      "status": str(result.status), "usage": dict(result.usage)}))
        return handler
    return layer("subagent", ["tool_call"], build,
                 needs=["durability", "sandbox", "budget"], after=["approval"])

async def run_child(factory, scope, task):
    """便捷入口：不经过工具，直接起一次子运行（拓扑内部也会用到）。"""
```

```python
# capability.py
"""能力层（SPEC M13.4.2）：文件五件套 / 沙箱两件 / 技能三件 + 结果截断。
能力按 spec.scopes 经 ToolContext 注入，工具自己不去找全局单例。
工具函数的第一个参数若标注为 ToolContext，框架在调用时注入它。"""

def fs_tools() -> list[FunctionTool]:
    """全部走 ctx.fs（虚拟路径 + 挂载表，越界即拒）。"""
    @tool(side_effects="read", scopes={"fs:read"})
    async def read_file(ctx: ToolContext, path: str, offset=0, limit=2000) -> str: …
    @tool(side_effects="write", scopes={"fs:write"})
    async def write_file(ctx: ToolContext, path: str, content: str) -> dict: …
    @tool(side_effects="write", scopes={"fs:write"})
    async def edit_file(ctx: ToolContext, path, old, new, count=1) -> dict: …
    @tool(side_effects="read", scopes={"fs:read"})
    async def glob(ctx: ToolContext, pattern) -> list[str]: …
    @tool(side_effects="read", scopes={"fs:read"})
    async def grep_path(ctx: ToolContext, pattern, glob="**/*", max_hits=200): …
    return [read_file, write_file, edit_file, glob, grep_path]

def sandbox_tools() -> list[FunctionTool]:
    """exec 只收 argv 列表，绝不收字符串命令；env 只接受密钥名。"""
    @tool(side_effects="shell", scopes={"sandbox:exec"}, timeout_s=60, sandbox=True)
    async def exec(ctx: ToolContext, argv: list[str], cwd="/work",
                   timeout_s=30, env_keys: list[str] = ()) -> dict:
        """在沙箱里执行命令（argv 列表）。
        Args:
            argv: 命令与参数，如 ["python", "-V"]
            env_keys: 需要注入的环境变量名（只取名字，值不回流）"""
        env = {name: await ctx.secrets.get(name) for name in env_keys}
        result = await ctx.sandbox.exec(argv, cwd=cwd, env=env, limits=None,
                                        timeout_s=timeout_s)
        return {"exit": result.exit, "stdout": result.stdout, "stderr": result.stderr,
                "timed_out": result.timed_out, "truncated": result.truncated}
    # kill 同构（幂等）
```

**封装手法**：
1. 子代理五条约束**逐条落进代码**并注释标号——特别是 `async with slots`（并发上限）与 `except CancelledError: raise`（取消传播必须 re-raise，吞掉会破坏 asyncio 语义）。
2. `slots` 第一次构造时钉进 scope：子层可能被多次创建（每层各造一个 Semaphore 总量失控——SPEC M13.7 的教训在代码里防住）。
3. 能力工具是**普通工具**（`@tool` 装饰器 + `ctx: ToolContext` 首参），没有特殊基类——能力体系完全长在工具体系上。
4. `env_keys` 只收名字不收值：密钥"只按名取、值不回流"（SecretBroker 协议）落到工具参数设计里。

---

# 阶段四 impl/ + adapters/ —— 可替换实现

## 4.1 `impl/stores/memory.py`：七条 C 不变量的实现

```python
"""存储的内存实现（SPEC M11、M7.2）。七条不变量都由这里体现，测试见 tests/test_stores.py：
    C1 历史不可变   put 只追加新 rev，旧 rev 内容不变
    C2 乐观并发     expect_rev 不匹配 → ConcurrencyError
    C3 命名空间强制 跨 ns 读取视为不存在
    C4 幂等写       同 dedup_key 不产生第二条
    C5 append-only  消息只追加
    C6 尾读有预算   tail(max_tokens) 从尾部往回取
    C7 点查命中     begin 命中返回 Recorded，否则 None"""

def _ns_key(ns: Namespace) -> tuple: return ns.as_tuple()

class MemoryCheckpointStore:
    """C1 + C2 + C3：多版本快照，旧 rev 永不修改。"""
    def __init__(self): self._rows = {}      # (ns 四元组, sid) → [版本列表]

    async def put(self, ns, sid, state, *, expect_rev=None) -> int:
        key = (_ns_key(ns), sid)
        versions = self._rows.setdefault(key, [])
        current = len(versions) - 1
        # 乐观并发只在"已有版本"时生效：没有旧版本就不存在冲突
        if expect_rev is not None and versions and expect_rev != current:
            raise ConcurrencyError(f"{sid}: 期望 rev={expect_rev}，实际 rev={current}")
        versions.append(copy.deepcopy(state.to_dict()))   # 深拷贝 = 旧版本不可变
        state.rev = len(versions) - 1
        return state.rev

    async def get(self, ns, sid, rev=None) -> Checkpoint | None:
        versions = self._rows.get((_ns_key(ns), sid))
        if not versions: return None
        index = len(versions) - 1 if rev is None else rev
        if index < 0 or index >= len(versions): return None
        raw = copy.deepcopy(versions[index])    # 取出也深拷贝：调用方改不动历史
        return Checkpoint(session_id=sid, rev=index, state=State.from_dict(raw))

    async def history(self, ns, sid, *, limit=50) -> list[int]:
        return list(range(len(self._rows.get((_ns_key(ns), sid), []))))[-limit:]

# MemorySessionStore（C3） / MemoryMessageLog（C5+C6：append 只追加、
#   tail(max_tokens) 从尾往回取） / MemoryMemoryStore（C4：upsert 按
#   dedup_key 去重、forget、expire） / MemoryIdempotency（C7：begin 命中
#   返回 Recorded；未注册的 key 占位返回 None）
```

**封装手法**：协议里的每个签名决策都在实现里兑现——`expect_rev` 对应 C2 乐观锁、`Namespace` 第一参对应 C3 隔离、`deepcopy` 进出双向保证 C1（存的时候旧版本不被后续写污染、取的时候调用方改不动历史）。**"没有旧版本就不存在冲突"** 这行注释是乐观锁的边界细节：首次 put 不可能冲突。

## 4.2 `impl/fakes.py` + `testing.py`

```python
# impl/fakes.py
"""测试替身：无模型、无网络。"""
@dataclass
class FakeModel:
    replies: list[ModelReply | str]      # 按调用次序回放；耗尽后重复最后一条
    calls: int = 0
    seen: list[list[dict]] = field(default_factory=list)   # 记录收到的 messages 供断言

    async def complete(self, messages, tools=None) -> ModelReply:
        self.calls += 1
        self.seen.append(list(messages))
        index = min(self.calls - 1, len(self.replies) - 1)
        reply = self.replies[index]
        return ModelReply(content=reply) if isinstance(reply, str) else reply

def tool_call(name, **args) -> ModelReply:
    return ModelReply(tool_calls=[ToolCall(name=name, args=args)])

def answer(text) -> ModelReply:
    return ModelReply(content=text)

# testing.py：兼容壳
"""兼容壳：harness.testing 已迁至 harness.impl.fakes。"""
from harness.impl.fakes import FakeModel, answer, tool_call
```

**封装手法**：FakeModel 的 `seen` 记录收到的消息——测试不但断言输出，还断言"模型看到了什么"（上下文装配正确性）。`tool_call()/answer()` 两个构造器让脚本一行一条：304 个测试全部靠它离线跑。

## 4.3 `impl/backends/`（fs.py / core.py / paths.py）

`FileSystem/Sandbox/ArtifactStore/SecretBroker/IndexBackend/Queue/Clock` 的内存与本地实现。其中 `paths.py` 是安全要点：虚拟路径 → 物理路径的**唯一换算点**，`resolve()` 后判前缀（用 `Path.resolve()` 再比较，防 `/work/../etc` 穿越），不能只做字符串前缀。`core.py`（393 行）是各后端的内存实现、`fs.py`（151 行）是本地文件系统挂载表——结构都是"协议方法 + 内存字典/真实 IO"。

## 4.4 `adapters/openai.py`

```python
"""OpenAI 适配器（SPEC M12.2 / M15.7）。
只做三件事：消息映射、工具映射、usage 归一化成 {input, output, total}。
没装 openai 时给出安装提示，不静默降级。"""

def _require_openai():
    try:
        import openai
    except ImportError as exc:
        raise ConfigError(
            "openai 适配器需要安装依赖：pip install agent-harness[openai]") from exc
    return openai

def normalize_usage(raw) -> dict[str, int]:
    """归一化 usage：上层记账与预算只认统一口径。"""
    data = raw if isinstance(raw, dict) else getattr(raw, "model_dump", lambda: {})()
    prompt = int(data.get("prompt_tokens", data.get("input_tokens", 0)) or 0)
    completion = int(data.get("completion_tokens", data.get("output_tokens", 0)) or 0)
    total = int(data.get("total_tokens", prompt + completion) or 0)
    return {"input": prompt, "output": completion,
            "total": total or prompt + completion}

def to_reply(response) -> ModelReply:
    """把 OpenAI 的 chat.completion 映射成契约类型。"""
    # choice.message.content / tool_calls（含旧式 function_call）/ finish_reason
    # arguments 是 JSON 字符串 → _json_loads 容错（空/坏 JSON 返回 {}）

class OpenAIModel:
    """实现 Model 协议：complete + stream。"""
    def __init__(self, name="gpt-4.1", *, client=None, temperature=0.0, **kwargs): …
    # complete() → client.chat.completions.create → to_reply
    # stream()  → 产出 ModelDelta(kind="text"/"tool_call"/"usage")
```

**封装手法**：适配器是**唯一允许 import openai 的文件**（核心零第三方依赖纪律）；SDK 的三类噪音（参数名差异 prompt_tokens/input_tokens、旧式 function_call、arguments JSON 字符串）全部消化在 `normalize_usage/to_reply/_json_loads` 三个函数里，内核只认契约类型。依赖缺失报 `ConfigError` 带 pip 安装命令——不静默降级。

---

# 阶段五 fp/ + assembly/ —— 门面与装配

## 5.1 `fp/frontends.py`：十种内置范式（590 行）

```python
"""十种内置架构范式（v3 / PROPOSAL §7）—— 可删的前端库。
这些类与用户自写架构完全同层、同一个 Program 协议：内核不认识它们，
删掉整个文件，框架照样能跑任意架构。它们不是框架算子，只是
Decision.program 的取值和 Decision.effects 的数量：
    seq      = program 换成下一个游标        branch   = program 换成某个 arm
    loop     = program 返回自己              parallel = effects 一批多个
    nest     = Effect(kind="child")          graph    = transition 读图数据算下一批节点
    backtrack= program 换回历史 + restore 恢复状态"""

def make_state(text, *, data=None, session_id="s1") -> State:
    """按现网 State 信封构造初始状态。"""
    return State(goal=Goal(text, session_id=session_id),
                 session=SessionRef(session_id), data=dict(data or {}))

def _batch(state) -> dict:
    return state.results.get("__batch__", {})

def _out(batch, key):
    value = batch.get(key)
    return value.get("output") if isinstance(value, dict) else value

@dataclass(frozen=True)
class Leaf:
    """辅助叶子：立即结束的程序（不是第 11 种架构）。"""
    name: ClassVar[str] = "leaf"; text: str = ""
    def describe(self): return f"leaf({self.text})"
    def to_spec(self): return {"kind": "leaf", "text": self.text}
    def transition(self, state): return Halt(self.text)

@dataclass(frozen=True)
class ToolUse:
    name: ClassVar[str] = "tool_use"
    calls: tuple[Effect, ...] = (); fired: bool = False
    def transition(self, state):
        if self.fired:
            return Halt(str(state.data.get("last_output", "")))
        effects = self.calls or (Effect("tool", args={"name": "echo",
                                "args": {"text": "hi"}}, key="last"),)
        return Decision(effects=effects, program=replace(self, fired=True),
                        note="call tool")

@dataclass(frozen=True)
class React:
    """program=self 就是循环，不需要 loop 算子。"""
    name: ClassVar[str] = "react"; max_steps: int = 8; step: int = 0
    def transition(self, state):
        if self.step >= self.max_steps:
            return Halt("max_steps", "degraded")
        reply = _out(_batch(state), "model")
        if reply is not None:
            calls = reply.get("tool_calls", []) if isinstance(reply, dict) else []
            if not calls:
                return Halt(str(reply.get("content", ""))
                            if isinstance(reply, dict) else str(reply))
            call = calls[0]
            return Decision(effects=(Effect("tool", args={"name": call["name"],
                                            "args": call.get("args", {})}, key="tool"),),
                            program=replace(self, step=self.step + 1), note="act")
        return Decision(effects=(Effect("model", key="model"),), program=self,
                        note="think")

@dataclass(frozen=True)
class PlanExecute:
    """phase 状态机（plan→exec）+ 游标。"""
    name: ClassVar[str] = "plan_execute"
    phase: str = "plan"; steps: tuple[dict, ...] = (); cursor: int = 0
    def transition(self, state):
        if self.phase == "plan":
            reply = _out(_batch(state), "model")
            if reply is None:
                return Decision(effects=(Effect("model", key="model"),),
                                program=self, note="plan")
            plan = reply.get("plan", []) if isinstance(reply, dict) else []
            return Decision(effects=(), program=replace(self, phase="exec",
                            steps=tuple(plan)), note="plan ready")
        if self.cursor >= len(self.steps):
            return Halt(str(state.data.get("last_output", "")))
        step = self.steps[self.cursor]
        return Decision(effects=(Effect("tool", args={"name": step["name"],
                                        "args": step.get("args", {})}, key="tool"),),
                        program=replace(self, cursor=self.cursor + 1),
                        note=f"step {self.cursor + 1}")

@dataclass(frozen=True)
class Reflection:
    """draft↔critic 相位轮换 + max_rounds。"""
    name: ClassVar[str] = "reflection"
    phase: str = "draft"; round: int = 0; max_rounds: int = 3
    def transition(self, state):
        batch = _batch(state)
        if self.phase == "draft":
            draft = _out(batch, "draft")
            if draft is None:
                return Decision(effects=(Effect("model", key="draft"),),
                                program=self, note="draft")
            text = draft.get("content", "") if isinstance(draft, dict) else str(draft)
            return Decision(effects=(), program=replace(self, phase="critic"),
                            patch={"draft": text}, note="draft ready")
        verdict = _out(batch, "model")
        if verdict is None:
            return Decision(effects=(Effect("model", key="model"),),
                            program=self, note="critic")
        passed = isinstance(verdict, dict) and verdict.get("verdict") == "pass"
        if passed or self.round >= self.max_rounds:
            return Halt(str(state.data.get("draft", "")))
        return Decision(effects=(),
                        program=replace(self, phase="draft", round=self.round + 1),
                        note="revise")

@dataclass(frozen=True)
class Router:
    name: ClassVar[str] = "router"
    arms: dict[str, Any] = field(default_factory=dict); fallback: Any = None
    def transition(self, state):
        reply = _out(_batch(state), "model")
        if reply is None:
            return Decision(effects=(Effect("model", key="model"),),
                            program=self, note="classify")
        name = reply.get("route", "general") if isinstance(reply, dict) else "general"
        arm = self.arms.get(name, self.fallback)
        if arm is None:
            return Halt(f"无匹配 arm：{name}", "refused")
        return Decision(effects=(), program=arm, patch={"route": name}, note=f"-> {name}")

@dataclass(frozen=True)
class RouterSkill:
    """分流（目录常驻）+ 能力包（按需加载正文）+ 执行体。"""
    name: ClassVar[str] = "router_skill"
    arms: dict[str, Any] = field(default_factory=dict); fallback: Any = None
    phase: str = "route"; chosen: str = ""
    def transition(self, state):
        batch = _batch(state)
        if self.phase == "route":
            reply = _out(batch, "model")
            if reply is None:
                return Decision(effects=(Effect("model", key="model"),), program=self,
                                note="select skill")
            name = reply.get("route", "general") if isinstance(reply, dict) else "general"
            if name not in self.arms:
                name = "general"
            return Decision(
                effects=(Effect("skill", args={"name": name, "part": "body"}, key="body"),),
                program=replace(self, phase="dispatch", chosen=name), note=f"load {name}")
        body = _out(batch, "body")
        arm = self.arms.get(self.chosen, self.fallback)
        if arm is None:
            return Halt("无匹配技能", "refused")
        return Decision(effects=(), program=arm,
                        patch={"skill": self.chosen, "skill_body": body},
                        note=f"run {self.chosen}")

@dataclass(frozen=True)
class Supervisor:
    """一批 child = 并行 fan-out，下一轮 join。"""
    name: ClassVar[str] = "supervisor"
    workers: dict[str, Any] = field(default_factory=dict)
    phase: str = "plan"
    def transition(self, state):
        if self.phase == "plan":
            reply = _out(_batch(state), "model")
            if reply is None:
                return Decision(effects=(Effect("model", key="model"),), program=self,
                                note="decompose")
            tasks = reply.get("tasks", []) if isinstance(reply, dict) else []
            effects = tuple(
                Effect("child", args={"goal": goal, "data": {}}, child=self.workers[name],
                       key=name)
                for name, goal in tasks if name in self.workers)
            return Decision(effects=effects, program=replace(self, phase="join"),
                            note="fan-out")
        outputs = [str(state.results.get(name, {}).get("output", ""))
                   for name in self.workers]
        return Halt(" | ".join(o for o in outputs if o))

@dataclass(frozen=True)
class Handoff:
    """角色间移交控制权：program=roles[target] + hops 上限。"""
    name: ClassVar[str] = "handoff"
    roles: dict[str, Any] = field(default_factory=dict)
    current: str = "triage"; hops: int = 0; max_hops: int = 6
    def transition(self, state):
        reply = _out(_batch(state), "model")
        if reply is None:
            return Decision(effects=(Effect("model", key="model"),), program=self,
                            note=f"{self.current} thinks")
        if isinstance(reply, dict) and reply.get("handoff") and self.hops < self.max_hops:
            target = reply["handoff"]
            return Decision(effects=(),
                            program=replace(self, current=target, hops=self.hops + 1),
                            patch={"last_role": self.current}, note=f"handoff -> {target}")
        text = reply.get("content", self.current) if isinstance(reply, dict) else str(reply)
        return Halt(f"{self.current}: {text}")

@dataclass(frozen=True)
class Blackboard:
    """多 agent 轮流写同一块黑板：一批 child × max_rounds 轮。"""
    name: ClassVar[str] = "blackboard"
    agents: tuple[Any, ...] = (); max_rounds: int = 2; round: int = 0
    @staticmethod
    def _key(index, agent): return f"{agent.name}-{index}"
    def transition(self, state):
        if self.round >= self.max_rounds:
            board = [str(state.results.get(self._key(i, a), {}).get("output", ""))
                     for i, a in enumerate(self.agents)]
            return Halt(" / ".join(v for v in board if v))
        effects = tuple(
            Effect("child", args={"goal": _goal(state), "data": {}}, child=a,
                   key=self._key(i, a))
            for i, a in enumerate(self.agents))
        return Decision(effects=effects, program=replace(self, round=self.round + 1),
                        patch={"board_rev": self.round}, note="write board")

@dataclass(frozen=True)
class Graph:
    """声明式前端：节点 + 条件边。纯 DAG 表达不了环——环放进节点内部。"""
    name: ClassVar[str] = "graph"
    nodes: dict[str, Effect] = field(default_factory=dict)
    edges: tuple[tuple[str, str, str], ...] = ()   # (src, dst, when)
    entry: str = ""; done: tuple[str, ...] = ()

    def to_spec(self) -> dict:
        return {"kind": "graph", "nodes": {k: asdict(v) for k, v in self.nodes.items()},
                "edges": [list(e) for e in self.edges], "entry": self.entry}

    def static_check(self) -> list[str]:
        """装配期可查：入口、悬空边、环。环必须放进节点内部或显式受控回边。"""
        problems: list[str] = []
        if self.entry not in self.nodes:
            problems.append(f"入口节点不存在：{self.entry}")
        # 悬空边检查 + Kahn 拓扑：
        for src, dst, _when in self.edges:
            if src not in self.nodes or dst not in self.nodes:
                problems.append(f"悬空边：{src} -> {dst}")
        …
        if seen != len(self.nodes):     # 拓扑数不完所有节点 = 有环
            problems.append("图中存在环：DAG 前端不允许回边（环请放进节点内部）")
        return problems

    @staticmethod
    def _ok(when, state) -> bool:
        if not when: return True
        if when.startswith("route:"):
            return state.data.get("route") == when.split(":", 1)[1]  # 条件边读 patch
        return True

    def transition(self, state):
        if not self.done:
            return Decision(effects=(replace(self.nodes[self.entry], key=self.entry),),
                            program=replace(self, done=(self.entry,)), note="entry")
        nxt = [dst for src, dst, when in self.edges
               if src in self.done and dst not in self.done and self._ok(when, state)]
        if not nxt:
            return Halt(str(state.data.get("last_output", "")))
        return Decision(effects=tuple(replace(self.nodes[n], key=n) for n in nxt),
                        program=replace(self, done=self.done + tuple(nxt)),
                        note="-> " + ",".join(nxt))

@dataclass(frozen=True)
class GraphSpec:
    """可序列化的图形态；编译成 Graph.transition，与用户自写架构同层。"""
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: tuple[tuple[str, str, str], ...] = (); entry: str = ""
    # from_dict / to_dict

def compile_graph(spec) -> Graph:
    """声明 → 程序。nodes 里每个值是 Effect 的字段字典。"""

def program_from_spec(spec) -> Any:
    """JSON Spec → 程序。工厂查 assembly.registry.PROGRAMS，无白名单。"""
    factory = PROGRAMS.get(kind)
    if factory is None:
        raise ConfigError(f"未知程序形态：{kind!r}；可用：{sorted(PROGRAMS)}")
    # arms/workers/roles/fallback/agents/calls/steps 里嵌套的 {"kind":…} 递归编译

def builtin_paradigms() -> list[tuple[str, Any, State]]:
    """验收夹具：十种架构各配一套 script 回放数据，供统一运行。"""

def _register_frontends() -> None:
    """注册到 assembly.registry.PROGRAMS（PROPOSAL §9.2）。
    前端库自己注册，assembly 不反向 import fp——分层约束不破，
    且新增一种前端只需在这里加一行。"""
    for name, cls in {"leaf": Leaf, "graph": Graph, "tool_use": ToolUse,
                      "react_loop": React, "plan_execute": PlanExecute,
                      "reflection": Reflection, "router": Router,
                      "router_skill": RouterSkill, "supervisor": Supervisor,
                      "handoff": Handoff, "blackboard": Blackboard}.items():
        if name not in PROGRAMS:
            register_program(name, _program_factory(name, cls))

_register_frontends()    # import 即注册
```

**封装手法**：
1. **所有程序都是 frozen dataclass**：状态推进靠 `replace(self, …)` 派生——程序本身可 `to_spec()` 进检查点、可回溯（换回历史实例），这直接依赖"程序是值"。
2. Graph 把"图能查什么"写进 `static_check()`（入口存在、无悬空边、无环），是治理分级在真实前端上的示范。
3. Graph 的条件边 `_ok("route:x")` 读的是 `state.data["route"]`——Router 用 `patch={"route": name}` 写的。前端之间**通过 State 数据通信**，互不 import。
4. 自注册让"新增一种前端"收敛为"加一行"，且 `program_from_spec` 无白名单（注册即用）。

## 5.2 `fp/__init__.py`：组合式门面

```python
"""L5 门面：组合式 API（SPEC §18）。三个类型，语义定死：
    Layer    单一扩展单元；>> 左为外层，| 回退
    Program  策略单元 = body + 若干层
    Harness  能力容器；run(program, goal)
Program 里没有实例，能力全在 Harness——这是"换后端不改程序"的类型级保证。"""

def compose(*layers) -> Layer:
    """把若干层合成一层；顺序仍由各层的 after/before 在 resolve 时拓扑排序。"""
    # names 收集 → build 里从右往左包 → Layer(name=" >> ".join(names),
    #   points/needs 并集，after/before 减去内部名字后并集：
    #   after=frozenset().union(*(lay.after - set(names) for lay in layers)))

def fallback(left, right) -> Layer:
    """回退：前者抛错则整体改用后者，二者共享同一内层。"""
    def build(nxt):
        inner_left, inner_right = left.build(nxt), right.build(nxt)   # 各自包同一 nxt
        async def handler(req):
            try:
                return await inner_left(req)
            except Exception:
                return await inner_right(req)
        return handler
    return Layer(name=f"{left.name} | {right.name}",
                 points=left.points | right.points, build=build,
                 needs=left.needs | right.needs)

def describe(program) -> str:
    """打印解析后的层顺序（组合看不见顺序，必须能打印）。"""
    parts = [getattr(program.body, "name", type(program.body).__name__)]
    for point in ("run", "step", "model_call", "tool_call"):
        names = [lay.name for lay in chain.resolve(program.layers, point)]
        if names:
            parts.append(f"{point}: " + " > ".join(names))
    return " | ".join(parts)

@dataclass(frozen=True)
class Program:
    body: Any
    max_steps: int = 24
    layers: tuple[Layer, ...] = ()
    scope: Any = None        # v3：RunScope 由装配期注入；Program 不持有能力实例

    @property
    def name(self) -> str:
        """v3 Program 协议的 name；由 body 决定，不新增字段。"""
        return str(getattr(self.body, "name", "react"))

    def __rshift__(self, lay) -> "Program":          # program >> layer
        return replace(self, layers=self.layers + (lay,))

    async def transition(self, state):
        """鸭子类型满足 v3 Program 协议（PROPOSAL §9.2，不重命名）。
        控制流仍由 body.next_step 决定；这里只把旧契约翻译成 Decision | Halt。"""
        from harness.kernel.legacy import LegacyProgram
        if self.scope is None:
            raise ConfigError("Program.transition 需要装配期注入 scope（请用 Harness.run）")
        return await LegacyProgram(self, self.scope).transition(state)

    def to_spec(self) -> ProgramSpec:
        """闭包层没有声明形态 → NotSerializable（显式降级不假装）。"""
        for lay in self.layers:
            if getattr(lay, "spec", None) is None:
                raise NotSerializable(f"层 {lay.name} 没有声明形态，无法序列化")

    @classmethod
    def from_spec(cls, spec, *, factories) -> "Program":
        """由声明形态重建；未知层名 → ConfigError（不静默跳过）。"""

def react(*, max_steps=24) -> Program: return Program(body=ReactPolicy(), …)
def workflow(*steps, max_steps=None) -> Program: …
def pe(planner, *, max_steps=24) -> Program: …

from harness.assembly.harness import Harness   # 能力容器属装配层
from harness.fp import frontends as _frontends  # 触发前端自注册
```

**封装手法**：
1. `compose/fallback` 是层的**代数**：compose 的 after/before 要减去内部名字（`after - set(names)`），否则组合体会跟自己的成员产生排序边、拓扑排序误判环。
2. `Program >> layer` 返回新 Program（frozen replace）——组合也是值运算。
3. `describe` 存在的理由写在注释里：组合式 API 看不见顺序，**必须能打印解析后的顺序**，否则用户没法调试。
4. 末尾 import Harness 与 frontends 的位置是刻意的：门面只在最后把装配层和前端库挂上，触发自注册。

## 5.3 `assembly/registry.py`：配置解析与注册表

```python
"""配置解析与注册表（SPEC M15.7）：name[:arg] 或 dict 两种形态。
未知名一律 ConfigError 并列出可用名字——排查成本从这里省。
需要第三方适配器的条目在未安装时给出明确的安装提示，不静默降级。"""

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

def parse_spec(spec, *, kind) -> tuple[str, str, dict]:
    """拆解配置项 → (name, arg, 额外参数)。
        "memory"                  → ("memory", "", {})
        "sqlite:runs.db"          → ("sqlite", "runs.db", {})
        {"kind": "postgres", "dsn": "..."}  → ("postgres", "", {"dsn": "..."})"""
    # dict 形态必须含 "kind"；arg 从 arg/dsn/path 三个键里取
    # 名字正则校验（小写字母开头 + 数字下划线）

def resolve(kind, spec, table) -> Any:
    """查表构造；未知 name → ConfigError 并列出可用名字。"""
    name, arg, extra = parse_spec(spec, kind=kind)
    factory = table.get(name)
    if factory is None:
        raise ConfigError(f"未知 {kind}：{name!r}；可用：{sorted(table)}")
    return factory(arg, **extra)

def _adapter(name, extra):
    """占位工厂：没装适配器时给出安装提示，不静默降级。"""
    def factory(arg="", **kwargs):
        raise ConfigError(f"{name} 需要安装适配器：pip install agent-harness[{extra}]")
    return factory

MODELS = {"fake": _fake_model, "openai": _adapter("openai", "openai"), …}
STORES = {"memory": _memory_checkpoint, "sqlite": _sqlite_checkpoint,
          "postgres": _adapter("postgres", "postgres"), …}
STORE_SLOTS = {"durability": …, "session": …, "messages": …,
               "memory": …, "idempotency": …}
BACKENDS = {"fs": …, "sandbox": …, "artifacts": …, "secrets": …,
            "index": …, "queue": …, "approval": …, "clock": …}
GUARDRAILS = {"injection": …, "pii": …, "secret_leak": …}
PROGRAMS = {}                       # 前端自注册进来
def register_program(name, factory): PROGRAMS[name] = factory
```

**封装手法**：字符串 DSL（`"sqlite:runs.db"`）+ dict（`{"kind": …}`）双形态，解析集中一处；`_adapter` 占位工厂把"没装依赖"变成带安装命令的装配期错误；`"可用：sorted(table)"` 让错误信息自带补全。

## 5.4 `assembly/build.py` + `assembly/config.py`

```python
# build.py
"""装配层：build(cfg) 是唯一实例化处。"""
@dataclass
class AgentConfig:
    model: Any
    tools: list = field(default_factory=list)
    mode: Literal["react", "workflow", "pe"] = "react"
    workflow: list[Step] | None = None
    planner: Any = None
    max_steps: int = 12
    system: str = ""
    guard: Any = None; budget: Budget | None = None; tracer: Any = None
    durability: Any = None; delivery: Any = None; reflector: Any = None
    context: Any = None; resilience: Any = None
    knowledge: Any = None; retrieval: Any = None
    memory: Any = None; memory_policy: dict | None = None
    name: str = "agent"

def build(config: AgentConfig) -> Agent:
    if config.mode == "workflow":
        if not config.workflow: raise ConfigError("mode=workflow 需要 workflow 步骤")
        if config.planner is not None: raise ConfigError("mode=workflow 不允许 planner")
        policy = WorkflowPolicy(config.workflow)
    elif config.mode == "react":
        if config.workflow: raise ConfigError("mode=react 不允许 workflow")
        if config.planner is not None: raise ConfigError("mode=react 不允许 planner")
        policy = ReactPolicy(max_steps=config.max_steps)
    elif config.mode == "pe":
        if config.workflow is not None: raise ConfigError("mode=pe 不允许 workflow")
        if config.planner is None: raise ConfigError("mode=pe 需要 planner")
        policy = PlanExecutePolicy(config.planner, max_steps=config.max_steps)
    else:
        raise ConfigError(f"未知 mode：{config.mode}")

    registry = ToolRegistry().add(*(as_tool(item) for item in config.tools))
    actor = Actor(model=config.model, tools=registry, resilience=config.resilience)
    context = config.context or BudgetedContext(system=config.system)
    return Agent(name=config.name, policy=policy, actor=actor, context=context,
                 guard=config.guard or AllowAllGuard(),
                 budget=config.budget or Budget(),
                 tracer=config.tracer or NullTracer(),
                 durability=config.durability or NullDurability(),
                 delivery=config.delivery or DefaultDelivery(),
                 reflector=config.reflector or NullReflector(),
                 max_steps=config.max_steps, knowledge=config.knowledge, …)
```

```python
# config.py（v2/v3 配置）
"""装配：配置 → Harness（SPEC M15）。
构造期把八条校验一次做完：缺依赖、层重名、顺序成环、body 组合、工具重名、
引用未注册护栏、挂载非法、插点非法。宁可启动时报错，也不运行期猜。"""

@dataclass(frozen=True)
class StoreSpec:
    """五个存储各一个槽，互不牵连（换记忆介质只改一行）。"""
    durability: Any = "memory"; session: Any = "memory"
    messages: Any = "memory"; memory: Any = "memory"; idempotency: Any = "memory"

@dataclass(frozen=True)
class BackendSpec:
    """八个执行/供应后端各一个槽。"""
    fs: Any = "memory"; sandbox: Any = "fake"; artifacts: Any = "memory"
    secrets: Any = "env"; index: Any = "memory"; queue: Any = "memory"
    approval: Any = "memory"; clock: Any = "system"

@dataclass(frozen=True)
class HarnessConfig:
    """只描述意图，不构造实例。"""
    model: Any = "fake"
    tools: tuple[Any, ...] = ()
    stores: StoreSpec = field(default_factory=StoreSpec)
    backends: BackendSpec = field(default_factory=BackendSpec)
    guardrails: tuple[str, ...] = ()
    layers: tuple[LayerSpec, ...] = ()
    budget: Budget = field(default_factory=Budget)
    system: str = ""; max_depth: int = 2
    namespace_tenant: str = "default"
    max_transitions: int = 64   # v3 全局终止护栏（PROPOSAL §5.1）

def validate(config) -> None:
    """九条构造期校验：挂载点 / 护栏已注册 / 工具名唯一 / 层声明合法 /
    存储·后端可解析 / 预算非负 / 深度合法 / 命名空间非空 / max_transitions 为正。"""
```

**封装手法**：
1. **判别联合**：`mode` 是唯一判别字段，三种模式的合法组合在 build 里逐条校验（workflow↔planner 互斥、pe 必须有 planner）——非法组合**构造期**拒绝，不运行期猜。
2. `HarnessConfig` 只描述意图（字符串 spec），`build_harness` 负责实例化——配置可序列化、可 diff、可审查。
3. 缺省件在 build 里显式补齐（AllowAllGuard/NullTracer/NullDurability/NullReflector/DefaultDelivery），延续"没有≠放行"。
4. `StoreSpec/BackendSpec` 槽位化：五个存储、八个后端**各一个槽**——换介质只改一行，槽间零牵连。

## 5.5 `assembly/harness.py` + `assembly/agent.py`

`harness.py`（235 行）：

```python
"""Harness：能力容器（SPEC M15.3）。
放在装配层而不是门面层：它要 new 具体部件（Actor/Framer/Encoder），
属于"构造"职责；门面只做组合。这样 assembly 不必反向依赖 fp。"""

@dataclass
class Harness:
    """模型、工具、存储、后端。不持有任何策略。"""
    model: Any = None
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    budget: Budget = field(default_factory=Budget)
    namespace: Namespace = field(default_factory=Namespace)
    stores: dict[str, Any] = field(default_factory=dict)
    backends: dict[str, Any] = field(default_factory=dict)
    guard: Any = None; pipes: tuple = (); filter: Any = None
    guardrails: tuple = (); system: str = ""; max_depth: int = 2
    max_transitions: int = 64
    layers: tuple = (); auto_layers: tuple = (); sinks: tuple = ()

    def scope_for(self, goal) -> RunScope:
        """把容器持有的能力装进一个只读作用域。"""
        return RunScope(namespace=replace(self.namespace,
                                          session=goal.session_id or "default"),
                        budget=self.budget, model=self.model,
                        actor=LlmActor(model=self.model, tools=self.tools),
                        framer=ModelFramer(system=self.system), encoder=ChatEncoder(),
                        guard=self.guard, pipes=tuple(self.pipes),
                        filter=self.filter or DefaultClassify(),
                        guardrails=tuple(self.guardrails), max_depth=self.max_depth,
                        **{k: v for k, v in self.backends.items()
                           if k in set(RunScope.__dataclass_fields__)})

    def new_runtime(self, state, *, sinks=None, record_only=False, limits=None,
                    layers=(), extra_handlers=None, hooks=()):
        """装配期注入能力：模型、护栏、事件出口、预算、横切层。
        Runtime 是唯一解释器；这里只负责把 Harness 持有的能力接上。"""
        scope = self.scope_for(state.goal)
        if sinks is not None:
            scope = replace(scope, events=_Fanout(tuple(sinks)))
        async def emit(name, **fields):
            sink = getattr(scope, "events", None)
            if sink is None: return
            try:
                await sink.emit(RunEvent(name=name, trace_id=state.trace_id,
                                         fields=fields))
            except Exception: pass            # 观测不影响运行
        return Runtime(
            layers=tuple(layers),
            limits=limits or Limits(max_transitions=self.max_transitions,
                                    max_calls=self.budget.calls,    # Budget→Limits 汇合
                                    max_tokens=self.budget.tokens),
            record_only=record_only, extra_handlers=extra_handlers, emit=emit,
            model=self.model, guard=self.guard, checks=tuple(self.pipes),
            classify=self.filter, hooks=tuple(hooks))

    async def interpret(self, program, state=None, *, goal=None, sinks=None,
                        record_only=False, limits=None, layers=(),
                        extra_handlers=None):
        """v3 唯一解释器入口：任意架构，只要满足 transition(state)。
        与 Harness.run 的区别：这里不假设 ReAct 循环，程序自己决定
        顺序、分支、并行、回溯、改图和谁持有控制权。"""
        st = state if state is not None else self._state_for(goal)
        runtime = self.new_runtime(st, sinks=sinks, record_only=record_only,
                                   limits=limits, layers=layers,
                                   extra_handlers=extra_handlers)
        return await runtime.interpret(program, st)

    async def dry_run_program(self, program, state=None, *, goal=None, **kwargs):
        """record_only=True：四段链照走，终端只记账不执行；返回 (结果, 效应清单)。"""

    async def run(self, program, goal, *, sinks=None, with_auto=True) -> RunResult:
        """v2 兼容入口：底层转发 run_loop → run_legacy → interpret。"""

    async def astream(self, program, goal):
        """流式出口：共用同一条内核，只是多挂一个队列 sink（SPEC M11.2）。"""
        # _QueueSink：溢出丢最旧并计数 → asyncio.Queue → 逐事件 yield，run.end 收尾

class _Fanout:
    """把事件扇出到多个 sink；任一失败不影响其余。"""
class _QueueSink:
    """把事件推入 asyncio 队列，供 astream 消费。溢出丢最旧并计数。"""
```

`agent.py`（370 行兼容壳，骨架）：

```python
"""Agent：v1 兼容壳（PROPOSAL §9.3 / §10）。
这里不再有循环。名字、构造参数、run / run_sync / resume / resume_sync
签名与 RunResult 语义全部保留；循环体已删除，改由
kernel.interpret.Runtime.interpret 驱动——全框架唯一循环。
旧路径的逐步语义（Guard 审批、Actor 执行、消息回灌、Reflector 重试、
Durability 存档、Tracer 事件）由注入的 CallbackRunner 与
after_commit 钩子复现，解释器本身不认识任何 v1 概念。"""

class Agent:
    def __init__(self, *, policy, actor, context, guard=None, budget=None, …):
        # 全部缺省件显式补齐（AllowAllGuard/NullTracer/NullDurability/
        # NullReflector/DefaultDelivery）

    async def run(self, goal, session=None) -> RunResult:
        state = State(goal=goal, session=session)
        await self._prepare(state)      # 记忆召回 + 知识检索写进 state.data
        return await self._loop(state)

    async def resume(self, session_id, decision: ApprovalDecision) -> RunResult:
        """审批恢复：load → 校验 pending → 过期抛 ApprovalExpired →
        reject 终态 REFUSED / modify 替换 args → 把批准步骤写回 state 重跑。"""

    async def _interpret(self, state) -> RunResult:
        """v1 语义编译成 transition，交给唯一解释器。"""
        async def run_one(effect, st) -> dict:
            # Guard.check → deny 短路 / ask 落盘 pending + durability.save
            #             + 返回 _halt(needs_approval)
            # tracer step.start → actor.execute → 消息回灌（assistant+tool 两条）
            # Reflector review → retry 则返回 skip_tail（保存后重试）
            # 工具错误回灌模型；WorkflowPolicy 没有模型 → 直接 failed
        async def after_commit(st, decision, results):
            # durability.save + tracer step.end
        runtime = Runtime(limits=Limits(max_transitions=self.max_steps + 2,
                                        max_calls=10**9, max_tokens=10**9,
                                        wall_seconds=300.0),
                          runner=CallbackRunner(run_one), after_commit=after_commit,
                          emit=None)
        out = await runtime.interpret(_V1Program(self, ctx), state)
        return await self._finish(out, state)

class _V1Program:
    """v1 BodyPolicy.next_step → 唯一协议 transition。"""
```

**封装手法**：v2 Harness 与 v1 Agent 是**两个容器一个内核**——`Harness.interpret` 直接驱动新协议程序，`Agent._interpret` 把 v1 语义编译成 transition 再交给同一个解释器。审批的两个出口对照看：`approval_layer`（在线，等 channel）与 `Agent.run_one`（离线，落盘 pending + Halt(needs_approval) + resume 恢复）。`_append_tool_messages` 手工拼 assistant/tool 两条消息——OpenAI 工具协议的回灌格式在这里归一。

## 5.6 `assembly/presets.py` + `assembly/fpresets.py`

```python
# presets.py（v1 AgentConfig 预设）
"""五个装配预设：最小、循环、工作流、P&E、生产。
预设不是"另一套实现"，只是 AgentConfig 的简写；换预设只改配置。"""
def build_minimal(*, model, tools=None, **kwargs): …
def build_react(*, model, tools=None, budget=None, tracer=None, guard=None, …): …
def build_workflow(*, model, workflow, tools=None, **kwargs): …
def build_pe(*, model, planner, tools=None, **kwargs): …
def build_production(*, model, tools=None, guard, budget, tracer, durability, …): …

# fpresets.py（v3 HarnessConfig 预设）
"""五个预设：配置简写，不是另一套实现（SPEC M15.6）。"""
def minimal(*, model="fake", tools=()):
    """冒烟测试：无任何横切层。预算 8000 token / 8 次。"""
def react(*, model="fake", tools=(), budget=None):
    """普通对话/工具 agent：预算 + 任务板。层在 Program 里声明；这里只给能力。"""
def production(*, model="fake", tools=()):
    """生产形态：全部能力打开。guardrails=("injection","pii","secret_leak")。"""
```

**封装手法**：预设是**配置简写不是新实现**——两代各一套（AgentConfig 系 / HarnessConfig 系），同一句话写在两个文件头里。`react` 预设注释点出 v3 的分工："层在 Program 里声明；这里只给能力"——能力归 Harness、策略归 Program 的边界连预设都遵守。

---

# 阶段六 门面与验收

## 6.1 `__init__.py`：公开 API

```python
"""agent-harness：可组合的 agent 基座。
公开 API 只承诺这一层；内部按六层组织：
    contracts（契约） · kernel（内核） · parts（部件）
    impl（实现） · assembly（装配） · fp（门面）"""

from harness.assembly.build import AgentConfig, build
from harness.assembly.presets import build_minimal, build_pe, build_production, …
from harness.contracts.errors import (ApprovalExpired, BudgetExceeded, ConfigError, …)
from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.types import (ActionResult, ApprovalRequest, Board, Brief,
                                     Decision, Done, Goal, GuardDecision, …)
from harness.assembly.agent import Agent
from harness.parts.actor import Actor
from harness.parts.body import (FunctionPlanner, PlanExecutePolicy,
                                ReactPolicy, ScriptedPlanner, WorkflowPolicy)
from harness.parts.budget import Budget
# … v1 公开面 + v3 转移契约（Transition 别名）+ fp 门面
```

**封装手法**：`__init__` 是**API 承诺清单**——能从这里 import 的才算稳定 API，其余是高级扩展点不承诺稳定。

## 6.2 `cli.py`：脚手架

```python
"""CLI 脚手架（SPEC §23 缺口 9 / ADR 19）。
    python -m harness.cli new <dir>     # 生成一个最小项目
    python -m harness.cli check <dsn>   # 探活存储后端"""

MAIN_TEMPLATE = '''"""最小 agent 项目：只改配置，不改框架。"""
import asyncio
from harness import Goal
from harness.assembly import HarnessConfig, build_harness
from harness.fp import describe, react
from harness.parts.middleware import taskboard_layer
from harness.parts.tools import tool

@tool
def hello(name: str) -> str:
    """打招呼。

    Args:
        name: 名字
    """
    return f"hello {name}"

async def main() -> None:
    harness = build_harness(HarnessConfig(model="fake", tools=(hello,)))
    program = react(max_steps=6) >> taskboard_layer()
    print(describe(program))
    result = await harness.run(program, Goal("打个招呼", session_id="demo"))
    print(result.status, result.answer)
'''
```

**封装手法**：模板本身就是**最佳实践文档**——@tool 的 docstring 带 Args 段（schema 推导要读）、`>>` 组合层、`describe` 打印解析顺序。`new` 命令生成 README + main.py + pyproject。

## 6.3 `examples/`：验收即教材

`interpret_minimal.py`（59 行，全文见仓库）——三个递进用例：裸函数程序 / 内置 ReAct / Leaf，证明"删掉 frontends.py ①②照样跑"。

`examples/unknown_architectures.py` —— 四种"框架作者没想过的架构"，**纯用户侧代码，框架 diff=0**：

```python
"""框架作者没想过的架构（v3 / PROPOSAL §8）——纯用户侧代码。
这四个架构全部写在 examples/ 里，只导入框架的公开契约与公开运行时：
contracts/decision.py 与 kernel/interpret.py 一行不改就能跑。"""

@dataclass(frozen=True)
class Backtrack:
    """回溯搜索（ToT / LATS）：试一个分支 → 评估 → 不合格就恢复快照、换下一分支。"""
    branches: tuple[str, ...] = ("alpha", "beta", "gamma")
    snapshots: tuple[dict, ...] = ()
    index: int = 0; phase: str = "try"

    def transition(self, state):
        if self.phase == "try":
            if self.index >= len(self.branches):
                return Halt("所有分支均失败", "failed")
            snap = state.snapshot()                      # 进分支前存快照
            branch = self.branches[self.index]
            return Decision(
                effects=(Effect("compute", args={"op": "upper", "args": [branch]},
                                key="candidate"),),
                program=replace(self, phase="evaluate",
                                snapshots=self.snapshots + (snap,)), note=f"try {branch}")
        verdict = _out(_batch(state), "model")
        if verdict is None:
            return Decision(effects=(Effect("model", key="model"),),
                            program=self, note="evaluate")
        candidate = state.results.get("candidate", {}).get("output", "")
        if isinstance(verdict, dict) and verdict.get("verdict") == "pass":
            return Halt(str(candidate))
        return Decision(effects=(),
                        program=replace(self, index=self.index + 1, phase="try"),
                        restore=self.snapshots[-1], note="backtrack")   # ← 回溯

@dataclass(frozen=True)
class SelfModifying:
    """运行时自改写控制流：图不是装配期定的，是跑出来的。"""
    remaining: tuple[str, ...] = ("n1", "n2", "n3"); generation: int = 0
    def transition(self, state):
        if not self.remaining:
            return Halt(f"动态图执行完毕（共 {self.generation} 代）")
        head, *tail = list(self.remaining)
        if state.data.get("promote") == head:
            tail = list(reversed(tail))                   # 运行结果改写剩余控制流
        nxt = replace(self, remaining=tuple(tail), generation=self.generation + 1)
        return Decision(effects=(Effect("compute", args={"op": "upper",
                                          "args": [head]}, key="last"),),
                        program=nxt, patch={"last_node": head},
                        note=f"gen{self.generation}:{head}")

@dataclass(frozen=True)
class ExternalControl:
    """控制权交给外部系统：程序只发 wait 效应，外部队列给什么指令就做什么。"""
    hops: int = 0
    def transition(self, state):
        command = _out(_batch(state), "cmd")
        if command is None:
            return Decision(effects=(Effect("wait", key="cmd"),),
                            program=self, note="await external")
        if command == "stop":
            return Halt(f"外部系统叫停（执行了 {self.hops} 条指令）")
        return Decision(effects=(Effect("compute", args={"op": "upper",
                                          "args": [str(command)]}, key="last"),),
                        program=replace(self, hops=self.hops + 1), note=f"follow {command}")

def bare_transition(state):        # 零封装：不写类，一个函数就是架构
    return Decision(effects=(Effect("compute", args={"op": "concat",
                                      "args": ["裸", "函数"]}, key="last"),),
                    program=FnProgram(lambda s: Halt(str(s.data["last_output"])),
                                      name="end"))
```

**封装手法**：验收判据本身是封装正确性的证明——四种架构（回溯/自改图/外部控制/裸函数）全部只 import 公开契约与公开运行时，`kernel/interpret.py` diff=0。回溯架构展示了 `Decision.restore` + `state.snapshot()` 的完整用法：快照存进程序自身的 frozen 字段（`snapshots=self.snapshots + (snap,)`），不偷放全局。

## 6.4 `tests/`：304 个测试的分层

```text
tests/
├── test_interpret.py            核心验收（唯一循环 + 效应系统 + 护栏 + 检查点）
├── test_unknown_architectures.py 框架 diff = 0 验收
├── test_compat.py               兼容与「解释器唯一」机械检查
├── test_stores.py               七条 C 不变量
└── …（v1/v2 各部件回归）
```

运行方式：

```bash
cd code/harness
PYTHONPATH=src python -m unittest discover -s tests -v      # 304 个测试
PYTHONPATH=src python examples/interpret_minimal.py
PYTHONPATH=src python examples/unknown_architectures.py
PYTHONPATH="src;." python -m proposals.demo     # 独立样张 14 案例
```

---

---

# 阶段七 v3.1 补充 —— SUPPLEMENT-PLAN 的落地施工

> 依据 `docs/harness/SUPPLEMENT-PLAN.md`（A 类接线 / B 类适配器）。边界纪律：
> 内核零第三方依赖、B 类不碰 kernel/contracts、每项配替换实验 + 离线测试。
> 本阶段完成后全量回归 338 个测试通过（含新增 34 个，`tests/test_supplement.py`）。

## 7.1 契约层最小增量（A 类允许的最小改动）

**`contracts/types.py`** —— `ModelReply` 新增一个带默认值的字段（只增不改）：

```python
@dataclass(frozen=True)
class ModelReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"
    parsed: Any = None   # v3.1（SUPPLEMENT A5）：结构化输出校验通过后的强类型结果
```

**`contracts/state.py`** —— `to_dict()/from_dict()` 补上 `results/journal` 两个 v3 字段。
这是 A2 的隐藏缺口：检查点经 `to_dict` 落库，缺这两个键则恢复后效应结果与
消费进度全部丢失（模型脚本游标归零 = 重放重复消费）。旧 payload 无此键时
缺省为空——只增不改，旧 run 仍可读：

```python
    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, …,
                # v3.1（SUPPLEMENT A2）：results/journal 必须落库——崩溃恢复
                # 依赖它们，否则恢复后效应结果与消费进度丢失。
                "results": _jsonable(self.results),
                "journal": _jsonable(self.journal), …}

    @classmethod
    def from_dict(cls, raw) -> "State":
        return cls(…, results=raw.get("results", {}), journal=raw.get("journal", {}))
```

## 7.2 `parts/tokens.py`（A6：真实 token 计数）

**【问题】** framing 按字符估算（1 token ≈ 4 字符），装配的账不可信。
**【封装】** 计数器抽象成协议，装配期注入——同一套取景/编码，换计数器只变精度：

```python
@runtime_checkable
class TokenCounter(Protocol):
    """计数协议：单段文本 + 一组消息两种口径。"""
    name: str
    def count(self, text: str) -> int: ...
    def count_messages(self, messages: Sequence[dict[str, Any]]) -> int: ...

class CharEstimator:
    """字符估算：1 token ≈ 4 字符。与旧 est_tokens 同口径（fake，离线测试用）。"""
    name = "char_estimate"
    def count(self, text): return max(1, len(text) // 4) if text else 0
    def count_messages(self, messages):
        return sum(self.count(str(m.get("content", ""))) for m in messages or ())

class TiktokenCounter:
    """真实现：tiktoken 精确计数。惰性 import，未装报 ConfigError 并给安装命令。"""
    name = "tiktoken"
    def __init__(self, model="gpt-4.1"):
        try:
            import tiktoken
        except ImportError as exc:
            raise ConfigError("tiktoken 计数器需要安装依赖：pip install agent-harness[tiktoken]") from exc
        self._enc = tiktoken.encoding_for_model(model)  # KeyError 则退 o200k_base

def make_counter(precision="chars", *, model="gpt-4.1") -> TokenCounter:
    """装配期便捷入口：precision="chars"（默认，离线）| "tiktoken"（真实现）。"""
```

**【接线】** `ModelFramer(system=…, counter=…)` 内部 `_est()` 优先走 counter、
缺省退回 `est_tokens`——替换实验：换计数器只变 tokens_est 数值，槽位集合
（取景决策）不变。`ChatEncoder(counter=…)` 让 `Pack.usage["estimated_tokens"]`
走精确口径，与厂商回传 usage 的偏差由此可量化。pyproject 新增 extras `tiktoken`。

## 7.3 `parts/body/pe.py` 重写（A1：重规划）

**【问题】** `Verdict.action` 定义了 `replan_all`、Budget 有 `replans` 计数器，
但全库无人消费——契约承诺落空。
**【封装】** PlanExecutePolicy 增加 `reflector/max_replans/budget` 三参；
每轮取下一步前只查**上一轮**的结果（`state.data["last_result"]`）：

```python
    async def next_step(self, state, ctx) -> Step | Done:
        section = state.section("pe")
        if "plan" not in section:
            plan = await self.planner.plan(state.goal, state)   # 首次规划
            section["plan"] = asdict(plan); section["index"] = 0; section["replans"] = 0

        # ---- A1：重规划检查（只查上一轮的结果；首步之前无结果可查）----
        if self.reflector is not None and section.get("index", 0) > 0:
            last_result = state.data.get("last_result")
            if last_result is not None:
                verdict = await self.reflector.review(last_result, state)
                if getattr(verdict, "action", "accept") == "replan_all":
                    return await self._replan(state, section,
                                              reason=str(getattr(verdict, "reason", "")))
        …  # 原有游标推进不变

    async def _replan(self, state, section, *, reason) -> Step | Done:
        """回到 Planner 重出计划；次数受上限约束，超限降级交付。"""
        replans = int(section.get("replans", 0))
        if replans >= self.max_replans:
            return Done(answer=state.data.get("last_output", ""),
                        reason=f"replan_limit({replans})")
        section["replan_context"] = {              # 重规划上下文写进自己的命名空间：
            "reason": reason,                      # Planner 可读，其余组件不感知
            "completed": self._completed_steps(section),   # 已完成步骤 = 原始依据
            "last_error": state.last_error or "",
        }
        plan = await self.planner.plan(state.goal, state)
        …  # 换新计划 + rev 递增 + index 归零
        if self.budget is not None and hasattr(self.budget, "replans"):
            self.budget.replans = max(self.budget.replans, replans)   # 镜像，不回滚
        return await self.next_step(state, None)   # 立即取新计划的第一个步骤
```

**封装手法**：重规划上下文放 `section("pe")`（自己的命名空间）；`completed`
取原计划 index 之前的步骤（Brief 语义：必须带原始依据）；超限走 Done 降级
而不是异常——**重规划是正常业务结局**；reflector=None 时该路径在代码里
根本不存在（DoD 可验证）。

## 7.4 `kernel/interpret.py` 增量（A2：检查点落盘 + 通用崩溃恢复）

```python
class Runtime:
    def __init__(self, *, …, checkpoint_store=None) -> None:
        # v3.1（SUPPLEMENT A2）：可插拔检查点落盘——实现 CheckpointStore 协议
        # （put(ns, sid, state, expect_rev) / get(ns, sid, rev)），复用既有存储。
        self.checkpoint_store = checkpoint_store
        …

    async def interpret(self, program, state) -> Outcome:
        …
            self.checkpoints.append({…内存列表…})
            if self.checkpoint_store is not None:
                # 落盘失败不静默：检查点是恢复的凭据，坏了必须让人知道
                # （与观测不同——观测失败吞掉，持久化失败上抛）。
                from harness.contracts.types import Namespace

                ns = Namespace(tenant=state.session.tenant,
                               user=getattr(state.goal, "user_id", "anonymous") or "anonymous",
                               session=state.session.session_id)
                await self.checkpoint_store.put(
                    ns, state.session.session_id, state, expect_rev=state.rev - 1)
            await self.emit("checkpoint", …)


async def resume_from_checkpoint(store, program, session_id, *, ns=None,
                                 rev=None, **runtime_kwargs) -> Outcome:
    """从检查点续跑（SPEC M11）。恢复是重放结论不是重新推理：状态取自
    检查点，已生效的副作用靠幂等键保证不重复。闭包程序不可序列化，
    program 由调用方重供给（声明式程序可用 program_from_spec 重建）。"""
    ns = ns or Namespace()
    checkpoint = await store.get(ns, session_id, rev)
    if checkpoint is None:
        raise ValidationFailed(f"没有可恢复的检查点：{session_id}…")
    return await Runtime(**runtime_kwargs).interpret(program, checkpoint.state)
```

**expect_rev 的算术要算清楚**：store 每次 put 会把 `state.rev` 重置为
`len(versions)-1`，下一次 put 的期望值恰好是 `state.rev - 1`——两套 rev
（解释器提交计数 / store 版本号）靠这个偏移保持一致。首次 put 无旧版本，
乐观锁天然不触发。

## 7.5 `assembly/agent.py` + `build.py` 增量（A4 预算接线 + A2 Agent 恢复入口）

```python
# build.py：AgentConfig 新增两个透传槽位
class AgentConfig(…):
    limits: Any = None       # 显式 Limits；缺省由 Budget 推导
    checkpoints: Any = None  # CheckpointStore，供崩溃恢复

# agent.py：Agent 构造与运行
class Agent:
    def __init__(self, *, …, limits=None, checkpoints=None):
        # v3.1（SUPPLEMENT A4）：显式 limits 优先；缺省由 Budget 推导——
        # 预算耗尽由解释器护栏触发（degraded），程序不再自查（消灭双重计数）。
        self.limits = limits
        self.checkpoints = checkpoints

    async def resume(self, session_id, decision: ApprovalDecision | None = None,
                     *, rev=None, ns=None) -> RunResult:
        """decision=None 且配置了 checkpoints → 崩溃恢复：按 session_id + rev
        取最近（或指定）检查点，重放续跑。ns 须与产生检查点时一致。"""
        if decision is None:
            return await self._resume_from_checkpoint(session_id, rev=rev, ns=ns)
        …  # 原审批恢复路径不变

    async def _resume_from_checkpoint(self, session_id, *, rev=None, ns=None):
        checkpoint = await self.checkpoints.get(ns or Namespace(), session_id, rev)
        if checkpoint is None:
            raise HarnessError(f"没有可恢复的检查点：{session_id}…")
        return await self._loop(checkpoint.state)   # policy 现场重供给，跳过 _prepare

# agent.py：_interpret 里的两处
#   ① after_commit：durability.save 之后追加 checkpoints.put（A2）
#   ② limits 构造：预算统一接线（A4）
        if self.limits is not None:
            limits = self.limits
        else:
            limits = Limits(max_transitions=self.max_steps + 2,
                            max_calls=self.budget.calls,      # ← Budget 口径
                            max_tokens=self.budget.tokens,
                            wall_seconds=300.0)

# _V1Program.transition：预算自查整段删除（替换为注释）
#   旧：if agent.budget is not None and agent.budget.exhausted: return Halt(…)
#   v3.1：Budget.calls/tokens 已映射进解释器 Limits，护栏统一触发。
```

**`kernel/legacy.py` 同样处理**（v2 路径的同款缺口）：删掉
`LegacyProgram.transition` 开头的 `budget.exhausted` 自查，`run_legacy` 把
`scope.budget.calls/tokens` 映射进 Runtime 的 Limits。替换实验
（`test_replacement.test_budget_replacement_only_changes_status`）证明：
紧预算 → degraded、松预算 → completed，且结论一致——预算只变状态不变形。

## 7.6 `parts/structured.py`（A5：结构化输出闭环，全文见仓库）

**【问题】** 适配器支持 `response_format: json_schema` 透传，但没有
"校验失败自动重试"回路；且内核零依赖纪律禁止 pydantic 进核心。
**【封装】** 三层：

```python
def validate_json(text, schema) -> tuple[Any, list[str]]:
    """内置零依赖校验器：JSON Schema 常用子集
    （type/required/properties/enum/nullable/items/additionalProperties）。"""
    # integer 槽位排除 bool（bool 是 int 子类）；未知一律报错，不猜

class StructuredModel:      # 实现 Model 协议的包装器
    def __init__(self, model, schema, *, validator=None, max_retries=2, …):
        # 内置校验器绑定 schema；自定义 validator 收 text 返回 (value, errors)
        # —— 要 pydantic 级强类型时传自定义 validator（依赖留在用户侧）
    async def complete(self, messages, tools=None, *, response_format=None):
        # 按签名显式分流 response_format（同 topology._call 的教训：
        # 不用 try/except TypeError 兜底——会把模型内部的 TypeError
        # 伪装成签名不匹配；FakeModel 等旧模型不支持该参数）
        for attempt in range(self.max_retries + 1):
            reply = await self.model.complete(…)
            value, errors = self.validator(reply.content)
            if not errors:
                object.__setattr__(reply, "parsed", value)   # frozen 注入
                return reply
            working.append({"role": "user",
                            "content": retry_instruction + "
校验错误：
- …"})
        raise ContractError(f"结构化输出在 {max_retries+1} 次尝试后仍未通过校验：{errors}")

def structured(model, schema, **kwargs) -> StructuredModel:
    """便捷入口：structured(model, {"type":"object", …}) -> 带校验的 Model。"""
```

**封装手法**：校验失败走**数据回灌**（错误文本进下一条 user 消息）而不是
异常重试——模型自愈需要看到错误；最终失败抛 `ContractError`（明确失败，
不静默给坏数据）；`reply.parsed` 携带强类型对象（契约新字段）；换底层模型
只改一行（只依赖 Model 协议）。

## 7.7 `parts/dispatch.py` 增量（A3：LLMRouter / VectorRouter）

```python
@dataclass
class LLMRouter:
    """小模型意图分类：把候选路线列进 prompt，模型回 JSON {"route": name}。
    离线测试注入 FakeModel；解析失败或未知路线 → fallback 并计数。"""
    routes: list[Route] = field(default_factory=list)
    model: Any = None
    default: str = "general"
    fallback_count: int = 0; total_count: int = 0
    fallback_rate = property(lambda self: self.fallback_count / self.total_count
                             if self.total_count else 0.0)   # 兜底率统一口径
    # _prompt：列路线 + 用户输入 + 输出格式约定
    # _parse：json.loads → {"route": name}；坏 JSON/未知名 → None

@dataclass
class VectorRouter:
    """嵌入检索路由：goal 文本查向量库，top1 文档的 source 标注决定路线。
    入库时把 source 写成 "route=<name>" 即完成标注；低于置信阈值或
    空结果 → fallback。依赖 IndexBackend 协议（不依赖具体实现）。"""
    index: Any = None
    namespace: Any = None
    k: int = 1; min_score: float = 0.0
    default: str = "general"
    fallback_count: int = 0; total_count: int = 0
```

**封装手法**：两路都实现 `Router` 协议（`route(goal) -> Route`），与
RuleRouter/AlwaysRoute 可互换；兜底率统计字段名统一（`fallback_count/
total_count/fallback_rate`），替换实验可直接对比分流质量。

## 7.8 `impl/backends/vector.py`（B3 嵌入抽象 + B1 的 fake）

```python
class HashingEmbedder:
    """确定性哈希嵌入：字符 2-gram + 3-gram 哈希累加，L2 归一化。
    同文本永远同向量（可回放）；语义弱但排序特征够用——
    它是"真 embedding 的 fake"（R6：每个真实现必须配 fake）。"""
    def embed(self, text) -> list[float]: …          # md5 分桶 → 256 维 → 归一化
    def embed_documents(self, docs) -> list[Document]:
        """给文档补 vector 字段（contracts Document.vector 此前无人写入）。"""

def _cosine(a, b): …
def _match_filters(metadata, filters):
    """过滤下推：先按 filters 筛，再算相似度（SPEC M12.2，防租户泄漏）。"""

class InMemoryVectorIndex:
    """IndexBackend 协议的内存向量实现（C3：跨 ns 读取视为不存在）。"""
    async def upsert(self, ns, docs) -> int: …       # 同 id 覆盖不追加
    async def search(self, ns, query, *, k, filters=None) -> list[Recalled]:
        # query 可传向量或文本；无 vector 的文档现场补嵌
```

**封装手法**：协议（IndexBackend）不变，`HashingEmbedder` 是 fake、
真 bge/openai 嵌入按同协议走 extras——嵌入→入库→检索全链路离线可跑；
注册表新增 `BACKENDS["index"]["vector"]` 槽位（`"memory"` 二元组打分 ↔
`"vector"` 向量余弦互换，召回质量变化、下游行为一致）。

## 7.9 B2：openai 槽位的自注册接线

**坑位**：最初把 `from harness.adapters.openai import OpenAIModel` 写进了
registry——被 `test_architecture.test_dependency_direction` 当场拦下
（assembly → adapters 越界）。正确做法是**前端库式自注册**：

```python
# adapters/openai.py 末尾
def _registry_factory(arg: str = "", **kwargs: Any) -> Any:
    return OpenAIModel(arg or "gpt-4.1", **kwargs)

try:
    from harness.assembly import registry as _registry

    _registry.MODELS["openai"] = _registry_factory     # 覆盖占位工厂
except Exception:
    pass                                               # 独立使用适配器时注册表可选
```

adapters → assembly 是合法方向（见 test_architecture 的 ALLOWED 表）；
registry 的 "openai" 槽位默认仍是占位（报带安装命令的 ConfigError），
用户 `import harness.adapters.openai` 一行即完成接线。

## 7.10 验收：conformance 基类 + test_supplement.py

**`tests/conformance.py` 新增 `IndexBackendConformance`**（检索后端一致性）：
MemoryIndex 与 InMemoryVectorIndex 走同一场景——upsert/search、过滤下推、
Namespace 隔离、top-k、同 id 幂等覆盖。真 Qdrant/pgvector 接入后同样跑这组。

**`tests/test_supplement.py`（34 个用例）** 验收矩阵：

| 补充项 | 测试 | 替换实验 |
|---|---|---|
| A1 重规划 | replan 触发新计划、replans 递增、超限降级 | reflector=None 时路径不存在 |
| A2 检查点 | Runtime 落盘、resume_from_checkpoint 续跑、Agent.resume(decision=None) | 检查点缺失显式报错 |
| A3 路由 | LLM/Vector 路由 + 兜底计数 | RuleRouter↔VectorRouter 返回形状一致 |
| A4 预算 | 预算耗尽 → 护栏 degraded（answer=max_calls/max_tokens） | 显式 limits 覆盖推导 |
| A5 结构化 | 校验失败回灌重试、parsed 注入、超限 ContractError | 换底层模型只改一行 |
| A6 计数 | 默认=字符口径、注入只变精度不变决策 | CharEstimator↔Tiktoken |
| B2 注册表 | openai 槽位报带安装命令的 ConfigError | fake 槽位照常 |
| B3 向量 | conformance 双实现 + VectorRouter 真链路 | MemoryIndex↔VectorIndex |

## 7.11 未尽事项（按计划顺序继续）

- **B1 真实现**：QdrantIndex / PGVectorIndex（extras `qdrant`/`pgvector`，
  槽位占位已就绪，接 conformance 基类验收）
- **B4** OTel/Langfuse Tracer、**B5** Docker Sandbox、**B6** MCP bridge
- **C 类**（评测体系/A2A/服务化/框架对照）：按计划在项目层，不进框架包

# 收尾：全部封装手法一张表

| # | 手法 | 出处章节 |
|---|---|---|
| 1 | Protocol 定签名、结构化类型（不继承） | 1.7 |
| 2 | 失败语义编码进签名（返回判定 vs 抛异常） | 1.7 / 2.1 |
| 3 | 契约只增不改（新字段带默认值、旧名转发） | 1.4 / 2.6 |
| 4 | frozen 值对象 + replace 派生（层/程序/作用域） | 1.4 / 3.3 / 5.1 |
| 5 | 显式缺省件（AllowAll/Null/DenyAll，没有≠放行） | 2.1 / 3.1 / 5.4 |
| 6 | 装配期报错优于运行期猜（schema 推导、判别联合、九条校验） | 3.5 / 5.4 |
| 7 | 注册代替 if 分支（handlers/PROGRAMS/LAYER_FACTORIES） | 2.4 / 5.1 / 5.3 |
| 8 | 声明式顺序 + 拓扑排序 + 环拒绝 | 2.2 |
| 9 | 单一提交点 / 唯一解释器 / 唯一出口（Delivery） | 2.5 / 1.7 |
| 10 | I/O 即数据（Effect 描述不执行、失败也是数据） | 1.4 / 2.4 |
| 11 | 观测不影响运行（emit/hook/audit 全吞异常） | 1.7 / 3.3 |
| 12 | fail-closed 兜底（未知异常→FAILED、检测器故障→block） | 2.1 / 3.2 |
| 13 | 幂等键（begin/commit 两段式、命中回放零计量） | 1.7 / 2.4 / 3.3 |
| 14 | 乐观锁版本化检查点（expect_rev、历史不可变） | 1.7 / 4.1 |
| 15 | 能力按声明注入（ToolSpec.scopes → ToolContext） | 1.4 / 3.10 |
| 16 | 检测与动作分离（Guardrail 只报风险、策略定动作） | 3.2 |
| 17 | 取景与编码分离（Framer 管留什么、Encoder 管长什么样） | 3.4 |
| 18 | 适配器吸收 SDK 噪音（usage 归一化、依赖缺失带安装提示） | 4.4 |
| 19 | 替换实验验收（换组件只消失一件事） | 6.4 |
| 20 | 每部件配 Fake（FakeModel/seen 断言、零网络） | 4.2 |

**怎么用这份教程**：想读懂某个文件，直接跳对应章节对照源码；想写自己的同类框架，按施工顺序抄（contracts 先行 → 内核 → 部件 → 实现 → 装配），每阶段用阶段六的验收标准收口。

