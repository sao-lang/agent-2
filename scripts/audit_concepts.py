"""全书基础概念清查：按六个概念域逐条扫描章节正文。

输出每条概念的命中章号与次数，供人工判定"覆盖 / 不足 / 缺失"。
关键词只用于定位，判定以回读原节为准。
"""

from __future__ import annotations

import re
from pathlib import Path

GROUPS: dict[str, dict[str, list[str]]] = {
    "模型层": {
        "token 与分词器": ["tokenizer", "BPE", "词表", "分词器"],
        "chat template 与特殊 token": ["chat template", "特殊 token", "对话模板"],
        "上下文窗口": ["上下文窗口", "window", "窗口上限"],
        "消息角色": ["system", "user", "assistant", "角色"],
        "finish_reason": ["finish_reason", "stop", "length"],
        "usage 与计费": ["usage", "input_tokens", "计费"],
        "温度与采样": ["temperature", "top_p", "采样"],
        "logprobs 与置信度": ["logprob", "概率", "置信"],
        "流式与 SSE": ["流式", "stream", "SSE"],
        "function calling": ["function calling", "tool_calls", "工具调用"],
        "结构化输出": ["json_schema", "structured", "结构化输出"],
        "max_tokens 与 stop": ["max_tokens", "stop=", "截断"],
        "多模态输入": ["多模态", "图片", "vision", "音频"],
        "KV cache 与推理": ["KV cache", "推理加速", "prefill"],
        "模型选型与能力边界": ["模型选型", "能力边界", "小模型"],
    },
    "Agent 层": {
        "工具 schema": ["schema", "工具定义", "parameters"],
        "并行工具调用": ["并行调用", "parallel tool", "多个工具"],
        "工具错误与重试": ["工具失败", "错误回灌", "retry"],
        "循环与终止": ["终止", "while", "退出条件"],
        "四种失控": ["失控", "无限循环", "空转"],
        "编排范式": ["ReAct", "Plan-and-Execute", "工作流"],
        "handoff 与 subagent": ["handoff", "subagent", "子 agent"],
        "反思与裁判": ["裁判", "反思", "reflect"],
        "状态设计": ["State", "状态设计", "reducer"],
        "持久化与幂等": ["checkpoint", "幂等", "恢复"],
        "MCP": ["MCP", "JSON-RPC", "tools/list"],
        "Skill 与三级加载": ["Skill", "SKILL.md", "三级加载"],
        "上下文裁剪": ["裁剪", "压缩", "summar"],
    },
    "RAG 层": {
        "文档解析": ["PDF", "解析", "unstructured", "markdown"],
        "切块策略": ["切块", "chunk", "分块"],
        "token 切块": ["token 切块", "TokenTextSplitter", "按 token"],
        "语义切块": ["语义切块", "semantic chunk"],
        "嵌入原理": ["向量空间", "embedding", "嵌入模型"],
        "距离与归一化": ["余弦", "cosine", "归一化", "点积"],
        "维度与截断": ["维度", "max_seq", "512"],
        "向量数据库": ["向量库", "vector store", "qdrant", "milvus", "pgvector"],
        "索引类型": ["HNSW", "IVF", "PQ", "Flat"],
        "元数据过滤": ["payload", "metadata", "filter"],
        "混合检索与 RRF": ["RRF", "混合检索", "BM25"],
        "重排": ["重排", "rerank", "CrossEncoder"],
        "查询改写": ["改写", "HyDE", "多查询"],
        "MMR 多样性": ["MMR", "多样性"],
        "检索指标 MRR/nDCG": ["MRR", "nDCG"],
        "上下文装配": ["槽位", "预算", "装配"],
        "长期记忆": ["长期记忆", "语义记忆", "情景记忆"],
        "知识治理": ["版本", "增量", "矛盾", "可溯源"],
        "引用校验": ["引用", "citation", "锚点"],
    },
    "约束层": {
        "沙箱与路径": ["沙箱", "resolve", "越界"],
        "网络出口": ["出站", "白名单", "SSRF", "元数据地址"],
        "护栏与规则": ["护栏", "黑名单", "白名单"],
        "PII": ["PII", "身份证", "手机号"],
        "注入": ["注入", "投毒", "间接注入"],
        "审批与中断": ["审批", "中断", "审批卡片"],
        "多智能体": ["多 Agent", "多智能体", "A2A"],
        "对外形态": ["同步", "异步", "流式"],
        "交付四件套": ["队列", "幂等", "限流", "鉴权"],
        "容器与镜像": ["Dockerfile", "镜像", "多阶段"],
        "密钥与配置": ["密钥", "环境变量", "配置管理"],
        "灰度与回滚": ["灰度", "回滚", "金丝雀"],
    },
    "度量层": {
        "计量字段": ["span", "trace_id", "usage"],
        "OTel 约定": ["OTel", "OpenTelemetry", "语义化"],
        "落盘与采样": ["落盘", "采样", "JSONL"],
        "RAG 评测": ["faithfulness", "context precision", "RAGAS"],
        "检索指标": ["recall", "precision", "命中率"],
        "Agent 评测": ["轨迹", "trajectory", "四层"],
        "裁判可信": ["kappa", "一致率", "裁判"],
        "多轮与 HITL": ["多轮", "HITL", "人在环"],
        "统计与区间": ["置信区间", "Wilson", "显著性"],
        "门禁": ["门禁", "阈值", "回归"],
        "成本归因": ["成本瀑布", "归因", "预算"],
        "延迟瀑布": ["TTFT", "延迟瀑布", "P95"],
        "复盘与回归": ["复盘", "五问", "事故"],
    },
    "工程基础": {
        "pydantic 与契约": ["pydantic", "BaseModel", "schema 校验"],
        "配置与 Settings": ["pydantic-settings", "配置项", "Settings"],
        "日志与错误分类": ["日志", "错误分类", "异常"],
        "测试与夹具": ["pytest", "单测", "fixture"],
        "依赖与版本": ["requirements", "版本锁定", "依赖"],
        "并发与线程": ["线程", "并发", "asyncio"],
    },
}


def chapters() -> list[Path]:
    return sorted(p for p in Path(".").glob("*.md") if re.match(r"^\d\d-", p.name))


def main() -> None:
    files = chapters()
    print(f"扫描 {len(files)} 章\n")
    for group, concepts in GROUPS.items():
        print(f"## {group}")
        print(f"{'概念':<26}{'命中章':<26}{'次数':>5}  判定")
        for name, keys in concepts.items():
            hits: list[str] = []
            total = 0
            for f in files:
                t = f.read_text(encoding="utf-8")
                c = sum(t.count(k) for k in keys)
                if c:
                    hits.append(f.name[:2])
                    total += c
            verdict = "覆盖" if total >= 5 else ("不足" if total else "缺失")
            print(f"{name:<26}{','.join(hits) or '-':<26}{total:>5}  {verdict}")
        print()


if __name__ == "__main__":
    main()
