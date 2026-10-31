"""一次运行在平台上的样子：五个对象怎么落。

不联网、不依赖 langfuse 包（本机未安装，见 README 的环境说明）。这里做两件事：
  1 把第 42 章手写的 span 树映射成平台的数据模型：trace / observation / score /
    dataset item / prompt version，五个对象各对应主线哪一章的产物
  2 打出"平台侧会看到的那一屏"：树 + 分数 + 成本

映射只描述对象关系，不调用任何 SDK。接真实平台时，写入顺序与这里的顺序一致：
先建 trace，再逐个写 observation，最后把 score 挂到 trace 或某条 observation 上。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 平台的对象类型（对应 langfuse 的 trace / observation / score / dataset / prompt）
OBS_TYPES = ("span", "generation", "event")


@dataclass
class Observation:
    obs_id: str
    parent_id: str | None
    name: str
    obs_type: str                 # span / generation / event
    start_ms: int
    end_ms: int
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    level: str = "DEFAULT"        # DEFAULT / WARNING / ERROR（平台侧的 status）

    @property
    def ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass
class Score:
    name: str
    value: float
    data_type: str                # NUMERIC / BOOLEAN / CATEGORICAL
    comment: str
    target: str                   # 挂到哪个对象：trace_id 或 obs_id


@dataclass
class DatasetItem:
    item_id: str
    case_id: str
    question: str
    expected: str
    trace_id: str = ""            # 跑过之后回填，评测结果与线上 trace 的连接点


@dataclass
class PromptVersion:
    name: str
    version: int
    labels: list[str] = field(default_factory=list)
    body: str = ""


def build_observations() -> list[Observation]:
    """一次 6 个 observation 的运行：检索、生成、工具、子 agent、审批。"""
    return [
        Observation("o-root", None, "run", "span", 0, 6_120),
        Observation("o-ret", "o-root", "retrieve", "span", 0, 420),
        Observation("o-gen", "o-root", "chat gpt-4.1-mini", "generation", 420, 2_600,
                    model="gpt-4.1-mini", input_tokens=9_800, output_tokens=320),
        Observation("o-tool", "o-root", "tool:read_file", "span", 2_600, 2_680),
        Observation("o-sub", "o-root", "subagent 检索", "span", 2_680, 5_400),
        Observation("o-appr", "o-root", "approve 覆写 policy.md", "event", 5_400, 6_120,
                    level="WARNING"),
    ]


SCORES = [
    Score("faithfulness", 0.50, "NUMERIC", "回答里有一条断言在上下文里没有依据", "o-gen"),
    Score("answer_relevancy", 0.17, "NUMERIC", "代理指标，只看版本间方向", "o-gen"),
    Score("user_feedback", 0.0, "BOOLEAN", "用户点了'没用'", "o-root"),
]

PROMPTS = [
    PromptVersion("qa-system", 1, ["prod"], "你是客服，只依据检索到的块回答。"),
    PromptVersion("qa-system", 2, ["staging"], "你是客服。只依据检索到的块回答；"
                                              "依据不足时回答'没有找到依据'。"),
]

ITEMS = [
    DatasetItem("item-01", "case-001", "退款多久到账？", "3 个工作日内", trace_id="t-9f31"),
    DatasetItem("item-02", "case-002", "生鲜可以无理由退货吗？", "不支持", trace_id="t-9f32"),
]


def tree(obs: list[Observation], root: str, prefix: str = "") -> list[str]:
    out: list[str] = []
    kids = [o for o in obs if o.parent_id == root]
    for i, o in enumerate(kids):
        last = i == len(kids) - 1
        mark = "└─" if last else "├─"
        tok = ""
        if o.input_tokens or o.output_tokens:
            tok = f"  in={o.input_tokens} out={o.output_tokens} cache={o.cache_tokens}"
        level = "" if o.level == "DEFAULT" else f"  [{o.level}]"
        out.append(f"{prefix}{mark} {o.name:<22}{o.obs_type:<11}{o.ms:>6}ms{tok}{level}")
        out.extend(tree(obs, o.obs_id, prefix + ("   " if last else "│  ")))
    return out


def pad(text: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    obs = build_observations()

    print("=== 1. 五个对象各对应主线哪一章的产物 ===")
    rows = [
        ("trace", "一次运行", "第 42 章 span 树的根", "trace_id"),
        ("observation", "树上的一个节点", "第 42 章的一条 span", "obs_id + parent_id"),
        ("score", "对运行或节点的判定", "第 43/44 章的指标与裁判", "target = trace_id 或 obs_id"),
        ("dataset item", "一条评测用例", "第 43 章的 case_id", "case_id"),
        ("prompt version", "一版提示词", "第 4 章的提示词 + 版本号", "name + version"),
    ]
    print("  " + pad("平台对象", 16) + pad("它是什么", 20) + pad("主线对应物", 30) + "连接键")
    for a, b, c, d in rows:
        print("  " + pad(a, 16) + pad(b, 20) + pad(c, 30) + d)

    print()
    print("=== 2. 一次运行在平台上的样子（树 + 分数 + 成本） ===")
    print("  trace t-9f31  qa-system v2  gpt-4.1-mini")
    print(f"  run {obs[0].ms}ms")
    for line in tree(obs, "o-root", "  "):
        print(line)

    gen = [o for o in obs if o.obs_type == "generation"]
    tok_in = sum(o.input_tokens for o in gen)
    tok_out = sum(o.output_tokens for o in gen)
    print(f"  汇总：{len(obs)} 个 observation（其中 {len(gen)} 个 generation）"
          f"  in={tok_in} out={tok_out}")
    print()
    print("  挂在这条 trace 上的 score：")
    for s in SCORES:
        target = "trace" if s.target == "o-root" else s.target
        print(f"    {pad(s.name, 18)}{s.data_type:<10}{s.value:>5.2f}  -> {target}  {s.comment}")

    print()
    print("=== 3. dataset item 与 trace 的连接 ===")
    for it in ITEMS:
        print(f"  {it.item_id}  case_id={it.case_id}  trace_id={it.trace_id}  {it.question}")
    print("  <- case_id 是评测的键，trace_id 是线上的键；一条 item 跑过一次就多一列 trace_id")

    print()
    print("=== 4. prompt 版本与标签 ===")
    for p in PROMPTS:
        print(f"  {p.name} v{p.version}  标签={p.labels}  {p.body}")
    print("  <- 评测报告必须带 prompt 版本，否则两次运行的差异说不清是谁改的")


if __name__ == "__main__":
    main()
