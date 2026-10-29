"""第 25 章示例：检查点、两种继续与幂等键。

不联网，只用标准库。邮件服务用 sqlite 的一张键表做替身：
dedupe=True 时 INSERT 成功才发，主键冲突说明这个键已经发过。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path

STEPS = ["取订单", "取政策", "发邮件", "汇总"]
KEY = "notify:A1001:2026-10"


# ---------------------------------------------------------------- 检查点

@dataclass
class Checkpoint:
    run_id: str
    step: int
    messages: list[dict]
    state: dict
    counters: dict
    result: dict | None = None
    pending_key: str | None = None
    status: str = "running"
    schema_version: int = 1


def save(path: str | Path, cp: Checkpoint) -> None:
    """先写临时文件再原子改名：检查点要么是旧的，要么是新的。"""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(cp), f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load(path: str | Path) -> Checkpoint:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("schema_version", 0) < 1:
        raise ValueError("检查点版本过老，无法恢复")
    return Checkpoint(**data)


# ---------------------------------------------------------------- 外部副作用

class MailOutbox:
    """邮件服务的替身。dedupe=True 时用主键插入做下游去重。"""

    def __init__(self, dedupe: bool) -> None:
        self.dedupe = dedupe
        self.sends = 0
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE effects(key TEXT PRIMARY KEY)")

    def send(self, key: str, body: str) -> str:
        if self.dedupe:
            try:
                self.conn.execute("INSERT INTO effects(key) VALUES (?)", (key,))
                self.conn.commit()
            except sqlite3.IntegrityError:
                return f"命中幂等键，跳过（累计 {self.sends} 封）"
        self.sends += 1
        return f"发出第 {self.sends} 封：{body}"


class ScriptedLLM:
    """脚本化模型：第二次调用给出不同结论，模拟重新推理的不确定性。"""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, messages: list[dict]) -> dict:
        self.calls += 1
        verdict = "可退" if self.calls == 1 else "不可退"
        return {"decision": verdict, "basis": "签收 3 天"}


# ---------------------------------------------------------------- 执行与恢复

def first_run(path: str | Path, outbox: MailOutbox, crash_after_send: bool,
              llm: ScriptedLLM | None = None) -> tuple[list[str], ScriptedLLM]:
    """跑到第 3 步的副作用处。返回轨迹与模型。"""
    llm = llm or ScriptedLLM()
    cp = Checkpoint(
        run_id="run-25",
        step=0,
        messages=[{"role": "user", "content": "订单 A1001 能不能退？"}],
        state={"order_id": "A1001", "facts": []},
        counters={"model_calls": 0},
    )
    trace: list[str] = []
    for i, name in enumerate(STEPS[:2], 1):
        cp.step = i
        cp.state["facts"].append(f"{name}完成")
        save(path, cp)
        trace.append(f"步 {i} {name}: ok")

    # 第 3 步：先推理、先写 pending、再执行副作用，最后才写完成。
    cp.counters["model_calls"] += 1
    cp.result = llm.decide(cp.messages)
    cp.pending_key = KEY
    save(path, cp)
    trace.append(f"步 3 判定: {cp.result['decision']}（检查点写入 pending）")

    if crash_after_send:
        trace.append("步 3 发邮件: " + outbox.send(KEY, f"订单 A1001 {cp.result['decision']}"))
        trace.append("崩溃：完成标记未写入，检查点仍是 step=2")
    return trace, llm


def resume(path: str | Path, outbox: MailOutbox, strategy: str = "replay",
           llm: ScriptedLLM | None = None,
           crash_before_commit: bool = False) -> tuple[list[str], Checkpoint, int]:
    """读检查点继续。返回 (轨迹, 检查点, 本次模型调用次数)。"""
    cp = load(path)
    calls_before = llm.calls if llm else 0
    trace = [f"读检查点：step={cp.step}，pending={cp.pending_key}"]

    if cp.pending_key:
        if strategy == "replay":
            decision = cp.result["decision"]
            trace.append(f"重放结论：{decision}，不调用模型")
        else:
            decision = llm.decide(cp.messages)["decision"]
            cp.result = {"decision": decision, "basis": "重新推理"}
            trace.append(f"重新推理：{decision}，调用模型 1 次")
        trace.append("发邮件: " + outbox.send(cp.pending_key, f"订单 A1001 {decision}"))
        if crash_before_commit:
            trace.append("在写完成标记前再次退出")
            return trace, cp, (llm.calls - calls_before if llm else 0)
        cp.step = 3
        cp.pending_key = None
        cp.state["facts"].append(f"通知已发（{decision}）")
        save(path, cp)
        trace.append("步 3 提交完成")

    for i in range(cp.step + 1, len(STEPS) + 1):
        cp.step = i
        cp.state["facts"].append(f"{STEPS[i - 1]}完成")
        save(path, cp)
        trace.append(f"步 {i} {STEPS[i - 1]}: ok")
    return trace, cp, (llm.calls - calls_before if llm else 0)


def decide_next_step(cp: Checkpoint, effect_exists) -> int:
    """pending 的两种事实：副作用已生效 / 未生效。返回下一步的 1-based 步号。"""
    if cp.pending_key is None:
        return cp.step + 1
    return cp.step + 2 if effect_exists(cp.pending_key) else cp.step + 1


def rerun_from_scratch(path: str | Path, outbox: MailOutbox) -> list[str]:
    """没有检查点时唯一的做法：从第一步重跑。"""
    cp = Checkpoint(
        run_id="run-25",
        step=0,
        messages=[{"role": "user", "content": "订单 A1001 能不能退？"}],
        state={"order_id": "A1001", "facts": []},
        counters={"model_calls": 0},
    )
    trace: list[str] = []
    for i, name in enumerate(STEPS, 1):
        if name == "发邮件":
            cp.pending_key = KEY
            trace.append("步 3 发邮件: " + outbox.send(KEY, "订单 A1001 可退"))
        else:
            trace.append(f"步 {i} {name}: ok")
        cp.step = i
        save(path, cp)
    return trace


def claim_memory(key: str, seen: set[str]) -> bool:
    """第一层：键记在调用方内存里。"""
    if key in seen:
        return False
    seen.add(key)
    return True


def claim_local(key: str, path: Path) -> bool:
    """第二层：键记在调用方自己的磁盘上，跨重启有效。"""
    done = set(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else set()
    if key in done:
        return False
    done.add(key)
    path.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
    return True


class TempDir:
    """示例用的临时目录。放在脚本旁边，跑完删掉，不碰系统临时目录。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> Path:
        shutil.rmtree(self.path, ignore_errors=True)
        self.path.mkdir(parents=True)
        return self.path

    def __exit__(self, *exc: object) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def main() -> None:
    with TempDir(Path(__file__).with_name("_run")) as td:
        base = Path(td)

        # 一、没有检查点：从头重跑
        print("=== 一、没有检查点：从头重跑 ===")
        p0 = base / "cp_none.json"
        box0 = MailOutbox(dedupe=False)
        trace0, _ = first_run(p0, box0, crash_after_send=True)
        for line in trace0:
            print("  " + line)
        print("  --- 重跑 ---")
        for line in rerun_from_scratch(p0, box0):
            print("  " + line)
        print(f"  副作用次数：{box0.sends}（期望 1）")
        print()

        # 二、第 3 步中断后恢复的轨迹（下游有幂等键）
        print("=== 二、第 3 步中断后恢复的轨迹 ===")
        p1 = base / "cp_after_send.json"
        box1 = MailOutbox(dedupe=True)
        trace, _ = first_run(p1, box1, crash_after_send=True)
        for line in trace:
            print("  " + line)
        cp = load(p1)
        print("  检查点：")
        print(textwrap.indent(json.dumps(asdict(cp), ensure_ascii=False, indent=2), "  "))
        print("  --- 新进程恢复 ---")
        trace, cp, _ = resume(p1, box1, strategy="replay")
        for line in trace:
            print("  " + line)
        print(f"  最终：邮件 {box1.sends} 封，检查点 step={cp.step}")
        print()

        # 二、两种继续：重放结论 vs 重新推理
        print("=== 三、两种继续（同一次崩溃）===")
        for strategy, label in (("replay", "重放结论"), ("reason", "重新推理")):
            p2 = base / f"cp_{strategy}.json"
            box2 = MailOutbox(dedupe=False)
            llm = ScriptedLLM()
            first_run(p2, box2, crash_after_send=False, llm=llm)
            trace, cp, new_calls = resume(p2, box2, strategy=strategy, llm=llm)
            print(f"  {label}：decision={cp.result['decision']}"
                  f"，本次模型调用 {new_calls} 次，累计 {llm.calls} 次，邮件 {box2.sends} 封")
        print()

        # 四、从第几步继续
        print("=== 四、从第几步继续 ===")
        p_decide = base / "cp_decide.json"
        first_run(p_decide, MailOutbox(dedupe=False), crash_after_send=True)
        cp_here = load(p_decide)
        print(f"  pending={cp_here.pending_key}，已生效 -> 第 "
              f"{decide_next_step(cp_here, lambda k: True)} 步；"
              f"未生效 -> 第 {decide_next_step(cp_here, lambda k: False)} 步")
        print()

        # 五、幂等键放在哪一层
        print("=== 五、幂等键放在哪一层 ===")
        seen_a: set[str] = set()
        seen_b: set[str] = set()
        f_a = base / "a.done"
        f_b = base / "b.done"
        print(f"  两个实例各自用内存：甲={claim_memory(KEY, seen_a)}，"
              f"乙={claim_memory(KEY, seen_b)} -> 各发 1 封，共 2 封")
        print(f"  两个实例各自落本地：甲={claim_local(KEY, f_a)}，"
              f"乙={claim_local(KEY, f_b)} -> 各发 1 封，共 2 封")
        shared = MailOutbox(dedupe=True)
        print(f"  共享下游键表：甲={shared.send(KEY, '订单 A1001 可退')}，"
              f"乙={shared.send(KEY, '订单 A1001 可退')} -> 共 {shared.sends} 封")
        print()

        # 六、无幂等键：连续两次恢复
        print("=== 六、无幂等键：两次恢复 ===")
        p3 = base / "cp_nokey.json"
        box3 = MailOutbox(dedupe=False)
        trace, _ = first_run(p3, box3, crash_after_send=True)
        for line in trace:
            print("  " + line)
        trace, _, _ = resume(p3, box3, crash_before_commit=True)
        print("  --- 恢复 1 ---")
        for line in trace:
            print("  " + line)
        trace, cp3, _ = resume(p3, box3)
        print("  --- 恢复 2 ---")
        for line in trace:
            print("  " + line)
        print(f"  副作用次数：{box3.sends}（期望 1）")
        print()

        # 七、有幂等键：同样两次恢复
        print("=== 七、有幂等键：两次恢复 ===")
        p4 = base / "cp_key.json"
        box4 = MailOutbox(dedupe=True)
        trace, _ = first_run(p4, box4, crash_after_send=True)
        for line in trace:
            print("  " + line)
        trace, _, _ = resume(p4, box4, crash_before_commit=True)
        print("  --- 恢复 1 ---")
        for line in trace:
            print("  " + line)
        trace, cp4, _ = resume(p4, box4)
        print("  --- 恢复 2 ---")
        for line in trace:
            print("  " + line)
        print(f"  副作用次数：{box4.sends}（期望 1）")
        print()

        # 八、两次恢复的副作用对照
        print("=== 八、两次恢复的副作用对照 ===")
        print("  场景          恢复次数   发出邮件   期望")
        print(f"  无幂等键         2        {box3.sends}       1")
        print(f"  有幂等键         2        {box4.sends}       1")
        print()

        # 九、去重是真的按键做的吗
        print("=== 九、换一个键会不会再发 ===")
        probe = MailOutbox(dedupe=True)
        probe.send(KEY, "订单 A1001 可退")
        probe.send(KEY, "订单 A1001 可退")
        probe.send("notify:A1001:2026-11", "订单 A1001 可退")
        print(f"  同键两次 + 换键一次：共 {probe.sends} 封（期望 2）")
        assert probe.sends == 2, probe.sends
        print("  断言通过：去重按键生效，不是无条件跳过")


if __name__ == "__main__":
    main()


