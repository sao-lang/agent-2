"""第 43 章 step2：包结构与多 provider 切换（离线可跑）。

运行：
    python code/framework/lc/ch43/step2_packages.py

上一级的痛点：
    "装一个 langchain 就够了" 是 0.x 时代的经验。
    1.x 拆成了几十个包，装错包会 ImportError，或者装了个空壳。

这一级做什么：
    ① 把 1.x 的包结构列成一张表，并打印本机真实装了什么
    ② 用 init_chat_model 演示"换 provider 只改一个字符串"
    ③ 演示 provider 写错时会抛什么错（比 ImportError 好定位）

关键概念：
    langchain-core     接口层（BaseChatModel / Runnable / Message），几乎不依赖别的东西
    langchain          主包（create_agent / 中间件），依赖 core
    langchain-openai   某个厂商的实现（1 个 provider 1 个包）
    langgraph          图编排（Agent 运行时就是一张图）
"""
from __future__ import annotations

import importlib.metadata as md
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _fake import scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


PACKAGES = [
    ("langchain-core", "接口与基础类型", "必须"),
    ("langchain", "主包：create_agent、中间件", "做 Agent 才需要"),
    ("langchain-openai", "OpenAI / 兼容接口的实现", "用 OpenAI 或兼容网关时"),
    ("langchain-anthropic", "Claude 实现", "可选"),
    ("langchain-ollama", "Ollama 实现", "本地模型时"),
    ("langgraph", "图编排（create_agent 的底座）", "做 Agent 时自动带上"),
    ("langgraph-checkpoint-sqlite", "检查点落 SQLite", "要跨重启恢复时"),
]


def main() -> None:
    line("① 1.x 的包结构：本机真实安装情况")
    print(f"  {'包名':<30}{'作用':<26}{'安装?':<8}版本")
    print("  " + "-" * 76)
    for name, role, when in PACKAGES:
        try:
            ver = md.version(name)
            got = "✓"
        except md.PackageNotFoundError:
            ver = f"（{when}）"
            got = "—"
        print(f"  {name:<30}{role:<26}{got:<8}{ver}")

    print("\n  → 只装 langchain-core 也能跑通本章前两级：消息、提示词、解析都是 core 的")
    print("  → 出现 ImportError 时先问：这个类属于 core 还是属于某个 provider 包？")

    line("② init_chat_model：换 provider 只改一个字符串")
    from langchain.chat_models import init_chat_model

    # 离线时不能真的建 OpenAI 客户端：它在构造阶段就要 key。
    # 所以这里只演示"名字 → 类"的映射，真的构造放到 demo_*_llm.py。
    try:
        m = init_chat_model("gpt-4o-mini", model_provider="openai", temperature=0)
        print(f"  init_chat_model('gpt-4o-mini', provider='openai') → {type(m).__name__}")
        print(f"    model_name = {getattr(m, 'model_name', None)}")
        print(f"    temperature = {getattr(m, 'temperature', None)}")
    except Exception as e:  # noqa: BLE001
        print(f"  init_chat_model 构造失败：{type(e).__name__}（离线环境没有 API Key 时属正常）")
        print(f"    原文：{str(e)[:110]}")
    print("  → 它只做两件事：按 provider 找实现类、把参数塞进去。不发请求。")

    print("\n  常见 provider 名字（写错会立刻报错，比 ImportError 好定位）：")
    for p in ["openai", "anthropic", "ollama", "google_genai", "deepseek"]:
        print(f"    - {p}")

    line("③ 写错 provider 会发生什么")
    try:
        init_chat_model("gpt-4o-mini", model_provider="opnai")
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {str(e)[:150]}")

    line("④ 企业封装：一个 make_llm() 收口所有模型创建")
    llm = scripted("好")

    def make_llm(env: str = "dev"):
        """业务代码只调这个函数，不直接 import 任何 provider 包。"""
        if env == "offline":
            return llm
        return init_chat_model(
            "gpt-4o-mini", model_provider="openai", temperature=0, timeout=30, max_retries=2
        )

    print(f"  make_llm('offline') → {type(make_llm('offline')).__name__}")
    print("  → 单元测试传 offline，生产读环境变量。改 provider 只改这一处。")


if __name__ == "__main__":
    main()
