"""第 15 章 step2：手写 SKILL.md 解析器 + 三层渐进式加载（离线）。

运行：
    python code/ch15_skills/step2_progressive_loader.py

上一级的痛点（step1）：你知道渐进式加载能省 token。但怎么实现？

这一级做什么：真的去读 `skills/` 目录下的 SKILL.md 文件，实现三层加载：

  L1 元数据  → 解析 YAML frontmatter，只取 name + description（常驻）
  L2 正文    → 命中的技能才读全文
  L3 资源    → 技能目录下的 scripts/ 或 references/，用到才读

  · 这是 Harness 加载 skills 的**真实机制**，不是比喻
  · 关键：description 是「触发门牌」—— 写得不好，技能永远不会被加载
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


SKILLS_DIR = Path(__file__).parent / "skills"


def token_of(text: str) -> int:
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(text) - han
    return int(han * 0.95 + other / 3.2)


# ============================================================ 解析 frontmatter
def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """拆出 YAML frontmatter 和正文。

    真实实现会用 PyYAML；这里手写，因为 frontmatter 只有「key: value」这一层。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    raw_meta, body = m.group(1), m.group(2)
    meta: dict[str, str] = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, body


# ============================================================ L1：扫目录，只读元数据
@dataclass
class SkillMeta:
    name: str
    description: str
    path: Path
    version: str = ""
    allowed_tools: str = ""


def scan_skills(root: Path) -> list[SkillMeta]:
    """只读 frontmatter，**不读正文**。这是 L1。

    注意：这里必须只读头部。如果这里就读了全文，渐进式加载就失效了。
    """
    out: list[SkillMeta] = []
    for md in sorted(root.glob("*/SKILL.md")):
        head = md.read_text(encoding="utf-8")
        meta, _ = parse_frontmatter(head)
        if not meta.get("name") or not meta.get("description"):
            continue  # 缺元数据的技能直接跳过，不报错
        out.append(
            SkillMeta(
                name=meta["name"],
                description=meta["description"],
                path=md,
                version=meta.get("version", ""),
                allowed_tools=meta.get("allowed-tools", ""),
            )
        )
    return out


# ============================================================ L2：命中才读正文
@dataclass
class LoadedSkill:
    meta: SkillMeta
    body: str
    resources: list[str] = field(default_factory=list)


def load_skill(meta: SkillMeta) -> LoadedSkill:
    """读全文。这是 L2 —— 只有命中的技能才会走到这里。"""
    text = meta.path.read_text(encoding="utf-8")
    _, body = parse_frontmatter(text)
    res_dir = meta.path.parent / "references"
    resources = [p.name for p in res_dir.glob("*")] if res_dir.exists() else []
    return LoadedSkill(meta=meta, body=body.strip(), resources=resources)


# ============================================================ 触发判定
def is_triggered(description: str, user_msg: str) -> bool:
    """判断一句话会不会触发这个技能。

    真实实现是让模型看 description 判断；这里用关键词模拟，
    因为要测的是「description 写得好不好」，不是模型强不强。
    """
    # description 里「当用户说 X、Y、Z 时用」这部分是关键
    m = re.search(r"当用户(?:说|要求|提到)(.*?)时用", description)
    if not m:
        # 没有明确的触发条件 —— 这是个坏 description
        return False
    triggers = re.split(r"[、，,/]", m.group(1))
    triggers = [t.strip() for t in triggers if t.strip()]
    return any(t in user_msg for t in triggers)


# ============================================================ 主流程
def main() -> None:
    metas = scan_skills(SKILLS_DIR)

    print("=" * 90)
    print(f"① L1 扫描：只读 frontmatter，发现 {len(metas)} 个技能")
    print("=" * 90)
    l1_text = []
    for m in metas:
        line = f"{m.name}: {m.description}"
        l1_text.append(line)
        print(f"  {m.name:<14}v{m.version:<8}{token_of(line):>4} token")
    l1 = token_of("\n".join(l1_text))
    print(f"\n  L1 常驻成本合计：{l1} token")

    print("\n" + "=" * 90)
    print("② 对照：如果把所有技能正文都塞进去")
    print("=" * 90)
    full = sum(token_of(s.body) for s in (load_skill(m) for m in metas))
    print(f"  全塞：{l1} + {full} = {l1 + full} token")
    print(f"  L1 only：{l1} token")
    print(f"  → L1 是全塞的 {l1 / (l1 + full):.0%}，省 {1 - l1 / (l1 + full):.0%}")

    print("\n" + "=" * 90)
    print("③ 真实对话：一句话进来，看它加载了什么")
    print("=" * 90)

    CASES = [
        "帮我 review 一下这个改动",
        "把这个服务部署到 staging",
        "接口变慢了，P99 从 200ms 涨到 2s",
        "帮我写一个快排",
        "今天天气怎么样",
    ]

    total_loaded_tokens = 0
    for q in CASES:
        hits = [m for m in metas if is_triggered(m.description, q)]
        print(f"\n  用户：{q}")
        if not hits:
            print(f"    → 没命中任何技能，只用 L1（{l1} token）")
            total_loaded_tokens += l1
            continue
        body_tokens = 0
        for m in hits:
            sk = load_skill(m)
            cost = token_of(sk.body)
            body_tokens += cost
            print(f"    → 命中 {m.name}（L2 加载正文 {cost} token）")
            # 只展示前 2 行，证明真的读到了正文
            for line in sk.body.splitlines()[:3]:
                if line.strip():
                    print(f"       | {line.strip()[:60]}")
        total_loaded_tokens += l1 + body_tokens
        print(f"    → 本次上下文 = L1 {l1} + 正文 {body_tokens} = {l1 + body_tokens} token")

    print("\n" + "=" * 90)
    print("④ 算总账：5 句话，全塞 vs 渐进式")
    print("=" * 90)
    n = len(CASES)
    full_cost = (l1 + full) * n
    print(f"  全塞：每句 {(l1 + full)} token × {n} 句 = {full_cost} token")
    # 渐进式：L1 每次都在，正文只在命中时加载
    progressive = 0
    for q in CASES:
        progressive += l1
        for m in metas:
            if is_triggered(m.description, q):
                progressive += token_of(load_skill(m).body)
    print(f"  渐进：{progressive} token")
    print(f"  → 省 {1 - progressive / full_cost:.0%}")

    print("\n" + "=" * 90)
    print("⑤ description 是「触发门牌」—— 写不好等于没写")
    print("=" * 90)
    good = "审查代码改动，找出高风险问题。当用户要求 review、检查 diff、看看有没有问题时用。"
    bad1 = "代码审查技能。"                      # 没有触发条件
    bad2 = "一个用来帮助审查代码的实用技能。"     # 同样没有触发条件
    for label, d in (("好", good), ("坏①", bad1), ("坏②", bad2)):
        hits = sum(1 for q in CASES if is_triggered(d, q))
        print(f"  {label:<6}{hits} / {len(CASES)} 句能触发   {d[:35]}…")
    print()
    print("  坏的 description 不是「效果差一点」，是**永远不加载**。")
    print("  因为模型只能靠这几十个字判断「现在该不该用这个技能」。")
    print()
    print("  好 description 的三段式：")
    print("    ① 做什么    「审查代码改动，找出高风险问题」")
    print("    ② 何时用    「当用户要求 review、检查 diff 时用」← 最关键")
    print("    ③ 何时不用  「不适用于写新代码」← 防止误触发")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print(f"  · L1 只占全塞的 {l1 / (l1 + full):.0%}，剩下 {1 - l1 / (l1 + full):.0%} 靠「命中才读」。")
    print(f"  · 5 句话实测省 {1 - progressive / full_cost:.0%}。")
    print("  · 三层加载的实现就是三步文件读取：glob 头部 → read 全文 → glob 资源。")
    print("  · **description 写不好 = 技能永远不被触发**，这是最常见的失效原因。")
    print()
    print("  下一级（step3）：把技能装进 Agent 循环，看它真的改变行为。")

    assert l1 < l1 + full
    assert progressive < full_cost


if __name__ == "__main__":
    main()
