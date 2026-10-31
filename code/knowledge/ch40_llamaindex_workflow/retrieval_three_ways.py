"""第 40 章 · 同一道检索题的三种写法。

运行：
    $env:PYTHONPATH="$PWD\\.libs"; $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch40_llamaindex_workflow/retrieval_three_ways.py

三种写法：QueryEngine 一条链、手写 while 循环、Workflow 事件驱动。
判据是"检索到的块与问题有没有词面重叠"，命中率低于阈值就改写重查；
改写表是固定的两条（原理演示），真实系统里改写本身是一次 LLM 调用。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ANSWER, REWRITE, ScriptedLLM, build_index, hit_line, setup  # noqa: E402

THRESHOLD = 0.5
MAX_ROUNDS = 2
REWRITE_MAP = {"退货邮费谁付": REWRITE}
Q_ANSWERABLE = "退货邮费谁付"
Q_MISSING = "如何申请专利"


def coverage(query: str, text: str) -> float:
    """问题里的字有多大比例出现在这个块里。原理演示，不是语义相关性。"""
    chars = set(query)
    return sum(1 for c in chars if c in text) / len(chars)


def top_hit(retriever, query: str):
    hits = retriever.retrieve(query)
    return hits, hits[0]


def section_1_query_engine(index, llm: ScriptedLLM) -> None:
    print("=== 1. QueryEngine：一条链，合成前无法判断 ===")
    engine = index.as_query_engine(similarity_top_k=3)
    for q in (Q_ANSWERABLE, Q_MISSING):
        before = len(llm.prompts)
        resp = engine.query(q)
        used = len(llm.prompts) - before
        cov = coverage(q, resp.source_nodes[0].node.text) if resp.source_nodes else 0.0
        print(f"  问：{q}")
        print(f"    回答：{resp.response}")
        print(f"    首位来源：{resp.source_nodes[0].node.ref_doc_id}，词面覆盖率 {cov:.2f}")
        print(f"    LLM 调用：{used} 次（合成已经发生，覆盖率再低也拦不住）")


def section_2_manual(index, llm: ScriptedLLM) -> None:
    print("=== 2. 手写循环：先判覆盖率，再决定要不要合成 ===")

    def answer(q: str) -> tuple[str, list[str]]:
        retriever = index.as_retriever(similarity_top_k=3)
        trace: list[str] = []
        query = q
        for rnd in range(MAX_ROUNDS):
            hits, top = top_hit(retriever, query)
            cov = coverage(query, top.node.text)
            trace.append(f"第 {rnd} 轮 {query!r} 首位={top.node.ref_doc_id} 覆盖={cov:.2f}")
            if cov >= THRESHOLD:
                synth = get_response_synthesizer(response_mode="compact")
                resp = synth.synthesize(q, nodes=hits)
                trace.append(f"合成：{len(hits)} 个节点")
                return str(resp), trace
            nxt = REWRITE_MAP.get(query)
            if nxt is None:
                trace.append("没有可用的改写，放弃（0 次合成调用）")
                return "资料里没有依据，无法回答。", trace
            query = nxt
        return "两轮都不够，放弃。", trace

    for q in (Q_ANSWERABLE, Q_MISSING):
        before = len(llm.prompts)
        text, trace = answer(q)
        print(f"  问：{q}")
        for line in trace:
            print(f"    {line}")
        print(f"    回答：{text}")
        print(f"    LLM 调用：{len(llm.prompts) - before} 次")


class Retrieved(Event):
    query: str
    round: int


class Judged(Event):
    query: str
    round: int
    covered: float


class Rewritten(Event):
    query: str
    round: int


class RagFlow(Workflow):
    """事件驱动版：检索 → 判定 → 改写或合成，每一步都是独立函数。"""

    def __init__(self, index, **kwargs):
        super().__init__(**kwargs)
        self.index = index
        self.trace: list[str] = []

    @step
    async def start(self, ctx: Context, ev: StartEvent) -> Retrieved:
        q = ev.get("query")
        await ctx.store.set("hits", [])
        return Retrieved(query=q, round=0)

    @step
    async def retrieve(self, ctx: Context, ev: Retrieved) -> Judged:
        hits = self.index.as_retriever(similarity_top_k=3).retrieve(ev.query)
        await ctx.store.set("hits", hits)
        cov = coverage(ev.query, hits[0].node.text)
        self.trace.append(f"句柄 {ev.round}: 检索 {ev.query!r} → {hits[0].node.ref_doc_id} 覆盖 {cov:.2f}")
        return Judged(query=ev.query, round=ev.round, covered=cov)

    @step
    async def judge(self, ctx: Context, ev: Judged) -> Rewritten | StopEvent:
        if ev.covered >= THRESHOLD:
            hits = await ctx.store.get("hits")
            synth = get_response_synthesizer(response_mode="compact")
            resp = synth.synthesize(ev.query, nodes=hits)
            self.trace.append(f"句柄 {ev.round}: 合成 {len(hits)} 个节点")
            return StopEvent(result=(str(resp), ev.round, "answered"))
        nxt = REWRITE_MAP.get(ev.query)
        if nxt is None or ev.round + 1 >= MAX_ROUNDS:
            self.trace.append(f"句柄 {ev.round}: 无改写可用，放弃")
            return StopEvent(result=("资料里没有依据，无法回答。", ev.round, "refused"))
        return Rewritten(query=nxt, round=ev.round + 1)

    @step
    async def rewrite(self, ctx: Context, ev: Rewritten) -> Retrieved:
        self.trace.append(f"改写：{ev.query!r} → 下一轮")
        return Retrieved(query=ev.query, round=ev.round)


async def section_3_workflow(index, llm: ScriptedLLM) -> None:
    print("=== 3. Workflow：同样的判断，写成带类型的事件 ===")
    for q in (Q_ANSWERABLE, Q_MISSING):
        before = len(llm.prompts)
        flow = RagFlow(index=index, timeout=5)
        text, rnd, status = await flow.run(query=q)
        print(f"  问：{q}")
        for line in flow.trace:
            print(f"    {line}")
        print(f"    结果：{text!r}，状态 {status}，用了 {rnd + 1} 轮")
        print(f"    LLM 调用：{len(llm.prompts) - before} 次")


def main() -> None:
    llm = setup()
    index = build_index()
    vectors = len(index.vector_store.data.embedding_dict)
    print(f"语料：向量库 {vectors} 条，阈值 {THRESHOLD}，最多 {MAX_ROUNDS} 轮")
    hits = index.as_retriever(similarity_top_k=3).retrieve(Q_ANSWERABLE)
    print(f"「{Q_ANSWERABLE}」原始检索：{hit_line(hits)}")
    section_1_query_engine(index, llm)
    section_2_manual(index, llm)
    asyncio.run(section_3_workflow(index, llm))


if __name__ == "__main__":
    main()
