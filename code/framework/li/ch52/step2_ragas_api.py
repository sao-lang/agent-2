"""第 52 章 step2：RAGAS 的 API 长什么样（带 import 守卫，离线可跑）。

运行：
    python code/framework/li/ch52/step2_ragas_api.py

上一级的痛点：
    你手算完了四个指标，但真实项目要跑 300 条 case、要出报表、要接 CI。

这一级做什么：
    ① 说明 RAGAS 的数据集格式（就三个字段）
    ② 用 import 守卫：装了 ragas 就演示真实 API，没装就打印等价的伪代码
    ③ 把"你的指标"和"RAGAS 指标"做口径对照（这是本章最重要的表）
    ④ 讲清 judge 的三个已知偏差，以及为什么要做"与人工标注的一致性校验"

⚠️ 本仓库**不在 CI 里装 ragas**：
   它要求 langchain-openai<=1.1.9（本仓库是 1.7.2 以上）并引入 langchain-classic，
   装了会把第 42–49 章的示例搞坏。这就是"可选依赖 + import 守卫"的实际原因。
"""
from __future__ import annotations

from typing import Any

try:                                     # ① 守卫：装了才用
    import ragas                        # noqa: F401
    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    HAS_RAGAS = True
    RAGAS_VERSION = getattr(ragas, "__version__", "unknown")
except Exception as e:                   # noqa: BLE001
    HAS_RAGAS = False
    RAGAS_VERSION = f"未安装（{type(e).__name__}）"


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# RAGAS 的数据集就是这四列（+ 可选 ground_truth）
DATASET: list[dict[str, Any]] = [
    {
        "user_input": "退款多久到账？",
        "retrieved_contexts": ["退款将在 7 个工作日内原路退回。"],
        "response": "退款将在 7 个工作日内原路退回。",
        "reference": "退款将在 7 个工作日内原路退回。",
    },
    {
        "user_input": "会员退货时优惠券能拿回来吗？",
        "retrieved_contexts": ["退货需在签收后 30 天内申请。"],
        "response": "优惠券可以返还，只要申请即可。",
        "reference": "会员退货时，已使用的优惠券不返还。",
    },
]


def main() -> None:
    line("① RAGAS 的数据集格式：只有四个字段")
    for i, row in enumerate(DATASET, 1):
        print(f"  第 {i} 条：")
        for k, v in row.items():
            print(f"    {k:<20} = {v!r}")
    print("""
  user_input          问题
  retrieved_contexts  检索到的上下文（列表）
  response            模型生成的答案
  reference           参考答案（可选，但算 context_recall / answer_correctness 需要）

  → 这个格式和第 40 章 evals/rag_cases.json 几乎一样，
    说明"评测集格式"是行业共识，不是某个框架发明的。""")

    line("② 真实 API（装了 ragas 才跑）")
    print(f"  ragas 状态：{RAGAS_VERSION}")
    if HAS_RAGAS:
        ds = EvaluationDataset.from_list(DATASET)
        result = evaluate(
            dataset=ds,
            metrics=[context_recall, context_precision, faithfulness, answer_relevancy],
        )
        print(f"  评测结果：{result}")
    else:
        print("""
  没装 ragas 时，等价的代码是（照抄即可，装上就能跑）：

      from ragas import EvaluationDataset, evaluate
      from ragas.metrics import (
          context_recall, context_precision, faithfulness, answer_relevancy,
      )

      ds = EvaluationDataset.from_list([
          {
              "user_input": q,
              "retrieved_contexts": ctx_list,
              "response": answer,
              "reference": gt,
          }
          for q, ctx_list, answer, gt in my_cases
      ])
      result = evaluate(dataset=ds, metrics=[...])
      print(result)          # 一个 DataFrame，带每条 case 的分数

  安装命令（注意会动 langchain 版本，务必在独立 venv 里试）：
      pip install ragas
  本仓库选择不装，理由见文件头。""")

    line("③ 口径对照：你以为的 vs RAGAS 的")
    print("""  | 指标 | 你的手算版（step1） | RAGAS 版 | 差异点 |
  |---|---|---|---|
  | context_recall | 金标句被上下文覆盖的比例 | 从 reference 里抽"论断"，逐条判是否被上下文支持（用 LLM） | 粒度不同：句子 vs 论断 |
  | context_precision | 命中句的平均精度 | 逐条判 retrieved 是否相关，再算平均精度 | 口径接近，但判定方式不同 |
  | faithfulness | 答案句与上下文的最大字面重合 | 从 response 抽论断，逐条判是否有上下文支持 | **LLM 判定，更准也更贵** |
  | answer_relevancy | 答案与问题的字面重合 | 从答案**反推问题**，与原问题算 embedding 相似度 | 目的不同：防"答得通顺但跑题" |
  | answer_correctness | 没有（你用人工比对） | 需要 ground_truth，用 LLM + 相似度综合 | **这是唯一直接判"对错"的** |

  → 关键结论：**RAGAS 的四个核心指标里，没有一个是"答案对不对"。**
    要判对错，必须有 ground_truth 并计算 answer_correctness，或者人工标注。""")

    line("④ judge 的三个已知偏差")
    print("""  1. 位置偏差（position bias）
     把两段上下文换个顺序，judge 的判断会变。典型表现：排在后面的证据被忽略。
     缓解：评测时**随机打乱上下文顺序**，看分数波动多大。

  2. 长度偏差（verbosity bias）
     更长的答案更容易被判"信息量更大"。典型表现：啰嗦的回答 faithfulness 偏高。
     缓解：同时报告 answer length；对比实验里控制长度。

  3. 自我偏好（self-preference）
     用 A 模型当 judge 时，它偏爱 A 模型写的答案（同类风格）。
     缓解：judge 用与生成**不同厂商**的模型；或用两两比较 + 人工抽样校准。

  → 所以：**judge 必须做一致性校验**（第 40 章）。
     做法：抽 30 条人工标注，算 judge 与人工的一致率（Kappa 或简单一致率）。
     低于 0.6 就说明这个 judge 在你的领域不可用。""")

    line("⑤ TruLens 是什么（一句话 + 一张表）")
    print("""  TruLens 是"带仪表盘的 RAG 评测"：它在你的应用外面包一层，
  记录每次调用的输入输出，再挂"反馈函数"（feedback functions）打分。

  | | RAGAS | TruLens |
  |---|---|---|
  | 形态 | 离线批评测（给数据集，出报表） | 在线 + 离线（包住应用，边跑边打分） |
  | 核心概念 | Dataset + Metric | App + Feedback + Dashboard |
  | RAG 三件套 | context_* / faithfulness / answer_* | groundedness / context_relevance / answer_relevance |
  | 适合 | 回归测试、发版前门禁 | 上线后持续监控、定位单次请求 |

  → 两者不冲突：**RAGAS 管"发版前"，TruLens 管"上线后"。**""")

    line("⑥ 什么时候该用框架，什么时候不该")
    print("""  用 RAGAS 当：
    · case 数 > 100，要出报表
    · 要与业界口径对齐（面试/论文/跨团队比较）
    · 需要 LLM judge 的细腻判定

  不用 RAGAS 当：
    · case < 30（手算更快，而且你能看懂每个数字）
    · 没有 ground_truth（RAGAS 大部分指标需要它）
    · 预算紧（judge 是 N 次模型调用）
    · 你的领域术语特殊（judge 经常判错，第 40 章讲过）

  → 最好的做法：**手算版做粗筛，RAGAS 做精筛，人工做仲裁。**""")


if __name__ == "__main__":
    main()
