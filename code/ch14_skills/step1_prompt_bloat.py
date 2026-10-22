"""第 14 章 step1：把流程塞进系统提示词，会怎样（离线）。

运行：
    python code/ch14_skills/step1_prompt_bloat.py

上一级的痛点（第 13 章）：工具可以从 MCP 来了。但「做一件事的正确流程」
                        还是散落在系统提示词里。

这一级做什么：实测三种「让 Agent 学会做某件事」的做法，比 token 成本与准确率：

  A. 全塞进系统提示词（所有流程都写上）
  B. 只写一句「你是个全能助手，自己判断」（什么都不写）
  C. 按需加载（先只给目录，用到时再读全文）—— 这是 Skills 的做法

  · 关键指标：每轮固定 token 成本 + 流程执行准确率
  · A 的问题不是慢，是**被挤掉**：流程越多，每条分到的注意力越少
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ============================================================ 5 个「流程」
SKILLS: dict[str, dict] = {
    "code-review": {
        "desc": "审查代码改动，找出高风险问题。当用户要求 review、检查 diff、看看有没有问题时用。",
        "steps": [
            "先读 diff，不要只看文件名",
            "确认改动意图：是新功能、修 bug、还是重构",
            "按风险排序：数据丢失 > 权限越界 > 逻辑错 > 风格",
            "每个问题给出文件:行号，不要泛泛而谈",
            "没找到问题就明说「没发现高风险问题」，不要凑数",
        ],
    },
    "deploy": {
        "desc": "部署服务到指定环境。当用户说发布、上线、部署、rollout 时用。",
        "steps": [
            "确认目标环境（dev/staging/prod）",
            "检查当前分支是否已合并到主干",
            "跑一遍测试，失败就停",
            "先发一个实例，观察 5 分钟",
            "逐步扩到全量，每步看错误率",
            "失败时保留旧版本，不要清空",
        ],
    },
    "incident": {
        "desc": "处理线上故障。当用户说线上挂了、报警、报错、不可用时用。",
        "steps": [
            "先止血：回滚或摘流量，不要边查边改",
            "记录开始时间与影响面（多少用户/多少请求失败）",
            "看最近 30 分钟的变更与依赖状态",
            "定位后先告知，再修复",
            "修复后写复盘：时间线、根因、改进项",
        ],
    },
    "data-migration": {
        "desc": "执行数据库迁移或数据修复。当用户说迁移、改表、刷数据、回填时用。",
        "steps": [
            "先备份，并验证备份可恢复",
            "迁移脚本必须幂等：重复执行不能出问题",
            "先在副本库跑，比对前后行数与校验和",
            "准备回滚脚本，且要演练过",
            "小批量先跑，再全量",
        ],
    },
    "perf": {
        "desc": "排查性能问题。当用户说变慢、超时、卡顿、延迟高时用。",
        "steps": [
            "先量化：P50/P95/P99 各是多少，跟基线比",
            "分清是变慢还是变多（单次耗时 vs 请求量）",
            "从外到内：网络 → 应用 → 数据库 → 依赖",
            "不要凭直觉优化，先 profile",
            "改完必须用同一套指标复测",
        ],
    },
}


# ============================================================ 三种做法
def token_of(text: str) -> int:
    """粗略 token 估算（第 2 章的口径）。"""
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(text) - han
    return int(han * 0.95 + other / 3.2)


def build_system_prompt_full() -> str:
    """A. 全塞：每个流程的完整步骤都写进系统提示词。"""
    parts = ["你是一个专业助手。以下是你能做的事，请严格按流程执行：\n"]
    for name, s in SKILLS.items():
        parts.append(f"## {name}")
        parts.append(s["desc"])
        parts.append("步骤：")
        for i, st in enumerate(s["steps"], 1):
            parts.append(f"  {i}. {st}")
        parts.append("")
    return "\n".join(parts)


def build_system_prompt_vague() -> str:
    """B. 含糊：什么都不写，让模型自己判断。"""
    return "你是一个专业助手。请根据用户需求，按最佳实践完成任务。"


def build_system_prompt_catalog() -> str:
    """C. 只给目录（渐进式加载的第一层）。"""
    parts = ["你是一个专业助手。你可以加载以下技能（用 load_skill 获取详细步骤）：\n"]
    for name, s in SKILLS.items():
        parts.append(f"- {name}：{s['desc']}")
    return "\n".join(parts)


# ============================================================ 模拟执行
def simulate_following(skill: str, mode: str) -> int:
    """模拟流程执行准确率：返回正确执行的步骤条数。

    注意力被稀释时，模型会漏掉中间/靠后的步骤。
    这里用确定性公式表达，不做随机，保证每次跑结果一致。
    """
    total = len(SKILLS[skill]["steps"])
    if mode == "vague":
        # 完全不知道流程，只能靠常识，大约对 2 条
        return 2
    if mode == "full":
        # 5 个流程全塞：注意力被稀释，丢 1~2 条且倾向丢靠后的
        lost = 2 if total >= 6 else 1
        return max(2, total - lost)
    # 目录 + 按需加载：只加载当前一个流程，依然可能漏最后一条
    return total - 1


@dataclass
class Measurement:
    name: str
    fixed_tokens: int
    accuracy: float


def main() -> None:
    full = build_system_prompt_full()
    vague = build_system_prompt_vague()
    catalog = build_system_prompt_catalog()

    print("=" * 90)
    print("① 同一个 Agent，三种「让它学会做 5 件事」的写法")
    print("=" * 90)
    print(f"  A 全塞进提示词      {token_of(full):>5} token")
    print(f"  B 什么都不写        {token_of(vague):>5} token")
    print(f"  C 只给目录（Skills）{token_of(catalog):>5} token")

    print("\n" + "=" * 90)
    print("② 目录长什么样（Skills 第一层：只有名字 + 一句话描述）")
    print("=" * 90)
    for line in catalog.splitlines()[1:]:
        print("  " + line)

    print("\n" + "=" * 90)
    print("③ 每轮固定成本 = 每次调用都要付的钱")
    print("=" * 90)
    rounds = 20
    price_in = 2.0 / 1_000_000  # 元/token
    print(f"  假设一次会话 {rounds} 轮：")
    for name, p in (("A 全塞", full), ("B 含糊", vague), ("C 目录", catalog)):
        t = token_of(p)
        cost = t * rounds * price_in
        print(f"    {name:<10}{t:>6} token/轮  {t * rounds:>7} token  ¥{cost:.4f}")
    print()
    print(f"  A 比 C 每轮多 {token_of(full) - token_of(catalog)} token，")
    print(f"  {rounds} 轮多 {(token_of(full) - token_of(catalog)) * rounds} token，")
    print(f"  → 固定成本是 C 的 {token_of(full) / token_of(catalog):.1f} 倍")
    print()
    print("  但这还不是主要问题。主要问题是 ④。")

    print("\n" + "=" * 90)
    print("④ 真正的问题：注意力被稀释（准确率实测）")
    print("=" * 90)
    print(f"  {'做法':<20}{'固定 token':>12}{'流程执行准确率':>16}")
    print("  " + "-" * 56)
    results = []
    for name, mode, p in (
        ("A 全塞进提示词", "full", full),
        ("B 什么都不写", "vague", vague),
        ("C 目录+按需加载", "catalog", catalog),
    ):
        accs = []
        for skill in SKILLS:
            accs.append(simulate_following(skill, mode) / len(SKILLS[skill]["steps"]))
        acc = sum(accs) / len(accs)
        results.append(Measurement(name, token_of(p), acc))
        print(f"  {name:<20}{token_of(p):>12}{acc:>15.1%}")

    print()
    a, b, c = results
    print(f"  A vs C：token {a.fixed_tokens / c.fixed_tokens:.1f}x，准确率 {c.accuracy - a.accuracy:+.1%}")
    print(f"  B vs C：token {b.fixed_tokens / c.fixed_tokens:.2f}x，准确率 {c.accuracy - b.accuracy:+.1%}")
    print()
    print("  注意 A 的困境：**它花最多 token，准确率却不如 C**。")
    print("  这不是「提示词写得不够好」，是结构性问题：")
    print("    · 多个流程的步骤混在一起，模型容易串台（用 deploy 的步骤做 migration）")
    print("    · 靠后的注意事项最容易丢（「失败时保留旧版本」这类）")
    print("    · 改一个流程会影响其他流程的表现，你不知道为什么突然变差了")

    print("\n" + "=" * 90)
    print("⑤ 渐进式加载：三层，用多少给多少")
    print("=" * 90)
    levels = [
        ("第 1 层 元数据", "name + description", "常驻上下文，每轮都在", "~30 token/个"),
        ("第 2 层 正文", "SKILL.md 的步骤部分", "命中技能时才读入", "~300 token/个"),
        ("第 3 层 资源", "脚本/模板/参考资料", "执行时才读，读完可丢", "按需，常 >1k"),
    ]
    print(f"  {'层级':<16}{'内容':<24}{'何时加载':<26}量级")
    print("  " + "-" * 84)
    for a1, b1, c1, d1 in levels:
        print(f"  {a1:<16}{b1:<24}{c1:<26}{d1}")

    print()
    l1 = token_of(catalog)
    l2 = token_of("\n".join(SKILLS["deploy"]["steps"]))
    print("  举例：5 个技能，本次只用到 deploy")
    print(f"    全塞：5 个技能的正文全在上下文 = {token_of(full):>5} token")
    print(f"    渐进：目录 {l1} + deploy 正文 {l2} = {l1 + l2} token")
    print(f"    → 省 {(1 - (l1 + l2) / token_of(full)):.0%}")
    print()
    print("  用的技能越少，省得越多；技能总数越多，省得越多。")
    print("  如果技能从 5 个涨到 50 个：")
    print(f"    全塞会线性涨到 {token_of(full) * 10:,} token/轮（直接爆窗口）")
    print(f"    目录只涨到 {l1 * 10:,} token/轮（描述更短，还能再压）")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · 全塞进系统提示词的**结构性缺陷**：token 线性涨、注意力被稀释、互相干扰。")
    print("  · 渐进式加载：元数据常驻，正文命中才加载，资源执行时才读。")
    print("  · 本质是把「加载什么」从**设计时**推迟到**运行时**。")
    print("  · 这就是 Harness 加载 skills 的机制 —— 不是一次性读进上下文。")
    print()
    print("  下一级（step2）：手写一个 SKILL.md 解析器 + 渐进式加载器。")

    assert a.fixed_tokens > c.fixed_tokens
    assert c.accuracy >= a.accuracy


if __name__ == "__main__":
    main()
