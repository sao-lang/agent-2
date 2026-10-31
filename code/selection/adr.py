"""ADR 五段式，以及"没有失效证据就拒绝"的校验。

不联网。校验规则就是本章的门槛：落选方案必须带一条失效证据与一个可观测信号，
回滚点必须写明回到第几级、由哪个数触发。缺一条就不通过。

运行：python code/selection/adr.py
"""

from __future__ import annotations

import re

REQUIRED = ("背景事实", "决定", "落选方案", "代价", "回滚点")


def validate(adr: dict) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED:
        if not adr.get(key):
            errors.append(f"缺少段落：{key}")

    for i, alt in enumerate(adr.get("落选方案", []), 1):
        name = alt.get("方案", f"第{i}个")
        if not alt.get("失效证据"):
            errors.append(f"落选方案『{name}』没有失效证据（只是偏好）")
        if not alt.get("失效信号"):
            errors.append(f"落选方案『{name}』没有可观测的失效信号")
        if not alt.get("失效层"):
            errors.append(f"落选方案『{name}』没说坏在哪一层")

    rollback = adr.get("回滚点", {})
    if not rollback.get("回到"):
        errors.append("回滚点没写回到第几级")
    elif not re.search(r"第\s*\d+\s*级", rollback["回到"]):
        errors.append(f"回滚点『{rollback['回到']}』没写清是第几级")
    trigger = rollback.get("触发数", "")
    if not trigger:
        errors.append("回滚点没写由哪个数触发")
    elif not re.search(r"(\d|率|P95|延迟|成本)", trigger):
        errors.append(f"回滚点触发条件『{trigger}』不可判：没有数或指标")
    return errors


def render(adr: dict) -> str:
    lines = [f"# ADR：{adr['标题']}", ""]
    lines.append("## 背景事实")
    lines += [f"- {x}" for x in adr["背景事实"]]
    lines += ["", "## 决定"]
    lines += [f"- {x}" for x in adr["决定"]]
    lines += ["", "## 落选方案与失效证据"]
    for alt in adr["落选方案"]:
        lines.append(f"- **{alt['方案']}**：{alt['失效证据']}")
        lines.append(f"  - 坏在哪一层：{alt['失效层']}")
        lines.append(f"  - 失效信号：{alt['失效信号']}")
    lines += ["", "## 代价"]
    lines += [f"- {x}" for x in adr["代价"]]
    lines += ["", "## 回滚点"]
    lines.append(f"- 回到：{adr['回滚点']['回到']}")
    lines.append(f"- 触发数：{adr['回滚点']['触发数']}")
    lines.append(f"- 回滚后先看：{adr['回滚点'].get('先看', '（未写）')}")
    return "\n".join(lines)


GOOD = {
    "标题": "客服工单助手的形态与校验层",
    "背景事实": [
        "中位 6 步、P95 11 步（30 条真实工单抽样）",
        "简单请求 70%、复杂 30%",
        "错误代价高：涉及退款金额，不可回滚，需审计留痕",
        "预算 600M tokens/月，P95 目标 8 秒，60000 次/月",
        "4 人团队，Python，已有工单系统与政策库",
    ],
    "决定": [
        "形态：单循环（不进图，不做多 agent）",
        "编排：规则 + 小模型两级分派；主体 ReAct；校验 = 外部裁判 + 提交前人工审批",
        "供给：工具（工单/退款）+ 政策 RAG + 审批卡",
        "可靠性：幂等键 + 审批 + 熔断 + 限流 + 降级三档",
        "交付：同步 + 超时降级（P95 目标 8 秒）",
    ],
    "落选方案": [
        {
            "方案": "一次调用直接答（不分派、不循环）",
            "失效证据": "30 条抽样里有 18 条需要查工单或政策库才能答，一次调用拿不到这些信息，"
                        "只能编；而退款动作不可回滚，编错的代价是一笔错账",
            "失效层": "供给层（缺工具）与校验层（无裁判）",
            "失效信号": "答案里出现具体金额或时效，但轨迹里没有任何一次工具调用",
        },
        {
            "方案": "多 agent 图（分派 + 退款 agent + 复核 agent）",
            "失效证据": "中位 6 步的任务拆成三个 agent，交接至少两次；按第 48 章的账，"
                        "token 上升四成以上，而错误率不会下降——退款错误的主因是政策理解，"
                        "不是上下文隔离",
            "失效层": "形态层（过度拆分）",
            "失效信号": "交接摘要长度接近子任务输入长度；子 agent 平均上下文小于摘要",
        },
    ],
    "代价": [
        "审批卡让人均处理时长增加约 12 秒，需要排班兜住峰值",
        "政策 RAG 要每周同步一次，否则答错率回升",
        "同步交付在 P95 超过 8 秒时要降级为'先答后补'",
    ],
    "回滚点": {
        "回到": "第 2 级（单循环，去掉分派层）",
        "触发数": "兜底率连续 7 天高于 15%，或审批驳回率高于 20%",
        "先看": "分派层的误判率与政策库的覆盖率",
    },
}

BAD_NO_EVIDENCE = {
    "标题": "把客服做成多 agent",
    "背景事实": ["工单量大"],
    "决定": ["上多 agent，一个分派、一个退款、一个复核"],
    "落选方案": [{"方案": "单循环", "失效层": "形态层"}],
    "代价": ["成本更高"],
    "回滚点": {"回到": "第 2 级"},
}

BAD_VAGUE_ROLLBACK = {
    "标题": "知识问答加裁判",
    "背景事实": ["答错代价低"],
    "决定": ["加一个 LLM 裁判"],
    "落选方案": [{"方案": "不加裁判", "失效证据": "抽样 20 条里有 3 条答非所问",
                  "失效层": "校验层", "失效信号": "答案与问题无关"}],
    "代价": ["每次多一次调用"],
    "回滚点": {"回到": "上一级", "触发数": "效果不好时"},
}


def main() -> None:
    print("=== 1. 一份通过的 ADR ===")
    print(render(GOOD))
    print()
    print(f"    校验结果：{'通过' if not validate(GOOD) else validate(GOOD)}")

    print()
    print("=== 2. 落选方案没有失效证据（被拒） ===")
    for e in validate(BAD_NO_EVIDENCE):
        print(f"    - {e}")

    print()
    print("=== 3. 回滚点写成'效果不好时'（被拒） ===")
    for e in validate(BAD_VAGUE_ROLLBACK):
        print(f"    - {e}")

    print()
    print("=== 4. 校验拦住的到底是什么 ===")
    print("    不是文风，是'这个决定能不能在三个月后被复盘'")
    print("    没有失效证据 -> 无法判断当时的取舍是否仍然成立")
    print("    没有回滚点   -> 选错了只能在原地加码，无法退回")


if __name__ == "__main__":
    main()
