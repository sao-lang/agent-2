"""第 2 章 · 第 4 级（可选补课）：OpenTelemetry 语义约定怎么写。

运行：
    python code/ch02_trace/step4_otel_conventions.py

⚠️ 这一级可以先跳过。等你真的要把 trace 送到 Jaeger / Langfuse /
   Datadog / 阿里云 ARMS 时，再回来看。

前置概念（先读这三行）：
  · span 的属性（attribute）= 卡片上的"附加字段"，key-value 形式
  · 语义约定（semantic conventions）= 业界约定好"字段叫什么名字"
  · 为什么需要它：你自己起名 attr1、attr2，别的平台不认，图表也画不出来

本文件做两件事：
  1. 打印一张"LLM 场景最常用的 12 个属性"对照表
  2. 演示"自己起名" vs "按约定起名" 导出后长什么样
"""
from __future__ import annotations

import json
import time
import uuid


# ============================================================ 1. 属性对照表

# 左边是你"想记录的信息"，右边是 OpenTelemetry GenAI 语义约定的标准名。
# 来源：OpenTelemetry Semantic Conventions for GenAI（gen_ai.* 命名空间）
OTEL_ATTR_TABLE = [
    ("哪个厂商的模型", "gen_ai.system", "openai / deepseek / dashscope"),
    ("这次请求的模型名", "gen_ai.request.model", "deepseek-chat"),
    ("服务端实际用的模型", "gen_ai.response.model", "deepseek-chat-0715"),
    ("操作类型", "gen_ai.operation.name", "chat / embeddings / text_completion"),
    ("输入 token 数", "gen_ai.usage.input_tokens", "420"),
    ("输出 token 数", "gen_ai.usage.output_tokens", "120"),
    ("temperature 参数", "gen_ai.request.temperature", "0.0"),
    ("max_tokens 参数", "gen_ai.request.max_tokens", "800"),
    ("结束原因", "gen_ai.response.finish_reasons", '["stop"]'),
    ("工具名（工具调用时）", "gen_ai.tool.name", "search_policy"),
    ("对话所属会话", "gen_ai.conversation.id", "thread-42"),
    ("Agent 名称", "gen_ai.agent.name", "refund-agent"),
]

print("=" * 82)
print("① LLM 场景最常用的 12 个标准属性（记住这张表就够用）")
print("=" * 82)
print(f"  {'你想记的信息':<22}{'标准属性名':<38}{'示例值'}")
print("  " + "-" * 80)
for what, key, example in OTEL_ATTR_TABLE:
    print(f"  {what:<22}{key:<38}{example}")

print("\n  三条记忆规律：")
print("    · 全部以 gen_ai. 开头（这是 GenAI 的命名空间，避免和其他系统撞名）")
print("    · request.* 表示'我请求什么'，response.* 表示'实际发生了什么'")
print("    · usage.* 专门放 token 用量（计费和成本分析靠它）")


# ============================================================ 2. 两种起名方式

def make_span(attrs: dict) -> dict:
    """模拟一个 span 的导出格式（贴近 OTLP/JSON）。"""
    now = time.time_ns()
    return {
        "traceId": uuid.uuid4().hex,
        "spanId": uuid.uuid4().hex[:16],
        "name": "chat deepseek-chat",
        "kind": "CLIENT",
        "startTimeUnixNano": now,
        "endTimeUnixNano": now + 1_200_000_000,
        "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items()],
    }


bad = make_span({
    "modelName": "deepseek-chat",     # ❌ 自己起的名字
    "tokensIn": 420,
    "tokensOut": 120,
    "provider": "deepseek",
})

good = make_span({
    "gen_ai.system": "deepseek",                    # ✅ 语义约定
    "gen_ai.request.model": "deepseek-chat",
    "gen_ai.usage.input_tokens": 420,
    "gen_ai.usage.output_tokens": 120,
})

print("\n" + "=" * 82)
print("② 导出后长什么样：自己起名 vs 按约定起名")
print("=" * 82)

print("\n  【自己起名】")
print("  " + json.dumps(bad["attributes"], ensure_ascii=False, indent=2).replace("\n", "\n  "))

print("\n  【按语义约定】")
print("  " + json.dumps(good["attributes"], ensure_ascii=False, indent=2).replace("\n", "\n  "))

print("\n  👉 结构完全一样，差别只在 key 的名字。")
print("     但平台是靠 key 名来识别数据的：")
print("     · Jaeger / Tempo 能把 gen_ai.usage.input_tokens 自动画成 token 用量图")
print("     · 你写的 tokensIn，平台不认识 → 图表空白 → 你还得自己写解析脚本")


# ============================================================ 3. 最小可用的埋点代码

print("\n" + "=" * 82)
print("③ 真正写代码时，只要在调模型的地方加 4 行")
print("=" * 82)

print("""
  from opentelemetry import trace

  tracer = trace.get_tracer("my-agent")

  with tracer.start_as_current_span("chat " + model_name) as span:
      resp = llm.invoke(messages)

      # ↓ 这 4 行就是"按语义约定埋点"
      span.set_attribute("gen_ai.system", "deepseek")
      span.set_attribute("gen_ai.request.model", model_name)
      span.set_attribute("gen_ai.usage.input_tokens", usage["input_tokens"])
      span.set_attribute("gen_ai.usage.output_tokens", usage["output_tokens"])
""")

print("  如果不想装 opentelemetry 全套，也可以只在自己的 span 上加：")
print("""
  with tracer.span("chat", attributes={
      "gen_ai.request.model": "deepseek-chat",
      "gen_ai.usage.input_tokens": 420,
  }):
      ...
""")
print("  （本书的 Tracer 就是这种轻量做法 —— 字段名照样遵守约定，")
print("    以后换成真 OTel 只需要改导出那一层，业务代码不用动。）")


# ============================================================ 4. 自查

print("\n" + "=" * 82)
print("④ 自查：你的埋点是否合格")
print("=" * 82)

checklist = [
    "每个 model_call 都记了 gen_ai.request.model",
    "每次调用都记了 input/output tokens（成本分析靠它）",
    "工具调用记了 gen_ai.tool.name",
    "错误记在 span 的 status/error 上，而不是只打日志",
    "span 的 name 能一眼看出是什么操作（如 'chat deepseek-chat'，不是 'span1'）",
]
for i, c in enumerate(checklist, 1):
    print(f"  [ ] {i}. {c}")

print("\n  前 3 条是'能算成本'的前提；第 4 条是'能定位问题'的前提；")
print("  第 5 条决定了你在 Jaeger 界面上能不能读懂。")
