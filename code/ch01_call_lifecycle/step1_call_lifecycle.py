"""第 1 章 step1：一次调用的完整链路（离线可运行）。

运行：
    python code/ch01_call_lifecycle/step1_call_lifecycle.py

本文件不使用 SDK，用一个假服务端展示请求与响应的字段，
目的是观察链路中每一步的数据形态，不涉及模型能力。

计数说明：这里的 token 数是字符数，仅用于演示字段流转，
与真实分词器的结果不同。第 3 章讲真实口径。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field


@dataclass
class CallRequest:
    model: str
    messages: list[dict]
    temperature: float = 0.0
    max_tokens: int = 256
    tools: list[dict] = field(default_factory=list)

    def to_payload(self) -> dict:
        payload = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.tools:
            payload["tools"] = self.tools
        return payload


@dataclass
class CallResponse:
    id: str
    content: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    tool_calls: list[dict] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def fake_server(payload: dict) -> dict:
    """模拟服务端返回。token 数为字符级估算，不代表真实分词结果。"""
    prompt_text = json.dumps(payload["messages"], ensure_ascii=False)
    reply = "签收后 7 天内可以申请无理由退货。"
    return {
        "id": "chatcmpl-demo-001",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(prompt_text),
            "completion_tokens": len(reply),
            "total_tokens": len(prompt_text) + len(reply),
        },
    }


def parse(raw: dict) -> CallResponse:
    choice = raw["choices"][0]
    usage = raw["usage"]
    message = choice["message"]
    return CallResponse(
        id=raw["id"],
        content=message.get("content") or "",
        finish_reason=choice["finish_reason"],
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        tool_calls=message.get("tool_calls", []),
    )


FINISH_REASONS = {
    "stop": "模型正常结束，content 可直接使用",
    "length": "达到 max_tokens 被截断，content 不完整",
    "tool_calls": "模型请求调用工具，content 通常为空",
    "content_filter": "被内容策略拦截，content 可能为空",
}


def main() -> None:
    req = CallRequest(
        model="demo-model",
        messages=[
            {"role": "system", "content": "你是售后助手。"},
            {"role": "user", "content": "耳机能退吗？"},
        ],
    )

    print("=" * 78)
    print("① 请求体：发给服务端的字段")
    print("=" * 78)
    print(json.dumps(req.to_payload(), ensure_ascii=False, indent=2))

    raw = fake_server(req.to_payload())

    print()
    print("=" * 78)
    print("② 响应体：服务端返回的原始结构")
    print("=" * 78)
    print(json.dumps(raw, ensure_ascii=False, indent=2))

    resp = parse(raw)

    print()
    print("=" * 78)
    print("③ 解析后：业务代码需要的字段")
    print("=" * 78)
    print(f"  正文 content          : {resp.content}")
    print(f"  结束原因 finish_reason: {resp.finish_reason}")
    print(f"  输入 token           : {resp.prompt_tokens}")
    print(f"  输出 token           : {resp.completion_tokens}")
    print(f"  合计                 : {resp.total_tokens}")

    print()
    print("=" * 78)
    print("④ finish_reason 的四种取值")
    print("=" * 78)
    for code, meaning in FINISH_REASONS.items():
        mark = "   <-- 本次" if code == resp.finish_reason else ""
        print(f"  {code:<16}{meaning}{mark}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
