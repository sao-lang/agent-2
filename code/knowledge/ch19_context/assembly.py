"""上下文装配：四个槽位的 token 计量、预算抢占、编号与压缩。

用真实组件：tiktoken 计数、trim_messages、ChatPromptTemplate、LLMChainExtractor。
模型用脚本化替身（FakeListChatModel），只演示装配，不做生成质量判断。
"""

from __future__ import annotations

import tiktoken
from langchain_classic.retrievers.document_compressors import LLMChainExtractor
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langchain_core.prompts import ChatPromptTemplate

ENC = tiktoken.get_encoding("cl100k_base")

SYSTEM = (
    "你是电商售后客服。只依据 <资料> 中的内容回答，资料不足时回答：资料里没有相关内容。"
    "每个结论后用 [编号] 标注来源。不要使用外部知识。"
)

TOOLS = "可用工具：query_order(订单号)、check_policy(条款号)、refund(订单号, 金额)。"

HISTORY = [
    ("用户", "我上周买的耳机还没到，订单 A1001。"),
    ("客服", "已为你查询 A1001，物流显示已发货，预计 48 小时送达。"),
    ("用户", "那如果我不想要了能退吗？"),
    ("客服", "签收后 7 天内可申请无理由退货，需保持未拆封。"),
    ("用户", "退货运费谁出？"),
    ("客服", "质量问题由商家承担，非质量问题由买家承担。"),
    ("用户", "那生鲜呢？我买的草莓坏了。"),
    ("客服", "生鲜不支持无理由退货，质量问题需 24 小时内拍照反馈。"),
    ("用户", "发票怎么开？"),
    ("客服", "订单页可以申请电子发票，时限 30 天。"),
    ("用户", "好的，我还有一个订单 A1002 没有发货。"),
    ("客服", "A1002 显示已打包，预计今天发出。"),
    ("用户", "能改地址吗？"),
    ("客服", "未发货前可以修改，请在订单页操作。"),
    ("用户", "那我先不退了。"),
    ("客服", "好的，如需帮助随时联系。"),
]

CHUNKS = [
    "质量问题导致的退货，往返运费由商家承担，买家需在签收后 7 天内提交凭证。",
    "非质量问题退货，商品需保持未拆封，运费由买家承担，申请时限同样是 7 天。",
    "生鲜类商品不支持无理由退货，质量问题需在签收后 24 小时内拍照反馈。",
    "发票可在订单页申请，开票时限为下单后 30 天，超过时限不再补开。",
    "价保规则：签收后 15 天内降价可补差价，活动价不参与。",
    "会员每月有 3 次免运费券，生日月双倍积分。",
    "换货需在签收后 7 天内申请，商品保持未拆封并附赠品。",
    "退款原路退回，银行卡 3 到 7 个工作日到账。",
]


def ntok(text: str) -> int:
    return len(ENC.encode(text))


def count_messages(messages) -> int:
    """trim_messages 的 token_counter 收到的是消息列表。"""
    total = 0
    for m in messages:
        content = m.content if hasattr(m, "content") else m
        if isinstance(content, str):
            total += ntok(content)
    return total


def slots() -> dict[str, int]:
    """四个槽位各占多少 token。"""
    return {
        "系统提示": ntok(SYSTEM),
        "工具清单": ntok(TOOLS),
        "对话历史": sum(ntok(u) + ntok(a) for u, a in HISTORY),
        "检索上下文": sum(ntok(f"[{i}] {c}") for i, c in enumerate(CHUNKS, 1)),
        "输出预留": 300,
    }


def assemble(system: str, tools: str, history: list[tuple[str, str]],
             chunks: list[str]) -> str:
    parts = [system, tools]
    if history:
        parts.append("对话历史：")
        parts += [f"{role}：{text}" for role, text in history]
    if chunks:
        parts.append("<资料>")
        parts += [f"[{i}] {c}" for i, c in enumerate(chunks, 1)]
        parts.append("</资料>")
    return "\n".join(parts)


def squeeze(history, chunks, budget: int) -> tuple[list, list, list[str]]:
    """超预算时先丢最旧的历史，再丢分数最低的块。返回 (历史, 块, 丢弃记录)。"""
    dropped: list[str] = []
    while history and ntok(assemble(SYSTEM, TOOLS, history, chunks)) > budget:
        history = history[2:]
        dropped.append("最旧的一轮对话")
    while chunks and ntok(assemble(SYSTEM, TOOLS, history, chunks)) > budget:
        chunks = chunks[:-1]
        dropped.append("排名最低的一块")
    return history, chunks, dropped


def main() -> None:
    print("=== 1. 四个槽位各占多少 ===")
    s = slots()
    total = sum(s.values())
    for name, tok in s.items():
        print(f"  {name:<8}{tok:>6} token  {tok / total:>6.0%}")
    print(f"  {'合计':<8}{total:>6} token")

    print()
    budget = 600
    print(f"=== 2. 预算 {budget} token 时的抢占 ===")
    full = ntok(assemble(SYSTEM, TOOLS, HISTORY, CHUNKS))
    print(f"  完整装配 {full} token，超预算 {full - budget}")
    h, c, dropped = squeeze(HISTORY, CHUNKS, budget)
    after = ntok(assemble(SYSTEM, TOOLS, h, c))
    print(f"  抢占后 {after} token，历史剩 {len(h) // 2} 轮，块剩 {len(c)} 条")
    print(f"  丢弃顺序 {dropped}")

    print()
    print("=== 3. trim_messages 只裁历史，不动系统提示 ===")
    messages = [SystemMessage(SYSTEM)] + [
        msg for u, a in HISTORY
        for msg in (HumanMessage(u), AIMessage(a))
    ]
    trimmed = trim_messages(
        messages,
        max_tokens=150,
        strategy="last",
        token_counter=count_messages,
        include_system=True,
        allow_partial=False,
    )
    before = sum(ntok(m.content) for m in messages)
    after_t = sum(ntok(m.content) for m in trimmed)
    print(f"  消息 {len(messages)} 条 {before} token -> {len(trimmed)} 条 {after_t} token")
    print(f"  保留的第一条 {trimmed[1].content[:18]!r}…")
    print(f"  系统提示在最前 {isinstance(trimmed[0], SystemMessage)}")

    print()
    print("=== 4. 带编号的模板 ===")
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM + "\n" + TOOLS),
        ("human", "对话历史：\n{history}\n\n<资料>\n{context}\n</资料>\n\n问题：{question}"),
    ])
    filled = prompt.invoke({
        "history": "\n".join(f"{r}：{t}" for r, t in h),
        "context": "\n".join(f"[{i}] {c}" for i, c in enumerate(c, 1)),
        "question": "退货运费谁出？",
    })
    print(f"  渲染后 {len(filled.messages)} 条消息，共 {sum(ntok(m.content) for m in filled.messages)} token")
    print(f"  编号出现 {filled.messages[-1].content.count('[')} 处")

    print()
    print("=== 5. 压缩：把块压成与问题相关的一句 ===")
    docs = [Document(page_content=c, metadata={"id": i}) for i, c in enumerate(c[:3], 1)]
    llm = FakeListChatModel(responses=[
        "质量问题导致的退货，往返运费由商家承担。",
        "非质量问题退货，运费由买家承担。",
        "生鲜类商品不支持无理由退货。",
    ])
    compressor = LLMChainExtractor.from_llm(llm)
    compressed = compressor.compress_documents(docs, "退货运费谁出")
    before_c = sum(ntok(d.page_content) for d in docs)
    after_c = sum(ntok(d.page_content) for d in compressed)
    print(f"  {len(docs)} 块 {before_c} token -> {len(compressed)} 块 {after_c} token")
    for d in compressed:
        print(f"    {d.page_content!r}")


if __name__ == "__main__":
    main()




