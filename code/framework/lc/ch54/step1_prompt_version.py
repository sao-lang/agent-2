"""第 54 章 step1：提示词是资产——版本、对比、回滚（离线）。

运行：
    python code/framework/lc/ch54/step1_prompt_version.py

第 42–45 章的痛点：
    你已经会用 ChatPromptTemplate 了。但提示词还是"写在代码里的一段字符串"：
    改一个字要发版、出了事没法回滚、两个版本效果差多少说不清。

这一级做什么：
    ① 把提示词从代码里抽出来，变成带版本号的文件
    ② 同一份评测集，跑两个版本，输出**逐条对比**（不是只看总分）
    ③ 一条命令回滚（因为旧版本文件还在）

关键原则：
    提示词的版本号不是"给领导看的"，是"回滚的坐标"。
    所以必须满足：**任何一版都能原样重跑**。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"


# ---------------------------------------------------------------- 提示词注册表
@dataclass
class PromptVersion:
    name: str
    version: str
    text: str
    tags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"


class PromptRegistry:
    """目录即注册表：prompts/{name}/{version}.json

    为什么用文件而不是数据库？
      · 能进 git：diff 可读、能 review、能 blame
      · 能回滚：checkout 到旧 tag 就行
      · 不需要服务：本地、CI、生产用同一套
    数据库方案适合"非技术人员也要改"的场景，那时再加。
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self, name: str, version: str = "latest") -> PromptVersion:
        folder = self.root / name
        if not folder.exists():
            raise FileNotFoundError(f"提示词不存在：{folder}")
        if version == "latest":
            versions = sorted(p.stem for p in folder.glob("v*.json"))
            if not versions:
                raise FileNotFoundError(f"{folder} 下没有 v*.json")
            version = versions[-1]
        path = folder / f"{version}.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        return PromptVersion(name, version, cfg["text"], cfg.get("tags", []))

    def list_versions(self, name: str) -> list[str]:
        return sorted(p.stem for p in (self.root / name).glob("v*.json"))


# ---------------------------------------------------------------- 极简评测
CASES = [
    ("我要退款，东西坏了", "可退"),
    ("用了半年了还能退吗", "不可退"),
    ("发票开错了", "需人工"),
    ("优惠券能退回来吗", "需人工"),
]


def run_case(behavior: dict[str, str], q: str) -> str:
    """用剧本模拟模型在某一版提示词下的输出。

    真实项目这里是：
        chain = chat_prompt_from(prompt) | llm | StrOutputParser()
        return chain.invoke({"q": q})
    """
    return behavior.get(q, "需人工")


@dataclass
class Score:
    correct: int = 0
    total: int = 0
    details: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def acc(self) -> float:
        return self.correct / self.total if self.total else 0.0


def evaluate(behavior: dict[str, str], cases: list[tuple[str, str]]) -> Score:
    s = Score()
    for q, want in cases:
        got = run_case(behavior, q)
        s.total += 1
        if got == want:
            s.correct += 1
        s.details.append((q, want, got))
    return s


def main() -> None:
    # 造两个版本（真实项目里这是两次 git commit）
    (PROMPT_DIR / "refund").mkdir(parents=True, exist_ok=True)
    (PROMPT_DIR / "refund" / "v1.json").write_text(json.dumps({
        "text": "你是售后助手。判断用户能否退款，只回答：可退 / 不可退 / 需人工。\n用户：{q}",
        "tags": ["baseline"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (PROMPT_DIR / "refund" / "v2.json").write_text(json.dumps({
        "text": ("你是售后助手。判断用户能否退款。\n"
                 "规则：1) 7 天内无理由可退；2) 超过 7 天且非质量问题不可退；"
                 "3) 涉及发票、优惠券一律需人工。\n"
                 "只回答：可退 / 不可退 / 需人工。\n用户：{q}"),
        "tags": ["baseline", "add-rules"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    reg = PromptRegistry(PROMPT_DIR)
    v1 = reg.load("refund", "v1")
    v2 = reg.load("refund", "v2")

    print("=" * 78)
    print("① 提示词注册表：目录即版本库")
    print("=" * 78)
    print(f"  refund 的版本：{reg.list_versions('refund')}")
    for p in (v1, v2):
        print(f"  {p.key:<16} tags={p.tags}  {len(p.text)} 字符")

    print("\n" + "=" * 78)
    print("② 两个版本跑同一份评测集：逐条对比，不只看总分")
    print("=" * 78)

    # 模拟模型行为：v1 缺少规则 → 发票/优惠券判错；v2 补了规则 → 判对
    behavior = {
        "v1": {
            "我要退款，东西坏了": "可退",
            "用了半年了还能退吗": "不可退",
            "发票开错了": "不可退",       # ← 错：应该是需人工
            "优惠券能退回来吗": "可退",   # ← 错：应该是需人工
        },
        "v2": {
            "我要退款，东西坏了": "可退",
            "用了半年了还能退吗": "不可退",
            "发票开错了": "需人工",
            "优惠券能退回来吗": "需人工",
        },
    }
    s1 = evaluate(behavior["v1"], CASES)
    s2 = evaluate(behavior["v2"], CASES)

    print(f"  {'问题':<22}{'期望':<8}{'v1':<8}{'v2':<8}变化")
    print("  " + "-" * 68)
    for (q, want, got1), (_, _, got2) in zip(s1.details, s2.details):
        mark = "✓ 修好" if got1 != want and got2 == want else (
            "✗ 改坏" if got1 == want and got2 != want else "")
        print(f"  {q[:20]:<22}{want:<8}{got1:<8}{got2:<8}{mark}")

    print(f"\n  准确率：v1 {s1.acc:.0%} → v2 {s2.acc:.0%}（{s2.acc - s1.acc:+.0%}）")
    print("  → 看逐条表才知道：v2 修好了 2 条、没改坏任何一条。")
    print("    **只看总分**的话，你无法判断这次改动是'修好 2 条'还是'修好 3 条又改坏 1 条'。")

    print("\n" + "=" * 78)
    print("③ 回归门禁：新版本不允许在旧用例上退步")
    print("=" * 78)
    regressed = [(q, w, g2) for (q, w, g1), (_, _, g2) in zip(s1.details, s2.details)
                 if g1 == w and g2 != w]
    print(f"  回归条数：{len(regressed)}")
    for q, w, g in regressed:
        print(f"    {q} 期望 {w}，v2 给了 {g}")
    print(f"  门禁判定：{'PASS' if not regressed else 'FAIL'}")

    print("\n  门禁规则（建议直接抄进 CI）：")
    print("    [ ] 新版本在**全部旧用例**上不得退步（regressed == 0）")
    print("    [ ] 总准确率不得下降")
    print("    [ ] 新增用例（这次踩的坑）必须写进用例集")
    print("  → 第一条最硬：允许'这次没提升'，不允许'这次弄坏了别的'。")

    print("\n" + "=" * 78)
    print("④ 回滚：因为旧版本文件还在")
    print("=" * 78)
    print("  线上出问题 → 改一行配置：load('refund', 'v1')")
    print("  → 前提是：**v1.json 没被删**。所以永远不要原地修改提示词文件，只能新增版本。")
    print("  → 常见错误：把 v1.json 改了内容却还叫 v1 —— 那就没法回滚了。")


if __name__ == "__main__":
    main()
