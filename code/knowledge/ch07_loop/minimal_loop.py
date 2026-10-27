"""最小循环：while + 终止三态（答完 / 超步 / 空转）。

不联网。模型用 fake_model.ScriptedModel 的剧本代替，脚本控制它在每步给什么。
跑三个剧本，观察三种终止各自长什么样。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fake_model import (
    ScriptedModel,
    answer_reply,
    execute,
    new_request,
    tool_call_reply,
)

MAX_STEPS = 8


@dataclass
class Run:
    status: str                    # done / max_steps / stalled
    steps: int
    answer: str | None = None
    trace: list[str] = field(default_factory=list)


def loop(model, request: dict, max_steps: int = MAX_STEPS) -> Run:
    """最小循环。三态终止：拿到答案、步数用尽、原地空转。"""
    trace: list[str] = []
    seen_calls: set[str] = set()

    for step in range(1, max_steps + 1):
        reply = model.post(request)
        choice = reply["choices"][0]
        message = choice["message"]
        reason = choice["finish_reason"]

        if reason == "stop":
            return Run("done", step, message.get("content"), trace)

        if reason != "tool_calls":
            trace.append(f"{step}: 非预期 finish_reason={reason}")
            return Run("stalled", step, None, trace)

        calls = message.get("tool_calls") or []
        signature = "|".join(
            f"{c['function']['name']}:{c['function']['arguments']}" for c in calls
        )
        trace.append(f"{step}: 调 {signature}")

        # 空转：与上一步完全相同的调用再来一次，说明结果没有被用上
        if signature in seen_calls:
            trace.append(f"{step}: 与之前某步的调用相同 -> 空转")
            return Run("stalled", step, None, trace)
        seen_calls.add(signature)

        request["messages"].append(message)
        for call in calls:
            request["messages"].append(execute(call))

    return Run("max_steps", max_steps, None, trace)


# ---------------------------------------------------------------- 三个剧本

def done_script(step: int, request: dict) -> dict:
    used = [m for m in request["messages"] if m["role"] == "tool"]
    if not used:
        return tool_call_reply("get_order", {"order_id": "A1001"}, step)
    if len(used) == 1:
        return tool_call_reply("get_policy", {}, step)
    return answer_reply("可以退：3 天前签收，政策窗口 7 天。", step)


def endless_script(step: int, request: dict) -> dict:
    """每一步都要一个新的订单号，永远不会重复 -> 只能靠步数上限停。"""
    return tool_call_reply("get_order", {"order_id": f"A{1000 + step}"}, step)


def stall_script(step: int, request: dict) -> dict:
    """同一调用反复要，说明上一步的结果它没有用上。"""
    return tool_call_reply("get_order", {"order_id": "A1001"}, step)


def main() -> None:
    cases = {
        "正常走完": done_script,
        "永远要新订单": endless_script,
        "原地打转": stall_script,
    }
    for name, script in cases.items():
        model = ScriptedModel(script)
        run = loop(model, new_request())
        print(f"=== {name} ===")
        for line in run.trace:
            print("  " + line)
        print(f"  -> status={run.status}  steps={run.steps}  answer={run.answer!r}")
        print()

    print("三种终止的判定条件：")
    rows = [
        ("done", "finish_reason == stop", "有正文可交付"),
        ("max_steps", "步数到达上限", "无正文；说明任务没走完"),
        ("stalled", "调用签名与之前某步重复", "无正文；说明结果没被用上"),
    ]
    for status, cond, meaning in rows:
        print(f"  {status:<10} {cond:<28} {meaning}")


if __name__ == "__main__":
    main()
