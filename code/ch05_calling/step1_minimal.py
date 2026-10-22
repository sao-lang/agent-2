"""第 5 章 step1：一次最小调用长什么样（离线可跑，有 key 则走真实）。

运行：
    python code/ch05_calling/step1_minimal.py

上一级的痛点（第 4 章）：选型选完了，现在要动手。但"调一次模型"这件事
                         远不止 client.chat(...) 一行——**失败方式有十几种**。

这一级做什么：用同一份"请求"分别走**离线假客户端**和**真实客户端**，
看清一次调用里到底发生了什么，以及五个必须处理的返回值字段。

设计要点：**没有 API key 也能跑**。离线客户端会返回一个结构完全相同的假响应，
所以你写的代码路径和线上完全一致——只是数据是假的。
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.settings import get_settings  # noqa: E402


# ============================================================ 统一响应结构
@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Response:
    """一次调用的完整结果。**五个字段都必须看，少一个就会线上出事。**

    这是本章的核心：不是"拿到 text 就完事"。
    """

    text: str
    finish_reason: str  # stop / length / tool_calls / content_filter
    model: str
    usage: Usage
    ttft_ms: float = 0.0  # 首字延迟（流式才有意义）
    total_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


# ============================================================ 离线假客户端
class FakeClient:
    """模拟真实客户端的响应形状。

    它**故意**模拟了三种真实会遇到的 finish_reason，
    这样你可以在没有 API key 的情况下练会"怎么判断回答是否完整"。
    """

    def __init__(self, model: str = "fake-model") -> None:
        self.model = model
        self.calls = 0

    def chat(self, messages: list[dict], max_tokens: int = 256) -> Response:
        self.calls += 1
        user = messages[-1]["content"]
        t0 = time.perf_counter()

        # 用一个极简的规则库模拟"回答"，重点是把 finish_reason 造出来
        if "太长" in user:
            text, reason = "这是一个被截断的回答，因为 max_tokens 太小"[: max_tokens // 4], "length"
        elif "敏感" in user:
            text, reason = "", "content_filter"
        else:
            text, reason = f"（离线假回答）你问的是：{user}", "stop"

        usage = Usage(input_tokens=len("".join(m["content"] for m in messages)) // 2, output_tokens=len(text) // 2)
        dt = (time.perf_counter() - t0) * 1000
        return Response(
            text=text,
            finish_reason=reason,
            model=self.model,
            usage=usage,
            ttft_ms=dt / 2,
            total_ms=dt,
            raw={"id": f"fake-{self.calls}", "object": "chat.completion"},
        )


# ============================================================ 真实客户端
def real_chat(messages: list[dict], max_tokens: int = 256) -> Response:
    """走 common.settings 的统一客户端。字段映射已在第 2 章校准过。"""
    from common.meter import usage_of
    from common.settings import make_llm

    s = get_settings()
    llm = make_llm(temperature=0.0, max_tokens=max_tokens)
    t0 = time.perf_counter()
    resp = llm.invoke(messages)
    total_ms = (time.perf_counter() - t0) * 1000
    u = usage_of(resp)
    return Response(
        text=resp.content if isinstance(resp.content, str) else str(resp.content),
        finish_reason=(resp.response_metadata or {}).get("finish_reason", "unknown"),
        model=s.model,
        usage=Usage(u["input_tokens"], u["output_tokens"]),
        ttft_ms=total_ms,  # 非流式：首字即全部
        total_ms=total_ms,
        raw=resp.response_metadata or {},
    )


def main() -> None:
    s = get_settings()
    has_key = s.api_key not in ("", "missing")
    print("=" * 82)
    print("一次最小调用：五个必须检查的字段")
    print("=" * 82)
    print(f"当前模型：{s.model}　API key：{'已配置' if has_key else '未配置（走离线）'}\n")

    client = FakeClient() if not has_key else None
    chat = client.chat if client else real_chat

    cases = [
        ("正常提问", "退货要几天？", 256),
        ("max_tokens 太小", "这是一段太长的问题，需要很长的回答", 8),
        ("触发内容过滤", "这段话包含敏感词", 256),
    ]

    for label, question, max_tokens in cases:
        messages = [
            {"role": "system", "content": "你是电商客服，回答不超过三句话。"},
            {"role": "user", "content": question},
        ]
        print(f"--- {label} ---")
        try:
            r = chat(messages, max_tokens=max_tokens)
        except Exception as e:  # noqa: BLE001 —— 教学脚本必须展示异常形态
            print(f"  ❌ 调用失败：{type(e).__name__}: {e}\n")
            continue

        print(f"  text            : {r.text!r}")
        print(f"  finish_reason   : {r.finish_reason}")
        print(f"  model           : {r.model}")
        print(f"  usage           : in={r.usage.input_tokens} out={r.usage.output_tokens} total={r.usage.total}")
        print(f"  latency         : ttft={r.ttft_ms:.1f}ms total={r.total_ms:.1f}ms")

        # 关键：**只看 text 会漏掉这两种情况**
        if r.finish_reason == "length":
            print("  ⚠️ 回答被 max_tokens 截断 —— 如果你直接把 text 返回给用户，就是'答一半'")
        elif r.finish_reason == "content_filter":
            print("  ⚠️ 输出被内容过滤 —— text 是空的，但这不是错误，是策略拦截")
        elif r.finish_reason == "stop":
            print("  ✅ 正常结束")
        print()

    print("=" * 82)
    print("为什么五个字段都要看")
    print("=" * 82)
    rows = [
        ("text", "给用户看的文本", "只看它 → 把截断/过滤当成成功"),
        ("finish_reason", "为什么停下来", "不看它 → 分不清'答完'和'被打断'"),
        ("model", "实际是哪个模型答的", "不看它 → 网关降级了你还以为在用贵的"),
        ("usage", "花了多少 token", "不看它 → 没有成本归因（第 39 章）"),
        ("total_ms", "等了多久", "不看它 → 用户投诉慢，你不知道慢在哪（第 37 章）"),
    ]
    print(f"  {'字段':<16}{'作用':<24}不看的后果")
    print("  " + "-" * 78)
    for f, use, risk in rows:
        print(f"  {f:<16}{use:<24}{risk}")

    print("\n" + "=" * 82)
    print("结论")
    print("=" * 82)
    print("  · 一次调用 = 发请求 + 拿五个字段 + **判断这次算不算成功**。")
    print("  · `finish_reason != 'stop'` 就是没成功，哪怕 `text` 不为空。")
    print("  · 离线假客户端的价值：**你可以先把失败分支写完再申请 API key**。")
    print("    这也是本书后面所有章节的做法——先让逻辑离线可测，再接真实模型。")


if __name__ == "__main__":
    main()
