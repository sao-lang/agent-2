"""第 13 章 step1：工具调用的三段式——模型只输出意图，不执行函数（离线）。

运行：
    python code/ch13_tool_calling/step1_three_stages.py

上一级的痛点（第 12 章）：你知道 Agent 需要工具，但你可能以为
                     "模型会自己去调函数" —— **不会，永远不会。**

这一级做什么：把一次工具调用拆成三段，让谁负责哪段清清楚楚：
  ① 声明（你）    把函数签名告诉模型
  ② 决策（模型）  模型输出"我要调 xxx，参数是 {...}"，**它只输出 JSON**
  ③ 执行（你）    你的代码真的去调函数，再把结果塞回上下文

关键：**模型输出的是"意图"，不是"执行"。**
     这个认知差是所有工具安全问题的根源（第 33 章）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


# ============================================================ ① 声明（你写）
@dataclass
class ToolSpec:
    name: str
    description: str
    params: dict[str, str]  # 参数名 → 类型说明
    fn: Callable[..., Any]


def query_order(order_id: str) -> str:
    return {"A12345": "已签收3天", "B777": "已签收20天"}.get(order_id, "订单不存在")


def get_weather(city: str, unit: str = "c") -> str:
    return f"{city} 晴 25{'°C' if unit == 'c' else '°F'}"


TOOLS = [
    ToolSpec("query_order", "查询订单状态，输入订单号", {"order_id": "string"}, query_order),
    ToolSpec("get_weather", "查询城市天气", {"city": "string", "unit": "string, c 或 f"}, get_weather),
]


def declare(tools: list[ToolSpec]) -> str:
    """把工具声明渲染成模型能读的文本（真实 API 里是 JSON Schema）。"""
    lines = []
    for t in tools:
        ps = ", ".join(f"{k}: {v}" for k, v in t.params.items())
        lines.append(f"- {t.name}({ps})：{t.description}")
    return "\n".join(lines)


# ============================================================ ② 决策（模型做）
class FakeLLM:
    """模拟模型的 tool_calls 输出。

    真实模型输出的是结构化的 tool_calls（不是自然语言），形如：
      {"name": "query_order", "arguments": "{\\"order_id\\": \\"A12345\\"}"}
    注意 arguments 是**字符串**（JSON 序列化过的），不是对象 —— 这是最容易踩的坑。
    """

    def decide(self, user: str, seen: set[str], observations: list[str]) -> dict:
        # 有关键：**先把上一轮的观察喂回来**，否则模型永远不知道结果
        if observations:
            return {"type": "final", "text": "根据查询结果：" + "；".join(observations)}

        if "订单" in user or "A12345" in user or "B777" in user:
            oid = "A12345" if "A12345" in user else ("B777" if "B777" in user else "A12345")
            key = f"query_order:{oid}"
            if key in seen:
                return {"type": "final", "text": f"订单 {oid} 状态：已签收3天"}
            return {
                "type": "tool_calls",
                "calls": [{"name": "query_order", "arguments": json.dumps({"order_id": oid})}],
            }
        if "天气" in user:
            city = "杭州" if "杭州" in user else "北京"
            return {
                "type": "tool_calls",
                "calls": [{"name": "get_weather", "arguments": json.dumps({"city": city}, ensure_ascii=False)}],
            }
        if "帮我删" in user or "drop" in user.lower():
            # 模型"想"调一个它自己编出来的工具 —— 这很常见
            return {
                "type": "tool_calls",
                "calls": [{"name": "delete_database", "arguments": "{}"}],
            }
        return {"type": "final", "text": "我可以帮你查订单或天气。"}


# ============================================================ ③ 执行（你做）
def execute(calls: list[dict], tools: list[ToolSpec]) -> list[dict]:
    """**这里是唯一真正执行的地方。** 也是唯一能加安全校验的地方。"""
    registry = {t.name: t for t in tools}
    out = []
    for c in calls:
        name = c["name"]
        tool = registry.get(name)
        if tool is None:
            # 模型编了一个不存在的工具 —— 必须拒绝，不能猜
            out.append({"name": name, "ok": False, "content": f"错误：工具 {name} 不存在"})
            continue
        try:
            args = json.loads(c["arguments"])  # ← 注意：arguments 是字符串
        except json.JSONDecodeError as e:
            out.append({"name": name, "ok": False, "content": f"参数不是合法 JSON：{e.msg}"})
            continue
        # 参数校验（真实项目里用 pydantic，第 6 章）
        missing = [p for p in tool.params if p not in args and p != "unit"]
        if missing:
            out.append({"name": name, "ok": False, "content": f"缺参数：{missing}"})
            continue
        try:
            result = tool.fn(**args)
            out.append({"name": name, "ok": True, "content": str(result)})
        except Exception as e:  # noqa: BLE001 —— 工具可能抛任何异常
            out.append({"name": name, "ok": False, "content": f"{type(e).__name__}: {e}"})
    return out


# ============================================================ 主流程
def chat(user: str, tools: list[ToolSpec], max_rounds: int = 3) -> tuple[str, list[str]]:
    llm = FakeLLM()
    seen: set[str] = set()
    observations: list[str] = []
    log: list[str] = []

    for r in range(1, max_rounds + 1):
        d = llm.decide(user, seen, observations)
        if d["type"] == "final":
            log.append(f"round{r}: 模型给出最终回答")
            return d["text"], log

        calls = d["calls"]
        log.append(f"round{r}: 模型输出 tool_calls = {calls}")
        for c in calls:
            try:
                args = json.loads(c["arguments"])
            except json.JSONDecodeError:
                args = {}
            seen.add(f"{c['name']}:{args.get('order_id', args.get('city', ''))}")

        results = execute(calls, tools)
        for res in results:
            mark = "✅" if res["ok"] else "❌"
            log.append(f"round{r}: 执行 {res['name']} → {mark} {res['content']}")
            # ← 关键：把观察结果回灌给模型（否则它永远不知道结果）
            observations.append(res["content"] if res["ok"] else f"{res['name']} 调用失败")

    return "超过轮数上限", log


def main() -> None:
    print("=" * 90)
    print("① 声明：模型看到的工具清单（就这几行）")
    print("=" * 90)
    print(declare(TOOLS))

    print("\n" + "=" * 90)
    print("② 决策 + ③ 执行：跑四个请求")
    print("=" * 90)
    for user in ("帮我查下订单 A12345", "杭州天气怎么样", "帮我删掉数据库", "你好"):
        print(f"\n【用户】{user}")
        answer, log = chat(user, TOOLS)
        for line in log:
            print(f"  {line}")
        print(f"  【最终】{answer}")

    print("\n" + "=" * 90)
    print("三段式：谁负责哪一段")
    print("=" * 90)
    stages = [
        ("① 声明", "你", "告诉模型有哪些工具、参数是什么", "工具描述写不清 → 模型选错工具"),
        ("② 决策", "**模型**", "输出 tool_calls（JSON），**不执行**", "模型幻觉出不存在的工具/参数"),
        ("③ 执行", "**你**", "真的调函数 + 校验 + 把结果回灌", "**唯一能加安全校验的地方**"),
    ]
    print(f"  {'阶段':<10}{'谁做':<10}{'做什么':<34}风险")
    print("  " + "-" * 86)
    for a, b, c, d in stages:
        print(f"  {a:<10}{b:<10}{c:<34}{d}")

    print("\n" + "=" * 90)
    print("三个必须记住的细节")
    print("=" * 90)
    print("  ① `arguments` 是**字符串**，不是对象")
    print("     真实 API 里它长这样：\"{\\\"order_id\\\": \\\"A12345\\\"}\"")
    print("     直接当字典用会报错，必须先 json.loads()")
    print()
    print("  ② 模型**会**编出不存在的工具名")
    print("     本例里'帮我删掉数据库'时，模型输出了 delete_database。")
    print("     它不是在攻击你，它只是'按最像的方式生成'（第 1 章讲的）。")
    print("     **执行前必须查白名单。**")
    print()
    print("  ③ 工具结果要**回灌上下文**，模型才知道下一步")
    print("     只执行不告诉模型 = 它永远不知道结果，会重复调用（第 12 章的'少状态'）")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · **模型只输出意图，永远不执行函数。** 执行权在你手上。")
    print("  · 所以'在 prompt 里写别删库'根本不算防线 —— 真正的防线在 execute() 里。")
    print("  · 三段里最容易出事的是第 ③ 段：工具白名单、参数校验、超时、幂等。")
    print()
    print("  下一级（step2）：把声明做得更可靠 —— 用 pydantic 定义 schema。")

    ans, _ = chat("帮我查下订单 A12345", TOOLS)
    assert "已签收3天" in ans


if __name__ == "__main__":
    main()
