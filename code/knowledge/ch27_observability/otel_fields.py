"""字段口径：自己的属性名怎么对上 OpenTelemetry 的 gen_ai 约定。

不联网。三件事：
  1 一张映射表：自己记的字段 -> 约定里的键
  2 同一个聚合查询，在"没映射"和"映射后"两种数据上各跑一次
  3 三种对不上的根因，各给一行数据

平台侧只会按约定里的键取值，键名不对，数据在库里也聚合不出来。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 自己 tracer 写的属性（很自然的一版）
OUR_ATTRS = {
    "provider": "openai",
    "model": "gpt-4.1-mini",
    "prompt_tokens": 9_800,
    "completion_tokens": 320,
    "latency_ms": 4_200,
}

# 约定里的键（gen_ai 语义化字段）
MAPPING = {
    "provider": "gen_ai.system",
    "model": "gen_ai.request.model",
    "prompt_tokens": "gen_ai.usage.input_tokens",
    "completion_tokens": "gen_ai.usage.output_tokens",
    "latency_ms": "gen_ai.server.request.duration",   # 注意单位：秒
}

SPAN_NAME_RULE = "chat {gen_ai.request.model}"


@dataclass
class Row:
    trace_id: str
    name: str
    attrs: dict = field(default_factory=dict)


def to_otel(attrs: dict) -> dict:
    """把自家属性翻译成约定键，顺便处理单位。"""
    out: dict = {}
    for k, v in attrs.items():
        key = MAPPING.get(k, k)
        if key == "gen_ai.server.request.duration":
            v = round(v / 1000, 3)          # 毫秒 -> 秒
        out[key] = v
    return out


def raw_rows() -> list[Row]:
    """没映射的数据：键还是自家名字。"""
    return [
        Row("t-1", "model call", dict(OUR_ATTRS)),
        Row("t-1", "model call", {**OUR_ATTRS, "prompt_tokens": 10_400,
                                  "completion_tokens": 280}),
        Row("t-2", "model call", {**OUR_ATTRS, "prompt_tokens": 7_200,
                                  "completion_tokens": 180}),
    ]


def span_name(otel_attrs: dict) -> str:
    """span 名称用约定写法：操作 + 模型。"""
    return "chat " + str(otel_attrs.get("gen_ai.request.model", "unknown"))


def mapped_rows() -> list[Row]:
    rows = []
    for r in raw_rows():
        attrs = to_otel(r.attrs)
        rows.append(Row(r.trace_id, span_name(attrs), attrs))
    return rows


def sum_by(rows: list[Row], key: str) -> dict[str, int]:
    """平台侧的典型聚合：按 trace 汇总某个键。"""
    out: dict[str, int] = {}
    for r in rows:
        out[r.trace_id] = out.get(r.trace_id, 0) + int(r.attrs.get(key, 0))
    return out


def main() -> None:
    print("=== 1. 一张映射表 ===")
    print(f"  {'自家字段':<20}{'约定键':<38}{'备注'}")
    for k, v in MAPPING.items():
        note = "单位：秒（自家是毫秒）" if v.endswith("duration") else ""
        print(f"  {k:<20}{v:<38}{note}")
    print(f"  span 名称约定：{SPAN_NAME_RULE}")

    print()
    print("=== 2. 同一个聚合，两种数据 ===")
    key = "gen_ai.usage.input_tokens"
    before = sum_by(raw_rows(), key)
    after = sum_by(mapped_rows(), key)
    print(f"  按 {key} 聚合（每 trace 的输入 token）：")
    print(f"    没映射：{before}")
    print(f"    映射后：{after}")
    print(f"  另一侧按 gen_ai.request.model 分组：没映射 -> "
          f"{sorted({r.attrs.get('gen_ai.request.model', '（空）') for r in raw_rows()})}，"
          f"映射后 -> {sorted({r.attrs.get('gen_ai.request.model', '（空）') for r in mapped_rows()})}")

    print()
    print("=== 3. 对不上的三种根因 ===")
    cases = [
        ("键名不同", "prompt_tokens", "gen_ai.usage.input_tokens",
         "平台按约定取值，取不到就是 0，看起来像'没有调用'"),
        ("单位不同", "latency_ms = 4200", "duration = 4.2 秒",
         "延迟报表放大 1000 倍，SLO 全红"),
        ("语义不同", "latency 含排队", "server.duration 只含服务端",
         "两边数字都不错，差的是口径，对账时永远差一截"),
    ]
    for name, ours, theirs, why in cases:
        print(f"  {name}：{ours}  ->  {theirs}")
        print(f"    {why}")

    print()
    print("=== 4. 一条符合约定的 span 属性（映射后） ===")
    otel = to_otel(OUR_ATTRS)
    for k, v in otel.items():
        print(f"  {k} = {v}")
    print("  <- 键名、单位、语义三样都对齐，平台侧才能直接聚合")


if __name__ == "__main__":
    main()
