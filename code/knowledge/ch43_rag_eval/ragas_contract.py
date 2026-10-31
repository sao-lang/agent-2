"""RAGAS 的接口契约：先看清它要什么，再决定怎么接。

本机未安装 ragas（脚本会自己检测并打印"未安装"），所以这里不执行任何 RAGAS 调用，
只做三件能离线做的事：
  1 检测 ragas 是否可导入，并给出安装命令
  2 打出四个指标各自的输入、依赖与它和 ragas_four.py 代理口径的差别
  3 打出 dataset -> evaluate -> 报告 -> CI 这条链上，框架替你做了什么、没做什么

接口只写确定存在的三个名字：EvaluationDataset、SingleTurnSample、evaluate。
指标的类名与构造参数在不同大版本之间改过，这里不写，接的时候以所装版本的
文档为准 —— 写错签名比不写更贵。
"""

from __future__ import annotations

import importlib.util

INSTALL = "pip install ragas datasets"

# 四个指标：输入、判分依赖、与代理口径的差别
METRICS = [
    ("faithfulness", "answer + contexts", "LLM 判分（拆断言 + 逐条判是否被上下文支持）",
     "代理版用二元组重合；RAGAS 版会把断言改写成独立陈述再判"),
    ("answer relevancy", "question + answer", "LLM + 嵌入（反推问题后算相似度）",
     "代理版直接算问答字面 F1；RAGAS 版比较的是'反推问题'与原问题"),
    ("context precision", "question + contexts + reference", "LLM 判分（逐块判相关）",
     "代理版用人工 rel 标注；RAGAS 版让 LLM 判每块是否相关"),
    ("context recall", "reference + contexts", "LLM 判分（标准答案逐句归因到块）",
     "代理版用重合度覆盖；RAGAS 版按句子归因"),
]

# 框架在一条跑批链上做与不做的事
PIPELINE = [
    ("dataset 构造", "给 SingleTurnSample 的字段形状；从文件读", "不替你决定样本从哪来、覆盖哪几类"),
    ("evaluate 跑批", "并发、重试、把每个指标的中间结果留下来", "不替你控成本：裁判也是一次次模型调用"),
    ("报告", "按样本给分，可导出", "不替你判'这个差异算不算数'（区间与门禁仍是第 45 章）"),
    ("CI 接入", "能被脚本调用，返回结构化结果", "不替你定阈值，也不替你处理密钥与配额"),
]


def pad(text: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def detect() -> None:
    print("=== 1. ragas 是否可用 ===")
    for name in ("ragas", "datasets", "langfuse", "opentelemetry"):
        ok = importlib.util.find_spec(name) is not None
        print(f"  {pad(name, 16)}{'已安装' if ok else '未安装'}")
    if importlib.util.find_spec("ragas") is None:
        print(f"  安装：{INSTALL}")
        print("  <- 本章的四个指标用代理口径离线复算；接 RAGAS 时换成真实指标，")
        print("     评测集、分层归因、门禁这三层结构不变")


def contract() -> None:
    print()
    print("=== 2. 四个指标要什么、依赖什么 ===")
    print("  " + pad("指标", 20) + pad("输入", 36) + "判分依赖")
    for name, inp, dep, _ in METRICS:
        print("  " + pad(name, 20) + pad(inp, 36) + dep)

    print()
    print("=== 3. 与 ragas_four.py 的代理口径差在哪 ===")
    for name, _, _, diff in METRICS:
        print(f"  {pad(name, 20)}{diff}")

    print()
    print("=== 4. 三个确定存在的入口 ===")
    print("  SingleTurnSample   一条单轮样本：用户输入、检索上下文、回答、参考答案")
    print("  EvaluationDataset  一组样本；可从文件构造，也可从列表构造")
    print("  evaluate           跑批入口：dataset + 指标列表 -> 逐样本分 + 汇总分")
    print("  <- 只写这三个名字：指标的类名与参数跨版本变过，按安装版本的文档接")


def pipeline() -> None:
    print()
    print("=== 5. dataset -> evaluate -> 报告 -> CI：框架做与不做 ===")
    print("  " + pad("环节", 16) + pad("框架做的", 44) + "仍要你做的")
    for a, b, c in PIPELINE:
        print("  " + pad(a, 16) + pad(b, 44) + c)
    print("  <- 用了它之后变得可做的三件事：批量跑几百条、逐样本留中间结果、把跑批接进 CI")
    print("     它没让'指标可信'变得更容易：裁判的偏差仍要按第 44 章的一致性去证")


def main() -> None:
    detect()
    contract()
    pipeline()


if __name__ == "__main__":
    main()
