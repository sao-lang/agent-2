"""A2A 最小往返：agent card -> message -> task -> artifact。

不联网、不起 HTTP 服务：直接调用 a2a-sdk 的请求处理器，把一次跨进程调用
在进程内走完。对象、状态机、序列化格式都是 SDK 的真实实现，只是省掉了
JSON-RPC 传输层。换成真实服务时，客户端那一行由 Client 发起，其余对象不变。

运行：python code/knowledge/ch34_a2a/roundtrip.py
依赖：a2a-sdk（见 requirements.txt）
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
from a2a.server.id_generator import IDGenerator, IDGeneratorContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from google.protobuf.json_format import MessageToDict

ORDER_DB = {
    "A1001": {"status": "已签收", "signed_days_ago": 3, "opened": False},
    "A1002": {"status": "已签收", "signed_days_ago": 12, "opened": True},
}


class SeqID(IDGenerator):
    """可读的 id 生成器：真实服务里用 UUID，这里为了让输出稳定。"""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.n = 0

    def generate(self, context: IDGeneratorContext) -> str:
        self.n += 1
        return f"{self.prefix}{self.n}"


class OrderAgent(AgentExecutor):
    """远端 agent 的执行体。真实实现里这里会调模型；示例用固定规则。"""

    def __init__(self) -> None:
        self.states: list[str] = []

    async def execute(self, context: RequestContext, event_queue) -> None:
        await event_queue.enqueue_event(
            t.Task(
                id=context.task_id,
                context_id=context.context_id,
                status=t.TaskStatus(state=t.TaskState.TASK_STATE_SUBMITTED),
                history=[context.message],
            )
        )
        self.states.append("SUBMITTED")

        await event_queue.enqueue_event(
            t.TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=t.TaskStatus(state=t.TaskState.TASK_STATE_WORKING),
            )
        )
        self.states.append("WORKING")

        order_id = context.get_user_input().strip().split()[0]
        order = ORDER_DB.get(order_id)
        if order is None:
            payload = {"error": "订单不存在", "order_id": order_id}
        else:
            window = 7
            eligible = (not order["opened"]) and order["signed_days_ago"] <= window
            payload = {
                "order_id": order_id,
                "status": order["status"],
                "eligible": eligible,
                "reason": "未拆封且在 7 天窗口内" if eligible else "超出窗口或已拆封",
            }

        await event_queue.enqueue_event(
            t.TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=t.Artifact(
                    artifact_id="art-1",
                    name="order-status",
                    description="订单状态与可退性",
                    parts=[
                        t.Part(
                            text=json.dumps(payload, ensure_ascii=False),
                            media_type="application/json",
                        )
                    ],
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
        self.states.append("COMPLETED")

    async def cancel(self, context: RequestContext, event_queue) -> None:
        raise NotImplementedError


def build_card() -> t.AgentCard:
    """agent card 是发现入口：客户端只知道域名，靠这份文档知道能做什么。"""
    return t.AgentCard(
        name="order-agent",
        description="订单查询与退货判定，输入订单号，输出 JSON 结论",
        version="1.0.0",
        supported_interfaces=[
            t.AgentInterface(
                url="http://127.0.0.1:9999/a2a",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        capabilities=t.AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["application/json"],
        skills=[
            t.AgentSkill(
                id="order-status",
                name="订单状态",
                description="按订单号查物流状态，并判断是否还在退货窗口内",
                tags=["order", "refund"],
                examples=["A1001 还能退吗", "查 A1002"],
            )
        ],
    )


def as_dict(obj) -> dict:
    return MessageToDict(obj, preserving_proto_field_name=False)


def show(title: str, obj) -> None:
    print(f"=== {title} ===")
    print(json.dumps(as_dict(obj), ensure_ascii=False, indent=2))
    print()


async def main() -> None:
    card = build_card()
    print(f"=== 0. 发现：GET {AGENT_CARD_WELL_KNOWN_PATH} ===")
    print(f"  客户端从这份文档里读到 {len(card.skills)} 个 skill、"
          f"{len(card.supported_interfaces)} 个接口")
    print(json.dumps(as_dict(card), ensure_ascii=False, indent=2))
    print()

    request = t.SendMessageRequest(
        message=t.Message(
            message_id="msg-1",
            role=t.Role.ROLE_USER,
            parts=[t.Part(text="A1001 还能退吗", media_type="text/plain")],
        ),
        configuration=t.SendMessageConfiguration(accepted_output_modes=["application/json"]),
    )
    show("1. 请求：message 带 id、role、parts", request)

    agent = OrderAgent()
    handler = DefaultRequestHandler(
        agent,
        InMemoryTaskStore(),
        card,
        request_context_builder=SimpleRequestContextBuilder(
            task_id_generator=SeqID("task-"),
            context_id_generator=SeqID("ctx-"),
        ),
    )
    task = await handler.on_message_send(request, ServerCallContext())
    show("2. 响应：task 带状态、历史与产物", task)

    artifact = task.artifacts[0]
    payload = json.loads(artifact.parts[0].text)
    print("=== 3. 客户端怎么用这个产物 ===")
    print(f"  产物名：{artifact.name}，id：{artifact.artifact_id}")
    print(f"  order_id={payload['order_id']} eligible={payload['eligible']}")
    print(f"  reason={payload['reason']}")
    print()
    print("=== 4. 状态序列（服务端记录） ===")
    print("  " + " -> ".join(agent.states))


if __name__ == "__main__":
    asyncio.run(main())
