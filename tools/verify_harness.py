#!/usr/bin/env python3
"""Harness 完成线门禁：一条命令判定「按当前判据可用」。

    python tools/verify_harness.py
    → GATE OK   （退出码 0）
    → GATE FAIL （退出码 1，附失败原因）

设计原则（决定它不会变成新的返工来源）：
  * 只断言「已有能力不退化」，**不断言「所有能力都齐全」**。
    前者是封闭集合、可以变绿；后者是开放集合、永远红。
  * 因此本门禁不会因为 AUDIT 文档里 44 项断点尚未修完而失败。
    断点是 backlog，不是门禁条件。
  * 三道检查全部是确定性的，不含模型判断：
      ① 审计快照 --check（判据 / 源码指纹未漂移）
      ② unittest 全量（338 个既有测试不退化）
      ③ 端到端冒烟（真实从装配入口跑到 RunResult）
  * 新发现的问题不在这里即时返工：登记进 AUDIT 文档 §6.5 backlog，
    等判据显式升版时一次性批量并入。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SNAPSHOT = ROOT / "docs" / "harness" / "audit-report.json"
AUDITOR = ROOT / "tools" / "audit_harness.py"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def env() -> dict[str, str]:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(SRC)
    e["PYTHONIOENCODING"] = "utf-8"
    return e


def check_snapshot() -> tuple[bool, str]:
    r = subprocess.run(
        [sys.executable, str(AUDITOR), "--check", str(SNAPSHOT)],
        cwd=ROOT, env=env(), capture_output=True, text=True,
    )
    out = (r.stdout + r.stderr).strip()
    if r.returncode == 0 and "CHECK OK" in out:
        return True, out.splitlines()[0]
    return False, out or f"exit={r.returncode}"


def check_unittest() -> tuple[bool, str]:
    r = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=ROOT, env=env(), capture_output=True, text=True,
    )
    combined = r.stdout + r.stderr
    summary = next(
        (ln.strip() for ln in combined.splitlines() if ln.startswith("Ran ")),
        "",
    )
    if r.returncode == 0 and "OK" in combined:
        return True, summary or "OK"
    tail = "\n".join(combined.splitlines()[-25:])
    return False, f"{summary}\n{tail}"


def check_smoke() -> tuple[bool, str]:
    """端到端：装配入口 → 唯一解释器 → RunResult。"""
    try:
        from harness.assembly.config import HarnessConfig, build_harness
        from harness.contracts.types import Goal
        from harness.fp import react
    except Exception as exc:  # noqa: BLE001 - 导入失败即门禁失败
        return False, f"import 失败：{type(exc).__name__}: {exc}"

    try:
        harness = build_harness(HarnessConfig(model="fake"))
        result = asyncio.run(
            harness.run(react(max_steps=3), Goal("gate-smoke", session_id="gate"))
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"运行失败：{type(exc).__name__}: {exc}"

    problems = []
    if not getattr(result, "ok", False):
        problems.append(f"status={result.status!r} 非 completed/degraded")
    usage = getattr(result, "usage", None)
    if not isinstance(usage, dict):
        problems.append("usage 不是 dict")
    elif not {"tokens", "calls"}.issubset(usage):
        problems.append(f"usage 缺字段：{sorted(usage)}")
    if not getattr(result, "trace_id", ""):
        problems.append("trace_id 为空")
    if problems:
        return False, "；".join(problems)
    return True, f"status={result.status} usage={usage} trace_id={result.trace_id[:8]}…"


def main() -> int:
    checks = [
        ("审计快照一致性 (--check)", check_snapshot),
        ("既有测试不退化 (unittest)", check_unittest),
        ("端到端冒烟 (build_harness → RunResult)", check_smoke),
    ]
    print("Harness 完成线门禁（只断言已有能力不退化）")
    failures = []
    for name, fn in checks:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001 - 门禁自身异常也算失败
            ok, detail = False, f"门禁异常：{type(exc).__name__}: {exc}"
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if ok else ""))
        if not ok:
            failures.append((name, detail))
    if failures:
        print("\nGATE FAIL")
        for name, detail in failures:
            print(f"  · {name}\n    {detail}")
        return 1
    print("\nGATE OK：按当前判据可用。判据演进请走 AUDIT §6.5 的升版流程。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
