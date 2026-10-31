"""LangGraph 的函数式 API：用 @task 与 @entrypoint 写同一条流水线。

不联网。三个 task 先提交、后取结果，所以两个 score 是并行的；
入口只负责编排，不关心每个 task 内部怎么算。

运行：python code/knowledge/ch36_langgraph/functional_api.py
"""

from __future__ import annotations

from langgraph.func import entrypoint, task

KEYWORDS = ["超时", "重试", "连接池", "权限"]


@task
def split(text: str) -> list[str]:
    return [s.strip() for s in text.replace("；", "。").split("。") if s.strip()]


@task
def score(sentence: str) -> dict:
    hits = [k for k in KEYWORDS if k in sentence]
    return {"sentence": sentence, "hits": hits, "weight": len(hits)}


@task
def rank(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: r["weight"], reverse=True)


@entrypoint()
def triage(text: str) -> list[dict]:
    sentences = split(text).result()
    # 先全部提交，再统一取结果：两个 score 之间没有依赖，可以并行
    futures = [score(s) for s in sentences]
    rows = [f.result() for f in futures]
    return rank(rows).result()


def main() -> None:
    text = "连接池耗尽导致超时。重试没有上限。权限配置缺失。磁盘只读。"
    rows = triage.invoke(text)
    print("=== 1. 函数式 API 的输出 ===")
    for r in rows:
        print(f"  权重 {r['weight']}  {r['sentence']}  hits={r['hits']}")
    print()
    print("=== 2. 与图 API 的对照 ===")
    print("  图 API：节点 + 边 + 状态，编译后 invoke")
    print("  函数式：task + entrypoint，直接调用函数，返回值就是状态")
    print("  <- 函数式适合'一条直线 + 少量并行'；需要条件边、检查点、跨节点状态时回图 API")


if __name__ == "__main__":
    main()
