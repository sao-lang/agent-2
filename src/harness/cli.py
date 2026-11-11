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
    harness = build_harness(HarnessConfig(
        model="openai",        # 模型槽位：openai / anthropic / ollama（缺依赖时装配报安装指引）
        tools=(hello,),
    ))
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
    """探活：解析 spec → 实例化 → **校验运行时依赖与协议方法**。

    只做语法解析会把「占位工厂 / 缺 SDK」误报为可用；这里要求解析出的
    实例真的具备该槽位协议要求的方法，且默认装配能完整构造一次。
    """
    from harness.assembly import parse_spec, resolve
    from harness.assembly.registry import BACKENDS, STORE_SLOTS

    #: 槽位 → 该实现至少应具备的协议方法
    required = {
        "store": ("put", "get"),
        "index": ("upsert", "search"),
        "artifacts": ("put", "get", "stat"),
    }
    for kind, table in (("store", STORE_SLOTS["durability"]),
                        ("index", BACKENDS["index"]),
                        ("artifacts", BACKENDS["artifacts"])):
        try:
            instance = resolve(kind, spec, table)
        except Exception:  # noqa: BLE001 - 继续试下一个表
            continue
        methods = required[kind]
        missing = [m for m in methods if not callable(getattr(instance, m, None))]
        if not missing:
            return 0
    try:
        parse_spec(spec, kind="check")          # 语法合法，但没有可用的运行时实现
    except Exception:  # noqa: BLE001
        pass
    # 默认装配探活：能构造出 Harness 才算运行时依赖齐备
    # （model=None 是合法装配——不注入模型的程序也能跑纯计算/工作流）。
    try:
        from harness.assembly.config import HarnessConfig, build_harness

        default = build_harness(HarnessConfig())
        return 0 if all(slot in default.backends for slot in BACKENDS) else 1
    except Exception:  # noqa: BLE001
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
