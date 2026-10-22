"""第 9 章 · 第 3 级：续跑时最危险的事 —— 副作用被执行两次。

运行：
    python code/ch09_durable/step3_idempotent.py

新增的一个概念：**幂等（idempotency）**。

检查点是"状态快照"，不是"事务"。它救不了已经发出去的邮件。
这一级用一个假的 `send_email`（会记录发送次数）演示三种情况：

  A. 没有幂等保护         → 崩溃恢复后，邮件发了 2 次
  B. 本地记录 executed     → 能挡住大部分，但挡不住"发成功但没来得及记录"
  C. 幂等键传给下游服务     → 真正可靠
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------- 假的下游服务

@dataclass
class MailService:
    """真实世界里，这个"去重"能力必须由下游服务提供，不能只在客户端做。"""

    sent: list[str] = field(default_factory=list)
    _seen_keys: set[str] = field(default_factory=set)

    def send(self, to: str, body: str, idempotency_key: str | None = None) -> str:
        if idempotency_key and idempotency_key in self._seen_keys:
            return "duplicate-ignored"
        self.sent.append(f"{to}: {body}")
        if idempotency_key:
            self._seen_keys.add(idempotency_key)
        return "sent"


@dataclass
class State:
    task_id: str
    to: str
    body: str
    executed: list[str] = field(default_factory=list)
    sent_ok: bool = False


# ---------------------------------------------------------------- 三种写法

def send_no_guard(state: State, mail: MailService) -> State:
    """A. 没有任何保护。"""
    mail.send(state.to, state.body)
    state.sent_ok = True
    return state


def send_local_guard(state: State, mail: MailService) -> State:
    """B. 只在本地记录（"发完再记"）。中间崩溃就会重复。"""
    key = f"email:{state.task_id}"
    if key in state.executed:
        return state
    mail.send(state.to, state.body)
    state.executed.append(key)      # ← 如果正好在这行之前崩溃，下一次还会发
    state.sent_ok = True
    return state


def send_idempotent(state: State, mail: MailService) -> State:
    """C. 幂等键传给下游：即使本地记录丢了，下游也能去重。"""
    key = f"email:{state.task_id}"
    result = mail.send(state.to, state.body, idempotency_key=key)
    if key not in state.executed:
        state.executed.append(key)
    state.sent_ok = result != "duplicate-ignored" or state.sent_ok
    return state


# ---------------------------------------------------------------- 模拟崩溃

def crash_and_retry(sender, *, crash_after_send: bool) -> tuple[MailService, int]:
    """跑一次 → 在"发完之后、记录之前"崩溃 → 从检查点恢复 → 再跑一次。

    返回 (邮件服务, 实际发送次数)。
    """
    mail = MailService()
    state = State(task_id="task-42", to="user@example.com", body="退款已受理")

    sender(state, mail)
    if crash_after_send:
        # 崩溃：状态没存下来，本地 executed 记录丢失
        state.executed = []
    sender(state, mail)            # 恢复后重跑同一步
    return mail, len(mail.sent)


def main() -> None:
    print("=" * 76)
    print("场景：发送一封确认邮件，发完之后立刻崩溃，恢复后重跑那一步")
    print("=" * 76)

    rows = []
    for label, fn, crash in [
        ("A. 无保护", send_no_guard, False),
        ("B. 本地记录 executed", send_local_guard, True),
        ("C. 幂等键传给下游", send_idempotent, True),
    ]:
        mail, count = crash_and_retry(fn, crash_after_send=crash)
        rows.append((label, count, mail.sent))

    print(f"\n{'写法':<24}{'用户实际收到几封':>16}  说明")
    print("-" * 76)
    for label, count, sent in rows:
        note = "❌ 重复发送" if count > 1 else "✅ 只发一封"
        print(f"{label:<24}{count:>16}  {note}")

    print("\n" + "=" * 76)
    print("为什么 B 挡不住")
    print("=" * 76)
    print("  B 的写法是「先发，再记录」：")
    print("      mail.send(...)          ← 成功了")
    print("      state.executed.append() ← 崩溃在这里，这行没执行")
    print()
    print("  恢复后 executed 里没有这个 key，于是又发了一次。")
    print("  这不是代码写错了，是「发」和「记」两件事不可能是原子的。")
    print()
    print("  即使改成「先记录，再发送」，也只是把窗口挪了个位置：")
    print("      state.executed.append() ← 记录了")
    print("      mail.send(...)          ← 崩溃在这里，邮件永远发不出去")
    print()
    print("  👉 结论：**客户端无论怎么排序，都消除不了这个窗口。**")
    print("     只有让下游服务记住「这个 key 我处理过」，才真正幂等。")

    print("\n" + "=" * 76)
    print("三种生产做法")
    print("=" * 76)
    print("  1. 幂等键（本例的做法 C）：每个副作用带一个稳定的 key，下游去重")
    print("  2. Outbox 模式：先写「待发送」记录到数据库，独立 worker 消费并标记完成")
    print("  3. 推到最后 + 人工确认：高风险动作（转账、删库）不做自动恢复（第 20 章）")


if __name__ == "__main__":
    main()
