# agent-harness

可组合的 agent 基座：`Topology(Agent[])`，`Agent = 分派 + 主体 + 校验`，治理/供给/交付作为横切能力挂在固定插点上。

> 设计背景与完整开发会话记录见 [`docs/harness/DEV-SESSION.md`](../../docs/harness/DEV-SESSION.md)。

## 当前状态

| 能力 | 状态 |
|---|---|
| 契约、State、RunResult、错误 | ✅ |
| Agent 循环、ReAct、Workflow、P&E | ✅ |
| 工具装饰器与注册表 | ✅ |
| Guard / Budget / Tracer / Durability / Delivery | ✅ |
| 人工审批与 `resume` | ✅ |
| RAG（InMemoryKnowledge + AutoRetrieval + Context） | ✅ 最小实现 |
| Memory（InMemoryMemory） | ✅ 最小实现 |
| P&E / Planner | ✅（Planner 只在 P&E） |
| Resilience | ✅ |
| Router | ✅ |
| Skills（目录 / as_workflow） | ✅ 最小实现 |
| 五个装配预设（minimal/react/workflow/pe/production） | ✅ |
| Supervisor / Handoff / Blackboard / Pipeline | ✅ |
| MCP | ⬜ 下一步 |
| OpenAI / Qdrant / OTel 适配器 | ⬜ 下一步 |

## 运行

```powershell
$env:PYTHONPATH="$PWD\code\harness\src"
$env:PYTHONIOENCODING='utf-8'

python -m unittest discover -s code/harness/tests -v
python code/harness/examples/refund_agent.py
```

## 最小用法

```python
import asyncio
from harness import AgentConfig, Goal, build, tool
from harness.testing import FakeModel, answer, tool_call


@tool
async def get_order(order_id: str) -> dict:
    """查询订单。"""
    return {"order_id": order_id, "status": "已签收"}


async def main():
    model = FakeModel([
        tool_call("get_order", order_id="A1001"),
        answer("已签收"),
    ])
    agent = build(AgentConfig(model=model, tools=[get_order], mode="react"))
    result = await agent.run(Goal("查 A1001"))
    print(result.status, result.answer)


asyncio.run(main())
```

## 关键约束

- 核心零第三方依赖；适配器放 `adapters/`。
- `build(cfg)` 是唯一实例化处。
- `Planner` 只属于 P&E；`mode=react` / `workflow` 传 `planner` 会在 `build` 时报错。
- `State` 只存可序列化数据；连接、锁、客户端不能进 State。
- 每次运行必须有 `RunResult.status`，不能只返回 State。

## 目录

```text
src/harness/
├── contracts.py     类型、Protocol、错误
├── state.py         State 信封
├── result.py        RunResult
├── agent.py         循环内核
├── body/            React / Workflow / PlanExecute
├── tools.py         工具
├── guard.py         Guard
├── budget.py        预算
├── tracer.py        事件
├── durability.py    检查点
├── delivery.py      出口
├── knowledge.py     检索
├── memory.py        记忆
├── retrieval.py     检索策略
├── context.py       上下文装配
├── build.py         装配
└── testing.py       FakeModel
```
