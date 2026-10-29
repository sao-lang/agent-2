"""四类能力的边界与一次冲突裁决。

裁决规则是写死的顺序（明确匹配的 Skill > 工具 > 检索 > 记忆），
这里把它跑在四条真实形状的请求上，看每条走到哪一类、理由是什么。

运行：python code/knowledge/ch26_skills/conflict_ruling.py
"""

from __future__ import annotations

CAPS = [
    ("工具", "能做什么动作", "第 6 章"),
    ("Skill", "按什么流程做", "第 26 章"),
    ("检索", "依据什么资料", "第 14–19 章"),
    ("记忆", "以前发生过什么", "第 20 章"),
]

# 每条请求带四个特征：是否命中某个 Skill、是否只要一个事实、是否要条文、是否指代过去
REQUESTS = [
    {"text": "A1001 能退吗？", "skill": "refund-review",
     "tool": "order__get_order", "rule_text": False, "past": False},
    {"text": "查一下 A1001 的状态", "skill": None,
     "tool": "order__get_order", "rule_text": False, "past": False},
    {"text": "退货政策第几条说了七天", "skill": None,
     "tool": None, "rule_text": True, "past": False},
    {"text": "我上次那笔退货最后怎么判的", "skill": None,
     "tool": None, "rule_text": False, "past": True},
]


def rule(req: dict) -> tuple[str, str]:
    """返回 (裁决, 理由)。顺序即优先级。"""
    if req["skill"]:
        return "Skill", f"命中流程 {req['skill']}，流程是审过的，优先于临时拼凑"
    if req["tool"] and not req["rule_text"] and not req["past"]:
        return "工具", f"只要一个事实，{req['tool']} 直接给，不必走流程"
    if req["rule_text"]:
        return "检索", "问的是条文本身，要的是依据，不是某笔订单的结论"
    if req["past"]:
        return "记忆", "指代过去发生的事，只有记忆里有"
    return "直接回答", "四类都没有可用依据，交回模型作答"


def width(s: str) -> int:
    """终端显示宽度：汉字算 2 列。"""
    return sum(2 if ord(c) > 127 else 1 for c in s)


def pad(s: str, n: int) -> str:
    return s + " " * max(0, n - width(s))


def main() -> None:
    print("=== 1. 四类能力各回答什么 ===")
    for name, what, where in CAPS:
        print(f"  {pad(name, 8)}{pad(what, 20)}{where}")

    print()
    print("=== 2. 四条请求的裁决 ===")
    for req in REQUESTS:
        verdict, why = rule(req)
        print(f"  {req['text']}")
        print(f"    命中：skill={req['skill']} tool={req['tool']} "
              f"条文={req['rule_text']} 过去={req['past']}")
        print(f"    裁决：{verdict} —— {why}")

    print()
    print("=== 3. 同一条请求按不同顺序裁，会走到哪 ===")
    order_a = ["Skill", "工具", "检索", "记忆"]
    order_b = ["工具", "检索", "记忆", "Skill"]
    req = REQUESTS[0]
    print(f"  请求：{req['text']}")
    print(f"  顺序 A {order_a} -> {pick_by_order(req, order_a)}")
    print(f"  顺序 B {order_b} -> {pick_by_order(req, order_b)}")


def pick_by_order(req: dict, order: list[str]) -> str:
    """同一批特征，只换优先级顺序。"""
    available = {
        "Skill": bool(req["skill"]),
        "工具": bool(req["tool"]) and not req["rule_text"] and not req["past"],
        "检索": req["rule_text"],
        "记忆": req["past"],
    }
    for name in order:
        if available[name]:
            return name
    return "直接回答"


if __name__ == "__main__":
    main()
