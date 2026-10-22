"""第 43 章 step2：LCEL——用 | 把零件接成一条流水线（离线）。

运行：
    python code/framework/lc/ch43/step2_lcel.py

上一级的痛点：
    step1 里你手写了 prompt.format() → model.invoke() → parser.parse()。
    三步写三行，还不是一个整体：没法统一重试、没法统一计费、没法流式。

这一级做什么：
    把三步用 | 接成 Runable。然后逐层加能力：
      step2  最小链 + 流式 + 批量
      step3  并行、分支、重试、降级、可配置

核心心智模型：
    Runnable 就是"有 invoke/stream/batch 三件套的东西"。
    | 就是函数组合：左边输出喂右边输入。
    你写 a | b | c，得到的是一个新的 Runnable，同样有 invoke/stream/batch。
"""
from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _fake import scripted, stream_text  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    line("① 手写三步 vs LCEL 一条链")
    prompt = ChatPromptTemplate.from_template("用一句话解释{term}，不超过 20 字。")

    # --- 手写版 ---
    m1 = scripted("token 是模型切分文本的最小单位。")
    raw1 = m1.invoke(prompt.format_messages(term="token"))
    print(f"  手写版第一步返回：{type(raw1).__name__}（不是字符串！）")
    print(f"  手写版最终结果  ：{StrOutputParser().parse(raw1)!r}")

    # --- LCEL 版 ---
    m2 = scripted("token 是模型切分文本的最小单位。")
    chain = prompt | m2 | StrOutputParser()
    print(f"  LCEL  ：{chain.invoke({'term': 'token'})!r}")
    print(f"  链的类型 = {type(chain).__name__}")

    line("② 链自带三件套：invoke / stream / batch")
    m3 = scripted("向量是把文本变成一串数字。")
    c3 = prompt | m3 | StrOutputParser()

    print("  stream：")
    print("    ", end="")
    for piece in stream_text(c3.stream({"term": "向量"})):
        print(piece, end="", flush=True)
    print()

    print("  batch（3 个输入一次提交，返回顺序与输入一致）：")
    m4 = scripted("甲。", "乙。", "丙。")
    c4 = ChatPromptTemplate.from_template("回答{q}") | m4 | StrOutputParser()
    print(f"    {c4.batch([{'q': '1'}, {'q': '2'}, {'q': '3'}])}")

    line("③ 同一份代码，不装框架也要看得懂")
    print("  chain.invoke(x) ≈ parse(model.invoke(prompt.format(x)))")
    print("  chain.stream(x) ≈ 逐个 yield 上面那三步产生的中间结果")
    print("  你并没有「少写逻辑」，你只是把「调用顺序」声明出来了。")

    line("④ 一个必须知道的坑：链是不可变的")
    base = ChatPromptTemplate.from_template("{q}") | scripted("答") | StrOutputParser()
    try:
        base.parser = StrOutputParser()  # 想改内部？不行
    except (AttributeError, ValueError) as e:
        print(f"  改内部属性 → {type(e).__name__}: {e}")
    print("  → Runnable 都是不可变的：要改行为用 .with_* 生成新链，不要改旧链")


if __name__ == "__main__":
    main()
