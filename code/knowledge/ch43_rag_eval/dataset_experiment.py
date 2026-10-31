"""评测集的数据模型：dataset / item / run / experiment。

不联网。20 条用例组成一份 dataset；同一份 dataset 上跑两次 experiment（v1 基线、
v2 候选），按 kind 与 intent 两个维度分组看变化。再加一份覆盖矩阵，看这份集合
缺哪一类样本 —— 缺的那一格，指标再高也测不出来。

所有通过/失败结果都是预置的（固定数据，不是模型实测），目的是演示
"评测集 + 两次 experiment" 这个数据结构，以及它怎么与 trace_id 对上。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DATASET = {"id": "ds-returns-2026-10", "version": 3, "created": "2026-10-01"}


@dataclass
class Item:
    item_id: str
    case_id: str
    kind: str                 # 正例 / 负例 / 边界
    intent: str               # 退货 / 退款 / 运费 / 发票
    question: str
    expected: str             # 期望行为：答对 / 说不知道 / 拼接两条
    source: str               # 线上抽样 / 专家标注 / 合成
    retired: bool = False
    trace_id: str = ""        # 跑过之后回填


@dataclass
class Experiment:
    exp_id: str
    dataset_version: int
    prompt_version: int
    model: str
    passed: dict[str, bool] = field(default_factory=dict)


ITEMS = [
    Item("i01", "c001", "正例", "退货", "未拆封的衣服能退吗？", "答对", "线上抽样"),
    Item("i02", "c002", "正例", "退货", "签收 5 天了还能退吗？", "答对", "线上抽样"),
    Item("i03", "c003", "正例", "退货", "退货运费谁承担？", "答对", "专家标注"),
    Item("i04", "c004", "正例", "退货", "换货可以改成退货吗？", "答对", "线上抽样"),
    Item("i05", "c005", "正例", "退货", "退货要保留吊牌吗？", "答对", "合成"),
    Item("i06", "c006", "正例", "退款", "退款多久到账？", "答对", "线上抽样"),
    Item("i07", "c007", "正例", "退款", "退款能退到银行卡吗？", "答对", "专家标注"),
    Item("i08", "c008", "正例", "退款", "部分退款怎么算？", "答对", "合成"),
    Item("i09", "c009", "正例", "运费", "运费险怎么用？", "答对", "线上抽样"),
    Item("i10", "c010", "正例", "运费", "包邮商品退货运费谁出？", "答对", "专家标注"),
    Item("i11", "c011", "正例", "发票", "退货后发票要退回吗？", "答对", "合成"),
    Item("i12", "c012", "负例", "退货", "去年买的还能无理由退吗？", "说不知道", "专家标注"),
    Item("i13", "c013", "负例", "退款", "退款能加急到 1 小时吗？", "说不知道", "线上抽样"),
    Item("i14", "c014", "负例", "退货", "拆封的食品能退吗？", "说不知道", "专家标注"),
    Item("i15", "c015", "负例", "发票", "能开 13% 的专票吗？", "说不知道", "合成"),
    Item("i16", "c016", "边界", "退货", "生鲜和普通商品退货规则一样吗？", "拼接两条", "专家标注"),
    Item("i17", "c017", "边界", "运费", "偏远地区退货运费怎么算？", "拼接两条", "线上抽样"),
    Item("i18", "c018", "边界", "退款", "用了优惠券的订单退款退多少？", "拼接两条", "专家标注"),
    Item("i19", "c019", "边界", "退货", "预售商品能退吗？", "拼接两条", "合成"),
    Item("i20", "c020", "边界", "运费", "两次退货合并寄回怎么算运费？", "拼接两条", "线上抽样"),
]

# 预置的两次 experiment 结果（固定数据，不是模型实测），按 case_id 记
V1_PASS = {"c001", "c002", "c003", "c004", "c005", "c007", "c008", "c009", "c011",
           "c012", "c014", "c015", "c016", "c017"}
V2_PASS = {"c001", "c002", "c003", "c004", "c005", "c006", "c007", "c008", "c009",
           "c011", "c012", "c013", "c014", "c015", "c016", "c017"}


def pad(text: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def rate(items: list[Item], passed: set[str]) -> str:
    k = sum(1 for i in items if i.case_id in passed)
    return f"{k}/{len(items)} = {k / len(items):.0%}"


def main() -> None:
    items = [i for i in ITEMS if not i.retired]
    print(f"=== 1. dataset {DATASET['id']} v{DATASET['version']}"
          f"（{len(items)} 条，退役 {len(ITEMS) - len(items)} 条） ===")
    print("  " + pad("kind", 8) + pad("条数", 6) + pad("期望行为", 14) + "来源")
    for kind in ("正例", "负例", "边界"):
        group = [i for i in items if i.kind == kind]
        expected = "、".join(sorted({i.expected for i in group}))
        src = "、".join(sorted({i.source for i in group}))
        print("  " + pad(kind, 8) + pad(str(len(group)), 6) + pad(expected, 14) + src)

    print()
    print("=== 2. 覆盖矩阵：intent × kind 的条数 ===")
    intents = ["退货", "退款", "运费", "发票"]
    kinds = ["正例", "负例", "边界"]
    print("  " + pad("intent", 8) + "".join(pad(k, 8) for k in kinds) + "合计")
    for it in intents:
        row = [sum(1 for i in items if i.intent == it and i.kind == k) for k in kinds]
        print("  " + pad(it, 8) + "".join(pad(str(c), 8) for c in row) + str(sum(row)))
    print("  <- 这一格里的 0 就是测不到的部分：某类意图没有负例，编造率就测不出来")

    print()
    v1 = Experiment("exp-101", DATASET["version"], 1, "gpt-4.1-mini", V1_PASS)
    v2 = Experiment("exp-102", DATASET["version"], 2, "gpt-4.1-mini", V2_PASS)
    print("=== 3. 两次 experiment ===")
    for e in (v1, v2):
        print(f"  {e.exp_id}  dataset v{e.dataset_version}  prompt v{e.prompt_version}"
              f"  {e.model}  通过 {rate(items, e.passed)}")

    print()
    print("=== 4. 按 kind 分组 ===")
    print("  " + pad("kind", 8) + pad("v1", 14) + "v2")
    for kind in kinds:
        group = [i for i in items if i.kind == kind]
        print("  " + pad(kind, 8) + pad(rate(group, v1.passed), 14) + rate(group, v2.passed))

    print()
    print("=== 5. 逐条差异：谁从失败变通过，谁反过来 ===")
    for i in items:
        a = i.case_id in v1.passed
        b = i.case_id in v2.passed
        if a != b:
            mark = "失败 -> 通过" if b else "通过 -> 失败"
            print(f"  {i.item_id} {i.kind} {i.intent}  {i.question}")
            print(f"    {mark}（{i.expected}）")

    print()
    print("=== 6. case_id 与 trace_id 的连接 ===")
    for i in items[:3]:
        print(f"  {i.item_id}  case_id={i.case_id}  trace_id={i.trace_id or '（尚未跑过）'}")
    print("  <- 跑过一次就回填 trace_id；没有这一列，评测报告与线上 trace 是两套世界")


if __name__ == "__main__":
    main()
