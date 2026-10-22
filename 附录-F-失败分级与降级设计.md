# 附录 F 失败分级与降级设计

> 系统的可靠性不取决于「不出错」，而取决于「出错时还能给出什么」。
>
> 这一份附录给你一套**可执行的分级方法**：把失败分成三级，每级有明确的判据、
> 重试规则和降级目标。不追求理论完备，追求**能直接写进代码**。

---

## F.1 为什么必须分级

不分级的典型后果：**所有失败都当成同一种**，于是：

| 现象 | 后果 |
|---|---|
| 所有失败都重试 3 次 | 永久性错误（参数错）重试 3 次浪费 3 倍时间和钱 |
| 所有失败都直接报错 | 一个可选依赖挂了，整个请求失败 |
| 所有失败都静默降级 | 真问题被掩盖，用户拿到错误答案还以为是对的 |

**分级的目的**：让"该重试的重试，该放弃的放弃，该降级的降级，该大声报错的报错"。

---

## F.2 三级失败模型

| 级别 | 名称 | 特征 | 恢复概率 | 处理策略 |
|---|---|---|---|---|
| **L1** | 瞬时失败 | 网络抖动、限流、超时、偶发 5xx | **高**（重试通常能成） | 有限重试 + 退避 |
| **L2** | 局部失败 | 某个依赖/某一步骤不可用（向量库挂了、rerank 服务超时） | **中**（能绕过） | 降级 + 标注 |
| **L3** | 全局失败 | 参数错误、认证失败、配额耗尽、数据损坏 | **低**（重试无用） | 立即失败 + 告警 |

### F.2.1 怎么判断一个错误属于哪级

**判据只有一个：重试是否有意义。**

| 错误类型 | 级别 | 判断依据 |
|---|---|---|
| `ConnectionError` / `TimeoutError` | L1 | 下一次可能就好 |
| HTTP 429（限流） | L1 | 等一会儿再试 |
| HTTP 500 / 502 / 503 / 504 | L1 | 服务端临时问题 |
| HTTP 400（参数错） | **L3** | 同样的参数重试还是错 |
| HTTP 401 / 403（认证/权限） | **L3** | 重试不会改变权限 |
| HTTP 404（资源不存在） | **L3** | 重试还是不存在 |
| HTTP 422（校验失败） | **L3** | 同上 |
| `QuotaExceeded` / 余额不足 | **L3** | 需要人去充值 |
| JSON 解析失败 | **L3** | 响应格式不对，重试大概率还是不对 |
| 向量库不可用 | **L2** | 可以退化成关键词检索 |
| rerank 服务超时 | **L2** | 可以退化成不 rerank |
| 缓存不可用 | **L2** | 可以直连后端 |

```python
from enum import Enum

class FailureLevel(Enum):
    TRANSIENT = "L1"     # 重试
    PARTIAL = "L2"       # 降级
    FATAL = "L3"         # 立即失败

TRANSIENT_CODES = {429, 500, 502, 503, 504}
FATAL_CODES = {400, 401, 403, 404, 422}

def classify(exc: Exception) -> FailureLevel:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return FailureLevel.TRANSIENT
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code in TRANSIENT_CODES:
        return FailureLevel.TRANSIENT
    if code in FATAL_CODES:
        return FailureLevel.FATAL
    # 默认当成 FATAL —— 这个默认值是故意的
    return FailureLevel.FATAL
```

> **为什么默认是 L3 而不是 L1？**
> 因为把 L3 当 L1 处理的代价（无限重试、放大故障）远大于反过来
> （少重试一次，用户重试一遍）。**默认保守。**

### F.2.2 一个真实的分错级的代价

> 💥 **事故：把 400 当 500 重试，把配额打爆**

某接口对超长输入返回 `400 context_length_exceeded`。
代码把 400 当瞬时错误，重试 5 次，指数退避到 16s。

结果：一个用户提交超长文本，触发 5 次调用尝试，**每次都计入配额**
（很多厂商的 400 错误也计费，因为模型确实做了 prefill）。

**正确做法：400 类错误绝不重试。**
而且应该在**发送前**就本地检查长度，根本不产生这个请求。

---

## F.3 每一级的处理策略

### F.3.1 L1 瞬时失败：重试的正确姿势

**四条必须同时满足**：

```
1. 只重试 L1
2. 指数退避 + 抖动
3. 有次数上限
4. 有总时间预算
```

```python
import random, time

def retry_l1(fn, max_attempts=3, base=0.5, cap=8.0, budget=20.0):
    start = time.monotonic()
    for i in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            if classify(exc) is not FailureLevel.TRANSIENT:
                raise                        # L2/L3 直接抛
            if i == max_attempts - 1:
                raise
            # 指数退避 + 抖动（抖动是为了避免重试风暴同步）
            delay = min(cap, base * (2 ** i)) * (0.5 + random.random())
            if time.monotonic() - start + delay > budget:
                raise                        # 超出预算就不再等
            time.sleep(delay)
```

**为什么必须有抖动**：1000 个客户端同时被限流，
如果都退避 1s、2s、4s，它们会**同时**回来，再次打爆服务。
抖动把它们打散。（这个现象叫 thundering herd。）

| 参数 | 建议值 | 理由 |
|---|---|---|
| `max_attempts` | 3 | 第 4 次成功的概率已经很低 |
| `base` | 0.5s | 太短没意义，太长用户等不住 |
| `cap` | 8s | 单次等待上限 |
| `budget` | 20s | 总预算；超过就放弃 |
| 抖动 | ±50% | 防同步 |

> 💥 **失败实验：无抖动的重试风暴**
>
> 模拟 200 个客户端同时收到 429，全部按 `1s, 2s, 4s` 退避重试，
> 把重试时刻按 0.25 秒分桶统计峰值：

```
无抖动：重试时刻集中在 1.0s / 3.0s / 7.0s 三个尖峰，每峰 200 个请求同时到达
有抖动（±50%）：最密的桶只有 53 个，其余散布在 0.75s / 1.0s / 1.25s 等
```

**同样的重试次数，峰值并发从 200 降到 53，约为原来的 1/4。**

<details>
<summary>复现脚本（可直接运行）</summary>

```python
import random
random.seed(7)

def peak(jitter: bool, clients: int = 200) -> int:
    bins = {}
    for _ in range(clients):
        t = 0.0
        for base in (1, 2, 4):
            t += base if not jitter else base * (0.5 + random.random())
            b = round(t * 4) / 4          # 0.25 秒分桶
            bins[b] = bins.get(b, 0) + 1
    return max(bins.values())
```

实测：`peak(False) == 200`，`peak(True) == 53`。
</details>

### F.3.2 L2 局部失败：降级的四个模板

降级的核心是：**放弃一个非核心能力，保住主链路。**

| 失败点 | 降级目标 | 代价 | 要不要告知用户 |
|---|---|---|---|
| 向量检索不可用 | 退化为关键词检索（BM25） | 召回质量下降 | 不用（用户无感） |
| rerank 不可用 | 用原始相似度排序 | 精度下降 | 不用 |
| 语义缓存不可用 | 关掉缓存直连 | 延迟上升、成本上升 | 不用 |
| 主模型不可用 | 切备用模型 | 质量可能下降 | **要**（尤其涉及合规时） |
| 长上下文压缩失败 | 截断到前 N 轮 | 丢失早期信息 | 不用 |
| 工具调用失败 | 告知用户"该数据暂时不可用" | 功能缺失 | **要** |
| 流式不可用 | 退回整段返回 | 感知变慢 | 不用 |

**怎么在代码里表达"降级了"**：不要静默降级，要在响应里带标记。

```python
@dataclass
class Answer:
    text: str
    degraded: list[str]   # ["vector_search_failed", "used_keyword_fallback"]
```

**这个字段的用处**：
1. 日志里能统计降级率（降级率高说明基础服务有问题）
2. 前端可以显示"部分结果可能不完整"
3. 事后复盘能区分"模型答错"和"降级导致答错"

> 💥 **事故：静默降级三个月，没人发现向量库一直没工作**

某系统向量库密码过期，连接一直失败。
代码里有 `try/except`，失败后自动退化成关键词检索。

结果：**三个月内所有检索都是关键词检索**，质量比预期低 20 个点，
但因为"能用"，没有任何告警。直到一个客户投诉"搜不到明显相关的内容"才被发现。

**修法三条**：
1. 降级时必须**打 WARN 日志**，带降级原因
2. 降级率进监控面板，超过 5% 告警
3. 降级标记必须出现在响应里（至少 debug 模式下）

### F.3.3 L3 全局失败：fail-fast 与错误信息

L3 要求**立即失败**，但"失败"不等于"返回 500 给用户看到堆栈"。

**错误信息的三层**：

| 给谁 | 内容 | 示例 |
|---|---|---|
| 用户 | 能理解 + 可行动 | "请求内容过长，请缩短到 8000 字以内" |
| 前端/调用方 | 错误码 + 分类 | `{"code": "INPUT_TOO_LONG", "retryable": false}` |
| 日志 | 完整上下文 + 原始异常 | 堆栈、请求 id、参数摘要（脱敏） |

```python
class ApiError(Exception):
    def __init__(self, code: str, user_msg: str, http_status: int, retryable: bool):
        self.code = code
        self.user_msg = user_msg
        self.http_status = http_status
        self.retryable = retryable

INPUT_TOO_LONG = ApiError(
    code="INPUT_TOO_LONG",
    user_msg="请求内容过长，请缩短到 8000 字以内。",
    http_status=400,
    retryable=False,     # ← 这个字段让调用方知道不要重试
)
```

**`retryable` 这个字段是被严重低估的**。
它把"要不要重试"的判断**从调用方转移到服务端**，而服务端最清楚。

### F.3.4 什么时候该 fail-fast

不是所有 L2 都应该降级。**有些情况宁可失败也不能降级**：

| 场景 | 该降级还是 fail-fast | 原因 |
|---|---|---|
| 检索质量下降 | 降级 | 用户可以接受"结果差一点" |
| 医疗/法律建议场景 | **fail-fast** | 降级后的答案可能有害 |
| 涉及金额计算 | **fail-fast** | 算错比不给结果更糟 |
| 权限校验失败 | **fail-fast** | 降级 = 权限绕过 |
| 内容安全过滤失败 | **fail-fast** | 降级 = 护栏失效 |

**判据：如果降级后的结果可能造成不可逆的损害，就 fail-fast。**

---

## F.4 降级矩阵（可直接抄）

把"每个依赖挂了怎么办"写成一张表，评审时逐行确认。

| 依赖 | 关键性 | L1 处理 | 挂了之后（L2/L3） | 用户可见影响 |
|---|---|---|---|---|
| LLM 主供应商 | **致命** | 重试 3 次 | 切备用供应商；都挂则 fail-fast | 短暂延迟 / 完全不可用 |
| LLM 备用供应商 | 高 | 重试 2 次 | 只用主供应商 | 无 |
| Embedding 服务 | 高 | 重试 3 次 | 用缓存过的向量；未命中则关键词检索 | 新文档检索质量下降 |
| 向量库 | 高 | 重试 2 次 | 关键词检索（BM25） | 召回下降，标注降级 |
| Rerank 服务 | 中 | 重试 2 次 | 用原始相似度 | 精度 -5~10 点 |
| 文档数据库 | **致命** | 重试 3 次 | fail-fast | 完全不可用 |
| 缓存（Redis） | 低 | 重试 1 次 | 直连后端 | 延迟↑、成本↑ |
| 日志/追踪 | 低 | **不重试** | 丢弃（本地缓冲后异步补发） | 无 |
| 限流计数器 | 中 | 重试 1 次 | 本地内存计数（可能不准） | 限流可能失效 |
| 内容安全过滤 | **致命** | 重试 2 次 | **fail-fast**（绝不降级） | 完全不可用 |
| 用户鉴权 | **致命** | 不重试 | fail-fast | 完全不可用 |

**读这张表的方法**：

1. 「关键性 = 致命」的行，**没有降级选项**。
2. 「关键性 = 低」的行，可以**直接丢弃**（日志丢了不影响业务）。
3. 中间的行，降级后**必须标注**。

---

## F.5 熔断：防止"重试把服务打死"

重试是双刃剑。下游已经挂了的时候，重试会**放大故障**。

```
下游挂了
  -> 每个请求重试 3 次
  -> 下游收到 3 倍请求
  -> 更慢、更容易挂
  -> 更多超时、更多重试
  -> 雪崩
```

**熔断器**就是解决这个的。三个状态：

```
        失败率 > 50%（且样本 > 20）
  CLOSED ────────────────────────> OPEN
    ↑                                │
    │  试探成功                       │ 等待 30s
    │                                ↓
    └────────────────────────── HALF_OPEN
                                  （放 3 个请求试探）
```

```python
class CircuitBreaker:
    def __init__(self, fail_threshold=0.5, min_samples=20, open_seconds=30):
        self.fail_threshold = fail_threshold
        self.min_samples = min_samples
        self.open_seconds = open_seconds
        self.state = "CLOSED"
        self.fails = 0
        self.total = 0
        self.opened_at = 0.0

    def allow(self, now: float) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if now - self.opened_at >= self.open_seconds:
                self.state = "HALF_OPEN"
                self.fails = self.total = 0
                return True
            return False
        return True   # HALF_OPEN：放少量请求试探

    def record(self, ok: bool, now: float) -> None:
        self.total += 1
        if not ok:
            self.fails += 1
        if self.total >= self.min_samples:
            rate = self.fails / self.total
            if rate > self.fail_threshold:
                self.state = "OPEN"
                self.opened_at = now
                self.fails = self.total = 0
            elif self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.fails = self.total = 0
```

**三个参数的取值理由**：

| 参数 | 值 | 理由 |
|---|---|---|
| `fail_threshold` | 0.5 | 一半都失败，基本可以确定是下游问题，不是你自己的参数问题 |
| `min_samples` | 20 | 太少会被偶发抖动误触发 |
| `open_seconds` | 30 | 太短起不到保护作用，太长恢复慢 |

> 💥 **事故：没有熔断，一个下游超时拖垮整个服务**

下游 rerank 服务变慢（从 50ms 到 5s）。因为代码里没熔断，
每个请求都在等 5s，线程池很快被占满（默认 40 线程 / 5s = 每秒只能处理 8 个请求）。

结果：**rerank 慢导致整个 API 不可用**，包括那些不需要 rerank 的请求。

**修法**：加熔断 + 给 rerank 设 800ms 超时 + 超时后直接跳过 rerank。
修完后：rerank 挂了，API 依然可用（只是精度略降）。

---

## F.6 可观测：怎么知道"现在在降级"

降级设计必须配可观测，否则你不知道降级是不是在天天触发。

**必须有的四个指标**：

| 指标 | 含义 | 告警阈值 |
|---|---|---|
| `degradation_total{reason}` | 各原因的降级次数 | 任一分钟 > 5% 请求量 |
| `circuit_state{dep}` | 每个依赖的熔断器状态 | 任一依赖 `OPEN` |
| `retry_total{attempt, outcome}` | 重试次数与结果 | 重试耗尽率 > 1% |
| `error_total{level, code}` | 按级别分组的错误 | L3 > 0.1%，L1 > 5% |

**"降级率"这个指标的价值**：
它是**质量下降的最早信号**——比用户投诉早得多，比错误率也早（因为降级不报错）。

---

## F.7 一页纸总结

```
失败三级：
  L1 瞬时  -> 重试（指数退避 + 抖动 + 次数上限 + 总预算）
  L2 局部  -> 降级（保住主链路 + 标注 + 监控降级率）
  L3 全局  -> fail-fast（错误码 + retryable=false + 告警）

判断依据：重试有没有意义
  有 -> L1    能绕 -> L2    都没 -> L3

四个必须：
  1. 默认把未知错误当 L3（保守）
  2. 降级绝不静默（打日志 + 进响应 + 进监控）
  3. 依赖挂了要熔断（失败率 > 50% 且样本 > 20）
  4. 可能造成不可逆损害的，一律 fail-fast

三个反模式：
  ❌ 所有错误都重试 3 次
  ❌ 所有失败都静默降级
  ❌ 降级了但没人知道（三个月后才发现）
```

---

## F.8 检查清单

- [ ] 我的代码里有一个 `classify(exc)` 函数，且默认返回 L3
- [ ] 我的重试有退避、有抖动、有次数上限、有总预算
- [ ] 我没有对 4xx 重试
- [ ] 每个 L2 依赖都有明确的降级目标和代价说明
- [ ] 降级会在响应里带标记（至少 debug 模式）
- [ ] 降级次数进了监控，有告警阈值
- [ ] 关键依赖有熔断器，参数经过评估
- [ ] 我逐行审过"降级矩阵"，确认了哪些"绝不降级"
- [ ] 每个 L3 错误都有 `code` + `user_msg` + `retryable`
- [ ] 我演练过"主模型挂了"、"向量库挂了"、"缓存挂了"三种场景
