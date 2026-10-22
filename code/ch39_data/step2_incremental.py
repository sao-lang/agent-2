"""第 39 章 step2：增量索引与多租户隔离（离线）。

运行：
    python code/ch39_data/step2_incremental.py

上一级的痛点：
    step1 每次都是"从头建一个 store"。真实项目里文档有 1200 份、每天变 10 份。

这一级做什么：
    ① 变更检测：按内容 hash（不是按修改时间）
    ② 增量策略对比：全量重建 vs 增量 vs 只重建受影响的分块
    ③ 多租户隔离：用元数据过滤，而不是"每个租户一张表"
    ④ 一个必须知道的坑：过滤放在"向量检索之前"和"之后"完全不同

关键认知：
    增量不是"优化"，是"能不能每天跑"的分水岭。
    全量重建 1200 篇 = 1200 次嵌入；增量 10 篇 = 10 次。差 120 倍。
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from step1_lifecycle import DOC_PATH, Chunk, clean, sha  # noqa: E402

TENANTS = ["acme", "globex", "initech"]


@dataclass
class TenantIndex:
    """一个"逻辑索引"，内部按租户打标（不是每个租户一份）。"""

    chunks: list[Chunk] = field(default_factory=list)
    embed_calls: int = 0          # 统计嵌入次数，用来算成本

    def add(self, ch: Chunk, tenant: str) -> None:
        ch.tags = [*ch.tags, f"tenant:{tenant}"]
        self.chunks.append(ch)
        self.embed_calls += 1

    def remove_doc(self, doc_id: str, tenant: str) -> int:
        before = len(self.chunks)
        self.chunks = [c for c in self.chunks
                       if not (c.doc_id == doc_id and f"tenant:{tenant}" in c.tags)]
        return before - len(self.chunks)

    def search(self, q: str, tenant: str, k: int = 3,
               filter_before: bool = True) -> list[Chunk]:
        """极简检索：字符重合度。重点在**过滤时机**，不在打分算法。"""
        qs = set(q)

        def score(c: Chunk) -> float:
            cs = set(c.text)
            return len(qs & cs) / len(qs) if qs else 0.0

        if filter_before:
            # ① 先按租户过滤，再排序取 top-k（正确）
            pool = [c for c in self.chunks if f"tenant:{tenant}" in c.tags]
            return sorted(pool, key=score, reverse=True)[:k]

        # ② 先全库排序取 top-k，再过滤（错误：可能一条都不剩）
        pool = sorted(self.chunks, key=score, reverse=True)[:k]
        return [c for c in pool if f"tenant:{tenant}" in c.tags]


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def load_chunks(version: int = 1) -> list[Chunk]:
    raw = DOC_PATH.read_text(encoding="utf-8")
    text, _ = clean(raw)
    import re
    sections = re.split(r"\n(?=#{2,3} )", text)
    out = []
    for i, sec in enumerate(sections):
        sec = sec.strip()
        if not sec:
            continue
        out.append(Chunk(
            doc_id=DOC_PATH.name, version=version,
            chunk_id=f"{DOC_PATH.stem}#v{version}#c{i:02d}",
            heading=sec.splitlines()[0].lstrip("# ").strip(),
            text=sec[:300], content_hash=sha(sec),
            source=DOC_PATH.name, updated_at="2025-01-01", tags=[],
        ))
    return out


def main() -> None:
    idx = TenantIndex()
    base = load_chunks()

    line("① 三个租户各自入库（同一份文档，三份拷贝——现实中通常如此）")
    for t in TENANTS:
        for c in base:
            # 块 id 加租户前缀，避免跨租户撞 id
            c2 = Chunk(**{**c.__dict__, "chunk_id": f"{t}:{c.chunk_id}"})
            idx.add(c2, t)
    print(f"  逻辑上 1 个索引，物理上 {len(idx.chunks)} 个块，嵌入调用 {idx.embed_calls} 次")
    print(f"  每个租户 {len(base)} 块")

    line("② 变更检测：按内容 hash，不按修改时间")
    raw = DOC_PATH.read_text(encoding="utf-8")
    h1 = sha(raw)
    time.sleep(0.01)
    path_mtime = DOC_PATH.stat().st_mtime
    h2 = sha(raw)
    print(f"  hash 两次一致（{h1 == h2}），但 mtime 会变（{path_mtime:.0f}）")
    print("  → 只按 mtime 判断，'git checkout 一遍'就会触发全量重建。")
    print("  → 只按 hash 判断，'改了一个错别字再改回来'不会触发（正确）。")

    line("③ 增量策略对比：1200 篇里改了 10 篇")
    total, changed = 1200, 10
    print(f"  {'策略':<26}{'嵌入次数':>10}{'相对全量':>10}")
    print("  " + "-" * 46)
    print(f"  {'A 全量重建':<26}{total:>10}{'1.00':>10}")
    print(f"  {'B 按文档增量':<26}{changed:>10}{changed / total:>10.3f}")
    print(f"  {'C 按块增量（只重算变了的块）':<26}{max(1, changed // 2):>10}"
          f"{max(1, changed // 2) / total:>10.3f}")
    print("\n  → B 差 120 倍；C 再差 2 倍，但 C 要求'块级 hash 比对'，复杂度上一个台阶。")
    print("    起步建议：先做 B（按文档增量），等文档量上万了再做 C。")

    line("④ 多租户隔离：过滤时机决定成败")
    # 为了让"先排序再过滤"真的出事，先让 acme 的块"看起来没那么像"：
    # 给 acme 的每个块末尾追加一个干扰词（模拟不同租户的文档版本略有差异）。
    for c in idx.chunks:
        if "tenant:acme" in c.tags:
            c.text = c.text + "（acme 定制版）"
    # 再给其他租户插入一批**与查询高度重合**的块（模拟"别的租户也有类似政策"）
    for t in ("globex", "initech"):
        for j in range(3):
            idx.add(Chunk(
                doc_id="other.md", version=1, chunk_id=f"{t}:other#c{j}",
                heading="退款时效", text="退款多久到账？7 个工作日内原路退回。",
                content_hash=f"h{j}", source="other.md", updated_at="2025-01-01", tags=[],
            ), t)

    q = "退款多久到账"
    for before in (True, False):
        got = idx.search(q, "acme", k=3, filter_before=before)
        label = "先过滤再排序（正确）" if before else "先排序再过滤（错误）"
        print(f"  {label}：返回 {len(got)} 条"
              + (f"，首条 = {got[0].chunk_id}" if got else "，**一条都没有**"))

    print("\n  → '先排序再过滤' 在 top-3 里只要没有 acme 的块，就返回 0 条。")
    print("    真实场景：别的租户的文档和你的高度相似（同一套产品说明书），top-3 很容易被占满。")
    print("    这是最经典的越权/数据丢失 bug —— **看起来是检索问题，其实是过滤位置错了**。")

    line("⑤ 删文档必须级联删索引")
    removed = idx.remove_doc(DOC_PATH.name, "acme")
    left = sum(1 for c in idx.chunks if "tenant:acme" in c.tags)
    print(f"  删除 acme 的 {DOC_PATH.name} → 移除 {removed} 块，剩余 {left} 块")
    total_left = len(idx.chunks)
    print(f"  其他租户不受影响：索引里还有 {total_left} 块")
    print("  → 真实项目还要做'反向对账'：列出所有源文件，逐个检查索引里是否还有它的块。")
    print("    以及对每个块检查源文件是否还存在（孤儿块）。")

    line("⑥ 一个更省的隔离方案（同一份文档，多租户共享物理索引）")
    print("""  当文档内容完全相同（比如你们的产品说明书），可以：
    · 物理上只存一份（chunk 的 tags 里放 ["tenant:acme","tenant:globex"]）
    · 检索时按 tenant 过滤

  省下的是嵌入成本（1 次 vs 3 次），代价是：
  · 删除一个租户要只摘掉 tag，不能删块
  · 权限判断更复杂（必须保证过滤真的生效）
  → 内部系统推荐"共享 + 过滤"，对外 SaaS 推荐"物理隔离"。""")

    line("⑦ 成本对照（按第 2 章口径）")
    print(f"  全量重建 1200 篇 × 平均 {len(base)} 块/篇 = {1200 * len(base):,} 次嵌入")
    print(f"  增量 10 篇 = {10 * len(base)} 次嵌入")
    print(f"  → 按第 7 章口径（1200 篇建库 ¥0.02），差额 ≈ ¥{(1200 - 10) / 1200:.1%} 的一次性成本")
    print("    钱不多，但**时间**差很多：全量可能要几分钟，增量几秒钟。")


if __name__ == "__main__":
    main()
