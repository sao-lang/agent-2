"""第 6 章 step2：三层容错解析 + schema 校验（离线）。

运行：
    python code/ch06_parse/step2_robust_parse.py

上一级的痛点（step1）：5 种真实输出里只有 1 种能直接 json.loads 成功（20%）。
                     你不能要求模型"每次都完美输出"——那不可能。

这一级做什么：给一个**三层防线**的解析器，把成功率从 20% 提到 100%，并区分：
  · 能救回来的（补全、剥壳、截取）
  · 救不回来但能识别的（截断、空输出）
  · **解析成功但语义非法**（字段缺失、枚举越界）← 最危险

第三层最重要：**JSON 合法不等于数据可用。**
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    OK = "ok"                    # 解析 + 校验都通过
    REPAIRED = "repaired"        # 救回来了，但用过修复手段
    TRUNCATED = "truncated"      # 明显被截断，必须重试
    EMPTY = "empty"              # 空输出
    INVALID = "invalid"          # JSON 合法但语义非法


@dataclass
class ParseResult:
    status: Status
    data: dict[str, Any] | None = None
    note: str = ""
    steps: list[str] = field(default_factory=list)


# ============================================================ 第一层：剥壳
def strip_wrapper(raw: str) -> tuple[str, list[str]]:
    """去掉代码块、去掉前导寒暄，只留下疑似 JSON 的部分。"""
    steps: list[str] = []
    s = raw.strip()

    # markdown 代码块 ```json ... ```
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
        steps.append("剥掉 markdown 代码块")

    # 从第一个 { 或 [ 开始截取（去掉"好的，这是结果："这类前言）
    start = min((i for i in (s.find("{"), s.find("[")) if i >= 0), default=-1)
    if start > 0:
        s = s[start:]
        steps.append("截掉前导说明文字")

    return s, steps


# ============================================================ 第二层：补全
def try_repair(raw: str) -> tuple[str, list[str]]:
    """对明显被截断的 JSON 做保守补全。

    只在"截断位置很明确"时才补——乱补比不补更危险。
    """
    steps: list[str] = []
    s = raw.rstrip()

    # 引号没闭合
    if s.count('"') % 2 == 1:
        s += '"'
        steps.append("补上未闭合的引号")

    # 括号没闭合：按未匹配数量补齐
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        missing = s.count(open_ch) - s.count(close_ch)
        if missing > 0:
            s += close_ch * missing
            steps.append(f"补上 {missing} 个 {close_ch}")

    # 末尾是逗号或冒号（明显没写完）
    s = re.sub(r"[,:]\s*$", "", s)
    return s, steps


# ============================================================ 第三层：校验
VALID_INTENT = {"退款", "退货", "换货", "咨询"}
REQUIRED = ("order_id", "problem", "intent")


def validate(data: Any) -> tuple[bool, str]:
    """JSON 合法 ≠ 数据可用。这一层检查**语义**。"""
    if not isinstance(data, dict):
        return False, f"顶层不是对象，而是 {type(data).__name__}"
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        return False, f"缺字段：{', '.join(missing)}"
    if data["intent"] not in VALID_INTENT:
        return False, f"intent 取值 '{data['intent']}' 不在允许列表 {VALID_INTENT}"
    oid = str(data["order_id"])
    if not re.fullmatch(r"[A-Z]\d{3,6}", oid):
        return False, f"order_id 格式非法：{oid}（应形如 A12345）"
    return True, ""


# ============================================================ 主流程
def parse(raw: str) -> ParseResult:
    steps: list[str] = []

    if not raw.strip():
        return ParseResult(Status.EMPTY, note="没有任何输出（可能是 content_filter）")

    def finish(data: Any, repaired: bool) -> ParseResult:
        """统一收口：**每一次解析成功都必须过 schema 校验**。"""
        ok, why = validate(data)
        if not ok:
            return ParseResult(Status.INVALID, None, note=why, steps=steps)
        return ParseResult(Status.REPAIRED if repaired else Status.OK, data, steps=steps)

    # 第 0 次尝试：原样
    try:
        data = json.loads(raw)
        steps.append("原样解析成功")
        return finish(data, repaired=False)
    except json.JSONDecodeError:
        steps.append("原样解析失败")

    # 第一层：剥壳
    stripped, s1 = strip_wrapper(raw)
    steps += s1
    try:
        return finish(json.loads(stripped), repaired=bool(s1))
    except json.JSONDecodeError:
        pass

    # 第二层：补全
    repaired_text, s2 = try_repair(stripped)
    steps += s2
    if s2:
        try:
            return finish(json.loads(repaired_text), repaired=True)
        except json.JSONDecodeError:
            pass

    # 判断是"截断"还是"乱码"
    if stripped.count("{") > stripped.count("}"):
        return ParseResult(Status.TRUNCATED, note="括号不匹配，疑似被 max_tokens 截断", steps=steps)
    return ParseResult(Status.INVALID, note="无法解析为 JSON", steps=steps)


# ---- 测试样本 ---------------------------------------------------------------
SAMPLES: list[tuple[str, str]] = [
    ('{"order_id":"A123","problem":"没声音","intent":"退款"}', "完美输出"),
    ('好的，这是结果：\n{"order_id":"B777","problem":"充不进","intent":"退货"}', "前面有寒暄"),
    ('```json\n{"order_id":"C900","problem":"发错","intent":"换货"}\n```', "markdown 代码块"),
    ('{"order_id":"D321","problem":"断了","intent":"退货"', "被截断（缺右括号）"),
    ('{"order_id":"E654","problem":"无声","intent":"退', "截断在字符串中间"),
    ('', "空输出"),
    ('{"order_id":"A123","problem":"没声音"}', "缺 intent 字段"),
    ('{"order_id":"A123","problem":"没声音","intent":"投诉"}', "intent 不在枚举里"),
    ('{"order_id":"12345","problem":"没声音","intent":"退款"}', "order_id 格式错"),
    ('完全不是 JSON 的一段话', "非 JSON"),
]


def main() -> None:
    print("=" * 92)
    print(f"{len(SAMPLES)} 种真实输出，三层解析")
    print("=" * 92)
    print(f"{'样本':<24}{'状态':<12}{'修复步骤'}")
    print("-" * 92)
    counts: dict[str, int] = {}
    for raw, label in SAMPLES:
        r = parse(raw)
        counts[r.status.value] = counts.get(r.status.value, 0) + 1
        steps_desc = " -> ".join(r.steps) if r.steps else "—"
        print(f"{label:<24}{r.status.value:<12}{steps_desc}")
        if r.note:
            print(f"{'':24}{'':12}  └─ {r.note}")
    print("-" * 92)

    ok = counts.get("ok", 0)
    repaired = counts.get("repaired", 0)
    bad = sum(v for k, v in counts.items() if k not in ("ok", "repaired"))
    n = len(SAMPLES)
    print(f"\n  可用的（ok + repaired）：{ok + repaired}/{n} = {(ok + repaired) / n:.0%}")
    print(f"  需要重试/拒答的：{bad}/{n} = {bad / n:.0%}")

    print("\n" + "=" * 92)
    print("对比：三种做法的可用率")
    print("=" * 92)
    # 裸解析：只看 json.loads，不看语义
    naive_json = sum(1 for raw, _ in SAMPLES if _is_json(raw))
    # 裸解析 + 校验：能解析但不过校验的也算失败
    naive_valid = sum(
        1 for raw, _ in SAMPLES if _is_json(raw) and validate(json.loads(raw))[0]
    )
    ours = ok + repaired
    print(f"  ① 只 json.loads（不校验）：{naive_json}/{n} = {naive_json / n:.0%}  ← **把非法数据当成功**")
    print(f"  ② json.loads + 校验：     {naive_valid}/{n} = {naive_valid / n:.0%}")
    print(f"  ③ 三层解析 + 校验：       {ours}/{n} = {ours / n:.0%}")
    print()
    print(f"  → 相对 ②，三层解析多救回 **{ours - naive_valid} 条**（剥壳 + 补全）")
    print(f"  → 剩下的 {n - ours} 条确实救不回来，被判为 invalid/truncated/empty → 走重试或拒答")
    print()
    print("  **注意：①的 40% 看起来和 ③ 一样高，但它全是'假成功'。**")
    print("  ①把'缺字段''枚举越界''ID 格式错'都算成功——这些会在下游炸，")
    print("  而 ③ 把同样这 3 条明确标成 `invalid` 并给出原因。")

    print("\n" + "=" * 92)
    print("第三层为什么最重要：JSON 合法 ≠ 数据可用")
    print("=" * 92)
    semantic = [
        ('{"order_id":"A123","problem":"没声音"}', "合法 JSON，但下游代码 data['intent'] 直接 KeyError"),
        ('{"order_id":"A123","problem":"x","intent":"投诉"}', "合法 JSON，但你的下游只处理 4 种 intent → 走错分支"),
        ('{"order_id":"12345","problem":"x","intent":"退款"}', "合法 JSON，但拿去查订单会查不到（少了字母前缀）"),
    ]
    for raw, risk in semantic:
        print(f"  {raw}")
        print(f"    └─ {risk}\n")

    print("  这三条**都能 json.loads 成功**，所以如果你只判断'解析成功了吗'，")
    print("  它们会一路流到数据库/下游服务，在那里炸——那时已经很难定位了。")

    print("\n" + "=" * 92)
    print("结论")
    print("=" * 92)
    print("  · 解析必须是**三层**：剥壳（去代码块/寒暄）→ 补全（未闭合括号）→ 校验（schema）。")
    print("  · 只有第一层和第二层解决不了时，才判为「需要重试」。")
    print("  · **第三层（schema 校验）不是可选项。** 它把'下游才炸'提前到'当场就知道'。")
    print("  · TRUNCATED 和 EMPTY 要分开处理：前者放大 max_tokens 重试，后者切备用模型（第 5 章）。")
    print()
    print("  下一级（step3）：把 schema 从手写 if 变成声明式——字段一变就改一处。")

    assert ok + repaired >= naive_valid, "三层解析的有效率不能低于裸解析+校验"


def _is_json(raw: str) -> bool:
    try:
        json.loads(raw)
        return True
    except json.JSONDecodeError:
        return False


if __name__ == "__main__":
    main()
