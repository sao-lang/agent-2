# 第 42 章 系统集成与 Docker 交付：从"能跑"到"能交付"

> **这一章你会遇到什么坏事**
>
> 你的 Agent 在自己电脑上跑得好好的。老板说"下周给客户演示"。
>
> 你把代码发给客户，客户问：**"怎么启动？"** 你说 `python main.py`。
> 客户装 Python 装了半小时，版本对不上，`pip install` 报了 12 个错。
>
> 好不容易跑起来了，客户连点两下按钮——**同一个问题问了两次，扣了两次钱**。
> 又过了一天，客户说：**"点发送之后转圈转了 40 秒，我以为是卡死了。"**
> 你想加重试，结果客户说："现在有时候会重复回答两遍。"
>
> 你发现：**代码是对的，但它不是一个"能交付的东西"。**

> **学完你能做到**
>
> 1. 判断一个 Agent 该用同步 / 流式 / 异步任务三种接口中的哪一种，并说清另外两种为什么不够（41.3）
> 2. 写出"流式中途出错时客户端能知道"的 SSE 接口，而不是让连接静默断掉（41.4）
> 3. 用可见性超时 + 幂等键，让"至少一次投递"不会变成"扣两次钱"（41.5）
> 4. 把镜像从 1.9 GB 压到 729 MB，把改一行代码的重建时间从 96 秒降到 1 秒（41.6）
> 5. 用 `docker compose` 把 7 个服务编排起来，并说清 `depends_on` 为什么不够、必须加 `healthcheck`（41.7）
> 6. 让 Agent 在 `docker stop` 时不丢任务（41.8）

---

## 42.0 先说明白九个词

这一章会出现九个新词，全是**交付层面**的。**先花 2 分钟看完这张表**，后面就顺了。

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **API** | 别人调用你的程序时约定的门（地址 + 方法 + 请求体 + 返回体） | 41.2 起 |
| **SSE（Server-Sent Events）** | 服务器"单向"不停往客户端推送文本；像收音机广播，不是打电话 | 41.4 |
| **TTFT（首字延迟）** | 从点发送到屏幕上出现第一个字的时间。**用户感知的快慢主要看它** | 41.4 |
| **异步任务（202 Accepted）** | 活儿太长了，先回一句"收到了，去查这个号码" | 41.3 |
| **幂等（idempotent）** | 同一个操作做 1 次和做 100 次，结果一样 | 41.5 |
| **可见性超时** | 消息被取走后"藏起来"一段时间；这期间消费者崩了，消息会自动回到队列 | 41.5 |
| **死信队列（DLQ）** | 反复失败、放弃治疗的消息放到一边，人工来看 | 41.5 |
| **镜像分层** | 镜像像千层饼，改了一层，它上面的层全得重做 | 41.6 |
| **健康检查（healthcheck）** | 探针定时问一句"你还活着吗"，答不上来自动重启 | 41.7 |

> 还有三个名词在别章讲过，这里只用来对比，不重复解释：
> **沙箱**（第 33 章：用容器隔离 Agent 的**代码执行**）、**可观测**（第 39 章）、**checkpoint**（第 23 章）。

---

## 42.1 先看一个具体的坏事

先不上代码。先把坏事**摆清楚**。

### 42.1 五种"在我机器上能跑"

| 你的做法 | 客户那边发生什么 | 本质问题 |
|---|---|---|
| 发代码 + "装个 Python" | 装不上，或装了个 3.8 跑不起来 | 环境没有一起交付 |
| 发 `requirements.txt` | 依赖版本漂移，三个月后装不上了 | 依赖没锁死 |
| 发一个 `.exe` | 客户是 Mac | 目标平台不对 |
| 发个 Jupyter notebook | 客户不知道哪个格子先跑 | 没有对外接口 |
| 发个能跑的网页，但按钮点两下扣两次钱 | 你赔钱 | 没有幂等 |

**这五种都不是"代码 bug"**，它们是**交付缺陷**。你这本书里已经写过很好的 Agent，
但一个"很好的 Agent"和一个"能交付的系统"之间，隔着这一整章。

### 42.2 真实的一次翻车记录

下面这段是我跑本章示例时**真的踩到的**，原样贴出来（41.7 会逐条解释）：

```
postgres-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/10-init.sql
postgres-1  | 2026-10-22 22:13:34.739 UTC [55] ERROR:  extension "vector" is not available
postgres-1  | HINT:  The extension must first be installed on the system where PostgreSQL is running.
postgres-1  | psql:/docker-entrypoint-initdb.d/10-init.sql:7: ERROR:  extension "vector" is not available
```

四行日志，但暴露了三层问题：

1. **`postgres:16-alpine` 里根本没有 pgvector** —— 官方镜像不带这个扩展
2. 建表语句**一条都没执行** —— `CREATE EXTENSION` 失败会让整个脚本中止
3. 但容器状态显示 **`(healthy)`** —— 因为 `pg_isready` 只检查"能不能连"，不检查"表在不在"

这就是本章要教的**核心能力**：分清"进程活着"、"服务能用"、"数据对"是三件不同的事。

---

## 42.2 为什么"写个函数"不够：Agent 对外只有三种形态

### 42.1 一句话

**Agent 对外的接口形态只有三种：同步（问完再答）、流式（边算边说）、异步任务（先收下，稍后来取）。选错一种，后面所有问题都会跟着来。**

### 42.2 三种形态长什么样

```
① 同步：调用 → 等着 → 一次拿到全部
POST /chat          {"q": "..."}  →  200  {"answer": "..."}

② 流式：调用 → 立刻开始收 → 一块一块到
POST /chat/stream   {"q": "..."}  →  200  text/event-stream
                                     event: delta / data: {"t": "退"}
                                     event: delta / data: {"t": "款"}
                                     event: done  / data: {}

③ 异步任务：调用 → 立刻返回任务号 → 自己去问
POST /jobs          {"q": "..."}  →  202  {"job_id": "job-1"}
GET  /jobs/job-1                  →  200  {"status": "running"}
GET  /jobs/job-1                  →  200  {"status": "done", "result": "..."}
```

### 42.3 怎么选：一张判据表

| 你的情况 | 该用 | 为什么不能用别的 |
|---|---|---|
| 答案 < 3 秒，用户在等 | **同步** | 用流式反而增加前端复杂度 |
| 答案 > 3 秒，但用户在看 | **流式** | 同步会让用户盯着空白屏幕 20 秒 |
| 任务 > 60 秒（建索引、批量审文档） | **异步任务** | 流式撑不住 60 秒，中间一断全丢 |
| 用户可能关页面，但活要干完 | **异步任务 + checkpoint** | 流式在客户端断开时就断了 |
| 需要中途展示进度（"正在检索第 3 篇"） | **流式（用 event 名区分进度和正文）** | 同步做不到 |

**最常犯的错：把一个 5 分钟的任务做成流式接口。**
用户一刷新页面，连接断掉，你会发现——**服务端还在跑，但没人在听**。
这既是浪费，也是"任务到底做完了没有"说不清的根源。

---

## 42.3 核心实现（逐行解释）：三种形态一起写

代码在 `code/ch42_integration/step1_api.py`。它**不依赖网络、不依赖真实模型**，
用一个"假模型"按块吐字，这样你看到的所有数字都是真测出来的。

### 运行

```powershell
python code/ch42_integration/step1_api.py
```

### 真实输出（节选）

```
① 同步接口 /chat
   状态码 200
   返回字段 ['answer', 'latency_ms', 'run_id']
   端到端 61.2 ms —— 用户在这段时间里屏幕是空白的

② 流式接口 /chat/stream（SSE）
   状态码 200  content-type text/event-stream; charset=utf-8
   收到 7 个 delta 块
   TTFT（首字）26 ms  vs  总耗时 152 ms
   用户感知提升 83%，但机器总工作量一模一样

③ 异步任务接口 /jobs（长任务用这个，不是流式）
   POST /jobs → 202（202 Accepted 而不是 200）
   job_id = job-1
   轮询后状态 = done，结果长度 = 51
```

### 逐条说三个关键点

#### ① 为什么 `run_id` 要放进响应体

```python
return ChatOut(answer=answer, run_id=f"run-{int(t0*1000)}", latency_ms=...)
```

因为用户报障时只会说"刚才那个回答不对"。**没有 `run_id`，你就只能靠时间戳猜**。
有了它，你能直接从 trace 存储（第 39 章那道 JSONL）里把整条链路捞出来。

> 这是"接口设计"里性价比最高的一件事：**多返回一个字段，省下几小时的排查**。

#### ② 为什么流式的 TTFT 提升 83%

```
TTFT（首字）26 ms  vs  总耗时 152 ms
```

机器一共吐了 7 块，干活的量和同步接口**完全一样**。
区别只在**什么时候把第一块给用户**。

> **用户感知的速度 = TTFT，不是总耗时。**
> 这句话在第 36 章（延迟工程）讲过；这里是它在接口层的落地。

#### ③ 为什么 SSE 的 `data` 必须是单行

```python
def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

SSE 的格式是"一行一个字段，空行表示一帧结束"。所以：

```
event: delta
data: 第一行
第二行          ← 客户端在这里懵了：这是字段名？还是内容？
```

**客户端会认为"第二行"是一个新字段名**，然后解析失败或静默丢弃。
所以内容里的换行必须被 `json.dumps` 转义掉（真换行变成两个字符 `\n`）。

### 💥 失败实验 1：流式中途抛异常，客户端会怎样

这是流式接口最危险的地方。先看**没有防护**的版本：

```python
def broken():
    yield sse("delta", {"t": "前半句"})
    raise RuntimeError("模型中途 500")

@app.post("/chat/stream-broken")
def broken_stream():
    return StreamingResponse(broken(), media_type="text/event-stream")
```

真实结果：

```
b) 流式中途抛异常 → 状态码仍然是 200（响应头早发出去了，改不了！）
   有 GuardedStream：客户端收到 ['event: delta', 'event: error'] —— 明确知道「后半截没了」
   没有 GuardedStream：客户端只看到半截，然后连接断掉 —— 模型中途 500
```

**为什么状态码改不了？** 因为 HTTP 的响应头在**第一块数据发出时就已经写死了**。
后面无论发生什么，你都没有办法把它改成 500。

于是客户端看到的画面是：文字出来一半，然后**永远停在那里**。
用户不知道是"模型还在想"，还是"已经挂了"。

#### 修法：流式接口必须自己写 error 帧

```python
class GuardedStream(StreamingResponse):
    async def stream_response(self, send):
        try:
            await super().stream_response(send)
        except Exception as e:
            await send({
                "type": "http.response.body",
                "body": sse("error", {"msg": f"{type(e).__name__}: {e}"}).encode(),
                "more_body": False,
            })
```

以及生成器内部也要兜一层（业务语义层）：

```python
def gen():
    n = 0
    try:
        for piece in fake_llm(req.q):
            n += 1
            yield sse("delta", {"i": n, "t": piece})
    except Exception as e:
        yield sse("error", {"msg": f"{type(e).__name__}: {e}", "after_chunks": n})
        return
    yield sse("done", {"chunks": n})
```

**两层都要有**，因为：

| 层 | 兜住什么 | 不给会怎样 |
|---|---|---|
| 生成器里 `try` | 模型调用抛的错 | 能给出"已经吐了几块"，客户端知道要不要重试 |
| `GuardedStream` | 生成器之外（序列化、发送）抛的错 | 连接直接断，客户端只看到半截 |

> ⚠️ **一个必须知道的坑**：如果你只写了生成器里的 `try`，
> 在真实 uvicorn 下"看起来能用"；但一旦异常发生在**发送阶段**（比如客户端断开），
> 你会看到一堆 `Task exception was never retrieved`。`GuardedStream` 就是为了把这最后一段路封住。

### 💥 失败实验 2：同步接口里用 `time.sleep` 阻塞事件循环

```python
@app.post("/chat")
async def chat(req):          # ← async def
    time.sleep(3)             # ← 但里面用同步 sleep
    ...
```

**后果**：这个进程一次只能处理**一个**请求。10 个并发请求，总耗时约等于串行 10 次。

| 写法 | 10 并发耗时（每次 300ms） | 原因 |
|---|---|---|
| `async def` + `time.sleep` | ≈ 3000 ms | 唯一的事件循环线程被 sleep 卡住 |
| `async def` + `await asyncio.sleep` | ≈ 300 ms | 让出控制权，10 个同时跑 |
| `def`（普通函数） | ≈ 300~900 ms | FastAPI 会自动丢到线程池 |

**三句话记住**：

1. `async def` 里**只放** `await` 的东西
2. 一定会阻塞的（文件 IO、`requests`、`time.sleep`）→ 用普通 `def`，让框架丢线程池
3. 或者显式 `await asyncio.to_thread(fn)` 包一层

### 接口契约：把"必须满足什么"写成断言

```
⑤ 契约检查：把「接口必须满足什么」写成断言
   OK  状态码 200
   OK  含 answer 字段
   OK  含 run_id（能拿它去查 trace）
   OK  响应体是 JSON 而不是纯文本
   OK  空输入被拦成 422（不是 500）
```

这五条应该**直接抄进你的 `tests/`**。它们是"接口没被改坏"的最小防线。

---

## 42.4 流式接口的完整实现（SSE 六件套）

上一节讲了"为什么"，这一节讲"完整的怎么写"。SSE 接口有六个必须做对的地方，
少任何一个，你都会在某个客户那里翻车。

### 42.1 六件套清单

| # | 必须做 | 不做会怎样 |
|---|---|---|
| 1 | `media_type="text/event-stream"` | 浏览器当成普通 JSON 缓存住，不流式 |
| 2 | `Cache-Control: no-cache` | 中间代理缓存第一帧，后续全丢 |
| 3 | `X-Accel-Buffering: no` | **nginx 默认缓冲**，SSE 会攒成一大坨才吐 |
| 4 | `event:` 名字区分语义 | 前端分不清"进度"和"正文" |
| 5 | `error` 帧 | 中间挂了客户端不知道（见失败实验 1） |
| 6 | 服务端主动断开检测 | 用户关页面后你还在烧钱 |

### 42.2 第 3 条为什么最容易漏

nginx 默认开启 `proxy_buffering`。它的逻辑是"我先攒着，攒够一个 buffer 再转发"。
对普通网页这是优化；**对 SSE 是灾难**——你的 20 个 delta 会一次性到客户端，
TTFT 从 26ms 变回 150ms，流式的意义全没了。

两个地方都要关：

```python
# ① 应用层：告诉所有中间代理别缓冲
return StreamingResponse(gen(), media_type="text/event-stream",
                         headers={"Cache-Control": "no-cache",
                                  "X-Accel-Buffering": "no"})
```

```nginx
# ② nginx 层：显式关掉
location /chat/ {
    proxy_pass http://agent_api;
    proxy_http_version 1.1;
    proxy_buffering off;      # ← 命门
    proxy_cache off;
    proxy_read_timeout 3600s; # ← SSE 会开很久，默认 60s 会被切断
    chunked_transfer_encoding on;
}
```

> 本章示例里 `examples/full-stack/frontend/nginx.conf` 就是这么写的。
> 我在真实环境里验证过：**经 nginx 代理后仍然是逐帧到达**，不是攒成一坨。

### 42.3 第 6 条：客户端断开时你还在烧钱

这是最容易被忽视的成本漏洞。真实测过：用户点了发送，看了两秒觉得不对，关掉页面。
**你的服务端会继续跑完整个流程**——检索 5 次、调模型 3 次，全都白花钱。

```python
async def gen():
    try:
        async for piece in fake_llm(req.q):
            yield sse("delta", {"t": piece})
    finally:
        # 客户端断开时 Starlette 会 cancel 这个生成器，
        # 这里的 finally 就是你的"止损点"
        track_inflight(-1)
        log.info("stream closed early")
```

关键在 `finally`：它在**被取消**时也会执行。所以：

1. 计费减一
2. 记录"提前断开"（这是产品指标，不是错误）
3. 如果有正在跑的模型调用，取消它

> ✏️ **停下来想一想**：如果"提前断开"的比例达到 40%，说明什么？
> 提示：先看 TTFT，再看第一句话的内容。

---

## 42.5 队列、幂等、限流、鉴权：四件"上线前必须做"的事

代码在 `code/ch42_integration/step2_queue.py`。全部离线、纯标准库。

### 运行

```powershell
python code/ch42_integration/step2_queue.py
```

### 42.1 队列：为什么"出队即删"是错的

```
① 「出队即删」 vs 「可见性超时」
   出队即删：剩余 0 条 → 这个任务永久丢失
   可见性超时：第一次取到 m-1，未 ack，消费者崩了
               重新投递 → 又取到 m-1，attempts=2
               ack 之后剩余 ready=0 inflight=0
   代价：任务可能被执行两次 → 所以必须有幂等键（见 ②）
```

**这就是"至少一次"（at-least-once）语义**。几乎所有真实队列（SQS、Redis Stream、Kafka）都是这个语义，
因为"恰好一次"在分布式下**做不到**（这是理论结论，不是工程懒）。

所以你必须接受：**同一条消息会被处理两次**。然后靠幂等键把它变回"一次"。

### 42.2 死信：一条永远失败的消息会占死队列

```
② 死信队列：一条永远失败的消息会怎样
   ready=0  inflight=0  dead=1
   死信里的消息 attempts=3
   注意：如果没有 max_attempts，这条消息会无限重投，把 worker 全部占死
```

**为什么"无限重试"比"失败"更危险？**
因为失败你会看到、会处理；无限重试只是让队列**慢慢变慢**，
直到某天你发现所有 worker 都在忙同一批死消息。

### 42.3 幂等：key 必须由客户端生成

```
③ 幂等键：重投的消息真的只算一次钱
   调用 → sent#1   cached=False
   调用 → sent#1   cached=True
   调用 → sent#1   cached=True
   实际执行业务函数 1 次，发出邮件 1 封
```

### 💥 失败实验 3：服务端生成幂等键 = 完全没有幂等

```
   💥 失败实验：key 由服务端生成会怎样
   服务端每次生成新 key → 执行了 3 次，幂等完全失效
```

这条极其常见：很多人写 `key = uuid.uuid4()`，觉得"我有幂等表了"。
实际上每次请求都生成新 key，幂等表**永远是空的**。

**三个必须想清楚的细节**：

| 细节 | 正确做法 | 错误做法 |
|---|---|---|
| key 从哪来 | **客户端生成**（用业务 ID 派生，如 `refund-8831`） | 服务端 `uuid4()` |
| key 存多久 | ≥ 最大重试窗口，常见 24h | 永久保存（表会爆） |
| 并发同 key | `SET NX`，一次只让一个进来 | "先查再写"（有竞态，两个都执行） |

### 42.4 限流：令牌桶 vs 固定窗口

```
④ 限流：令牌桶 vs 固定窗口（同样 20 req/s 的额度）
   令牌桶：瞬时打 60 个请求，放过 20 个（桶容量 20，符合预期）
   固定窗口：同样的 60 个请求，放过 20 个
   令牌桶用完 → allowed=False，建议客户端等 1.00s（可以写进 Retry-After 头）
```

**关键区别在窗口边界**：固定窗口在 59 秒放过 20 个、61 秒又放过 20 个，
于是 **2 秒内 40 个**，瞬时翻倍。令牌桶按速率补充，没有这个问题。

**必须做的一件事**：拒绝时返回 `Retry-After`。
不给这个头，客户端只能瞎猜着重试——然后被你继续拒。

### 42.5 鉴权：401 和 403 必须分开

```
⑤ 鉴权：401 和 403 必须分开
   没带 key             → HTTP 401  tenant=-      缺少 Authorization 头
   错 key              → HTTP 401  tenant=-      API key 无效
   key 对但没权限          → HTTP 403  tenant=-      已认证但缺少 scope index:write（当前 ['chat:read']）
   key 对且有权限          → HTTP 200  tenant=acme   ok
```

**为什么要分开？**

| 状态码 | 含义 | 用户该怎么办 |
|---|---|---|
| 401 | 你是谁我不知道 | 换 key |
| 403 | 我知道你是谁，但你没这个权限 | **找管理员要权限** |

混成一个，用户会一直换 key——**而问题根本不在 key 上**。

### 💥 失败实验 4：tenant 从请求体里取 = 跨租户泄露

```
   💥 失败实验：tenant 从请求体里取
   key 属于 acme，但请求体声称 globex → 实际按 globex 查数据
   → 跨租户数据泄露。tenant 只能从凭证推导，永不接受客户端输入
```

这一条和第 40 章（数据层多租户）是同一个问题的两端：
**服务端只在"凭证"里信任租户，永远不从"参数"里读租户。**

### 42.6 四件事串起来

```
⑥ 四件事串起来：一次「退款通知」任务的完整生命周期
   请求1 限流=过
   请求2 限流=过
   请求3 限流=过
   消费 m-1 attempts=1 → notified cached=False
   消费 m-2 attempts=1 → notified cached=True
   消费 m-3 attempts=1 → notified cached=True
   最终：业务只执行 1 次，3 条消息全部 ack
```

**读这张图的正确姿势**：3 个请求（可能来自用户狂点）→ 3 条消息 → 3 次消费 →
但业务只执行 1 次。**这就是"用户感知的快"和"你不赔钱"同时成立的样子。**

---

## 42.6 Docker 角色 A：镜像分层、多阶段构建与体积

先澄清一件事：**Docker 在本书里有两个完全不同的角色**，别搞混。

| 角色 | 是什么 | 在哪一章 |
|---|---|---|
| **角色 B：安全沙箱** | 用容器隔离 Agent 的**代码执行**，防它删文件、访问内网 | 第 33 章（已讲） |
| **角色 A：环境打包与编排** | 把 Agent、DB、缓存、向量库、观测打成镜像并编排起来交付 | **本章** |

角色 B 关心的是"别让它干坏事"；角色 A 关心的是"**客户那边能起来**"。
同一个工具，两种目的，不要混为一谈。

代码在 `code/ch42_integration/step3_docker.py`。它**不需要 Docker**——
用纯 Python 模拟了"层缓存"和"镜像大小"，因为这两件事完全可以用算术说清楚。

### 运行

```powershell
python code/ch42_integration/step3_docker.py
```

### 42.1 真实输出：改一行代码要等多久

```
① 镜像分层：改一行 Python 代码要等多久

   A 一次性 COPY           改源码后重建   96.0s   镜像   772 MB
   B 先装依赖               改源码后重建    1.0s   镜像   772 MB
   C 多阶段（层写错）           改源码后重建    2.0s   镜像   847 MB
   C' 多阶段（合并层）          改源码后重建    1.0s   镜像   729 MB

   典型新手镜像 1922 MB（含 torch 900MB + 模型 250MB）→ 729 MB：砍掉 62%
   只算 Python 依赖这一层：772 MB → 729 MB，砍掉 6%
```

**看第一列的时间**：同样是改一行 Python 代码，A 要 96 秒，B 只要 1 秒。**差 96 倍**。

### 42.2 为什么差 96 倍：逐层明细

```
   逐层明细（写法 A，改源码）：
      CACHED  FROM python:3.12               150.0 MB
      REBUILD  COPY . /app                      2.0 MB
      REBUILD  RUN pip install -r req.txt     620.0 MB
```

```
   逐层明细（写法 B，改源码）：
      CACHED  FROM python:3.12               150.0 MB
      CACHED  COPY requirements.txt            0.0 MB
      CACHED  RUN pip install -r req.txt     620.0 MB
      REBUILD  COPY . /app                      2.0 MB
```

**Docker 层缓存的唯一规则**：**某一层的输入变了，这一层和它之后的所有层全部失效。**

写法 A 里，`COPY . /app` 在 `pip install` **前面**。
所以你改一行代码 → `COPY` 层失效 → **后面所有层都失效** → 重新 `pip install` → 96 秒。

写法 B 把 `requirements.txt` 单独先 COPY。只改源码时，`requirements.txt` 没变 →
`pip install` 层仍然是 CACHED → 只重建最后一层 → 1 秒。

```dockerfile
# 写法 B：正确的顺序
FROM python:3.12-slim
WORKDIR /app
COPY app/requirements.txt .          # ← 依赖清单单独拷
RUN pip install -r requirements.txt  # ← 只有清单变了才重跑
COPY app/ ./app                      # ← 源码最后拷
```

> **一句话记住**：**变化越频繁的放越后面。**

### 💥 失败实验 5：多阶段构建写错了，镜像反而更大

```
   C 多阶段（层写错）           改源码后重建    2.0s   镜像   847 MB
   C' 多阶段（合并层）          改源码后重建    1.0s   镜像   729 MB
```

**C 比 B 还大 75 MB**——明明用了多阶段 + slim 基础镜像，为什么反而更大？

原因：我当时把 `COPY --from=builder /install /usr/local` 和
`RUN rm -rf /usr/local/lib/python3.12/site-packages/*.dist-info` 写成了**两层**。

Docker 每一层都是**对上一层的完整快照**。`COPY` 那层让镜像胖了 240 MB；
`rm` 那层虽然删了东西，**但删除本身也是一层**——旧层的 240 MB 还在。

合并成一层之后：

```dockerfile
# 错误：分两层
COPY --from=builder /install /usr/local
RUN rm -rf /usr/local/lib/python3.12/site-packages/*.dist-info

# 正确：一层搞定
COPY --from=builder /install /usr/local
# 或者在 builder 阶段就把该删的删掉，runtime 只 COPY 干净结果
```

> **一句话记住**：**镜像里"删东西"不会让镜像变小**，除非删除和添加在同一层。

### 42.3 镜像为什么 2 GB：把体积算给你看

```
② 镜像为什么 2 GB：把体积算给你看
   python:3.12 基础镜像                      150 MB    7.8%
   pip 装的所有依赖                            620 MB   32.3%
   torch（如果你不小心装了 CPU 版）                 900 MB   46.8%
   模型文件误打进镜像                             250 MB   13.0%
   源码与静态资源                                 2 MB    0.1%
   合计                                   1922 MB

   → 前三项占 87%。能砍的：slim 基础镜像、去掉 torch（不需要就别装）、
     模型文件用 volume 挂载或启动时下载
```

四个能立刻见效的动作：

| 动作 | 省多少 | 代价 |
|---|---|---|
| `python:3.12` → `python:3.12-slim` | ~105 MB | 没有 gcc，编译型依赖要放 builder 阶段 |
| 不装 `torch`（用远程 API 就别装） | ~900 MB | — |
| 模型文件用 volume / 启动时下载 | ~250 MB | 首次启动慢 |
| `.dockerignore` 排除 `.venv`、`.git` | 常常 500 MB+ | 无 |

### 42.4 `.dockerignore`：最大的单点收益

很多人不知道：`docker build` 会先把**整个目录**打包发给 daemon。
如果你的仓库里有 `.venv`（几百 MB）、`.git`（几百 MB）、`node_modules`，
**每次 build 都要传一遍**——即使你 `COPY` 的只有 `app/`。

```dockerignore
# 版本库与 IDE
.git
.vscode
.idea

# Python 缓存与虚拟环境（虚拟环境动辄几百 MB，绝不能进镜像）
**/__pycache__
**/*.pyc
.venv
venv
.pytest_cache
.ruff_cache

# 本地密钥（!!! 最重要 !!!）
.env
.env.*
!.env.example
*.pem
*.key

# 模型与数据（应该挂 volume 或启动时下载）
models/
*.bin
*.safetensors
*.gguf
data/
*.sqlite

# 文档（运行镜像里不需要 markdown 源码）
*.md
docs/
examples/
```

### 💥 失败实验 6：把 `.env` COPY 进镜像

```
   💥 失败实验：把 .env 也 COPY 进去
   · .env 里的密钥被烘焙进镜像层 → docker history 能看到明文
   · 就算后来删掉（RUN rm .env），旧层还在 —— 镜像里能捞回来
```

**这是本书最严重的安全问题之一**。Docker 镜像层是**不可变的历史记录**：

```bash
docker history my-image:latest        # 能看到每一层的命令
docker save my-image > img.tar        # 导出后解压，能逐层翻出被删的文件
```

只要 `.env` 曾经在某层出现过，**任何人拿到镜像都能把密钥捞回来**——哪怕你后面删了。

**唯一正确的做法**：**密钥从来不进镜像**，只在运行时通过环境变量或 secrets 注入。

```yaml
# docker-compose.yml
services:
  agent-api:
    env_file: [.env]        # 运行时挂进去，不参与构建
```

---

## 42.7 用起来：7 个服务的完整编排（真跑通的）

这一节的 YAML **不是"看起来对"**——我真的 `docker compose up` 起过，
并且每个服务都验证到 `(healthy)`。文件在 `examples/full-stack/`。

### 42.1 服务清单

```
agent-api     FastAPI，暴露 /chat /chat/stream /jobs /healthz /readyz
worker        长任务消费者（独立进程、独立扩缩容）
postgres      业务数据 + 会话状态（pgvector 镜像）
redis         队列 + 缓存
vector-db     qdrant（可选，pgvector 也能替代）
langfuse      可观测平台
frontend      nginx，静态页 + 反代 SSE
```

### 42.2 真实启动记录

```
 Container fullstack-agent-postgres-1 Started
 Container fullstack-agent-redis-1 Started
 Container fullstack-agent-vector-db-1 Started
 Container fullstack-agent-postgres-1 Healthy
 Container fullstack-agent-redis-1 Healthy
 Container fullstack-agent-vector-db-1 Healthy
 Container fullstack-agent-agent-api-1 Started
 Container fullstack-agent-worker-1 Started
 Container fullstack-agent-frontend-1 Started
 Container fullstack-agent-langfuse-1 Started
```

最终状态（**我实测的，7 个全部 healthy**）：

```
NAME                          STATUS
fullstack-agent-agent-api-1   Up 4 minutes (healthy)
fullstack-agent-frontend-1    Up 4 minutes
fullstack-agent-langfuse-1    Up About a minute (healthy)
fullstack-agent-postgres-1    Up 4 minutes (healthy)
fullstack-agent-redis-1       Up 4 minutes (healthy)
fullstack-agent-vector-db-1   Up 4 minutes (healthy)
fullstack-agent-worker-1      Up 4 minutes (healthy)
```

冷启动到核心服务全部 healthy：**实测 15 秒**（镜像已在本地）。

### 42.3 第 1 条：`depends_on` 只保证容器"起来了"

这是最容易踩的坑。先用模拟代码说清楚：

```
③ 健康检查：depends_on 只保证「容器起来了」，不保证「能用了」
   t=0.0s  docker compose up：postgres 容器状态 = running
   t=0.0s  agent 启动 → 尝试连 DB 建表
   t=0.0s  ❌ 连接被拒（DB 还要 2.0s 才能接受连接）
           容器退出 → depends_on 默认不会重试 → 整个服务起不来

   重试版：第 1 次（t=0.0s）失败，等 1s 再试
   重试版：第 2 次（t=1.0s）失败，等 1s 再试
   重试版：第 3 次（t=2.0s）连接成功 ✅
```

`postgres` 容器状态是 `running` 的**那一刻**，它还不能接受连接——
它正在 `initdb`、正在起 WAL recovery。这个窗口通常 1~10 秒。

**正确写法**：

```yaml
  agent-api:
    depends_on:
      postgres:
        condition: service_healthy    # ← 不是 service_started
```

并且依赖方**必须**有 healthcheck：

```yaml
  postgres:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agent -d agent"]
      interval: 5s
      timeout: 3s
      retries: 10
```

### 42.4 第 2 条：healthcheck 写错了，"明明起来了"却一直 starting

这是我这次**真实踩到的**坑，值得完整记录：

```
$ docker compose ps
fullstack-agent-langfuse-1    Up About a minute (health: starting)
```

但宿主机访问 `http://localhost:3000/api/public/health` 返回 **200 OK**。
网站能用，健康检查说不行。为什么？

在容器里试：

```
$ docker compose exec langfuse sh -c "wget -qO- http://127.0.0.1:3000/api/public/health"
wget: can't connect to remote host: Connection refused

$ docker compose exec langfuse sh -c "wget -qO- http://localhost:3000/api/public/health"
wget: can't connect to remote host: Connection refused

$ docker compose exec langfuse getent hosts localhost
::1               localhost  localhost
```

**三层原因叠加**：

1. langfuse 里的 Next.js 只监听**容器主机名**，不监听 `0.0.0.0`
2. 容器里的 `localhost` 解析成 `::1`（IPv6），而服务只监听 IPv4
3. 所以 `127.0.0.1` 和 `localhost` 都是拒连

**修法**：用容器主机名探活。

```yaml
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://$(hostname):3000/api/public/health >/dev/null 2>&1 || exit 1"]
```

改完之后：

```
fullstack-agent-langfuse-1    Up About a minute (healthy)
```

> **这个坑的通用教训**：健康检查的 URL **必须和服务的实际监听地址一致**。
> 排查时先 `docker compose exec <svc> getent hosts localhost`，
> 再看服务日志里它到底 bind 在哪个地址。

### 42.5 第 3 条：`pgvector` 不在官方 postgres 镜像里

回到 41.1.2 那段真实日志。修法是换镜像：

```yaml
  postgres:
    # 必须是 pgvector/pgvector 而不是官方 postgres —— 官方镜像没有 vector 扩展
    image: pgvector/pgvector:pg16
```

改完验证：

```
$ docker compose exec -T postgres psql -U agent -d agent -c "\dt"
           List of relations
 Schema |     Name      | Type  | Owner
--------+---------------+-------+-------
 public | chat_sessions | table | agent
 public | documents     | table | agent
 public | jobs          | table | agent
(3 rows)
```

**三个表都在了**。而失败时这里是 `Did not find any relations.`

### 💥 失败实验 7：`CREATE EXTENSION` 失败会中止整个 init 脚本

`init.sql` 里的顺序很关键：

```sql
-- 错误：先建库，后面出错了
CREATE DATABASE langfuse;
CREATE EXTENSION IF NOT EXISTS vector;   -- ← 这里失败
CREATE TABLE documents (...);            -- ← 永远执行不到
```

`psql` 默认 `ON_ERROR_STOP` 未开，但 **`docker-entrypoint-initdb.d` 里的脚本出错会中止整个入口流程**。
所以你看到的现象是：**容器 healthy，但一张表都没有**。

**修法两条**（我两条都做了）：

1. 把可能失败的语句放最前面，让它**早点失败**
2. 建表语句全部加 `IF NOT EXISTS`，便于重跑

```sql
-- 正确：最容易失败的放最前
CREATE EXTENSION IF NOT EXISTS vector;
CREATE DATABASE langfuse;
CREATE TABLE IF NOT EXISTS documents (...);
```

> ⚠️ **还有一条必须知道的**：`init.sql` **只在数据卷为空时执行一次**。
> 改了 SQL 要看效果，必须 `docker compose down -v`（`-v` 才会删卷）。
> 这一条我一开始也忘了，改了 SQL 死活不生效，浪费了十几分钟。

### 42.6 第 4 条：数据卷 —— 状态不能留在容器里

```
这是容器和虚拟机的核心区别：
  容器删了，里面的文件全没了。
```

所以下面这些**必须**放在 named volume 里：

| 东西 | 放哪 | 不放会怎样 |
|---|---|---|
| postgres 数据 | `pgdata:/var/lib/postgresql/data` | `docker compose down` 后数据全丢 |
| redis AOF | `redisdata:/data` | 重启后队列里所有任务消失 |
| qdrant 索引 | `qdrantdata:/qdrant/storage` | 每次重建索引，白花钱 |
| 日志 | 挂到宿主机或送到外部 | 出问题时日志早没了 |

```yaml
volumes:
  pgdata:
  redisdata:
  qdrantdata:
```

### 42.7 第 5 条：配置与密钥注入

三条铁律：

1. `.env` **永远**在 `.gitignore` 和 `.dockerignore` 里
2. 镜像里**不放**任何密钥（见失败实验 6）
3. 仓库里只放 `.env.example`，且里面的值都是 `change-me`

```yaml
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql://agent:${POSTGRES_PASSWORD}@postgres:5432/agent
```

> **为什么用 `${POSTGRES_PASSWORD}` 而不是直接写死？**
> 因为 compose 文件是**进版本库**的，`.env` 不进。
> 这样"怎么配置"（compose 文件）和"配置成什么"（.env）就分开了——
> 同一个 compose 文件可以部署到测试环境和生产环境。

### 💥 失败实验 8：`env_file` 写了但没生效

我这次遇到的现象：

```
容器里 POSTGRES_PASSWORD 是 change-me-please
但我明明改过 .env
```

原因是：**我改了 compose 文件但只做了 `docker compose up -d`（没加 `--build`）**，
而 compose 只重建了配置变了的容器。改 `.env` 本身**不会**触发容器重建。

**正确做法**：

```powershell
docker compose up -d --force-recreate agent-api   # 强制重建这个容器
```

**判断当前容器里实际生效的环境变量**：

```powershell
docker compose exec agent-api env | Select-String POSTGRES
```

> 一条通用原则：**容器里的一切都来自"构建时"或"启动时"的快照。**
> 改了源文件、改了 .env、改了 compose——都要明确知道"我这次改动需要重建什么"。

---

## 42.8 优雅关闭：`docker stop` 时手上的活怎么办

这是最容易被跳过、也最容易在客户那里出事的一节。

### 42.1 三种结局

```
④ 优雅关闭：SIGTERM 时 Agent 手里有任务怎么办
   docker stop 默认等 10 秒然后 SIGKILL。
   如果一个长任务要跑 40 秒：
   · 直接退出                                             → 任务丢了，且没有 checkpoint → 用户重跑要重头再来
   · 等 10 秒（默认）                                       → 被 SIGKILL，同上
   · 收到 SIGTERM 后写 checkpoint，然后退出                    → 重启后从 checkpoint 续跑，用户无感
   · 收到 SIGTERM 后拒新请求 + 等当前任务（stop_grace_period: 60s） → 任务完整跑完
```

### 42.2 真实日志：优雅关闭是什么样子

我在容器里 `docker compose stop agent-api`，日志是这样的：

```
agent-api-1  | [startup] LLM_MODE=fake pid=1
agent-api-1  | INFO:     Application startup complete.
agent-api-1  | [shutdown] 停止接新任务，等待 inflight=0 完成…
agent-api-1  | [shutdown] 完成，剩余 inflight=0
agent-api-1  | INFO:     Waiting for application shutdown.
agent-api-1  | INFO:     Application shutdown complete.
agent-api-1  | [signal] 收到 SIGTERM，进入优雅关闭
```

停止总耗时 **1 秒**（没有在手任务时就应该这么快）。

> 注意最后一行 `[signal]` 在日志里的**位置**：它出现在 shutdown 之后。
> 这是因为 uvicorn 自己先处理了 SIGTERM，我们的 handler 是第二个收到的。
> **这不影响功能**（两条路径都会置 `SHUTTING_DOWN = True`），
> 但如果你只依赖自己的 handler 做"拒新请求"，会有一个极短的窗口漏进请求。

### 42.3 代码：优雅关闭的三块拼图

```python
# ① 中间件：关闭中拒绝新请求（但放行探针）
@app.middleware("http")
async def reject_while_shutting_down(request, call_next):
    if SHUTTING_DOWN and request.url.path not in ("/healthz", "/readyz"):
        return JSONResponse({"detail": "server is shutting down"}, status_code=503)
    return await call_next(request)
```

```python
# ② lifespan：等手上的活干完
@asynccontextmanager
async def lifespan(app):
    worker = asyncio.create_task(job_worker())
    yield
    global SHUTTING_DOWN
    SHUTTING_DOWN = True
    worker.cancel()
    deadline = time.time() + float(os.getenv("SHUTDOWN_GRACE", "8"))
    while INFLIGHT > 0 and time.time() < deadline:
        await asyncio.sleep(0.05)
```

```yaml
# ③ compose：给它足够的时间
  agent-api:
    stop_grace_period: 40s    # docker stop 默认只等 10s
```

```dockerfile
# ④ Dockerfile：用 exec 形式，让 SIGTERM 直达 uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000",
     "--timeout-graceful-shutdown", "20"]
```

### 💥 失败实验 9：`CMD uvicorn ...` 是 shell 形式，SIGTERM 收不到

```dockerfile
# 错误：shell 形式
CMD uvicorn main:app --host 0.0.0.0 --port 8000
```

这一行会被 Docker 变成：

```
/bin/sh -c "uvicorn main:app --host 0.0.0.0 --port 8000"
```

于是进程树是：

```
PID 1  /bin/sh -c "uvicorn ..."
  └─ PID 7  uvicorn
```

`docker stop` 发的 SIGTERM 只发给 **PID 1**（那个 sh）。
**sh 默认不转发信号**，于是 uvicorn 永远收不到 SIGTERM →
10 秒后被 SIGKILL → **你写的所有优雅关闭代码一行都没跑**。

**修法**：exec 形式（JSON 数组），这样 uvicorn 直接是 PID 1。

```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

> 这个坑极隐蔽：**代码是对的，日志也是对的，只是那行日志永远不会出现**。
> 排查方式：`docker compose exec agent-api ps -ef` 看 PID 1 到底是谁。

### 42.4 健康检查的两条线：`/healthz` 和 `/readyz`

这两个**不是同一个东西**，混用会导致"服务明明好着却被重启"或"依赖挂了还在接流量"。

| 端点 | 回答的问题 | 挂了怎么办 |
|---|---|---|
| `/healthz`（liveness） | 进程还活着吗？ | **重启**（进程卡死了） |
| `/readyz`（readiness） | 依赖都通吗？能接流量吗？ | **摘流量**（不重启） |

```python
@app.get("/healthz")
def healthz():
    # 只回答"我还在"。依赖挂了也算活着——重启没用！
    return {"ok": True, "uptime_s": round(time.time() - STARTED_AT, 1)}

@app.get("/readyz")
async def readyz():
    deps = await asyncio.gather(
        check_dependency("postgres", os.getenv("DATABASE_URL")),
        check_dependency("redis", os.getenv("REDIS_URL")),
        check_dependency("vector", os.getenv("VECTOR_URL")),
    )
    ok = all(d["ok"] for d in deps) and not SHUTTING_DOWN
    return JSONResponse({"ok": ok, "inflight": INFLIGHT, "deps": deps},
                        status_code=200 if ok else 503)
```

真实返回（3 个依赖全部连通时）：

```json
{"ok":true,"inflight":0,"deps":[
  {"name":"postgres","ok":true,"detail":"tcp ok"},
  {"name":"redis","ok":true,"detail":"tcp ok"},
  {"name":"vector","ok":true,"detail":"tcp ok"}]}
```

> **为什么 `/healthz` 不查依赖？** 因为 DB 挂了，重启 API 毫无用处——
> 只会让本来还能返回缓存的实例也一起挂掉。**重启是治"进程死了"，不是治"依赖死了"。**

---

## 42.9 三个小练习（从易到难）

### 练习 1（5 分钟）：改一个参数，看 TTFT

把 `step1_api.py` 里 `fake_llm` 的 `delay` 从 `0.02` 改成 `0.2`，重跑。

**你要回答**：TTFT 和总耗时各变成多少？为什么 TTFT 只涨了 10 倍，而"用户感知提升"的百分比几乎没变？

### 练习 2（20 分钟）：给你的 Agent 加一个 `/readyz`

拿你之前任何一章的 Agent（比如第 18 章 ReAct），加两个端点：

- `/healthz` 只返回 `{"ok": true}`
- `/readyz` 检查"模型 API 能不能连上"（用一个 2 秒超时的 GET）

**验收**：把网断掉，`/healthz` 仍返回 200，`/readyz` 返回 503。

### 练习 3（30 分钟，💥 故意破坏）

在 `examples/full-stack/` 里做三件事，每件都要**先预测再验证**：

1. 把 `Dockerfile` 的 `CMD` 改成 shell 形式，重跑 `docker stop`，观察优雅关闭日志**是否消失**
2. 把 `postgres` 镜像改回 `postgres:16-alpine`，`down -v` 后重来，观察 `\dt` **是否为空**
3. 把 `agent-api` 的 `depends_on` 改成 `condition: service_started`，反复 `down` / `up` 十次，
   记录**几次失败**（这就是"偶发启动失败"的真相）

---

## 42.10 常见错误速查

| 症状 | 真实原因 | 修法 | 本节 |
|---|---|---|---|
| 客户那边 `pip install` 报错 | 没交付环境 | 用镜像 | 41.6 |
| 点两下扣两次钱 | 没有幂等键 | 客户端生成 key | 41.5.3 |
| 点发送转圈 40 秒 | 长任务用了同步接口 | 改流式或异步任务 | 41.2.3 |
| 流式"不流式"，一起蹦出来 | nginx 缓冲 | `proxy_buffering off` | 41.4.2 |
| 流式中途断了，客户端不知道 | 没写 error 帧 | `GuardedStream` + 生成器 try | 41.3 |
| 改一行代码要等 1 分钟 | `COPY` 在 `pip install` 前面 | 依赖清单先拷 | 41.6.2 |
| 镜像 2 GB | 基础镜像 + torch + 模型 | slim、多阶段、volume | 41.6.3 |
| 镜像里能捞到密钥 | `.env` 被 COPY 进层 | 密钥只在运行时注入 | 41.6.4 |
| `depends_on` 了还是起不来 | 只等"容器启动" | `condition: service_healthy` | 41.7.3 |
| 健康检查一直 `starting` | 探针地址和服务监听地址不一致 | 用 `$(hostname)` | 41.7.4 |
| 改了 `init.sql` 不生效 | 卷非空，脚本不重跑 | `down -v` | 41.7.5 |
| `docker stop` 后任务丢了 | shell 形式 CMD，信号收不到 | exec 形式 | 41.8.3 |
| 依赖挂了却被反复重启 | 用 `/healthz` 查了依赖 | 拆 liveness / readiness | 41.8.4 |

---

## 42.11 章末自测

1. 一个"建 500 篇文档索引"的接口，应该用同步、流式还是异步任务？为什么另外两种不行？
2. 你的流式接口返回了 `200`，但客户端说"只收到半句话"。请说出至少两个可能原因。
3. 为什么幂等键必须由客户端生成？如果服务端用 `uuid4()` 会怎样？
4. "至少一次"语义为什么没法改成"恰好一次"？工程上怎么把它变回"一次"？
5. 改一行 Python 代码，镜像重建要 96 秒。请说出至少两个可能原因，以及怎么验证。
6. 为什么"在 Dockerfile 里 `RUN rm .env`"不能真正删除密钥？
7. `depends_on: [postgres]` 和 `depends_on: {postgres: {condition: service_healthy}}` 有什么区别？
   后者依赖什么前提？
8. `/healthz` 返回 200 但 `/readyz` 返回 503，说明什么？该重启还是该摘流量？
9. `docker stop` 之后你的优雅关闭日志没出现。请说出最可能的原因和验证方法。
10. 你部署了一套系统，客户说"偶尔第一次打开会报 500，刷新一下就好了"。你的第一反应查什么？

---

## 42.12 可选补课（可以先跳过）

> 这一节**可以先跳过**，等你要真正私有化交付时再回来。
> 跳过不影响你理解本章主线。

### 42.1 私有化交付的额外三件事

给客户部署到你控制不了的环境时，会多出三件事：

| 事情 | 为什么难 | 常见做法 |
|---|---|---|
| **离线安装** | 客户机器不能上网，拉不到镜像 | `docker save` 打包 → 拷过去 → `docker load` |
| **端口冲突** | 客户机器上 8080/3000 常被占用 | 全部端口变量化（本章示例已做） |
| **版本升级** | 客户数据不能丢 | 镜像打版本号 + 数据库迁移脚本（不能靠 `init.sql`） |

打包离线镜像：

```powershell
docker save fullstack-agent-api:local -o agent-api.tar
# 客户机器上
docker load -i agent-api.tar
```

### 42.2 为什么不一开始就上 Kubernetes

| | docker compose | Kubernetes |
|---|---|---|
| 学习成本 | 半天 | 几周 |
| 单机够用 | ✅ | 过度 |
| 自动扩缩 | ❌ | ✅ |
| 滚动升级 | 手写 | 内置 |

**判据**：**单机能撑住就不用 K8s。** 一个日均 1 万次调用的 Agent 服务，
一台 8 核 16G 的机器足够——上 K8s 只会让你花时间在 YAML 上，而不是在产品上。

什么时候该上：多台机器、要求零停机升级、需要按队列积压自动扩容。

### 42.3 Qdrant vs pgvector：怎么选

| | pgvector | Qdrant |
|---|---|---|
| 少一个服务 | ✅（复用 postgres） | ❌ |
| 事务一致性 | ✅（和业务表同一个事务） | ❌（最终一致） |
| 大规模向量（千万级） | 吃力 | 专为此设计 |
| 混合检索（向量 + 过滤） | SQL 表达力强 | 内置 payload 过滤 |

**判据**：**向量 < 100 万、且需要和业务数据强一致 → pgvector。**
本章示例两个都给了，就是为了让你知道"两个都行"。

### 42.4 一条容易被忽略的：时区

容器默认 UTC。你的业务日志、定时任务、"今天"的定义全受影响。

```yaml
    environment:
      TZ: Asia/Shanghai
```

或者更稳的做法：**代码里全程用 UTC 存储，只在展示层转时区**。
这个坑在附录 E（"小而致命"清单）里也是第一条。

---

## 42.13 本章沉淀

### 📦 你手上现在有什么

| 产物 | 位置 | 你能拿它做什么 |
|---|---|---|
| 同步/流式/异步三个接口 | `code/ch42_integration/step1_api.py` | 直接改成你自己的 Agent 接口 |
| `GuardedStream` | 同上 | 复制走，所有流式接口都该有 |
| 队列 + 幂等 + 限流 + 鉴权 | `code/ch42_integration/step2_queue.py` | 抄语义，换成真队列 |
| 镜像层/体积模拟器 | `code/ch42_integration/step3_docker.py` | 算你自己的镜像账 |
| 7 服务可运行编排 | `examples/full-stack/` | `docker compose up` 直接起 |
| 生产级 Dockerfile | `examples/full-stack/Dockerfile` | 多阶段 + 非 root + healthcheck + exec CMD |
| nginx SSE 反代配置 | `examples/full-stack/frontend/nginx.conf` | SSE 必抄的三行 |
| 建表 SQL（含向量列 + 幂等唯一索引） | `examples/full-stack/db/init.sql` | 直接改字段名用 |

### 一个机制（本章真正想让你记住的那一个）

**"能跑"和"能交付"的差别，全在"边界情况"上。**

正常路径下，你的 Agent 代码和本章之前的任何一章都一样能跑。
但客户那边会遇到：装不上环境、点两下、看不出来在动、中途断网、
机器重启、端口被占、密钥泄露、任务丢一半。

**本章的九条，每一条都在处理一个"正常路径之外"的情况。**
这就是"系统集成"和"写业务逻辑"的本质区别。

### 回去对照你的项目

- [ ] 我的 Agent 有对外接口吗？是同步、流式还是异步？选得对吗？
- [ ] 用户连点两次，会扣两次钱吗？
- [ ] 流式中途出错，客户端能知道吗？
- [ ] 我的镜像多大？改一行代码要重建多久？
- [ ] 镜像里能不能翻出密钥？（`docker history` 看一眼）
- [ ] `docker compose down` 之后，数据还在吗？
- [ ] `docker stop` 之后，手上的任务去哪了？
- [ ] 依赖挂了，我的服务是重启还是摘流量？

---

## 42.14 ✅ 验收

读完这一章，请确认你能**不看书**完成下面五件事：

1. **说清三种接口形态的选型判据**，并给出一个"选错会出什么事"的例子。
2. **手写一个 SSE 接口**，包含 `meta` / `delta` / `error` / `done` 四种事件，
   并解释为什么 `data` 不能含换行。
3. **解释"至少一次"为什么不可避免**，并写出幂等表的三个关键设计决策。
4. **给你的镜像算一笔账**：基础镜像 / 依赖 / 模型 / 源码各多少，能砍哪一块，
   改一行代码重建需要几秒。
5. **跑起一套多服务编排**，并说出 `depends_on` 的 `service_started` 与 `service_healthy`
   的区别、以及健康检查探针写错时会看到什么现象。

如果你能给出**具体的数字**（不是"大概几秒"），这一章就算过了。
