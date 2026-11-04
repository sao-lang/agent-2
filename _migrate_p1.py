"""P1 迁移脚本：把扁平 harness 包重排成七层。

用法（在仓库根执行）：
    python _migrate_p1.py

步骤：建目录 -> git mv -> 把所有包内相对导入改写为绝对导入（harness.<layer>.<mod>）。
不碰 adapters/ 与 __init__.py（后者由手写替换）。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "code" / "harness" / "src" / "harness"

# 旧模块名（点分，相对 harness）-> 新模块名（相对 harness）
MAP: dict[str, str] = {
    "contracts": "contracts.types",
    "state": "contracts.state",
    "result": "contracts.result",
    "errors": "contracts.errors",
    "agent": "kernel.agent",
    "actor": "parts.actor",
    "budget": "parts.budget",
    "context": "parts.context",
    "delivery": "parts.delivery",
    "dispatch": "parts.dispatch",
    "durability": "parts.durability",
    "guard": "parts.guard",
    "knowledge": "parts.knowledge",
    "memory": "parts.memory",
    "reflector": "parts.reflector",
    "resilience": "parts.resilience",
    "retrieval": "parts.retrieval",
    "skills": "parts.skills",
    "tools": "parts.tools",
    "topology": "parts.topology",
    "tracer": "parts.tracer",
    "testing": "impl.fakes",
    "build": "assembly.build",
    "presets": "assembly.presets",
    "body.pe": "parts.body.pe",
    "body.react": "parts.body.react",
    "body.workflow": "parts.body.workflow",
    "body.planner": "parts.body.planner",
}

# 文件移动计划：旧相对路径 -> 新相对路径
MOVES: dict[str, str] = {
    "contracts.py": "contracts/types.py",
    "state.py": "contracts/state.py",
    "result.py": "contracts/result.py",
    "errors.py": "contracts/errors.py",
    "agent.py": "kernel/agent.py",
    "actor.py": "parts/actor.py",
    "budget.py": "parts/budget.py",
    "context.py": "parts/context.py",
    "delivery.py": "parts/delivery.py",
    "dispatch.py": "parts/dispatch.py",
    "durability.py": "parts/durability.py",
    "guard.py": "parts/guard.py",
    "knowledge.py": "parts/knowledge.py",
    "memory.py": "parts/memory.py",
    "reflector.py": "parts/reflector.py",
    "resilience.py": "parts/resilience.py",
    "retrieval.py": "parts/retrieval.py",
    "skills.py": "parts/skills.py",
    "tools.py": "parts/tools.py",
    "topology.py": "parts/topology.py",
    "tracer.py": "parts/tracer.py",
    "testing.py": "impl/fakes.py",
    "build.py": "assembly/build.py",
    "presets.py": "assembly/presets.py",
    "body/pe.py": "parts/body/pe.py",
    "body/react.py": "parts/body/react.py",
    "body/workflow.py": "parts/body/workflow.py",
    "body/planner.py": "parts/body/planner.py",
}

FROM_RE = re.compile(r"^(\s*)from (\.+)([\w.]*) import (.+)$")


def resolve(level: int, rest: str) -> str:
    """把相对导入解析成相对 harness 的点分模块名。"""
    # level=1 表示 '.'，level=2 表示 '..'；旧代码里两者的基准包都是 harness
    return rest


def rewrite(path: Path) -> int:
    changed = 0
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        m = FROM_RE.match(line.rstrip("\n"))
        if not m:
            out.append(line)
            continue
        indent, dots, rest, names = m.group(1), m.group(2), m.group(3), m.group(4)
        old = resolve(len(dots), rest)
        new = MAP.get(old)
        if new is None:
            out.append(line)
            continue
        out.append(f"{indent}from harness.{new} import {names}\n")
        changed += 1
    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return changed


def main() -> int:
    for d in ("contracts", "kernel", "parts/body", "impl", "assembly", "fp"):
        (SRC / d).mkdir(parents=True, exist_ok=True)
    for old, new in MOVES.items():
        dst = SRC / new
        dst.parent.mkdir(parents=True, exist_ok=True)
        print(f"git mv {old} -> {new}")
        subprocess.run(["git", "mv", f"code/harness/src/harness/{old}",
                        f"code/harness/src/harness/{new}"], cwd=ROOT, check=True)
    total = 0
    for new in MOVES.values():
        total += rewrite(SRC / new)
    print(f"imports rewritten: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
