"""第 7 章产出：三种反思，从最没用到最有用。

核心结论（本章要证明的）：
  1. 纯自我反思（模型评自己）——几乎无效，还增加成本
  2. 带外部信号的反思（测试/规则/检索）——有效
  3. Reflexion（把失败教训写进记忆，下次带着教训做事）——对重复性任务有效

实验设计：用一个"有明确正确答案"的任务（算数/格式校验），
这样"反思是否有效"可以用对错率来衡量，而不是靠感觉。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable


# ============================================================ 任务与外部信号

TASK_PROMPT = """请把下面这段话里的金额全部换算成"分"（1元=100分），
并以 JSON 输出：{{"amounts_in_cents": [...]}}

文本：{text}"""


def ground_truth(text: str) -> list[int]:
    """标准答案：正则抽金额，×100。这就是"外部信号"——它不依赖模型判断。"""
    nums = re.findall(r"(\d+(?:\.\d+)?)\s*元", text)
    return [int(round(float(n) * 100)) for n in nums]


def check_format(output: str) -> tuple[bool, str]:
    """外部信号 1：格式必须合法 JSON 且字段正确。"""
    try:
        data = json.loads(output)
    except json.JSONDecodeError as e:
        return False, f"输出不是合法 JSON：{e}"
    if "amounts_in_cents" not in data:
        return False, "缺少字段 amounts_in_cents"
    if not isinstance(data["amounts_in_cents"], list):
        return False, "amounts_in_cents 必须是数组"
    return True, "格式正确"


def check_values(output: str, truth: list[int]) -> tuple[bool, str]:
    """外部信号 2：数值必须与标准答案一致。

    这就是"有外部信号"和"没有外部信号"的分水岭：
    模型自己写反思时，它无法判断 1299 和 12.99 哪个对；
    而 ground_truth 可以。
    """
    try:
        got = json.loads(output)["amounts_in_cents"]
    except Exception:  # noqa: BLE001
        return False, "无法解析输出"
    if sorted(got) != sorted(truth):
        return False, f"数值不符：期望 {truth}，实际 {got}"
    return True, "数值正确"


# ============================================================ 三种反思实现

@dataclass
class Attempt:
    n: int
    output: str
    ok: bool
    feedback: str


@dataclass
class ReflectionLoop:
    """统一的反思循环，通过 mode 切换三种策略。

    这个设计让你能**用同一批数据**跑三种策略，直接对比——
    而不是"我感觉加了反思好像好了点"。
    """

    llm: Callable[[str], str]
    mode: str  # "none" | "self" | "external" | "reflexion"
    max_rounds: int = 3
    lessons: list[str] = field(default_factory=list)

    def run(self, text: str) -> dict[str, Any]:
        truth = ground_truth(text)
        attempts: list[Attempt] = []
        prompt = TASK_PROMPT.format(text=text)

        if self.mode == "reflexion" and self.lessons:
            prompt += "\n\n【过往教训，务必遵守】\n" + "\n".join(f"- {l}" for l in self.lessons)

        for i in range(self.max_rounds):
            out = self.llm(prompt)
            ok, fb = check_format(out)
            if ok:
                ok, fb = check_values(out, truth)
            attempts.append(Attempt(i + 1, out, ok, fb))

            if ok:
                break

            if self.mode == "none":
                break  # 不反思：错了就错了

            if self.mode == "self":
                # 纯自我反思：模型评自己，没有外部信号
                prompt += f"\n\n你上次的输出：{out}\n请仔细检查并修正可能的错误。"
            elif self.mode == "external":
                # 带外部信号：把校验器的具体错误告诉它
                prompt += f"\n\n你上次的输出：{out}\n校验未通过：{fb}\n请修正后重新输出。"
            elif self.mode == "reflexion":
                # 把教训沉淀下来（跨任务复用）
                lesson = f"输出必须严格是 JSON，且金额已转换为分（{fb}）"
                if lesson not in self.lessons:
                    self.lessons.append(lesson)
                prompt = TASK_PROMPT.format(text=text)
                prompt += "\n\n【过往教训，务必遵守】\n" + "\n".join(f"- {l}" for l in self.lessons)

        return {
            "mode": self.mode,
            "rounds": len(attempts),
            "success": attempts[-1].ok,
            "attempts": attempts,
            "lessons": list(self.lessons),
        }


# ============================================================ 模拟模型

class MockModel:
    """模拟一个"第一次总犯错"的模型。

    为什么要模拟？因为真实模型的随机性会让对比实验不可复现。
    这里把"错误模式"固定下来，你就能确定地看到三种反思的差异。
    """

    def __init__(self, fail_mode: str = "cents") -> None:
        self.calls = 0
        self.fail_mode = fail_mode

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        text = re.search(r"文本：(.+)", prompt)
        txt = text.group(1) if text else ""
        nums = re.findall(r"(\d+(?:\.\d+)?)\s*元", txt)

        has_feedback = "校验未通过" in prompt
        has_lesson = "过往教训" in prompt

        # 只有在"收到具体错误反馈"或"有过往教训"时，才修正
        fixed = has_feedback or has_lesson

        if self.fail_mode == "cents":
            vals = [int(round(float(n) * 100)) for n in nums] if fixed else [float(n) for n in nums]
            return json.dumps({"amounts_in_cents": vals}, ensure_ascii=False)

        if self.fail_mode == "format":
            if fixed:
                return json.dumps({"amounts_in_cents": [int(round(float(n) * 100)) for n in nums]})
            return f"金额分别是 {nums}（已换算为分）"  # 天然语言，不是 JSON

        return ""
