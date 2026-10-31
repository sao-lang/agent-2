"""同一问题：RAG Top-3 块 vs wiki 条目。"""

from __future__ import annotations

from wiki_core import answer_from_wiki, compile_all, rag_top3


def main() -> None:
    question = "PLUS 会员定制商品能退吗？"
    print("question:", question)
    print("\n--- RAG Top-3 ---")
    for doc_id, text, score in rag_top3(question):
        print(f"{doc_id}  score={score:.2f}  {text}")
    print("\nwiki 条目：")
    entries = compile_all(include_exceptions=True)
    print(answer_from_wiki(question, entries))
    print("\n差异：RAG 的 Top-3 命中会员、例外、换货，缺 d1 的 7 天基础规则；")
    print("      条目把 d1+d2+d5 合成一条，并保留来源与交叉链接。")


if __name__ == "__main__":
    main()
