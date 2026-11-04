"""CLI 脚手架（SPEC §23 缺口 9 / ADR 19）。

    python -m harness.cli new <dir>     # 生成一个最小项目
    python -m harness.cli check <dsn>   # 探活存储后端（P8 占位，返回可用性）
"""

from __future__ import annotations

import sys
from pathlib import Path

MAIN_TEMPLATE = '''"""最小 agent 项目：只改配置，不改框架。"""

import asyncio

from harness import Goal
from harness.assembly import HarnessConfig, build_harness
from harness.fp import describe, react
from harness.parts.middleware import taskboard_layer
from harness.parts.tools import tool


@tool
def hello(name: str) -> str:
    """打招呼。

    Args:
        name: 名字
    """
    return f"hello {name}"


async def main() -> None:
    harness = build_harness(HarnessConfig(model="fake", tools=(hello,)))
    program = react(max_steps=6) >> taskboard_layer()
    print(describe(program))
    result = await harness.run(program, Goal("打个招呼", session_id="demo"))
    print(result.status, result.answer)


if __name__ == "__main__":
    asyncio.run(main())
'''

README_TEMPLATE = r"""# {name}

用 agent-harness 生成的最小项目。

## 运行

```powershell
$env:PYTHONPATH="$PWD\../../src"     # 开发期直接引用本仓库
python main.py
```

## 三个入口

- **能力**：`HarnessConfig`（模型 / 工具 / 存储 / 后端）
- **策略**：`react(...) >> layer`（组合，纯值）
- **执行**：`harness.run(program, goal)` / `harness.astream(...)` / `harness.dry_run(...)`

换模型只改 `HarnessConfig(model="openai:gpt-4.1")`；换记忆介质只改
`StoreSpec(memory="postgres:$DSN")`。
"""


def new_project(target: str) -> Path:
    root = Path(target)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "main.py").write_text(MAIN_TEMPLATE, encoding="utf-8")
    (root / "README.md").write_text(
        README_TEMPLATE.format(name=root.name or "agent-app"), encoding="utf-8"
    )
    (root / "skills" / ".gitkeep").write_text("", encoding="utf-8")
    return root


def check(spec: str) -> int:
    """探活：解析存储/后端 spec，能解析就返回 0。"""
    from harness.assembly import parse_spec, resolve
    from harness.assembly.registry import BACKENDS, STORE_SLOTS

    for table in (STORE_SLOTS["memory"], BACKENDS["index"]):
        try:
            resolve("check", spec, table)
            return 0
        except Exception:  # noqa: BLE001 - 继续试下一个表
            continue
    parse_spec(spec, kind="check")          # 至少语法要合法
    return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command, *rest = args
    if command == "new":
        if not rest:
            print("用法：harness new <dir>")
            return 2
        root = new_project(rest[0])
        print(f"已生成：{root}")
        return 0
    if command == "check":
        if not rest:
            print("用法：harness check <spec>")
            return 2
        code = check(rest[0])
        print("可用" if code == 0 else "不可用（语法合法但无匹配实现）")
        return code
    print(f"未知命令：{command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
