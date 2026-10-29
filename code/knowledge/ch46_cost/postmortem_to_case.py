"""从一次事故到一条永不回归的用例：五问、分类、修好、固化。

不联网。事故的现场是"生鲜退货答错了"，用五问走到根因，归到"检索/版本"这一类；
然后把这次输入做成一条用例，分别在旧配置与新配置上跑一遍——旧配置必须失败，
新配置必须通过。这一步过不了，说明修的不是根因。
"""

from __future__ import annotations

import json

# 事故记录（人工整理）
INCIDENT = {
    "id": "INC-0314",
    "start": "2026-03-14 10:20",
    "end": "2026-03-14 11:05",
    "symptom": "生鲜退货咨询回答'可以退'，实际政策不支持",
    "impact": "37 次会话给出错误承诺",
}

WHYS = [
    "为什么答错？——回答依据的块写着'7 天内可退'，没有生鲜例外",
    "为什么依据了那一块？——检索把 15 天版本的旧块排在了第一条",
    "为什么旧块还在？——文档更新时新块插入了，旧块只标了 inactive，没有过滤",
    "为什么没有过滤？——检索实现里没写 active 条件，靠调用方自觉",
    "为什么靠调用方自觉？——入库与检索是两个模块，'失效'语义没有统一在一处",
]

# 失败分类：决定修复方向
FAILURE_CLASSES = {
    "数据与版本": "旧版本块未过滤、条目过期",
    "检索质量": "召回缺失、排序不当",
    "生成": "编造、漏要点",
    "编排": "步数、终止条件",
    "权限": "越权、审批绕过",
    "基础设施": "超时、限流、依赖故障",
}

# 知识库：生鲜条目有两个版本，旧版本块仍被标为 active
DOCS = [
    {"id": "policy#4", "version": 1, "active": True,
     "text": "生鲜商品签收后 7 天内可退。"},
    {"id": "policy#4", "version": 2, "active": True,
     "text": "生鲜类商品不支持无理由退货。"},
    {"id": "policy#3", "version": 2, "active": True,
     "text": "质量问题退货，签收后 15 天内提交凭证。"},
]
CURRENT_VERSION = 2


def retrieve(question: str, config: str) -> dict:
    """两种配置：旧的不看版本，新的只看当前版本。"""
    hits = [d for d in DOCS if "生鲜" in d["text"] or "退货" in d["text"]]
    if config == "new":
        hits = [d for d in hits if d["version"] == CURRENT_VERSION]
    hits.sort(key=lambda d: d["version"])          # 旧配置下老版本排前面
    return hits[0]


def answer(question: str, config: str) -> str:
    chunk = retrieve(question, config)
    return f"根据{doc_id(chunk)}：{chunk['text']}"


def doc_id(chunk: dict) -> str:
    return f"{chunk['id']}@v{chunk['version']}"


# 从事故固化出来的一条用例
CASE = {
    "case_id": "reg-0314-01",
    "question": "生鲜订单可以无理由退货吗？",
    "must_contain": "不支持",
    "must_not_contain": "可以退",
    "source": "INC-0314",
}


def judge(ans: str) -> tuple[bool, str]:
    if CASE["must_contain"] not in ans:
        return False, f"缺少关键结论'{CASE['must_contain']}'"
    if CASE["must_not_contain"] in ans:
        return False, f"出现了不该有的说法'{CASE['must_not_contain']}'"
    return True, "结论正确"


def main() -> None:
    print("=== 1. 事故记录 ===")
    for k, v in INCIDENT.items():
        print(f"  {k:<8}{v}")

    print()
    print("=== 2. 五问法 ===")
    for i, why in enumerate(WHYS, 1):
        print(f"  问 {i}：{why}")
    print(f"  根因：{WHYS[-1].split('——')[-1]}")

    print()
    print("=== 3. 失败分类 ===")
    print(f"  归到「数据与版本」：{FAILURE_CLASSES['数据与版本']}")
    print("  修复方向：检索层加版本过滤，而不是改提示词")

    print()
    print("=== 4. 固化成用例 ===")
    print("  " + json.dumps(CASE, ensure_ascii=False, indent=2).replace("\n", "\n  "))

    print()
    print("=== 5. 旧配置与新配置各跑一遍 ===")
    for config in ("old", "new"):
        ans = answer(CASE["question"], config)
        ok, why = judge(ans)
        chunk = retrieve(CASE["question"], config)
        print(f"  [{config}] 召回 {doc_id(chunk)}  回答：{ans}")
        print(f"         判定：{'通过' if ok else '失败'}（{why}）")

    print()
    print("=== 6. 这条用例的后续 ===")
    print("  旧配置失败、新配置通过 -> 修复有效，用例进入回归集")
    print("  若两边都通过 -> 事故没复现，用例没抓到根因，需要重新写")
    print("  若两边都失败 -> 根因还在，别急着写复盘")


if __name__ == "__main__":
    main()
