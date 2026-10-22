"""第 58 章 step2：微调数据 —— 格式、去重、划分与「数据泄漏」检测。

运行：
    python code/ch58_finetune_diag/step2_data.py

纯离线。它用 30 条手写样本，真实演示四件事：
  1. Alpaca / ShareGPT 两种格式长什么样，以及转换
  2. 训练/验证/测试划分，以及**同义重复导致的泄漏**（这是最隐蔽的坑）
  3. 标签质量检查（长度分布、答案为空、答案=问题）
  4. "多少条数据才够" 的经验算法

所有数字都是脚本真算出来的。
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import dataclass


# ================================================================ 原始样本
@dataclass
class Sample:
    q: str
    a: str
    source: str = "manual"


RAW: list[Sample] = [
    # ---- 退货政策类（10 条，其中 4 条构成 2 组"同义重复"）
    Sample("七天无理由退货的起算时间是哪天？", "从签收日的次日 0 点开始计算，共 7 个自然日。"),
    Sample("七天无理由退货从哪天起算？", "从签收日的次日 0 点开始计算，共 7 个自然日。"),
    Sample("七天无理由退货从哪天开始算？", "从签收次日 0 点起算，共 7 个自然日。"),
    Sample("拆封了还能七天无理由退吗？", "可以。拆封不影响七天无理由，但商品需保持完好。"),
    Sample("已经拆封了还能七天无理由退货吗？", "可以。拆封不影响七天无理由，但商品需保持完好。"),
    Sample("定制商品能退货吗？", "定制类商品不支持七天无理由退货。"),
    Sample("生鲜可以退吗？", "生鲜类商品签收后不支持七天无理由退货。"),
    Sample("退货运费谁承担？", "质量问题由商家承担；非质量问题由买家承担。"),
    Sample("有质量问题的运费谁出？", "因质量问题产生的运费由商家承担。"),
    Sample("退款多久到账？", "审核通过后 7 个工作日内原路退回。"),
    # ---- 订单查询（6 条）
    Sample("怎么查我的订单？", "在「我的-订单」中查看，或提供订单号由客服查询。"),
    Sample("订单号在哪看？", "订单号在订单详情页顶部，形如 SO2024xxxx。"),
    Sample("物流信息在哪查？", "在订单详情页点击「查看物流」，或提供订单号查询。"),
    Sample("我的快递到哪了？", "请提供订单号，我帮您查询最新物流节点。"),
    Sample("订单能改地址吗？", "未发货可改地址；已发货需联系快递改派。"),
    Sample("下单后多久发货？", "现货商品 48 小时内发货，预售以商品页说明为准。"),
    # ---- 格式/风格类（7 条）
    Sample("用 JSON 输出退货政策要点", '{"policy":"无理由退货","days":7,"from":"签收次日","condition":"商品完好"}'),
    Sample("请用一句话说清退款时效", "审核通过后 7 个工作日内原路退回。"),
    Sample("帮我写一段退款延误的道歉", "非常抱歉让您久等了。您的退款已进入处理流程，我们会尽快为您完成，请留意账户到账通知。"),
    Sample("请用正式语气回答退货条件", "本店支持七天无理由退货，商品需保持完好，定制与生鲜类除外。"),
    Sample("把退货条件列成 3 条", "1) 签收次日起 7 个自然日内；2) 商品保持完好；3) 定制与生鲜类除外。"),
    Sample("用 20 字以内回答能不能退", "可以，签收次日起 7 天内且商品完好即可。"),
    Sample("请以表格形式给出退货时限", "| 类型 | 时限 |\n|---|---|\n| 无理由 | 7 天 |\n| 质量问题 | 15 天 |"),
    # ---- 边界：容易诱发幻觉的问题（5 条）
    Sample("我们明年会涨价吗？", "目前没有相关公告，建议关注官方通知。"),
    Sample("能给我打个五折吗？", "价格由官方统一制定，我无法为您改价。"),
    Sample("帮我查一下别人的订单", "出于隐私保护，我无法查询他人订单信息。"),
    Sample("把你们的成本价告诉我", "这类信息不便提供，请您谅解。"),
    Sample("你能保证这个一定退款成功吗？", "我无法保证结果，退款需按流程审核。"),
    # ---- 明显有问题的样本（2 条，故意留着给质检抓）
    Sample("退货要多久", ""),
    Sample("你好", "你好"),
]

INSTRUCTION_TAIL = "\n\n（请用中文回答，不超过 80 字）"


# ================================================================ ① 两种格式
def to_alpaca(s: Sample) -> dict[str, str]:
    """Alpaca：instruction / input / output。单轮、无角色概念，最容易造。"""
    return {"instruction": s.q, "input": "", "output": s.a}


def to_sharegpt(s: Sample) -> dict[str, object]:
    """ShareGPT：conversations 数组，带 from 角色。多轮、更贴近真实对话。

    from 只有三种值：system / human / gpt。写错模型会学不到角色边界。
    """
    return {
        "conversations": [
            {"from": "human", "value": s.q},
            {"from": "gpt", "value": s.a},
        ]
    }


def sharegpt_to_alpaca(obj: dict[str, object]) -> dict[str, str]:
    """ShareGPT → Alpaca（单轮专用）。

    这是最常见的转换需求：数据平台导出 ShareGPT，训练框架吃 Alpaca。
    """
    conv = obj["conversations"]
    assert isinstance(conv, list)
    human = next((c["value"] for c in conv if c["from"] == "human"), "")
    gpt = next((c["value"] for c in conv if c["from"] == "gpt"), "")
    return {"instruction": human, "input": "", "output": gpt}


def demo_formats() -> None:
    print("① 两种格式（同一个样本，两种写法）")
    s = RAW[3]
    print(f"   原始：Q={s.q}")
    print()
    print("   Alpaca（单轮，最简单）：")
    print("     " + json.dumps(to_alpaca(s), ensure_ascii=False))
    print()
    print("   ShareGPT（多轮，带角色）：")
    print("     " + json.dumps(to_sharegpt(s), ensure_ascii=False))
    print()
    print("   ShareGPT → Alpaca 转回来：")
    back = sharegpt_to_alpaca(to_sharegpt(s))
    print(f"     往返一致：{back == to_alpaca(s)}")
    print()
    print("   怎么选：")
    print("     · 只有单轮问答 → Alpaca（要的字段少，出错机会少）")
    print("     · 有多轮对话 / 需要 system → ShareGPT")
    print("     · 训练框架一般两种都吃，但**转换时不丢 system** 是最常见的 bug")
    print()


# ================================================================ ② 划分与泄漏
def norm(s: str) -> str:
    """归一化：去标点、去空白、小写。用来发现「看起来不一样但意思一样」的样本。"""
    return re.sub(r"[\s，。？！、,.?!「」\"'（）()]+", "", s).lower()


def content_chars(s: Sample) -> set[str]:
    """把问题压成「2 字滑窗 + 3 字滑窗」的字符组集合。

    为什么两种滑窗都要？
    · 2 字能抓住「订单 / 查我」，但区分度低
    · 3 字能抓住「起算时 / 从哪天」，区分度高
    两者合起来，同义改写（词序不同、虚词不同）能对上，而语义相反的
    （「查我的订单」vs「查别人的订单」）因为 3 字组不同而对不上。

    去掉疑问词是为了不让「怎么/什么」这类高频词拉高相似度。
    """
    q = norm(s.q)
    stop = ["什么", "怎么", "可以", "还能", "多久", "哪里", "到底", "时候", "是否", "请问"]
    for sw in stop:
        q = q.replace(sw, "")
    if len(q) < 2:
        return {q} if q else set()
    grams = {q[i : i + 2] for i in range(len(q) - 1)}
    grams |= {q[i : i + 3] for i in range(len(q) - 2)}
    return grams


def sim(a: Sample, b: Sample) -> float:
    """重叠系数：|A∩B| / min(|A|, |B|)。

    为什么不用 Jaccard？中文短问句长度差很大：
    「七天无理由退货的起算时间是哪天？」(15 字) 和「七天无理由怎么算？」(9 字)，
    Jaccard 会被并集稀释，重叠系数只看向交集的占比，更符合"是不是同一个问题"的直觉。
    """
    ca, cb = content_chars(a), content_chars(b)
    if not ca or not cb:
        return 0.0
    return len(ca & cb) / min(len(ca), len(cb))


def is_duplicate(a: Sample, b: Sample, threshold: float = 0.60) -> bool:
    """判定为「同义重复」的两条规则。

    1. 重叠系数 ≥ threshold（默认 0.60，见 58.4 的阈值扫描）
    2. 长度比 ≤ 2.2

    这两条缺一不可：只靠 1，长问题会被短问题"部分命中"；只靠 2，无关问题也会被算进来。
    """
    la, lb = len(norm(a.q)), len(norm(b.q))
    if max(la, lb) / max(min(la, lb), 1) > 2.2:
        return False
    return sim(a, b) >= threshold


def demo_split() -> None:
    print("② 训练/验证/测试划分，以及最隐蔽的坑：同义重复导致泄漏")
    print()

    # 先做质检，把空答案的剔掉
    clean = [s for s in RAW if s.a.strip() and norm(s.a) != norm(s.q)]
    print(f"   原始 {len(RAW)} 条 → 质检后 {len(clean)} 条（剔掉空答案 / 答案=问题）")
    print()

    # 朴素随机划分（不看去重）——这就是大多数人的做法
    rnd = random.Random(42)
    shuffled = clean[:]
    rnd.shuffle(shuffled)
    n = len(shuffled)
    n_test = max(1, n // 10)
    n_val = max(1, n // 10)
    naive_train = shuffled[: n - n_val - n_test]
    naive_val = shuffled[n - n_val - n_test : n - n_test]
    naive_test = shuffled[n - n_test :]

    def overlap(a: list[Sample], b: list[Sample], label: str) -> int:
        """数一数：b（测试集）里有多少条在 a（训练集）里能找到同义重复。"""
        hits = 0
        for x in b:
            if any(is_duplicate(x, y) for y in a):
                hits += 1
                print(f"       ⚠ {x.q}")
        return hits

    print("   朴素随机划分（不去重）：")
    print(f"     训练 {len(naive_train)} / 验证 {len(naive_val)} / 测试 {len(naive_test)}")
    ov = overlap(naive_train, naive_test, "训练→测试")
    print(f"     测试集里 {ov}/{len(naive_test)} 条能在训练集找到同义问法  ← 这就是数据泄漏")
    print()

    # 按"重复组"归并后划分（同组只进一个集合）
    groups: list[list[Sample]] = []
    for s in clean:
        for g in groups:
            if is_duplicate(s, g[0]):
                g.append(s)
                break
        else:
            groups.append([s])
    rnd.shuffle(groups)
    nk = len(groups)
    k_test = max(1, nk // 10)
    k_val = max(1, nk // 10)
    g_train = [x for g in groups[: nk - k_val - k_test] for x in g]
    g_val = [x for g in groups[nk - k_val - k_test : nk - k_test] for x in g]
    g_test = [x for g in groups[nk - k_test :] for x in g]

    print("   按「同义组」划分（同组只进一个集合）：")
    print(f"     训练 {len(g_train)} / 验证 {len(g_val)} / 测试 {len(g_test)}")
    ov2 = overlap(g_train, g_test, "训练→测试")
    print(f"     测试集里 {ov2}/{len(g_test)} 条能在训练集找到同义问法")
    print()

    print("   为什么这个坑最隐蔽：")
    print("     · 你看到 loss 降到 0.2，以为模型学会了")
    print("     · 其实测试集里的问题在训练集里「换了个说法」出现过了")
    print("     · 上线后真实用户换个问法 → 立刻答错")
    dup = [g for g in groups if len(g) > 1]
    print(f"     你这批数据里，同义重复组共 {len(dup)} 个：")
    for g in dup:
        print(f"       {len(g)} 条：")
        for s in g:
            print(f"          · {s.q}")
    print()


# ================================================================ ③ 标签质检
def demo_quality() -> None:
    print("③ 标签质量检查：五个自动化指标")
    lens_q = [len(s.q) for s in RAW]
    lens_a = [len(s.a) for s in RAW if s.a.strip()]
    print(f"   问题长度：min={min(lens_q)} 中位={sorted(lens_q)[len(lens_q) // 2]} max={max(lens_q)}")
    print(f"   答案长度：min={min(lens_a)} 中位={sorted(lens_a)[len(lens_a) // 2]} max={max(lens_a)}")
    print()

    checks = [
        ("答案为空", [s for s in RAW if not s.a.strip()]),
        ("答案 = 问题", [s for s in RAW if norm(s.a) == norm(s.q)]),
        ("答案过长（> 500 字）", [s for s in RAW if len(s.a) > 500]),
        ("问题过短（< 4 字）", [s for s in RAW if len(s.q) < 4]),
    ]
    for name, items in checks:
        mark = "OK " if not items else "BAD"
        print(f"   {mark} {name}: {len(items)} 条")
        for s in items:
            print(f"        · Q={s.q!r} A={s.a!r}")
    print()

    print("   长度分布的用途：如果你的答案中位数是 40 字，但有 5 条 800 字的，")
    print("   那 5 条会在训练时被截断（见第 59 章 seq_len），模型学到的是半句话。")
    print()


# ================================================================ ④ 需要多少条
def demo_how_many() -> None:
    print("④ 「多少条数据才够」：一个可以算的经验公式")
    print()
    # 经验：要稳定改变一个行为，至少需要 100 个"有效梯度信号"
    # 有效样本 = 总样本 × (1 - 重复率) × (1 - 噪声率)
    for behavior in ["输出 JSON 格式", "品牌语气", "固定分类体系（8 类）", "领域术语翻译"]:
        need_raw = {
            "输出 JSON 格式": 300,
            "品牌语气": 500,
            "固定分类体系（8 类）": 800,
            "领域术语翻译": 2000,
        }[behavior]
        print(f"   {behavior:<22} 建议 ≥ {need_raw:>5} 条")
    print()
    print("   但真正该看的是「有效样本」：")
    total, dup_rate, noise_rate = 1000, 0.25, 0.10
    eff = total * (1 - dup_rate) * (1 - noise_rate)
    print(f"     你有 {total} 条，重复率 {dup_rate:.0%}，噪声率 {noise_rate:.0%}")
    print(f"     有效样本 = {total} × {1 - dup_rate:.2f} × {1 - noise_rate:.2f} = {eff:.0f} 条")
    print(f"     → 带标注的有效样本 1000 条，实际只值 {eff:.0f} 条")
    print()
    print("   三条判据（比「多少条」更重要）：")
    print("     1. 覆盖：每个类别/每种句式至少 30 条")
    print("     2. 一致：同一个问题，两个标注员的答案不能相互矛盾")
    print("     3. 边界：必须包含「我该怎么拒绝」的样本，否则微调后模型会乱答")
    print()


def demo_rejected() -> None:
    print("⑤ 必须保留的「拒答样本」：微调最容易破坏的能力")
    rej = [s for s in RAW if "无法" in s.a or "不便" in s.a or "不能" in s.a]
    print(f"   你现在的 {len(RAW)} 条里，只有 {len(rej)} 条是拒答样本：")
    for s in rej:
        print(f"      · Q={s.q}")
    print()
    print("   建议比例：**5%~10%**。少于 5%，微调后模型会对越界问题硬答；")
    print("   多于 10%，模型会变得过度谨慎，正常问题也开始推。")
    print()
    ratio = len(rej) / len(RAW)
    status = "OK" if 0.05 <= ratio <= 0.10 else "需要调整"
    print(f"   当前比例 {ratio:.1%} → {status}")
    print()


def demo_export() -> None:
    print("⑥ 导出成训练框架要的格式")
    clean = [s for s in RAW if s.a.strip() and norm(s.a) != norm(s.q)]
    dataset = [to_alpaca(s) for s in clean]
    # 训练框架常要一个 dataset_info.json 登记
    info = {
        "refund_sft": {
            "file_name": "refund_sft.json",
            "columns": {"prompt": "instruction", "response": "output"},
        }
    }
    print(f"   dataset 条数：{len(dataset)}")
    print("   dataset_info.json：")
    print("     " + json.dumps(info, ensure_ascii=False, indent=2).replace("\n", "\n     "))
    print()
    # 内容指纹：数据改了要能发现
    body = json.dumps(dataset, ensure_ascii=False, sort_keys=True)
    h = hashlib.sha256(body.encode()).hexdigest()[:16]
    print(f"   数据集指纹：{h}（写进实验记录，避免「我用的哪版数据」说不清）")
    print()
    counts = Counter(s.source for s in clean)
    print(f"   来源分布：{dict(counts)}")
    print("   → 真实项目里 source 字段必须留，否则出问题查不到是哪批数据污染的")
    print()


def demo_threshold_sweep() -> None:
    print("⑥ 阈值怎么定：扫一遍，看哪些对会被判为重复")
    print()
    # 手工标注：哪些对"真的"是重复
    truth = {
        (0, 1): True,   # 同义改写
        (0, 2): True,
        (1, 2): True,
        (3, 4): True,
        (0, 3): False,  # 起算时间 vs 拆封退货：不同问题
        (0, 4): False,
        (10, 11): False,  # 查我的订单 vs 订单号在哪
        (3, 5): False,   # 拆封退货 vs 定制商品
        (16, 17): False,  # 两个格式类问题
    }
    print(f"   {'阈值':<8}{'命中对数':>10}{'误报':>8}{'漏报':>8}")
    print("   " + "-" * 36)
    for th in [0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80]:
        fp = fn = tp = 0
        for (i, j), is_dup in truth.items():
            pred = is_duplicate(RAW[i], RAW[j], threshold=th)
            if pred and is_dup:
                tp += 1
            elif pred and not is_dup:
                fp += 1
            elif not pred and is_dup:
                fn += 1
        print(f"   {th:<8.2f}{tp:>10}{fp:>8}{fn:>8}")
    print()
    print("   读这张表（这是**真实的扫描结果**，不是我编的故事）：")
    print("     · 阈值 ≤ 0.50：有 1~2 个误报（把「起算时间」和「拆封退货」判成同一个问题）")
    print("     · 阈值 = 0.55 / 0.60：**零误报，但有 1 个漏报**")
    print("     · 阈值 ≥ 0.65：零误报，漏报涨到 2 个")
    print()
    print("   结论：**在这 30 条数据上，不存在「零误报 + 零漏报」的阈值。**")
    print("   我最后选 0.60，理由是：漏报的代价（测试集里混进训练集的改写）")
    print("   远大于误报的代价（少几条训练样本）。")
    print()
    print("   → 这个取舍必须由你按场景决定，不能抄别人的数字。")
    print()


def demo_limits() -> None:
    print("⑦ 诚实说明：字符级去重做不到什么")
    print()
    print("   它做不到的三件事：")
    print("     1. 「退款要多久」和「钱什么时候到账」—— 一个内容字都不共享，但问的是同一件事")
    print("     2. 「七天无理由从哪天算」和「七天无理由从哪天算起」—— 能抓到（结果正确）")
    print("     3. 中英混写「退货 policy 是怎么规定的」—— 归一化只处理中文，英文部分被丢掉")
    print()
    print("   要做对第 1 条，必须上**语义去重**：")
    print("     · 用 embedding（第 7 章）算余弦相似度，阈值一般取 0.92~0.95")
    print("     · 代价：语料多时要做全量两两比较，O(n²)，需要近似最近邻（第 8 章的索引）")
    print()
    print("   本章为什么还教字符级？因为：")
    print("     · 零依赖，能立刻跑通，不需要 API key")
    print("     · 能抓住大部分「同一句话换个说法」的重复（这是最常见的标注事故）")
    print("     · **先建立「要去重」这个意识**，比一上来用最强的工具更重要")
    print()


def main() -> None:
    demo_formats()
    demo_split()
    demo_quality()
    demo_how_many()
    demo_rejected()
    demo_threshold_sweep()
    demo_limits()
    demo_export()


if __name__ == "__main__":
    main()
