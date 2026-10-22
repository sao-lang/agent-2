"""第 6 章 step1：模板的四个真实陷阱（离线）。

运行：
    python code/ch06_parse/step1_template_traps.py

上一级的痛点（第 5 章）：调用层做对了，但 prompt 还硬编码在代码里。
                         一旦有 20 个场景，你会有 20 个 f-string，改一处要找三遍。

这一级做什么：先用 f-string / .format() 写模板，**让坑真的炸出来**，再给出正确写法。

  坑 1  模板里有字面量 JSON      → .format() 把 {"a": 1} 当成占位符 → KeyError
  坑 2  f-string 拼模板          → 能跑，但模板不可复用、转义麻烦
  坑 3  string.Template 的 $ 没转义 → 金额被当成变量，静默变成空
  坑 4  模型输出不是合法 JSON     → json.loads 抛异常（5 种情况只成 1 种）

核心结论：**模板引擎只解决"变量替换"，不解决"输出不可靠"。**
"""
from __future__ import annotations

import json
import string
from dataclasses import dataclass


@dataclass
class Ticket:
    order_id: str
    text: str


CASES = [
    Ticket("A12345", "耳机右耳没声音，要退款"),
    Ticket("B777", "优惠券 {满300减30} 还能用吗？"),
    Ticket("C900", "我用的是 {name} 这个牌子"),
    Ticket("D321", '返回 {"status": 500} 报错了'),
]


# ============================================================ 坑 1
TEMPLATE_WITH_JSON = """抽取信息，严格按这个格式输出：
{"order_id": "A123", "problem": "耳机没声音"}

工单：{ticket}"""


def build_with_format(t: Ticket) -> str:
    return TEMPLATE_WITH_JSON.format(ticket=t.text)


# ============================================================ 坑 2
def build_with_fstring(t: Ticket) -> str:
    return f"""抽取信息，严格按这个格式输出：
{{"order_id": "A123", "problem": "耳机没声音"}}

工单：{t.text}"""


# ============================================================ 坑 3
TEMPLATE_DOLLAR = string.Template("""工单：$ticket
备注：满 $300 减 $30""")


def build_dollar(t: Ticket) -> str:
    return TEMPLATE_DOLLAR.safe_substitute(ticket=t.text)


# ============================================================ 正确写法
PLACEHOLDER = "<<<TICKET>>>"
SAFE_BODY = """抽取信息，严格按这个格式输出：
{"order_id": "...", "problem": "..."}

工单内容：
<<<TICKET>>>
"""


def build_safe(t: Ticket) -> str:
    return SAFE_BODY.replace(PLACEHOLDER, t.text)


SAFE_TEMPLATE = string.Template(
    """抽取信息，严格按这个格式输出：
{"order_id": "...", "problem": "..."}

工单内容：
$ticket
"""
)


def build_string_template(t: Ticket) -> str:
    return SAFE_TEMPLATE.safe_substitute(ticket=t.text)


# ============================================================ 坑 4
BAD_OUTPUTS = [
    ('{"order_id": "A123", "problem": "没声音"}', "完整"),
    ('{"order_id": "A123", "problem": "没声', "被截断（finish_reason=length）"),
    ('好的，这是结果：\n{"order_id": "A123", "problem": "没声音"}', "前面加了寒暄"),
    ('```json\n{"order_id": "A123"}\n```', "包了 markdown 代码块"),
    ('', "空输出（content_filter）"),
]


def try_parse(raw: str) -> tuple[dict | None, str]:
    try:
        return json.loads(raw), "成功"
    except json.JSONDecodeError as e:
        return None, f"{type(e).__name__}: {e.msg}"


def main() -> None:
    print("=" * 88)
    print("坑 1：模板里含字面量 JSON + .format()")
    print("=" * 88)
    try:
        build_with_format(CASES[0])
        print("  （没炸？）")
    except (KeyError, IndexError) as e:
        print(f"  {type(e).__name__}: {e}")
        print('  -> 模板里的 {"order_id": ...} 被当成了占位符 order_id')
    print()
    print("  最隐蔽的一个：**模板本身没问题，是引擎选错了。**")

    print("\n" + "=" * 88)
    print("坑 2：f-string —— 能跑，但模板不可复用")
    print("=" * 88)
    out = build_with_fstring(CASES[0])
    print("  输出正常：")
    for line in out.splitlines()[:2]:
        print(f"     {line}")
    print()
    print("  但代价是：")
    print("     - 模板和代码绑死，无法从配置文件 / 数据库读取")
    print("     - 每多一个 JSON 示例，就要多一层 {{ }} 转义")
    print("     - 无法给运营 / 产品自己编辑")

    print("\n" + "=" * 88)
    print("坑 3：string.Template 里的 $ 没转义")
    print("=" * 88)
    out = build_dollar(CASES[0])
    print("  输出：")
    for line in out.splitlines():
        print(f"    {line}")
    print()
    print("  注意 $300 / $30 变成了空 -> 金额静默丢失，模板不报错")
    print("  正确写法：模板里写成 $$300，或改用 replace 方案（根本不用 $）")

    print("\n" + "=" * 88)
    print("正确写法：两种都能用")
    print("=" * 88)
    print(f"{'工单':<10}{'replace 写法':<22}{'string.Template':<22}含大括号")
    print("-" * 88)
    for t in CASES:
        a, b = build_safe(t), build_string_template(t)
        print(
            f"{t.order_id:<10}{'保留原文' if t.text in a else '丢失':<22}"
            f"{'保留原文' if t.text in b else '丢失':<22}"
            f"{'是' if '{' in t.text else '-'}"
        )
    print("-" * 88)
    print("\n  共同点：**模板里只用一个不会和内容冲突的占位符**。")
    print("    replace 方案：<<<TICKET>>>，正常文本里几乎不可能出现")
    print("    string.Template：$ticket，但要小心 $ 转义")

    print("\n" + "=" * 88)
    print("坑 4：模型输出不一定是合法 JSON（真正的大头）")
    print("=" * 88)
    print(f"{'情况':<28}{'解析结果'}")
    print("-" * 88)
    ok = 0
    for raw, note in BAD_OUTPUTS:
        parsed, result = try_parse(raw)
        ok += parsed is not None
        print(f"{note:<28}{result}")
    print("-" * 88)
    print(f"  5 种情况只有 {ok} 种能直接 json.loads 成功（成功率 {ok / len(BAD_OUTPUTS):.0%}）")
    print()
    print("  这不是模型不行，是**输出格式没被约束、也没被容错**。")
    print("  下一级（step2）解决：三层容错解析 + schema 校验。")

    print("\n" + "=" * 88)
    print("结论")
    print("=" * 88)
    print("  - **不要用 .format() 拼含 JSON 示例的模板** —— 一定 KeyError。")
    print("  - f-string 能跑，但模板不可复用、不可外置、转义地狱。")
    print("  - 正确写法：唯一占位符 + replace，或 string.Template（注意 $ 转义）。")
    print("  - **但模板只是第一步。** 真正的难题是模型不一定按格式输出 ——")
    print("    这一步解决「拼装」，下一步解决「解析」。")

    assert all(t.text in build_safe(t) for t in CASES)


if __name__ == "__main__":
    main()
