"""一份 20 条留出集上的触发矩阵。

判定器是脚本化的（词面命中），替的是"模型读 description 后决定该不该用这套流程"
那一步。换判定器时，用例集、四个计数、两个错误率的口径都不变。

四版 description 只差两处：有没有"什么时候用"、有没有边界段。

运行：python code/knowledge/ch26_skills/trigger_matrix.py
"""

from __future__ import annotations

# ---------------------------------------------------------------- 留出集

# (问法, 期望)  期望 1 = 该进退货审查；0 = 不该进
CASES = [
    ("A1001 能退吗？", 1),
    ("这单还能退货吗，签收 3 天了", 1),
    ("我签收一周了，可以退吗", 1),
    ("订单 A1002 想退货，怎么弄", 1),
    ("拆封了还能退吗", 1),
    ("定制商品能退货吗", 1),
    ("退货运费谁出", 1),
    ("超过 7 天还能退吗", 1),
    ("预售的什么时候能退", 1),
    ("这个订单能退多少钱", 1),
    ("换货的话能退差价吗", 0),
    ("发票能退了重开吗", 0),
    ("退货政策第 3 条写了什么", 0),
    ("你们几点下班", 0),
    ("物流到哪了", 0),
    ("我要投诉快递", 0),
    ("帮我写一段退货说明的文案", 0),
    ("上次那个退货的事后来怎么样了", 0),
    ("会员等级有什么权益", 0),
    ("维修点在哪", 0),
]

# ---------------------------------------------------------------- 四版 description

WHAT = ["退"]          # 域词：四版都一样，只写"做什么"时能给出的全部

DESCS = {
    "A": {
        "text": "处理电商退货审查。",
        "what": WHAT, "when": [], "exclude": [],
    },
    "B": {
        "text": ("处理电商退货审查，判断订单是否符合退货条件。当用户询问订单能否退货、"
                 "想退货、要求给出退货结论时使用。需要订单号。"),
        "what": WHAT,
        "when": ["能退", "可以退", "想退", "退货吗", "怎么退"],
        "exclude": [],
    },
    "C": {
        "text": ("处理电商退货审查，判断订单是否符合退货条件。当用户询问订单能否退货、"
                 "想退货、要求给出退货结论时使用。需要订单号。"
                 "只处理退货，换货、维修、发票、退款不属于本流程。"),
        "what": WHAT,
        "when": ["能退", "可以退", "想退", "退货吗", "怎么退"],
        "exclude": ["换货", "维修", "发票", "退款"],
    },
    "D": {
        "text": ("处理电商退货审查，判断订单是否符合退货条件。当用户询问订单能否退货、"
                 "想退货、退货运费谁承担、要求给出退货结论时使用。需要订单号。"
                 "只处理退货，换货、维修、发票、退款不属于本流程。"),
        "what": WHAT,
        "when": ["能退", "可以退", "想退", "退货吗", "怎么退", "运费"],
        "exclude": ["换货", "维修", "发票", "退款"],
    },
}


def decide(case: str, desc: dict) -> int:
    """1 = 触发。边界段优先；没有触发条件段时，域词命中即触发。"""
    if any(w in case for w in desc["exclude"]):
        return 0
    if not desc["when"]:
        return 1 if any(w in case for w in desc["what"]) else 0
    hit = any(w in case for w in desc["what"]) and any(w in case for w in desc["when"])
    return 1 if hit else 0


def confusion(name: str, desc: dict) -> dict:
    tp = fn = tn = fp = 0
    rows = []
    for case, want in CASES:
        got = decide(case, desc)
        rows.append((case, want, got))
        if want == 1 and got == 1:
            tp += 1
        elif want == 1:
            fn += 1
        elif got == 0:
            tn += 1
        else:
            fp += 1
    return {"name": name, "tp": tp, "fn": fn, "tn": tn, "fp": fp, "rows": rows}


def width(s: str) -> int:
    """终端显示宽度：汉字算 2 列。"""
    return sum(2 if ord(c) > 127 else 1 for c in s)


def pad(s: str, n: int) -> str:
    return s + " " * max(0, n - width(s))


def main() -> None:
    print("=== 1. 留出集：20 条（10 条该触发 / 10 条不该触发）===")
    print("  " + pad("#", 4) + pad("期望", 6) + "A  B  C  D  问法")
    results = {k: confusion(k, d) for k, d in DESCS.items()}
    for i, (case, want) in enumerate(CASES, 1):
        marks = "".join(f"{decide(case, DESCS[k])}  " for k in "ABCD")
        print("  " + pad(str(i), 4) + pad(str(want), 6) + marks + case)

    print()
    print("=== 2. 四版 description 的账 ===")
    pos = sum(1 for _, w in CASES if w == 1)
    neg = len(CASES) - pos
    print("  " + pad("版本", 6) + pad("正确触发", 10) + pad("漏触发", 8) +
          pad("正确拒绝", 10) + pad("误触发", 8) + pad("召回", 10) + "误触发率")
    for k in "ABCD":
        r = results[k]
        print("  " + pad(k, 6) + pad(str(r["tp"]), 10) + pad(str(r["fn"]), 8) +
              pad(str(r["tn"]), 10) + pad(str(r["fp"]), 8) +
              pad(f"{r['tp']}/{pos}", 10) + f"{r['fp']}/{neg}")

    print()
    print("=== 3. 哪一条一直没有被判对 ===")
    for k in "ABCD":
        for case, want, got in results[k]["rows"]:
            if want != got:
                tag = "漏触发" if want == 1 else "误触发"
                print(f"  {k}: {tag} {case}")


if __name__ == "__main__":
    main()
