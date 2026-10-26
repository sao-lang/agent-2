"""第 1 章 step3：链路各环节的职责与失败形式（离线可运行）。

运行：
    python code/ch01_call_lifecycle/step3_failure_modes.py

本文件把一次调用拆成六个环节，逐个注入故障，
观察每个环节失败时上层能观察到什么现象。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass
class Stage:
    name: str
    responsibility: str
    failure: str
    symptom: str


STAGES = [
    Stage(
        "组装请求",
        "把 system、历史消息、本轮输入拼成 messages 数组",
        "漏掉 system，或消息顺序错",
        "模型行为不符合设定；回答不相关",
    ),
    Stage(
        "序列化传输",
        "messages 与参数编码为 JSON 发送",
        "非 ASCII 字符编码错误，或超长被拒",
        "400/413；或内容变成乱码",
    ),
    Stage(
        "服务端排队与执行",
        "排队等待算力，按参数生成 token",
        "排队超时，或生成被限流",
        "429/503；重试后成功",
    ),
    Stage(
        "生成终止",
        "达到终止条件后停止生成",
        "达到 max_tokens，或触发内容策略",
        "finish_reason 为 length 或 content_filter",
    ),
    Stage(
        "返回解析",
        "读取 choices、message、usage、finish_reason",
        "字段缺失或结构变化",
        "KeyError；或 content 为空但未报错",
    ),
    Stage(
        "业务使用",
        "把 content 交给下游逻辑",
        "未检查 finish_reason，直接使用不完整内容",
        "用户收到半句话，系统无异常记录",
    ),
]


def main() -> None:
    print("=" * 100)
    print("① 一次调用的六个环节")
    print("=" * 100)
    for i, s in enumerate(STAGES, 1):
        print(f"\n  {i}. {s.name}")
        print(f"     职责：{s.responsibility}")
        print(f"     失败：{s.failure}")
        print(f"     现象：{s.symptom}")

    print()
    print("=" * 100)
    print("② 按「谁该负责」分组")
    print("=" * 100)
    print("  调用方负责：组装请求、序列化、返回解析、业务使用")
    print("  服务方负责：排队与执行、生成终止")
    print()
    print("  前三项失败会抛异常，能被发现。")
    print("  最后一项失败不抛异常：请求成功、状态码 200、usage 正常。")

    print()
    print("=" * 100)
    print("③ 各环节失败的可观测性")
    print("=" * 100)
    print(f"  {'环节':<14}{'是否抛异常':<12}{'是否计入成本':<14}{'能否事后定位'}")
    print("  " + "-" * 92)
    rows = [
        ("组装请求", "否", "是", "能，看 messages"),
        ("序列化传输", "是", "否", "能，看错误码"),
        ("服务端排队", "是", "否", "能，看错误码"),
        ("生成终止", "否", "是", "能，看 finish_reason"),
        ("返回解析", "是", "是", "能，看堆栈"),
        ("业务使用", "否", "是", "不能，除非记录 finish_reason"),
    ]
    for a, b, c, d in rows:
        print(f"  {a:<14}{b:<12}{c:<14}{d}")

    print()
    print("  只有最后一行同时满足：不抛异常、计入成本、默认无法定位。")

    print()
    print("=" * 100)
    print("④ 一份足够的调用记录应包含的字段")
    print("=" * 100)
    fields = [
        ("request_id", "服务端返回的 id，用于向厂商追查"),
        ("model", "实际使用的模型名，可能被路由改写"),
        ("messages", "本次实际发送的内容，不是你以为发送的内容"),
        ("finish_reason", "决定 content 是否可用"),
        ("prompt_tokens", "成本与窗口占用的依据"),
        ("completion_tokens", "成本依据"),
        ("latency_ms", "从发出到收到的耗时"),
        ("error", "失败时的错误码与原始信息"),
    ]
    for name, why in fields:
        print(f"  {name:<18}{why}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
