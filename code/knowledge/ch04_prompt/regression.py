"""提示词回归测试：总数上升，掩盖了一条回归。

五个用例、两个版本，走的是真实的 openai 客户端与 JSON mode；服务端是脚本化的
（`fake_server`），按"版本 × 用例"回放回答。判定由代码做：把回放的内容解析成对象，
再看里头的值满不满足这一例的期望。真实使用时，这一段换成模型的真实回答即可。

结论不是"变好了"：修好两条、弄坏一条，而分类统计里看不出来。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from fake_server import chat_completion, client_for, scripted_server

POLICY_A = "- 签收后 7 天内可以申请退货\n- 商品需未拆封"

POLICY_B = (
    "- 签收后 7 天内可以申请退货\n"
    "- 商品需完好\n"
    "- 定制商品不支持退货\n"
    "- 信息不足时 eligible 填 null，并在 reason 里说明缺什么"
)


@dataclass
class Case:
    name: str
    category: str
    text: str
    check: Callable[[dict], bool]


def eligible_is(value: bool) -> Callable[[dict], bool]:
    return lambda obj: obj.get("eligible") is value


def is_refusal(obj: dict) -> bool:
    """拒答：eligible 为 null，且 reason 里说了缺什么。"""
    return obj.get("eligible") is None and bool(obj.get("reason"))


CASES = [
    Case("常规退货", "常规", "订单 A1001：签收 3 天，未拆封，普通商品", eligible_is(True)),
    Case("超期退货", "边界", "订单 A1002：签收 30 天，未拆封，普通商品", eligible_is(False)),
    Case("定制商品", "边界", "订单 A1003：签收 3 天，未拆封，定制商品", eligible_is(False)),
    Case("已拆封", "边界", "订单 A1004：签收 3 天，已拆封，普通商品", eligible_is(False)),
    Case("空输入", "异常", "", is_refusal),
]

# 脚本化后端按 (版本, 用例名) 回放回答。A 版少了定制条款与 null 约束；
# B 版补上这两条，同时把"未拆封"改成了"完好"。
ANSWERS = {
    "A": {
        "常规退货": {"eligible": True, "reason": "签收 3 天，未拆封，可以退"},
        "超期退货": {"eligible": False, "reason": "签收 30 天，超过 7 天"},
        "定制商品": {"eligible": True, "reason": "签收 3 天，未拆封，可以退"},
        "已拆封": {"eligible": False, "reason": "商品已拆封，不符合条件"},
        "空输入": {"eligible": True, "reason": "签收 3 天，未拆封，可以退"},
    },
    "B": {
        "常规退货": {"eligible": True, "reason": "签收 3 天，未拆封，可以退"},
        "超期退货": {"eligible": False, "reason": "签收 30 天，超过 7 天"},
        "定制商品": {"eligible": False, "reason": "定制商品不支持退货"},
        "已拆封": {"eligible": True, "reason": "商品完好，可以退"},
        "空输入": {"eligible": None, "reason": "缺少订单信息，无法判断"},
    },
}


def build_messages(policy: str, text: str) -> list[dict]:
    """提示词：政策 + 输入数据 + 输出格式。数据用 <<< >>> 包住。"""
    return [
        {"role": "system", "content": "你是退货客服，只依据给定政策判断。"},
        {"role": "user", "content": (
            f"# 政策\n{policy}\n\n"
            f"# 输入\n<<<\n{text}\n>>>\n\n"
            '# 输出\n只输出 JSON：{"eligible": true|false|null, "reason": "不超过 30 字"}，'
            "不要 markdown 包裹。"
        )},
    ]


def run(version: str, policy: str) -> dict[str, bool]:
    """跑一遍用例集，返回逐例结果。"""
    results: dict[str, bool] = {}

    def respond(index: int, body: dict) -> dict:
        name = CASES[min(index, len(CASES) - 1)].name
        content = json.dumps(ANSWERS[version][name], ensure_ascii=False)
        return chat_completion(content=content, usage=(body["messages"][1]["content"].__len__(), 30))

    print("=" * 72)
    print(f"版本 {version}")
    print("=" * 72)
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        for case in CASES:
            reply = client.chat.completions.create(
                model="demo-model", messages=build_messages(policy, case.text),
                response_format={"type": "json_object"})
            obj = json.loads(reply.choices[0].message.content or "{}")
            ok = case.check(obj)
            results[case.name] = ok
            print(f"  {case.name:<8}{case.category:<4}"
                  f" eligible={str(obj.get('eligible')):<5}"
                  f" {'通过' if ok else '失败'}   {obj.get('reason')}")
    return results


def by_category(results: dict[str, bool]) -> dict[str, tuple[int, int]]:
    """按类别聚合：返回 {类别: (通过数, 总数)}。"""
    out: dict[str, tuple[int, int]] = {}
    for case in CASES:
        ok, total = out.get(case.category, (0, 0))
        out[case.category] = (ok + int(results[case.name]), total + 1)
    return out


def self_test() -> None:
    """判定函数自己也要有测试：它错了，整个回归集都会失真。"""
    assert eligible_is(True)({"eligible": True})
    assert not eligible_is(True)({"eligible": False})
    assert not eligible_is(True)({"eligible": None})
    assert is_refusal({"eligible": None, "reason": "缺少订单信息"})
    assert not is_refusal({"eligible": None, "reason": ""})
    print("判定函数自测通过")


def main() -> None:
    self_test()
    print()
    a = run("A", POLICY_A)
    print()
    b = run("B", POLICY_B)
    print()

    pa, pb = sum(a.values()), sum(b.values())
    print("=" * 72)
    print("总数与分类")
    print("=" * 72)
    print(f"  总数：{pa}/{len(CASES)} → {pb}/{len(CASES)}（+{pb - pa}）")
    ca, cb = by_category(a), by_category(b)
    for cat in ("常规", "边界", "异常"):
        ok_a, total = ca[cat]
        ok_b, _ = cb[cat]
        mark = "" if ok_a == ok_b else f"   <- {ok_a}→{ok_b}"
        print(f"  {cat:<4}{ok_a}/{total} → {ok_b}/{total}{mark}")

    print()
    print("=" * 72)
    print("逐例比较")
    print("=" * 72)
    fixed = [k for k in a if not a[k] and b[k]]
    broke = [k for k in a if a[k] and not b[k]]
    print(f"  修好的：{fixed}")
    print(f"  弄坏的：{broke}")
    print()
    print("  只看总数：3 变 4，变好了。")
    print("  逐例比较：修好两条，弄坏一条。")
    print("  按类别看：边界类 2/3 → 2/3，修好与弄坏正好抵消，看不出那条回归。")

    print()
    print("=" * 72)
    print("用例集的四条要求")
    print("=" * 72)
    print("  1. 覆盖类别：常规、边界、异常各有用例")
    print("  2. 保留历史失败：定制商品与空输入曾经失败，必须一直在")
    print("  3. 逐例比较：总数是标量，它丢掉了哪条对哪条错")
    print("  4. 每次改动跑同一批：换用例集就不可比")


if __name__ == "__main__":
    main()
