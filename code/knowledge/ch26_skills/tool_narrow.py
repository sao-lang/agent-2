"""工具收窄：允许清单前后的工具数、清单 token、选择结果。

选择器是脚本化的（字符二元组重合度最高者胜），替的是"模型从清单里挑一个工具"
那一步。它只用来比较同一批任务在两种清单下的结果，不代表模型的真实误选率。

运行：python code/knowledge/ch26_skills/tool_narrow.py
"""

from __future__ import annotations

import re

import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")

TOOLS = [
    {"name": "order__get_order", "desc": "查询订单状态与签收天数"},
    {"name": "order__get_policy", "desc": "查询退货政策窗口天数"},
    {"name": "order__search", "desc": "按关键词搜索订单"},
    {"name": "order__refund_apply", "desc": "提交退款申请"},
    {"name": "order__cancel", "desc": "取消订单"},
    {"name": "order__address", "desc": "修改收货地址"},
    {"name": "kb__search", "desc": "按关键词搜索知识库文档"},
    {"name": "kb__get_doc", "desc": "按文档编号读取知识库文档"},
    {"name": "kb__create_doc", "desc": "新建知识库文档"},
    {"name": "kb__list", "desc": "列出知识库目录"},
    {"name": "kb__update", "desc": "更新知识库文档"},
    {"name": "crm__get_customer", "desc": "查询客户资料"},
    {"name": "crm__add_note", "desc": "给客户添加备注"},
    {"name": "crm__list_orders", "desc": "列出客户历史订单"},
    {"name": "crm__ticket", "desc": "创建工单"},
    {"name": "crm__close_ticket", "desc": "关闭工单"},
    {"name": "crm__send_email", "desc": "发送邮件给客户，说明进度或通知"},
    {"name": "crm__sms", "desc": "发送短信"},
    {"name": "ops__run_sql", "desc": "执行只读 SQL 查询"},
    {"name": "ops__export", "desc": "导出报表 CSV"},
]

# 阶段 -> 允许的工具（allowed-tools）
STAGES = {
    "查订单": ["order__get_order", "order__get_policy", "order__search", "order__address"],
    "退货判定": ["order__get_order", "order__get_policy", "order__refund_apply"],
    "写知识": ["kb__search", "kb__get_doc", "kb__create_doc", "kb__update"],
    "客户沟通": ["crm__get_customer", "crm__add_note", "crm__list_orders",
                 "crm__send_email", "crm__ticket"],
    "数据": ["ops__run_sql", "ops__export"],
}

# (任务, 阶段, 正确工具)
TASKS = [
    ("查一下 A1001 的订单状态", "查订单", "order__get_order"),
    ("退货窗口是几天", "查订单", "order__get_policy"),
    ("在知识库里搜退货条款", "写知识", "kb__search"),
    ("读一下知识库文档 D2031", "写知识", "kb__get_doc"),
    ("提交 A1001 的退款申请", "退货判定", "order__refund_apply"),
    ("把 A1001 收货地址改到杭州", "查订单", "order__address"),
    ("查客户 C88 的资料", "客户沟通", "crm__get_customer"),
    ("给客户 C88 加一条备注", "客户沟通", "crm__add_note"),
    ("列出客户 C88 的历史订单", "客户沟通", "crm__list_orders"),
    ("发一封邮件告诉客户退款进度", "客户沟通", "crm__send_email"),
    ("只读 SQL 查一下昨天的订单量", "数据", "ops__run_sql"),
    ("导出一份报表 CSV", "数据", "ops__export"),
    ("把退货条款更新到知识库", "写知识", "kb__update"),
]


def grams(text: str) -> set[str]:
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def pick(task: str, tools: list[dict]) -> str:
    """字符二元组重合最多者胜；同分取清单里靠前的。"""
    t = grams(task)
    scored = [(-len(t & grams(x["name"].replace("__", " ") + " " + x["desc"])), i, x["name"])
              for i, x in enumerate(tools)]
    return sorted(scored)[0][2]


def listing(tools: list[dict]) -> str:
    return "\n".join(f"{t['name']}: {t['desc']}" for t in tools)


def visible(allowed: list[str]) -> list[dict]:
    keep = set(allowed)
    return [t for t in TOOLS if t["name"] in keep]


def width(s: str) -> int:
    """终端显示宽度：汉字算 2 列。"""
    return sum(2 if ord(c) > 127 else 1 for c in s)


def pad(s: str, n: int) -> str:
    return s + " " * max(0, n - width(s))


def run(tools: list[dict], tasks: list[tuple[str, str, str]], label: str) -> int:
    """在一份清单上跑一批任务，返回选对的条数。"""
    ntok = len(ENC.encode(listing(tools)))
    wrong = [(task, pick(task, tools), want) for task, _, want in tasks]
    bad = [w for w in wrong if w[1] != w[2]]
    print(f"  {pad(label, 10)}可见 {len(tools):>2} 个工具 {ntok:>4} token"
          f"   选对 {len(tasks) - len(bad)}/{len(tasks)}")
    for task, got, want in bad:
        print(f"      误选：{task} -> {got}（应为 {want}）")
    return len(tasks) - len(bad)


def main() -> None:
    print("=== 1. 收窄前：20 个工具全部可见 ===")
    ok_all = run(TOOLS, TASKS, "全量")

    print()
    print("=== 2. 按阶段收窄（allowed-tools 生效）===")
    ok_narrow = 0
    for stage, allowed in STAGES.items():
        tasks = [t for t in TASKS if t[1] == stage]
        ok_narrow += run(visible(allowed), tasks, stage)
    print(f"  合计：全量 {ok_all}/{len(TASKS)}，收窄后 {ok_narrow}/{len(TASKS)}")
    all_tok = len(ENC.encode(listing(TOOLS)))
    stage_tok = sorted(len(ENC.encode(listing(visible(a)))) for a in STAGES.values())
    print(f"  清单体积：全量 {all_tok} token，五个阶段 {stage_tok[0]}–{stage_tok[-1]} token")

    print()
    print("=== 3. 收窄过头：每个阶段只留一个工具 ===")
    for stage, allowed in STAGES.items():
        one = visible(allowed[:1])
        tasks = [t for t in TASKS if t[1] == stage]
        names = {x["name"] for x in one}
        missing = [t for t, _, want in tasks if want not in names]
        print(f"  {pad(stage, 10)}只留 {len(one)} 个 -> 本阶段 {len(missing)}/{len(tasks)} 个任务"
              f"的必需工具不在清单里")


if __name__ == "__main__":
    main()
