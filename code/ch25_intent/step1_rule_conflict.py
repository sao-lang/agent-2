"""第 25 章 · 第 1 级：关键词规则什么时候会骗你。

运行：
    python code/ch25_intent/step1_rule_conflict.py

这一级只做一件事：把"关键词规则"的**三种典型失败**跑出来。

  ① 一句多意图（"我要退款但是物流也不更新"）→ 命中两个关键词
  ② 否定表达（"我不想退款"）→ 命中"退款"，但意图相反
  ③ 隐含表达（"东西到现在还没影儿"）→ 一个关键词都没命中

第 ① 种最容易出事故：如果代码"按规则顺序取第一个"，
你会得到一个**置信度很高、但完全错**的判断。
"""
from __future__ import annotations

RULES = [
    ("refund", ("退款", "退货", "退钱", "不要了"), "refund_flow"),
    ("shipping", ("物流", "快递", "什么时候到", "发货", "签收"), "logistics_flow"),
    ("complaint", ("投诉", "举报", "太差", "气死", "12315"), "complaint_flow"),
    ("product_qa", ("怎么样", "参数", "颜色", "尺码", "支持", "能不能"), "qa_rag"),
    ("chitchat", ("你好", "在吗", "谢谢", "哈哈"), "chitchat"),
]

CASES = [
    ("我要退款但是物流也不更新", "refund", "一句多意图"),
    ("我不想退款，就想问问进度", "shipping", "否定表达"),
    ("东西到现在还没影儿", "shipping", "隐含表达（无关键词）"),
    ("这个耳机参数怎么样", "product_qa", "普通"),
    ("我要投诉，太差了", "complaint", "普通"),
]


def hits_of(text: str) -> list[tuple[str, str, str]]:
    """返回 [(意图, 路由, 命中的关键词)]。"""
    hits = []
    for intent, kws, route in RULES:
        for k in kws:
            if k in text:
                hits.append((intent, route, k))
                break
    return hits


def naive_pick(text: str) -> tuple[str | None, float]:
    """最常见的错误实现：按规则顺序取第一个命中的。"""
    hits = hits_of(text)
    return (hits[0][0], 0.9) if hits else (None, 0.0)


def guard_pick(text: str) -> tuple[str | None, float, str]:
    """修正版：多个意图命中 → 主动放弃，交给模型。"""
    hits = hits_of(text)
    if not hits:
        return None, 0.0, "无关键词命中 → 交给模型"
    if len({h[0] for h in hits}) > 1:
        return None, 0.0, f"命中 {len({h[0] for h in hits})} 个意图 → 主动放弃"
    return hits[0][0], 0.9, f"唯一命中「{hits[0][2]}」"


def main() -> None:
    print("=" * 82)
    print("第 1 级：关键词规则的三种失败")
    print("=" * 82)
    print(f"{'输入':<26}{'期望':<12}{'朴素实现':<14}{'修正实现':<24}")
    print("-" * 82)

    wrong_naive = 0
    for text, expect, kind in CASES:
        n_intent, n_conf = naive_pick(text)
        g_intent, g_conf, g_note = guard_pick(text)
        if n_intent != expect:
            wrong_naive += 1
        n_str = f"{n_intent}@{n_conf}" if n_intent else "None"
        g_str = f"{g_intent or '放弃'}"
        print(f"{text:<24}{expect:<12}{n_str:<16}{g_str:<14}{g_note}")

    print(f"\n  朴素实现错 {wrong_naive}/{len(CASES)} 条")

    print("\n" + "=" * 82)
    print("为什么「朴素实现」最危险")
    print("=" * 82)
    t = "我要退款但是物流也不更新"
    hits = hits_of(t)
    print(f"  输入：{t}")
    print(f"  命中：{[(h[0], h[2]) for h in hits]}")
    print("  朴素实现按规则顺序取第一个 → refund@0.9（这次恰好是对的）")
    print()
    print("  但把规则表里 refund 和 shipping 调个顺序，同一条输入就会判成 shipping@0.9：")
    print("    → 用户要退款，系统去查物流 —— 而且日志显示「置信度 0.9」")
    print()
    print("  ⚠️ 这类错误最难排查：日志一切正常、置信度很高、流程也走完了。")
    print("     只有用户投诉你才知道判错了。")
    print()
    print("  👉 正确做法：**多个意图同时命中时，规则层主动放弃**，交给模型。")
    print("     这条规则能干掉一整类「高置信度错判」。")

    print("\n" + "=" * 82)
    print("另外两种失败，规则层永远解决不了")
    print("=" * 82)
    print("  · 否定表达「我不想退款」：关键词只看到「退款」两个字")
    print("  · 隐含表达「东西到现在还没影儿」：一个关键词都没命中")
    print()
    print("  👉 所以规则层只能做「高频、明确、无歧义」的那部分，")
    print("     剩下的必须交给模型 —— 这就是下一级的三级路由。")


if __name__ == "__main__":
    main()
