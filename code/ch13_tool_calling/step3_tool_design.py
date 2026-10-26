"""第 13 章 step3：工具设计原则——同样的能力，两种设计差多少（离线）。

运行：
    python code/ch13_tool_calling/step3_tool_design.py

上一级的痛点（step2）：安全检查做完了。但你发现模型总是选错工具、传错参数。
                     这不是模型笨，是**工具描述没写好**。

这一级做什么：同一个能力用两种方式暴露给模型，量化差异：
  · 坏设计：一个万能工具 run_sql(sql)，或者名字含糊的 do_stuff
  · 好设计：语义化命名 + 少参数 + 描述里带"什么时候用"

关键：**工具是给模型看的 API，不是给程序员看的。**
     模型只能靠 name / description / 参数名来猜，你不能口头解释。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, str]
    fn: Callable[..., Any]


# ============================================================ 两种设计
def run_sql(sql: str) -> str:
    if "order" in sql.lower():
        return "A12345|已签收3天"
    if "refund" in sql.lower():
        return "R-345|处理中"
    return "空结果"


def query_order_status(order_id: str) -> str:
    return {"A12345": "已签收3天"}.get(order_id, "订单不存在")


def query_refund_status(refund_no: str) -> str:
    return {"R-345": "处理中"}.get(refund_no, "受理单不存在")


BAD_TOOLS = [
    Tool("run_sql", "执行 SQL 查询", {"sql": "string"}, run_sql),
    Tool("do_stuff", "处理一些事情", {"x": "string"}, lambda x: "ok"),
]

GOOD_TOOLS = [
    Tool(
        "query_order_status",
        "根据订单号查询订单当前状态（已签收/在途/已取消）。"
        "当用户提到订单、物流、签收时用这个。",
        {"order_id": "string，形如 A12345 的订单号"},
        query_order_status,
    ),
    Tool(
        "query_refund_status",
        "根据受理单号查询退款进度。"
        "当用户问「钱什么时候到」时用这个，不要用 query_order_status。",
        {"refund_no": "string，形如 R-345 的受理单号"},
        query_refund_status,
    ),
]

# (用户问题, 正确答案里必须出现的关键词)
CASES = [
    ("我的订单 A12345 到哪了", "已签收3天"),
    ("A12345 签收了没", "已签收3天"),
    ("退款 R-345 进度怎么样", "处理中"),
    ("我的钱什么时候到", "处理中"),
    ("帮我查一下 R-345", "处理中"),
    ("订单状态查询 A12345", "已签收3天"),
]


def render(tools: list[Tool]) -> str:
    return "\n".join(
        f"- {t.name}({', '.join(f'{k}: {v}' for k, v in t.params.items())})：{t.description}"
        for t in tools
    )


class FakeLLM:
    """模拟模型的工具选择。

    真实模型是根据 description 的语义匹配来选的；
    这里用关键词打分模拟——**description 里出现相关词，得分就高**。
    """

    def choose(self, user: str, tools: list[Tool]) -> tuple[Tool | None, dict]:
        best, best_score = None, 0.0
        for t in tools:
            score = 0.0
            hay = (t.name + " " + t.description).lower()
            for kw in ("订单", "签收", "物流"):
                if kw in user and kw in hay:
                    score += 2
            for kw in ("退款", "钱", "受理"):
                if kw in user and kw in hay:
                    score += 2
            for kw in ("sql", "查"):
                if kw in user and kw in hay:
                    score += 0.5   # 模糊词给低权重
            for kw in ("处理", "事情"):
                if kw in user and kw in hay:
                    score += 0.2
            if score > best_score:
                best, best_score = t, score

        if best is None:
            return None, {}

        # 参数抽取
        args: dict[str, Any] = {}
        m = re.search(r"\b(A\d{3,6})\b", user)
        if m and "order_id" in best.params:
            args["order_id"] = m.group(1)
        m = re.search(r"\b(R-\d{3})\b", user)
        if m and "refund_no" in best.params:
            args["refund_no"] = m.group(1)
        if "sql" in best.params:
            args["sql"] = f"select * from order where id='{user}'"
        if "x" in best.params:
            args["x"] = user
        return best, args


def run(tools: list[Tool]) -> tuple[int, list[str]]:
    llm = FakeLLM()
    ok = 0
    detail = []
    last_ids: dict[str, str] = {}   # 记住对话里出现过的单号
    for user, expect in CASES:
        t, args = llm.choose(user, tools)
        if t is None:
            detail.append(f"  「{user}」→ 没选出工具")
            continue

        # 从当前句子里抽单号；抽不到就用对话历史里出现过的（多轮上下文补参）
        m = re.search(r"\b(A\d{3,6})\b", user)
        if m:
            last_ids["order_id"] = m.group(1)
        m = re.search(r"\b(R-\d{3})\b", user)
        if m:
            last_ids["refund_no"] = m.group(1)

        for pname in t.params:
            if pname not in args and pname in last_ids:
                args[pname] = last_ids[pname]

        try:
            out = str(t.fn(**args))
        except Exception as e:  # noqa: BLE001
            out = f"异常 {type(e).__name__}"
        good = expect in out
        ok += good
        detail.append(f"  {'✅' if good else '❌'} 「{user}」→ {t.name} → {out[:30]}")
    return ok, detail


def main() -> None:
    print("=" * 94)
    print("① 坏设计：模型看到的工具清单")
    print("=" * 94)
    print(render(BAD_TOOLS))
    bad_ok, bad_detail = run(BAD_TOOLS)
    print(f"\n  正确率：{bad_ok}/{len(CASES)}")
    for line in bad_detail:
        print(line)

    print("\n" + "=" * 94)
    print("② 好设计：同一个能力，换一种暴露方式")
    print("=" * 94)
    print(render(GOOD_TOOLS))
    good_ok, good_detail = run(GOOD_TOOLS)
    print(f"\n  正确率：{good_ok}/{len(CASES)}")
    for line in good_detail:
        print(line)

    print("\n" + "=" * 94)
    print(f"③ 差异：{bad_ok}/{len(CASES)} vs {good_ok}/{len(CASES)}")
    print("=" * 94)
    print("  同样的后端能力，只改了「怎么告诉模型」，正确率就变了。")
    print("  因为**模型只能靠 name + description + 参数名来猜**，")
    print("  你没有别的渠道跟它解释。")

    print("\n" + "=" * 94)
    print("五条工具设计原则")
    print("=" * 94)
    rules = [
        ("① 一个工具做一件事", "run_sql 是反例：查订单和查退款混在一起",
         "拆成 query_order_status / query_refund_status"),
        ("② 名字要能自解释", "do_stuff 是反例：模型只能看到名字",
         "用动词_名词：query_order_status"),
        ("③ 描述里写「什么时候用」", "只写「查询订单状态」不够",
         "当用户提到订单、物流、签收时用这个"),
        ("④ 写「什么时候不要用」", "两个工具容易混时，必须给负例",
         "**不要用 query_order_status**（第 3 章的负例原理）"),
        ("⑤ 参数少且强类型", "run_sql(sql) 让模型自由发挥",
         "query_order_status(order_id: 形如 A12345)"),
    ]
    print(f"  {'原则':<22}{'反例':<32}正确做法")
    print("  " + "-" * 90)
    for a, b, c in rules:
        print(f"  {a:<22}{b:<32}{c}")

    print("\n" + "=" * 94)
    print("为什么 run_sql 是特别坏的设计")
    print("=" * 94)
    print("  ① **安全**：模型可以生成任意 SQL（step2 的注入问题）")
    print("  ② **可靠**：每次写的 SQL 都不一样，无法预测、无法缓存")
    print("  ③ **可测**：你怎么给'模型可能写的任意 SQL'写测试？")
    print("  ④ **权限**：一个 run_sql 工具等于把整个库的权限给了模型")
    print()
    print("  正确做法：**把 SQL 封装在工具内部**，只暴露业务语义。")
    print("    ❌ run_sql(\"select * from orders where id='A12345'\")")
    print("    ✅ query_order_status(order_id=\"A12345\")")
    print()
    print("  这样：参数可校验、SQL 可审计、权限可控制、结果可缓存。")

    print("\n" + "=" * 94)
    print("结论")
    print("=" * 94)
    print("  · 工具是**给模型看的 API**：名字、描述、参数名就是全部信息。")
    print("  · 描述里必须写「什么时候用」和「什么时候不要用」。")
    print("  · **不要给模型 `run_sql` 这类万能工具** —— 安全、可靠、可测三方面都输。")
    print("  · 工具粒度：一个工具一个业务动作，不是一张表一个工具。")
    print()
    print("  下一级（第 14 章）：工具多了怎么管 —— 这就是 MCP。")

    assert good_ok >= bad_ok


if __name__ == "__main__":
    main()
