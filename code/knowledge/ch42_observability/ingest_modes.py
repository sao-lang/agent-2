"""三种接入方式：同一段代码，上报出来的东西不一样。

不联网，也不依赖 langfuse / opentelemetry 包（本机均未安装）。三种方式在这里
用"能看到哪些节点"来模拟，运行数据是同一份，差别只在可见范围：

  sdk      在业务代码里打点：看得到每一步，但跨进程要自己传 trace_id
  otel     标准协议 + traceparent：看得到每一步，且跨进程自动串起来
  gateway  网关代理：只看得到模型 HTTP 调用，工具、检索、审批都看不见

结论不是"哪种更好"，而是"哪种能回答哪几个问题"。
"""

from __future__ import annotations

from dataclasses import dataclass

# 一次运行的节点：name / 类型 / 是否模型 HTTP 调用 / 是否在另一个进程
NODES = [
    ("run", "run", False, False),
    ("step-1 定位", "model", True, False),
    ("tool:read_file", "tool", False, False),
    ("step-2 读政策", "model", True, False),
    ("subagent 检索", "subagent", False, True),
    ("sub:改写查询", "model", True, True),
    ("tool:search", "tool", False, True),
    ("sub:摘要", "model", True, True),
    ("approve 覆写 policy.md", "approve", False, False),
    ("step-3 写文件", "model", True, False),
]

MODES = {
    "sdk": {"model": True, "tool": True, "approve": True, "subagent": True,
            "run": True, "cross": False},
    "otel": {"model": True, "tool": True, "approve": True, "subagent": True,
             "run": True, "cross": True},
    "gateway": {"model": True, "tool": False, "approve": False, "subagent": False,
                "run": False, "cross": True},
}

QUESTIONS = ["花了多少钱", "哪一步最慢", "为什么失败", "改动变好了吗", "能不能复现"]


@dataclass
class View:
    mode: str
    visible: list[tuple[str, str, bool, bool]]
    cross: bool


def view(mode: str) -> View:
    spec = MODES[mode]
    vis = [n for n in NODES if spec.get(n[1], False)]
    if mode == "gateway":
        # 网关只看得见模型 HTTP 调用；子 agent 的三个模型调用在另一个进程，
        # 但网关在链路上，所以照样看得见（只是拿不到父子关系）
        vis = [n for n in NODES if n[2]]
    return View(mode, vis, bool(spec["cross"]))


def answers(v: View) -> dict[str, str]:
    """每一列：这个视角能不能回答那个问题。"""
    model_calls = sum(1 for n in v.visible if n[2])
    steps = len(v.visible)
    if v.mode == "gateway":
        return {
            "花了多少钱": f"能（{model_calls} 次模型调用）",
            "哪一步最慢": "不能（只有 HTTP 调用，没有步骤名）",
            "为什么失败": "不能（看不到工具与审批）",
            "改动变好了吗": "部分（只能比总 token 与总时长）",
            "能不能复现": "部分（有请求体，没有内部状态）",
        }
    return {
        "花了多少钱": f"能（{model_calls} 次模型调用）",
        "哪一步最慢": f"能（{steps} 个节点）",
        "为什么失败": "能（按步骤下钻）",
        "改动变好了吗": "能（需带 prompt 版本）",
        "能不能复现": "能（带 trace_id + 版本）" if v.cross else "同进程能，跨进程会断",
    }


def pad(text: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    print("=== 1. 同一份运行，三种接入分别看得见几个节点 ===")
    print("  " + pad("节点", 24) + pad("类型", 10) + pad("sdk", 8) + pad("otel", 8) + "gateway")
    for name, kind, http, other_proc in NODES:
        marks = []
        for m in ("sdk", "otel", "gateway"):
            vis = {n[0] for n in view(m).visible}
            marks.append("可见" if name in vis else "—")
        print("  " + pad(name, 24) + pad(kind, 10)
              + "".join(pad(x, 8) for x in marks))

    print()
    print("=== 2. 每个视角能回答哪几个问题 ===")
    print("  " + pad("接入方式", 12) + pad("可见节点", 10) + pad("跨进程", 10) + "回答")
    for m in ("sdk", "otel", "gateway"):
        v = view(m)
        a = answers(v)
        ok = [q for q in QUESTIONS if not a[q].startswith("不能")]
        print("  " + pad(m, 12) + pad(str(len(v.visible)), 10)
              + pad("自动" if v.cross else "要手传", 10) + f"{len(ok)}/5 个问题")

    print()
    for m in ("sdk", "otel", "gateway"):
        print(f"  [{m}]")
        for q in QUESTIONS:
            print(f"    {pad(q, 18)}{answers(view(m))[q]}")
        print()

    print("=== 3. 同一段代码三种接入的改动量 ===")
    cost = [
        ("sdk", "每个入口加装饰器；子进程显式传 trace_id", "一条运行约 6 处"),
        ("otel", "启动处初始化 exporter；每步开 span", "一处初始化 + 每步"),
        ("gateway", "只改 base_url 与 key", "零代码，无内部步骤"),
    ]
    print("  " + pad("方式", 12) + pad("改哪里", 44) + "改动量")
    for a, b, c in cost:
        print("  " + pad(a, 12) + pad(b, 44) + c)
    print("  <- 侵入性越低的接入，覆盖范围越窄；这不是实现问题，是观测点的位置决定的")


if __name__ == "__main__":
    main()
