"""第 20 章 · 第 3 级：Reflexion —— 把教训存下来，下个任务直接用。

运行：
    python code/ch20_reflection/step3_reflexion.py

新增的一个概念：**教训（lesson）跨任务复用**。

第 2 级的反思只对"这一次"有用：下一个任务还得重新试一遍、再被裁判打回一次。
Reflexion 多了一步：失败后写一条**条件化的经验**，塞进下一次的提示词。

两个必须注意的工程点（本章 20.5 节详述）：
  · 教训必须**有验证条件**，不能写成绝对规则（否则换个场景全错）
  · 教训必须**有上限**，否则越攒越脏
"""
from __future__ import annotations

import json
import re

TASKS = [
    "耳机 12.99 元，运费 3 元。",
    "会员 99 元，加购 20 元。",
    "押金 10 元，手续费 1.5 元。",
]


def truth_of(text: str) -> list[int]:
    return [int(round(float(n) * 100)) for n in re.findall(r"(\d+(?:\.\d+)?)\s*元", text)]


def verify(output: str, truth: list[int]) -> tuple[bool, str]:
    try:
        got = json.loads(output)["amounts_in_cents"]
    except Exception:  # noqa: BLE001
        return False, "不是合法 JSON 或缺少 amounts_in_cents"
    if sorted(got) != sorted(truth):
        return False, f"数值不符：期望 {truth}，实际 {got}"
    return True, "通过"


# ---------------------------------------------------------------- 教训库

class LessonStore:
    """教训库：有上限、有命中计数、有验证条件。

    为什么每条教训都要带 `when`？
    因为"所有金额都 ×100"这种绝对规则，换个任务（要求输出元）就全错。
    教训必须是条件规则：「当要求输出分为单位时，金额要 ×100」。
    """

    def __init__(self, limit: int = 5) -> None:
        self.limit = limit
        self.items: list[dict] = []          # {"when": ..., "rule": ..., "hits": int}

    def add(self, when: str, rule: str) -> None:
        if any(i["rule"] == rule for i in self.items):
            return
        self.items.append({"when": when, "rule": rule, "hits": 0})
        if len(self.items) > self.limit:
            # 淘汰"最没被用到"的那条
            self.items.sort(key=lambda i: i["hits"])
            self.items.pop(0)

    def render(self) -> str:
        if not self.items:
            return ""
        lines = [f"- 当 {i['when']} 时：{i['rule']}" for i in self.items]
        return "\n\n【过往教训（条件规则，先核对是否适用）】\n" + "\n".join(lines)

    def hit(self, rule: str) -> None:
        for i in self.items:
            if i["rule"] == rule:
                i["hits"] += 1


# ---------------------------------------------------------------- 模型

class ModelWithLessons:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        text = re.search(r"文本：(.+)", prompt)
        txt = text.group(1) if text else ""
        nums = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)\s*元", txt)]
        knows_rule = "×100" in prompt
        vals = [int(round(n * 100)) for n in nums] if knows_rule else nums
        return json.dumps({"amounts_in_cents": vals})


def run_task(text: str, model: ModelWithLessons, store: LessonStore) -> dict:
    prompt = f"把金额换算成分，JSON 输出。文本：{text}" + store.render()
    for round_no in range(1, 4):
        out = model(prompt)
        ok, fb = verify(out, truth_of(text))
        if ok:
            return {"ok": True, "rounds": round_no}
        # 写一条**条件化**的教训，并带上裁判给的具体错误
        store.add(when="要求输出以「分」为单位的 JSON", rule=f"金额要 ×100（上次错误：{fb}）")
        prompt = (f"把金额换算成分，JSON 输出。文本：{text}" + store.render()
                  + f"\n\n你上次的输出：{out}\n校验未通过：{fb}\n请修正。")
    return {"ok": False, "rounds": 3}


def main() -> None:
    print("=" * 72)
    print("第 3 级：Reflexion（教训跨任务复用）")
    print("=" * 72)

    store = LessonStore(limit=5)
    model = ModelWithLessons()
    total = 0

    for i, text in enumerate(TASKS, 1):
        r = run_task(text, model, store)
        first_round_ok = r["rounds"] == 1
        total += r["rounds"]
        print(f"  任务{i}: 首轮{'✅成功' if first_round_ok else '❌失败'} "
              f"轮数={r['rounds']} 教训数={len(store.items)}")

    print(f"\n  三个任务总轮数：{total}（平均 {total / len(TASKS):.2f} 轮/任务）")
    print("\n  教训库内容：")
    for it in store.items:
        print(f"    · 当 {it['when']} 时：{it['rule'][:60]}")

    print("\n" + "=" * 72)
    print("和上一级比，差在哪")
    print("=" * 72)
    print("  · 第 2 级：每个任务都要被裁判打回一次 → 6 轮 / 3 个任务")
    print("  · 第 3 级：第一个任务交学费，后面直接命中 → 4 轮 / 3 个任务")
    print("  · 任务越多，差距越大 —— 这就是 Reflexion 适合「重复性任务」的原因")
    print()
    print("  ⚠️ 但注意：教训库是**新的风险面**。")
    print("     · 教训写错了（无条件规则）→ 以后每个任务都错")
    print("     · 教训没有隔离（跨用户共享）→ 数据泄露")
    print("     · 教训没有上限 → 上下文爆炸 + 互相矛盾")
    print("     所以每条都要带「当……时」这个前提，第 27 章会讲怎么治理。")


if __name__ == "__main__":
    main()
