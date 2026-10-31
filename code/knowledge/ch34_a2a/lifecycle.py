"""A2A 的任务生命周期：input-required 之后怎么续，以及丢掉 task_id 会怎样。

不联网。用 a2a-sdk 的请求处理器在进程内走两轮：
  1. 第一轮缺订单号 -> 任务进入 INPUT_REQUIRED，status.message 里带追问
  2. 第二轮带上 task_id -> 同一个任务继续，产出 artifact 并 COMPLETED
  3. 反例：第二轮不带 task_id -> 服务端新建一个任务，上一轮的历史接不上

运行：python code/knowledge/ch34_a2a/lifecycle.py
"""

from __future__ import annotations

import asyncio
import json

import a2a.types as t
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.agent_execution.simple_request_context_builder import (
    SimpleRequestContextBuilder,
)
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from roundtrip import ORDER_DB, SeqID, build_card


class AskingAgent(AgentExecutor):
    """缺参数时把任务停在 INPUT_REQUIRED，而不是猜一个订单号。"""

    def __init__(self) -> None:
        self.states: list[str] = []

    async def execute(self, context: RequestContext, event_queue) -> None:
        if context.current_task is None:
            await event_queue.enqueue_event(
                t.Task(
                    id=context.task_id,
                    context_id=context.context_id,
                    status=t.TaskStatus(state=t.TaskState.TASK_STATE_SUBMITTED),
                    history=[context.message],
                )
            )
            self.states.append(f"{context.task_id}:SUBMITTED")

        text = context.get_user_input()
        order_id = next((w for w in text.split() if w in ORDER_DB), None)
        if order_id is None:
            await event_queue.enqueue_event(
                t.TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=t.TaskStatus(
                        state=t.TaskState.TASK_STATE_INPUT_REQUIRED,
                        message=t.Message(
                            message_id=f"ask-{len(self.states)}",
                            task_id=context.task_id,
                            context_id=context.context_id,
                            role=t.Role.ROLE_AGENT,
                            parts=[t.Part(text="请提供订单号，例如 A1001")],
                        ),
                    ),
                )
            )
            self.states.append(f"{context.task_id}:INPUT_REQUIRED")
            return

        await event_queue.enqueue_event(
            t.TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=t.TaskStatus(state=t.TaskState.TASK_STATE_WORKING),
            )
        )
        self.states.append(f"{context.task_id}:WORKING")
        order = ORDER_DB[order_id]
        payload = {
            "order_id": order_id,
            "status": order["status"],
            "eligible": (not order["opened"]) and order["signed_days_ago"] <= 7,
        }
        await event_queue.enqueue_event(
            t.TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=t.Artifact(
                    artifact_id="art-1",
                    name="order-status",
                    parts=[t.Part(text=json.dumps(payload, ensure_ascii=False))],
                ),
                last_chunk=True,
            )
        )
        await event_queue.enqueue_event(
            t.TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=t.TaskStatus(state=t.TaskState.TASK_STATE_COMPLETED),
            )
        )
        self.states.append(f"{context.task_id}:COMPLETED")

    async def cancel(self, context: RequestContext, event_queue) -> None:
        await event_queue.enqueue_event(
            t.TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=t.TaskStatus(state=t.TaskState.TASK_STATE_CANCELED),
            )
        )


def make_handler(agent: AgentExecutor) -> DefaultRequestHandler:
    return DefaultRequestHandler(
        agent,
        InMemoryTaskStore(),
        build_card(),
        request_context_builder=SimpleRequestContextBuilder(
            task_id_generator=SeqID("task-"),
            context_id_generator=SeqID("ctx-"),
        ),
    )


def user_message(mid: str, text: str) -> t.Message:
    return t.Message(message_id=mid, role=t.Role.ROLE_USER, parts=[t.Part(text=text)])


async def main() -> None:
    handler = make_handler(AskingAgent())

    first = await handler.on_message_send(
        t.SendMessageRequest(message=user_message("m1", "查一下我的订单")),
        ServerCallContext(),
    )
    print("=== 1. 第一轮：缺参数，任务停在 INPUT_REQUIRED ===")
    print(f"  task_id={first.id} state={t.TaskState.Name(first.status.state)}")
    print(f"  追问：{first.status.message.parts[0].text}")
    print(f"  历史消息数：{len(first.history)}")
    print()

    followup = user_message("m2", "A1001")
    followup.task_id = first.id
    followup.context_id = first.context_id
    second = await handler.on_message_send(
        t.SendMessageRequest(message=followup), ServerCallContext()
    )
    print("=== 2. 第二轮：带 task_id，接上同一个任务 ===")
    print(f"  task_id={second.id} state={t.TaskState.Name(second.status.state)}")
    print(f"  历史消息数：{len(second.history)}")
    print(f"  产物：{second.artifacts[0].parts[0].text}")
    print()

    agent = AskingAgent()
    handler2 = make_handler(agent)
    a = await handler2.on_message_send(
        t.SendMessageRequest(message=user_message("m3", "查一下我的订单")),
        ServerCallContext(),
    )
    loose = user_message("m4", "A1001")          # 故意不带 task_id
    b = await handler2.on_message_send(
        t.SendMessageRequest(message=loose), ServerCallContext()
    )
    print("=== 3. 反例：第二轮不带 task_id ===")
    print(f"  第一轮 task_id={a.id}，第二轮 task_id={b.id}")
    print(f"  第二轮历史消息数：{len(b.history)}"
          f"（只有本轮这一条，上一轮的追问不在里面）")
    print("  <- task_id 是续接的唯一句柄；丢了它，服务端只能当成一件新事")
    print()
    await handler2.on_cancel_task(t.CancelTaskRequest(id=a.id), ServerCallContext())
    print("=== 4. 服务端看到的状态序列 ===")
    for line in agent.states:
        print("  " + line)


if __name__ == "__main__":
    asyncio.run(main())
