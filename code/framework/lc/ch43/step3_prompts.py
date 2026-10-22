"""第 43 章 step3：提示词模板的四种写法与一个坑（离线）。

运行：
    python code/framework/lc/ch43/step3_prompts.py

上一级的痛点：
    聊天接口只认"消息列表"。如果每次都手拼 f-string，会出现三个问题：
      · 变量漏填时静默变成 "None"
      · 拼接位置散落在各处，改格式要改十个地方
      · 无法把提示词当资产（版本、复用、测试）

这一级做什么：
    ① PromptTemplate / ChatPromptTemplate 的基本用法
    ② MessagesPlaceholder：把"历史消息"插进模板
    ③ few-shot 与从文件加载
    ④ 一个坑：变量名写错不会报错，只会静默填空

看完你要能回答：
    什么时候用 PromptTemplate（单段文本），什么时候用 ChatPromptTemplate（多角色）？
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.prompts import (
    ChatPromptTemplate,
    FewShotChatMessagePromptTemplate,
    MessagesPlaceholder,
    PromptTemplate,
    load_prompt,
)

HERE = Path(__file__).parent
TEMPLATE_FILE = HERE / "templates" / "review.json"


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    line("① PromptTemplate：一段文本 + 变量")
    t = PromptTemplate.from_template("把这句话翻译成{lang}：{text}")
    print(f"  input_variables = {t.input_variables}")
    print(f"  渲染结果         = {t.format(lang='英文', text='今天下雨了')!r}")

    line("② ChatPromptTemplate：多角色（真实项目 90% 用这个）")
    chat = ChatPromptTemplate.from_messages(
        [
            ("system", "你是{guild}的助手，回答不超过{max_words}字。"),
            ("human", "{question}"),
        ]
    )
    msgs = chat.format_messages(guild="售后", max_words="50", question="能退吗？")
    for m in msgs:
        print(f"  {type(m).__name__:<15}{m.content!r}")

    line("③ MessagesPlaceholder：把历史消息原样插进去")
    with_history = ChatPromptTemplate.from_messages(
        [
            ("system", "你是售后助手。"),
            MessagesPlaceholder("history"),          # ← 这里塞多轮
            ("human", "{question}"),
        ]
    )
    from langchain_core.messages import AIMessage, HumanMessage

    filled = with_history.format_messages(
        history=[HumanMessage("我上周买的"), AIMessage("好的，请问什么问题？")],
        question="耳机没声了",
    )
    for m in filled:
        print(f"  {type(m).__name__:<15}{m.content!r}")
    print(f"\n  共 {len(filled)} 条消息（history 占了 2 条）")

    line("④ few-shot：用示例固定输出风格")
    example = ChatPromptTemplate.from_messages([("human", "{q}"), ("ai", "{a}")])
    few_shot = FewShotChatMessagePromptTemplate(
        example_prompt=example,
        examples=[
            {"q": "退款多久", "a": "7 个工作日"},
            {"q": "能换货吗", "a": "可以，30 天内"},
        ],
    )
    final = ChatPromptTemplate.from_messages([("system", "只回答一句话结论。"), few_shot, ("human", "{q}")])
    out = final.format_messages(q="保修多久")
    print(f"  渲染出 {len(out)} 条消息：")
    for m in out:
        print(f"    {type(m).__name__:<15}{m.content!r}")

    line("⑤ 从文件加载：提示词变成资产（可 review / 可回滚）")
    TEMPLATE_FILE.parent.mkdir(exist_ok=True)
    TEMPLATE_FILE.write_text(
        """{
  "_type": "prompt",
  "input_variables": ["diff", "rules"],
  "template": "Review rules:\\n{rules}\\n\\nDiff:\\n{diff}"
}""",
        encoding="utf-8",
    )
    # 注意 encoding：Windows 默认 GBK，load_prompt 不传编码时会 UnicodeDecodeError
    loaded = load_prompt(TEMPLATE_FILE, encoding="utf-8")
    print(f"  从 {TEMPLATE_FILE.name} 载入：{type(loaded).__name__}")
    print(f"  input_variables = {loaded.input_variables}")
    print(f"  渲染            = {loaded.format(diff='+a=1', rules='no bare except')[:50]!r}")
    print("  ⚠️ load_prompt 在 1.x 已标弃用：新项目用 langchain_core.load.load()/loads()")
    print("     或干脆自己 json.load + PromptTemplate（更可控，也不受版本影响）")

    line("⑥ 一个坑：变量名写错时，表现取决于你怎么调")
    bad = PromptTemplate.from_template("你好{name}")
    try:
        print(f"  bad.format(nmae='张三') = {bad.format(nmae='张三')!r}")
    except KeyError as e:
        print(f"  KeyError: {e}")
    print("  → 拼错变量名时抛 KeyError（这个还算好，至少当场炸）")
    print("  → 真危险的是 partial_variables 兜底成空串：线上表现为「模型突然不按格式答」")
    print("    做法：用 Pydantic 定义输入模型，或在测试里断言 input_variables 集合。")


if __name__ == "__main__":
    main()
