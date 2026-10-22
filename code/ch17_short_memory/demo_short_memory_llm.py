"""第 17 章示例 2：用真模型抽槽位（需要 API key，未配置就优雅退出）。

运行：
    python code/ch17_short_memory/demo_short_memory_llm.py

它演示 step3 的"真模型版本"：
  · 把 schema 写进 prompt（不是写正则）
  · 要求模型只输出 JSON
  · 解析失败 / 冲突时进入"待确认"，而不是直接写进正式槽位

对比离线版 step3_schema_slots.py：
  规则版拦不住的"我叫他帮我看看"，真模型靠语义就能判断主语。
  但真模型会引入新的错法（编造字段、JSON 不合法），所以校验那层不能省。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.context import est_tokens  # noqa: E402
from common.settings import get_settings, make_llm  # noqa: E402

SCHEMA_DESC = """字段：
- name：用户的姓名（只记用户本人，不记他提到的人）
- city：用户长期所在城市
- order_id：订单号
- budget：预算金额（只输出数字）
- product：购买的商品名
没有提到的字段不要输出。"""

EXTRACT_PROMPT = """从用户这句话里抽取信息，只输出 JSON，不要解释。

{schema}

用户说：{text}

输出格式：{{"<字段名>": "<值>"}}，没有可抽取的字段就输出 {{}}"""

CONFLICT_PROMPT = """判断这两句话是否互相矛盾（同一件事的前后两个说法）。

旧：{old}
新：{new}

只输出 JSON：{{"conflict": true/false, "reason": "一句话"}}"""


def parse_json(raw: str) -> dict:
    raw = str(raw).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group(0)) if m else {}


def extract(llm, text: str) -> dict[str, str]:
    raw = llm.invoke(EXTRACT_PROMPT.format(schema=SCHEMA_DESC, text=text)).content
    data = parse_json(raw)
    allowed = {"name", "city", "order_id", "budget", "product"}
    return {k: str(v) for k, v in data.items() if k in allowed and v not in ("", None)}


def is_conflict(llm, old: str, new: str) -> bool:
    try:
        return bool(parse_json(llm.invoke(CONFLICT_PROMPT.format(old=old, new=new)).content).get("conflict"))
    except (json.JSONDecodeError, AttributeError):
        return True  # 判不了就当冲突，交给人看


CASES = [
    "我叫张伟，是做物流的，人在杭州。",
    "订单号 A12345，上周买的蓝牙耳机，预算本来 500 元以内。",
    "我叫他帮我看看这个订单",
    "我朋友叫李雷，他住在南京",
    "订单号改成 B67890",
]


def main() -> None:
    s = get_settings()
    if not s.api_key or s.api_key in ("missing", "sk-xxx"):
        print("[!] 本示例需要真实模型 API，未配置 OPENAI_API_KEY，跳过。")
        print("    离线版请运行：python code/ch17_short_memory/step3_schema_slots.py")
        return

    llm = make_llm()
    values: dict[str, str] = {}
    pending: dict[str, str] = {}

    print("=" * 70)
    print("真模型抽槽位")
    print("=" * 70)
    for text in CASES:
        got = extract(llm, text)
        print(f"\n  输入：{text}")
        print(f"  抽出：{got or '（无）'}")
        for k, v in got.items():
            if k in values and values[k] != v:
                if is_conflict(llm, values[k], v):
                    pending[k] = v
                    print(f"    {k}: {values[k]} -> {v} 判定为冲突，挂起待确认")
                    continue
            values[k] = v

    print("\n" + "=" * 70)
    print("最终槽位")
    print("=" * 70)
    for k, v in values.items():
        print(f"  {k:<10}= {v}  （{est_tokens(v)} token）")
    if pending:
        print("\n  待确认（可能和旧值冲突）：")
        for k, v in pending.items():
            print(f"  {k:<10}= {v}  （当前生效：{values.get(k)}）")

    print("\n  [!] 真模型的价值在语义判断，代价在不确定：")
    print("      它可能漏字段、可能编字段、可能输出不合法的 JSON。")
    print("      所以『待确认』这一层永远不能省。")


if __name__ == "__main__":
    main()
