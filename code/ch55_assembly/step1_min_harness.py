"""第 55 章 step1：最小可跑的 Harness——五层零件串起来（离线）。

运行：
    python code/ch55_assembly/step1_min_harness.py

前面几章你有了散零件：
  · 第 12 章：Tool（怎么调能力）
  · 第 13 章：MCP（能力从哪来）
  · 第 14 章：Skill（流程怎么挑、怎么用）

这一级做什么：写一个约 200 行的 Harness，把五层装起来并跑真实请求：

    Registry（工具从哪来）
      → SkillLoader（流程按需加载）
        → Guard（安全检查）
          → Loop（循环 + 终止条件）
            → Trace（记录每一步）

关键：**每一层都能单独替换**。这才是 Harness 的意义——
不是把代码写在一起，是把边界划清楚。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ============================================================ ① Registry：工具从哪来
@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    fn: Callable[..., Any]
    source: str = "local"  # local / mcp:服务名


class Registry:
    """统一登记本地工具和 MCP 工具。

    要点：**工具来源必须记下来**。出问题时第一个要问的是
    「这个工具是谁提供的」。
    """

    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> None:
        if t.name in self.tools:
            raise ValueError(f"工具重名：{t.name}（已有来自 {self.tools[t.name].source}）")
        self.tools[t.name] = t

    def register_mcp(self, server_name: str, tools: list[dict],
                     handlers: dict[str, Callable]) -> None:
        """从 MCP 的 tools/list 结果批量登记（第 13 章的形状）。"""
        for spec in tools:
            self.register(
                Tool(
                    name=f"{server_name}__{spec['name']}",  # 命名空间前缀
                    description=spec["description"],
                    schema=spec["inputSchema"],
                    fn=handlers[spec["name"]],
                    source=f"mcp:{server_name}",
                )
            )

    def manifest(self, names: list[str] | None = None) -> str:
        """渲染成给模型看的清单（三段式的 ①）。"""
        items = list(self.tools.values()) if names is None else [self.tools[n] for n in names if n in self.tools]
        lines = []
        for t in items:
            props = ", ".join(t.schema.get("properties", {}))
            lines.append(f"- {t.name}({props})：{t.description}")
        return "\n".join(lines)

    def call(self, name: str, args: dict[str, Any]) -> str:
        t = self.tools.get(name)
        if t is None:
            return f"错误：工具 {name} 不存在（可用：{', '.join(self.tools)}）"
        return str(t.fn(**args))


# ============================================================ ② SkillLoader：三层加载
@dataclass
class SkillMeta:
    name: str
    description: str
    path: Path


class SkillLoader:
    """L1 只读 frontmatter；L2 命中才读正文。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.metas: list[SkillMeta] = []
        self._scan()

    def _scan(self) -> None:
        for md in sorted(self.root.glob("*/SKILL.md")):
            meta, _ = self._parse(md.read_text(encoding="utf-8"))
            if meta.get("name") and meta.get("description"):
                self.metas.append(SkillMeta(meta["name"], meta["description"], md))

    @staticmethod
    def _parse(text: str) -> tuple[dict[str, str], str]:
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
        if not m:
            return {}, text
        meta = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        return meta, m.group(2)

    def catalog(self) -> str:
        """L1：常驻系统提示词的部分。"""
        return "\n".join(f"- {m.name}：{m.description}" for m in self.metas)

    def pick(self, user_msg: str) -> SkillMeta | None:
        """判断触发哪个技能（真实实现交给模型；这里用触发词模拟）。"""
        for m in self.metas:
            t = re.search(r"当用户(?:说|要求|提到)(.*?)时用", m.description)
            if not t:
                continue
            if any(k.strip() in user_msg for k in re.split(r"[、，,/]", t.group(1)) if k.strip()):
                return m
        return None

    def load(self, meta: SkillMeta) -> str:
        """L2：读全文（不含 frontmatter）。"""
        _, body = self._parse(meta.path.read_text(encoding="utf-8"))
        return body.strip()

    def allowed_tools(self, meta: SkillMeta) -> list[str]:
        raw, _ = self._parse(meta.path.read_text(encoding="utf-8"))
        return [x.strip() for x in raw.get("allowed-tools", "").split(",") if x.strip()]


# ============================================================ ③ Guard：四层检查
class Guard:
    """第 12 章的四层检查，装进 Harness 的一层。"""

    def __init__(self) -> None:
        self.denied: set[str] = set()

    def check(self, name: str, args: dict[str, Any]) -> str | None:
        """返回 None 表示放行，返回字符串表示拒绝理由。"""
        if name in self.denied:
            return f"工具 {name} 在禁用名单"
        if any(k in name for k in ("delete", "drop", "truncate")):
            return f"工具 {name} 是危险动作，需人工审批"
        return None


# ============================================================ ④ Trace：记录每一步
@dataclass
class Trace:
    steps: list[dict[str, Any]] = field(default_factory=list)

    def add(self, kind: str, **kw: Any) -> None:
        self.steps.append({"kind": kind, **kw})

    def dump(self) -> str:
        out = []
        for i, s in enumerate(self.steps, 1):
            detail = ", ".join(f"{k}={v}" for k, v in s.items() if k != "kind")
            out.append(f"    {i:>2}. [{s['kind']}] {detail}")
        return "\n".join(out)


# ============================================================ ⑤ Loop：装配起来
class Harness:
    def __init__(self, registry: Registry, skills: SkillLoader, guard: Guard) -> None:
        self.registry = registry
        self.skills = skills
        self.guard = guard

    def run(self, user_msg: str, max_steps: int = 5) -> dict[str, Any]:
        trace = Trace()
        trace.add("request", msg=user_msg[:24])

        skill = self.skills.pick(user_msg)
        tool_count = len(self.registry.tools)
        if skill:
            body = self.skills.load(skill)
            allowed = self.skills.allowed_tools(skill)
            narrowed = [n for n in self.registry.tools if any(a in n for a in allowed)]
            tool_count = len(narrowed) if narrowed else tool_count
            trace.add("skill_loaded", name=skill.name, chars=len(body), tools=tool_count)
        else:
            trace.add("skill_loaded", name="无", chars=0, tools=tool_count)

        planned = self._plan(user_msg, skill)
        result_text = "（无操作）"
        finished = False
        for i, (tool, args) in enumerate(planned, 1):
            if i > max_steps:
                trace.add("stop", reason="达到最大步数")
                finished = True
                break
            trace.add("decide", step=i, tool=tool)
            reason = self.guard.check(tool, args)
            if reason:
                trace.add("blocked", tool=tool, reason=reason)
                result_text = f"操作被拦截：{reason}"
                continue
            out = self.registry.call(tool, args)
            trace.add("call", tool=tool, result=out[:26])
            result_text = out
        if not finished:
            trace.add("stop", reason="计划执行完毕")

        return {"skill": skill.name if skill else None, "result": result_text,
                "tools_visible": tool_count, "trace": trace}

    def _plan(self, msg: str, skill: SkillMeta | None) -> list[tuple[str, dict[str, Any]]]:
        """模拟模型决策。真实实现是把 manifest 给模型，让它输出 tool_calls。"""
        if skill and skill.name == "code-review":
            return [("git_diff", {"scope": "staged"}), ("read_file", {"path": "src/user.py"})]
        if skill and skill.name == "deploy":
            return [("run_test", {}), ("deploy_instance", {"env": "prod", "percent": 1})]
        if "订单" in msg:
            return [("order-mcp__query_order_status", {"order_id": "A12345"})]
        if "删" in msg:
            return [("delete_user", {"user_id": "u1"})]
        return []


# ============================================================ 建工具
def build_registry() -> Registry:
    r = Registry()
    r.register(Tool("git_diff", "读取当前 diff",
                    {"type": "object", "properties": {"scope": {"type": "string"}}},
                    lambda scope: f"diff({scope}): +12 -3 in src/user.py"))
    r.register(Tool("read_file", "读文件",
                    {"type": "object", "properties": {"path": {"type": "string"}}},
                    lambda path: f"{path}: 第 42 行有删除逻辑"))
    r.register(Tool("run_test", "跑测试", {"type": "object", "properties": {}},
                    lambda: "48 passed, 0 failed"))
    r.register(Tool("deploy_instance", "部署一个实例",
                    {"type": "object", "properties": {"env": {"type": "string"},
                                                     "percent": {"type": "integer"}}},
                    lambda env, percent: f"已部署 {percent}% 到 {env}"))
    r.register(Tool("delete_user", "删除用户",
                    {"type": "object", "properties": {"user_id": {"type": "string"}}},
                    lambda user_id: f"已删除 {user_id}"))
    r.register_mcp(
        "order-mcp",
        [
            {"name": "query_order_status", "description": "查订单状态",
             "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}}}},
            {"name": "apply_refund", "description": "申请退款",
             "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}}}},
        ],
        {"query_order_status": lambda order_id: f"{order_id} 已签收3天",
         "apply_refund": lambda order_id: f"{order_id} 退款已提交"},
    )
    return r


def main() -> None:
    registry = build_registry()
    skills = SkillLoader(Path(__file__).parent.parent / "ch14_skills" / "skills")
    guard = Guard()
    harness = Harness(registry, skills, guard)

    print("=" * 90)
    print("① Harness 的五层，各管一件事")
    print("=" * 90)
    layers = [
        ("Registry", "工具从哪来", f"{len(registry.tools)} 个（本地 5 + MCP 2）"),
        ("SkillLoader", "流程按需加载", f"L1 目录 {len(skills.metas)} 个技能"),
        ("Guard", "危险动作拦截", "delete/drop/truncate 一律拦"),
        ("Loop", "循环与终止条件", "max_steps=5"),
        ("Trace", "每一步都可查", "request/decide/call/blocked/stop"),
    ]
    for a, b, c in layers:
        print(f"  {a:<14}{b:<18}{c}")

    print("\n" + "=" * 90)
    print("② L1 目录（每轮都在上下文里）")
    print("=" * 90)
    for line in skills.catalog().splitlines():
        print("  " + line)

    print("\n" + "=" * 90)
    print("③ 工具清单（含来源）")
    print("=" * 90)
    for t in registry.tools.values():
        print(f"  {t.name:<30}[{t.source}]")

    print("\n" + "=" * 90)
    print("④ 跑四个真实请求")
    print("=" * 90)
    for msg in ("帮我 review 这个改动", "把这个服务部署到 prod",
                "查一下订单 A12345", "帮我删掉这个用户"):
        r = harness.run(msg)
        print(f"\n  用户：{msg}")
        print(f"    skill: {r['skill']}   可见工具: {r['tools_visible']}")
        print(f"    结果:  {r['result']}")
        print("    trace:")
        print(r["trace"].dump())

    print("\n" + "=" * 90)
    print("⑤ 三个关键设计")
    print("=" * 90)
    print("  ① **每层可单独替换**")
    print("     Registry 换成真实 MCP 客户端 → 其他层不用改")
    print("     SkillLoader 换成从数据库读 → 其他层不用改")
    print("     Guard 换成读策略文件 → 其他层不用改")
    print()
    print("  ② **工具名带来源前缀**（order-mcp__query_order_status）")
    print("     两个 MCP 服务都有 query 时不会冲突")
    print("     日志里一眼看出是谁提供的")
    print()
    print("  ③ **skill 的 allowed-tools 收窄工具集**")
    print("     code-review 只挂 git_diff/read_file，deploy 只挂 run_test/deploy_instance")
    print("     可见工具从 7 个降到 2 个（第 13 章：选对率随之上升）")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · Harness = 五层的**边界**，不是五段代码堆在一起。")
    print("  · 关键在「每层可单独替换」—— 这是能不能长期维护的分水岭。")
    print("  · 装配顺序：Registry → Skill → Guard → Loop → Trace。")
    print("  · trace 不是调试用的奢侈品，它是**唯一的排查依据**。")
    print()
    print("  下一级（step2）：装配错了会怎样 —— 四种典型故障。")

    assert len(registry.tools) == 7
    assert harness.run("帮我删掉这个用户")["result"].startswith("操作被拦截")
    assert harness.run("帮我 review 这个改动")["tools_visible"] == 2


if __name__ == "__main__":
    main()
