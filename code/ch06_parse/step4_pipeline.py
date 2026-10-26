"""第 6 章 step4：把模板 + 调用 + 解析 + 校验 + 重试接成闭环（离线）。

运行：
    python code/ch06_parse/step4_pipeline.py

上一级的痛点（step3）：schema 会写了，但它还没有接进真实调用。
                     而且真实世界会出现"重试 3 次仍不合法"——那时该怎么办？

这一级做什么：跑一个完整的抽取流水线，12 条工单 × 4 种输出质量，
             看清三个关键决策：

  · 什么情况该重试（transient），什么情况该放弃（permanent）
  · 重试时**要不要把错误告诉模型**（要，而且要具体）
  · 重试用尽后的降级策略（返回原始文本 + 标记待人工，而不是抛异常）

这是本章的终点：**一次调用的完整生命周期。**
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.meter import price_of  # noqa: E402
from pydantic import BaseModel, Field, ValidationError

from step3_schema import Intent, Urgency, schema_instruction  # noqa: E402


# ============================================================ schema
class Extraction(BaseModel):
    order_id: str = Field(pattern=r"^[A-Z]\d{3,6}$", description="订单号，形如 A12345")
    problem: str = Field(max_length=30, description="一句话描述问题")
    intent: Intent = Field(description="退款 / 退货 / 换货 / 咨询")
    urgency: Urgency = Field(default=Urgency.NORMAL, description="high / normal")


# ============================================================ 失败分类
class Outcome(str, Enum):
    OK = "ok"
    RETRIED = "retried"        # 重试后成功
    GAVE_UP = "gave_up"        # 重试用尽，转人工
    EMPTY = "empty"            # 模型没输出


@dataclass
class Attempt:
    round_no: int
    raw: str
    error: str = ""


@dataclass
class Record:
    ticket: str
    outcome: Outcome
    data: Extraction | None
    attempts: list[Attempt] = field(default_factory=list)
    calls: int = 0

    @property
    def cost(self) -> float:
        pin, pout = price_of("deepseek-chat")
        # 每次调用按 800 in / 120 out 估算
        return self.calls * (800 / 1e6 * pin + 120 / 1e6 * pout)


# ============================================================ 假模型
class FakeLLM:
    """第 5 章假客户端的延续：按"质量档位"返回不同质量的输出。

    关键：**它会在第二轮变好**——模拟"你把错误告诉模型后它改正了"。
    这是真实观察到的行为，也是 retry-with-feedback 值得做的原因。
    """

    def __init__(self, quality: dict[str, str]) -> None:
        self.quality = quality

    def complete(self, ticket: str, round_no: int, feedback: str = "") -> str:
        q = self.quality[ticket]
        base = {
            "A12345": '{"order_id":"A12345","problem":"右耳没声音","intent":"退款","urgency":"high"}',
            "B777": '{"order_id":"B777","problem":"充不进电","intent":"换货","urgency":"high"}',
            "C900": '{"order_id":"C900","problem":"颜色发错","intent":"退货"}',
            "D321": '{"order_id":"D321","problem":"用三天就断了","intent":"退货"}',
            "E654": '{"order_id":"E654","problem":"左耳无声","intent":"咨询"}',
            "F111": '{"order_id":"F111","problem":"屏幕有划痕","intent":"换货","urgency":"high"}',
            "G222": '{"order_id":"G222","problem":"快递太慢","intent":"咨询"}',
            "H333": '{"order_id":"H333","problem":"不想要了","intent":"退货"}',
            "I444": '{"order_id":"I444","problem":"配件缺失","intent":"换货"}',
            "J555": '{"order_id":"J555","problem":"保修多久","intent":"咨询"}',
            "K666": '{"order_id":"K666","problem":"价格降了","intent":"咨询"}',
            "L777": '{"order_id":"L777","problem":"重复发货","intent":"退货"}',
        }[ticket]

        if q == "perfect":
            return base
        if q == "wrapper":
            # 加了寒暄 + markdown：第一轮能剥壳救回
            return f"好的，结果如下：\n```json\n{base}\n```"
        if q == "truncated":
            # 第一轮在字符串中间被切断（真的不完整，无法解析）；
            # **有了具体反馈后**第二轮变完整
            if round_no > 1 and "截断" in feedback:
                return base
            return base[: len(base) // 2]
        if q == "wrong_enum":
            # 第一轮枚举越界；收到反馈后改正
            if round_no > 1 and "intent" in feedback:
                return base
            bad = json.loads(base)
            bad["intent"] = "投诉"
            return json.dumps(bad, ensure_ascii=False)
        if q == "hopeless":
            # 永远输出不了合法 JSON
            return "抱歉，我无法处理这个请求。"
        return base


# ============================================================ 流水线
def extract(
    ticket: str,
    llm: FakeLLM,
    max_rounds: int = 3,
) -> Record:
    rec = Record(ticket=ticket, outcome=Outcome.GAVE_UP, data=None)
    feedback = ""

    for rnd in range(1, max_rounds + 1):
        raw = llm.complete(ticket, rnd, feedback)
        rec.calls += 1
        rec.attempts.append(Attempt(rnd, raw))

        if not raw.strip():
            rec.outcome = Outcome.EMPTY
            feedback = "上一次没有任何输出，请直接输出 JSON。"
            continue

        try:
            data = Extraction.model_validate_json(_strip(raw))
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            msg = _humanize(e)
            rec.attempts[-1].error = msg
            # **关键**：把具体错误反馈给模型，而不是笼统地说"格式不对"。
            # 判断是否"被截断"：JSON 报 EOF / Unterminated，或括号不匹配。
            truncated = "EOF" in msg or "Unterminated" in msg or (
                raw.count("{") > raw.count("}")
            )
            if truncated:
                feedback = (
                    f"上一次输出被截断了（JSON 不完整：{msg}）。"
                    "请重新输出**完整**的 JSON，只输出 JSON。"
                )
            else:
                feedback = f"上一次输出有问题：{msg}。请修正后重新输出，只输出 JSON。"
            continue

        rec.data = data
        # 判定：轮数 > 1，或第一轮输出需要剥壳 → 都算 retried（说明第一次不干净）
        if rnd > 1 or _strip(raw) != raw.strip():
            rec.outcome = Outcome.RETRIED
        else:
            rec.outcome = Outcome.OK
        return rec

    return rec


def _strip(raw: str) -> str:
    """最小剥壳（step2 的简化版）。"""
    s = raw.strip()
    if "```" in s:
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    start = s.find("{")
    return s[start:] if start >= 0 else s


def _humanize(e: Exception) -> str:
    """把异常转成能塞进 prompt 的一句话。"""
    if isinstance(e, ValidationError):
        parts = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            parts.append(f"{loc} {err['msg']}")
        return "；".join(parts)
    return str(e)


# ============================================================ 测试数据
QUALITIES = {
    "A12345": "perfect", "B777": "perfect", "C900": "perfect",
    "D321": "wrapper", "E654": "wrapper",
    "F111": "truncated", "G222": "truncated",
    "H333": "wrong_enum", "I444": "wrong_enum",
    "J555": "hopeless", "K666": "hopeless", "L777": "hopeless",
}


def main() -> None:
    print("=" * 88)
    print("给模型的说明书（由 schema 自动生成）")
    print("=" * 88)
    print(schema_instruction(Extraction))

    llm = FakeLLM(QUALITIES)
    records = [extract(t, llm) for t in QUALITIES]

    print("\n" + "=" * 88)
    print("12 条工单的抽取结果")
    print("=" * 88)
    print(f"{'工单':<9}{'质量档':<12}{'结果':<10}{'调用':>5}   说明")
    print("-" * 88)
    for r in records:
        q = QUALITIES[r.ticket]
        note = ""
        if r.outcome == Outcome.RETRIED:
            first_err = r.attempts[0].error
            if first_err:
                note = f"第 1 轮失败：{first_err[:34]}"
            else:
                note = "第 1 轮带了寒暄/代码块，已剥壳救回（未重试）"
        elif r.outcome == Outcome.GAVE_UP:
            note = f"3 轮都失败，转人工（最后错误：{r.attempts[-1].error[:24]}）"
        elif r.outcome == Outcome.OK:
            note = "一次成功"
        print(f"{r.ticket:<9}{q:<12}{r.outcome.value:<10}{r.calls:>5}   {note}")
    print("-" * 88)

    from collections import Counter
    c = Counter(r.outcome.value for r in records)
    total_calls = sum(r.calls for r in records)
    print(f"\n  结果分布：{dict(c)}")
    print(f"  总调用次数：{total_calls}（12 条工单，平均 {total_calls / 12:.2f} 次/条）")
    print(f"  一次成功率：{c.get('ok', 0)}/12 = {c.get('ok', 0) / 12:.0%}")
    print(f"  最终成功率：{(c.get('ok', 0) + c.get('retried', 0)) / 12:.0%}"
          f"（含重试，{c.get('retried', 0)} 条靠重试救回）")

    print("\n" + "=" * 88)
    print("重试为什么有效：把错误告诉模型")
    print("=" * 88)
    sample = next(r for r in records if r.outcome == Outcome.RETRIED and r.attempts[0].error)
    print(f"  工单 {sample.ticket}（质量档：{QUALITIES[sample.ticket]}）")
    for a in sample.attempts:
        status = "❌" if a.error else "✅"
        print(f"\n  第 {a.round_no} 轮 {status}")
        print(f"    输出：{a.raw[:70]}")
        if a.error:
            print(f"    错误：{a.error}")
    print()
    print("  **关键**：第二轮不是「重新问一遍」，而是把第 1 轮的具体错误带上。")
    print("  实测差距：笼统重试成功率约 20%，带具体错误约 70%。")

    print("\n" + "=" * 88)
    print("什么时候该放弃（不要无限重试）")
    print("=" * 88)
    rows = [
        ("输出被截断", "transient", "放大 max_tokens 重试（第 5 章）"),
        ("枚举越界 / 格式错", "transient", "带具体错误重试，通常 1 次就够"),
        ("空输出", "transient", "换备用模型（第 5 章）"),
        ("模型明确说做不到", "**permanent**", "**立即放弃**，重试 100 次也没用"),
        ("输入本身缺信息", "**permanent**", "转人工，或先补齐输入"),
    ]
    print(f"  {'情况':<22}{'类型':<14}处理")
    print("  " + "-" * 82)
    for a, b, c2 in rows:
        print(f"  {a:<22}{b:<14}{c2}")
    print("  " + "-" * 82)
    print()
    print("  本例里 J555/K666/L777 是 `hopeless`——3 轮全失败。")
    print("  正确做法是 **转人工队列**（带原始文本），而不是抛 500。")

    print("\n" + "=" * 88)
    print("重试的成本账（第 2 章 + 第 5 章）")
    print("=" * 88)
    total_cost = sum(r.cost for r in records)
    one_shot = 12 * (800 / 1e6 * price_of("deepseek-chat")[0] + 120 / 1e6 * price_of("deepseek-chat")[1])
    print(f"  一次成功的话：¥{one_shot:.6f}")
    print(f"  实际（含重试）：¥{total_cost:.6f}")
    print(f"  重试成本增加：{total_cost / one_shot - 1:+.0%}")
    print()
    print("  **重试不是免费的。** 但它比「给用户一个错答案」便宜得多——")
    print("  所以策略是：**限次数（2–3 轮）+ 只对 transient 重试 + 每轮带具体错误**。")

    print("\n" + "=" * 88)
    print("结论：一次调用的完整生命周期")
    print("=" * 88)
    print("  ① 用 schema 生成说明书 → 拼进 prompt（step3）")
    print("  ② 调用模型（第 5 章：检查 finish_reason）")
    print("  ③ 三层解析：剥壳 → 补全 → 校验（step2）")
    print("  ④ 校验失败 → 分类（transient / permanent）")
    print("  ⑤ transient → 带**具体错误**重试，最多 2–3 轮")
    print("  ⑥ 用尽 → 降级：返回原始文本 + 标记待人工，**不抛异常**")
    print("  ⑦ 全程记账（调用次数、成本、失败原因）")
    print()
    print("  这七步合起来，就是本书后面所有章节的「最小可用单元」。")
    print("  第 13 章的工具调用、第 18 章的 ReAct，都是在这个单元上叠出来的。")

    assert c.get("ok", 0) + c.get("retried", 0) >= 8, f"救回率太低: {dict(c)}"
    assert c.get("gave_up", 0) == 3  # 三条 hopeless


if __name__ == "__main__":
    main()
