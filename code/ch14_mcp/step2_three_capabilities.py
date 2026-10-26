"""第 14 章 step2：MCP 的三种能力——tools / resources / prompts 别混用（离线）。

运行：
    python code/ch14_mcp/step2_three_capabilities.py

上一级的痛点（step1）：你会手写协议了。但真实 MCP 服务不止暴露"工具"，
                     还有 resources 和 prompts —— 用错会让模型行为很奇怪。

这一级做什么：在同一台服务里暴露三种能力，然后跑同一批用户请求，
             对比"只有 tools"和"三种都用对"的效果差异。

  · **tools**     有副作用或需要计算 → 模型"调用"（第 13 章）
  · **resources** 只读数据，可直接塞进上下文 → 模型"读取"，不需要决策
  · **prompts**   预置的提示词模板 → 由**用户/UI** 选择，不占模型决策

关键：把"只读数据"做成 tool，是最常见的误用。
     它让模型每读一个文件都要多一轮决策（多一次调用、多一次失败可能）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# ============================================================ 服务端（三种能力）
@dataclass
class Server:
    name: str
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    resources: dict[str, str] = field(default_factory=dict)
    prompts: dict[str, str] = field(default_factory=dict)

    def add_tool(self, name: str, description: str, schema: dict, fn: Callable[..., Any]) -> None:
        self.tools[name] = {"description": description, "inputSchema": schema, "fn": fn}

    def add_resource(self, uri: str, content: str) -> None:
        # resource 的 key 是 URI，不是名字
        self.resources[uri] = content

    def add_prompt(self, name: str, template: str) -> None:
        self.prompts[name] = template

    # ---- 协议方法 ----
    def list_tools(self) -> list[dict]:
        return [{"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
                for n, t in self.tools.items()]

    def list_resources(self) -> list[dict]:
        return [{"uri": u, "mimeType": "text/plain"} for u in self.resources]

    def list_prompts(self) -> list[dict]:
        return [{"name": n, "description": f"预置模板：{n}"} for n in self.prompts]

    def call_tool(self, name: str, args: dict) -> str:
        t = self.tools.get(name)
        if t is None:
            return f"错误：工具 {name} 不存在"
        return str(t["fn"](**args))

    def read_resource(self, uri: str) -> str:
        return self.resources.get(uri, f"错误：资源 {uri} 不存在")

    def get_prompt(self, name: str, args: dict | None = None) -> str:
        tpl = self.prompts.get(name, "")
        for k, v in (args or {}).items():
            tpl = tpl.replace("{" + k + "}", str(v))
        return tpl


# ============================================================ 建服务
def build() -> Server:
    s = Server("docs-mcp")

    # ① tool：有副作用（需要写工单）
    s.add_tool(
        "create_ticket",
        "创建一张售后工单。会产生实际记录。",
        {"type": "object", "properties": {"order_id": {"type": "string"}, "reason": {"type": "string"}},
         "required": ["order_id", "reason"]},
        lambda order_id, reason: f"已创建工单 T-{order_id[-3:]}（原因：{reason}）",
    )

    # ② resource：只读数据，直接可塞上下文
    s.add_resource("docs://policy/refund", "退款政策：审核通过后 3–7 个工作日原路退回。")
    s.add_resource("docs://policy/return", "退货政策：签收后 7 天内可申请无理由退货。")
    s.add_resource("docs://faq/vip", "会员权益：会员享受优先审核，退款时效缩短一天。")

    # ③ prompt：用户可选的操作模板
    s.add_prompt("summarize_policy", "请把下面的政策总结成三条要点：\n{content}")
    s.add_prompt("compare_policy", "比较以下两份政策的差异：\nA: {a}\nB: {b}")

    return s


# ============================================================ 两种接入方式
def bad_design(s: Server) -> dict:
    """错误做法：把所有 resource 也包成 tool。

    模型每读一份文件都要：决策 → 调用 → 回灌 → 再决策。
    """
    for uri in s.list_resources():
        name = uri["uri"].replace("docs://", "").replace("/", "_")
        s.add_tool(
            name,
            f"读取 {uri['uri']}",
            {"type": "object", "properties": {}},
            lambda _u=uri["uri"]: s.read_resource(_u),
        )
    return s


def count_calls_bad(s: Server, questions: list[str]) -> int:
    """模拟：模型每条问题都要自己决定读哪个 resource → 多轮。"""
    calls = 0
    for q in questions:
        # 第 1 轮：决定读哪个
        calls += 1
        # 第 2 轮：读完再答
        calls += 1
    return calls


def count_calls_good(s: Server, questions: list[str]) -> int:
    """正确做法：resource 由宿主按"要不要检索"决定，模型只答一次。"""
    return len(questions)  # 每条问题 1 次生成调用


def main() -> None:
    QUESTIONS = [
        "退款多久到账？",
        "退货有几天？",
        "会员有什么好处？",
        "退款和退货有什么区别？",
    ]

    print("=" * 90)
    print("① 一台服务暴露三种能力")
    print("=" * 90)
    s = build()
    print(f"  tools     ({len(s.list_tools())})  ：{[t['name'] for t in s.list_tools()]}")
    print(f"  resources ({len(s.list_resources())})：{[r['uri'] for r in s.list_resources()]}")
    print(f"  prompts   ({len(s.list_prompts())})  ：{[p['name'] for p in s.list_prompts()]}")

    print("\n" + "=" * 90)
    print("② 三种能力分别谁在用")
    print("=" * 90)
    table = [
        ("tool", "模型", "调用（call）", "有副作用 / 需要计算", "create_ticket"),
        ("resource", "**宿主/客户端**", "读取（read）", "只读数据，可直接进上下文", "policy/refund"),
        ("prompt", "**用户/UI**", "选取（get）", "预置的提示词模板", "summarize_policy"),
    ]
    print(f"  {'能力':<10}{'谁发起':<16}{'动作':<14}{'适用':<28}例子")
    print("  " + "-" * 88)
    for a, b, c, d, e in table:
        print(f"  {a:<10}{b:<16}{c:<14}{d:<28}{e}")

    print("\n" + "=" * 90)
    print("③ 常见误用：把 resource 包成 tool")
    print("=" * 90)
    bad = build()
    bad_design(bad)
    print(f"  误用后 tools 数量：{len(bad.list_tools())}（原来 1 个，现在 4 个）")
    print(f"  → {[t['name'] for t in bad.list_tools()]}")
    print()
    print("  代价：模型每读一份文档，都要多一轮『决策 → 调用 → 回灌』。")
    bad_calls = count_calls_bad(bad, QUESTIONS)
    good_calls = count_calls_good(s, QUESTIONS)
    print(f"    {len(QUESTIONS)} 条问题：误用 {bad_calls} 次调用 vs 正确 {good_calls} 次")
    print(f"    → 多花 {(bad_calls / good_calls - 1):.0%}")
    print()
    print("  更麻烦的是**可靠性**：")
    print("    · 每次多读一个资源，就多一次失败可能（超时、格式错）")
    print("    · 模型可能选错资源（4 个名字很像的 tool）")
    print("    · 你会看到'明明知识库里有，它却没读到'")

    print("\n" + "=" * 90)
    print("④ 正确用法演示")
    print("=" * 90)
    print("  resource（宿主直接读，不进模型决策）：")
    for uri in ("docs://policy/refund", "docs://faq/vip"):
        print(f"    read({uri}) → {s.read_resource(uri)[:40]}")
    print()
    print("  prompt（用户点按钮选取，不占模型决策）：")
    print("    get_prompt('summarize_policy', {'content': '...'})")
    print(f"    → {s.get_prompt('summarize_policy', {'content': '退款3-7天到账'})!r}")
    print()
    print("  tool（真的需要做事时才用）：")
    print("    call('create_ticket', {'order_id': 'A12345', 'reason': '不想要了'})")
    print(f"    → {s.call_tool('create_ticket', {'order_id': 'A12345', 'reason': '不想要了'})}")

    print("\n" + "=" * 90)
    print("⑤ 判断口诀")
    print("=" * 90)
    print("  问三个问题：")
    print("    ① 这个操作会**改变状态**吗？  会 → tool")
    print("    ② 这个内容是**只读数据**吗？  是 → resource")
    print("    ③ 这是**给用户点的模板**吗？  是 → prompt")
    print()
    print("  反例对照：")
    print("    ❌ read_file(path) 做成 tool    → 应该做成 resource（如果是只读）")
    print("    ✅ create_ticket() 做成 tool    → 因为有副作用")
    print("    ❌ '总结政策'做成 tool          → 应该是 prompt（用户选的模板）")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · tools = 模型调用；resources = 宿主读取；prompts = 用户选取。")
    print("  · **把 resource 做成 tool 是最常见的误用**：多一轮决策、多一次失败可能。")
    print("  · 判据：会改变状态 → tool；只读数据 → resource；给用户点的 → prompt。")
    print("  · 真实 MCP 服务常常三种都暴露，宿主按需使用。")
    print()
    print("  下一级（step3）：工具多到 30 个以后怎么办 —— MCP 的分组与发现。")

    assert len(bad.list_tools()) > len(s.list_tools())
    assert bad_calls > good_calls


if __name__ == "__main__":
    main()
