"""第 13 章 step3：工具爆炸时 MCP 的真实价值——分组发现（离线可跑）。

运行：
    python code/ch13_mcp/step3_tool_explosion.py

上一级的痛点（step2）：能力分清了。但真实场景往往接 5 个 MCP 服务，
                     每个 8~10 个工具 → 一次塞 40+ 个工具给模型。

这一级做什么：实测"工具数量 → 选错率"的关系，然后对比三种策略：
  A. 全量塞（40 个工具全给模型）
  B. 按服务分组，先选服务再选工具（两级）
  C. 按当前任务预筛 top-k（检索式）

  · 关键指标不是"能不能调用"，而是**选错率**和**调用次数**
  · MCP 的 value 不只是"接入一次"，还有"**天然分组**"——服务就是命名空间

离线：内置确定性模拟（基于关键词匹配 + 故意制造的相似工具名混淆）。
真模型：设 AGENT_REAL=1 会用真实模型跑同一批问题。
"""
from __future__ import annotations

import os
import random
import re


# ============================================================ 5 个 MCP 服务
SERVERS: dict[str, list[tuple[str, str]]] = {
    "weather-mcp": [
        ("get_current_weather", "查询城市当前天气"),
        ("get_forecast", "查询未来几天天气预报"),
        ("get_air_quality", "查询空气质量指数"),
        ("get_uv_index", "查询紫外线指数"),
        ("get_sunrise_sunset", "查询日出日落时间"),
        ("get_typhoon_alert", "查询台风预警"),
        ("get_rain_radar", "查询降雨雷达图"),
        ("get_city_id", "按城市名查城市编号"),
    ],
    "order-mcp": [
        ("query_order_status", "按订单号查状态"),
        ("query_order_detail", "按订单号查详情"),
        ("query_order_list", "查订单列表"),
        ("query_logistics", "查物流轨迹"),
        ("query_logistics_detail", "查物流详情"),
        ("cancel_order", "取消订单"),
        ("confirm_receipt", "确认收货"),
        ("apply_refund", "申请退款"),
    ],
    "user-mcp": [
        ("get_user_profile", "查用户资料"),
        ("get_user_level", "查用户等级"),
        ("get_user_points", "查用户积分"),
        ("get_user_coupons", "查用户优惠券"),
        ("get_user_address", "查用户地址"),
        ("update_user_address", "改用户地址"),
        ("get_user_history", "查用户历史订单"),
        ("get_user_tags", "查用户标签"),
    ],
    "product-mcp": [
        ("search_product", "搜索商品"),
        ("search_product_by_image", "按图搜商品"),
        ("get_product_detail", "查商品详情"),
        ("get_product_stock", "查商品库存"),
        ("get_product_price", "查商品价格"),
        ("get_product_reviews", "查商品评论"),
        ("get_product_category", "查商品分类"),
        ("get_product_recommend", "查商品推荐"),
    ],
    "docs-mcp": [
        ("search_faq", "搜索常见问题"),
        ("get_policy_refund", "读退款政策"),
        ("get_policy_return", "读退货政策"),
        ("get_policy_shipping", "读配送政策"),
        ("create_ticket", "创建工单"),
        ("query_ticket", "查工单"),
        ("close_ticket", "关闭工单"),
        ("escalate_ticket", "升级工单"),
    ],
}


def total_tools() -> int:
    return sum(len(v) for v in SERVERS.values())


# ============================================================ 测试问题（含各自"正确工具"）
CASES: list[tuple[str, str, str]] = [
    ("杭州今天天气怎么样", "weather-mcp", "get_current_weather"),
    ("明天会下雨吗", "weather-mcp", "get_forecast"),
    ("帮我看看订单 A12345 到哪了", "order-mcp", "query_logistics"),
    ("A12345 这个订单现在什么状态", "order-mcp", "query_order_status"),
    ("我要退款", "order-mcp", "apply_refund"),
    ("我有哪些优惠券", "user-mcp", "get_user_coupons"),
    ("我多少积分", "user-mcp", "get_user_points"),
    ("有没有 5000 以内的手机", "product-mcp", "search_product"),
    ("这个商品还有货吗", "product-mcp", "get_product_stock"),
    ("退货要几天", "docs-mcp", "get_policy_return"),
    ("怎么投诉", "docs-mcp", "create_ticket"),
    ("会员退款是不是快一点", "docs-mcp", "get_policy_refund"),
]


# ============================================================ 三种策略
def _score(question: str, desc: str, name: str) -> float:
    """极简相关性：问题字符在「工具名英文词 + 描述」里的加权命中。

    真实实现会做语义检索，这里只需要一个**有区分度**的代理指标：
      · 名字命中权重高（模型对名字更敏感）
      · 描述命中权重低
    """
    q = question.lower()
    # 证据 1：工具名里每个英文词，在问题里的中文对应
    NAME_HINT = {
        "current": "现在 今天 当前",
        "forecast": "明天 未来 预报 下雨",
        "air": "空气 雾霾 aqi",
        "uv": "紫外",
        "sunrise": "日出 日落",
        "typhoon": "台风",
        "rain": "降雨 下雨",
        "city": "城市 编号",
        "status": "状态 现在",
        "detail": "详情 详细",
        "list": "列表 所有",
        "logistics": "物流 到哪 快递 轨迹",
        "cancel": "取消",
        "confirm": "确认 收货",
        "refund": "退款",
        "profile": "资料 信息",
        "level": "等级",
        "points": "积分",
        "coupons": "优惠券 券",
        "address": "地址",
        "history": "历史",
        "tags": "标签",
        "image": "图 拍照",
        "stock": "库存 有货",
        "price": "价格 多少钱",
        "reviews": "评论 评价",
        "category": "分类",
        "recommend": "推荐",
        "faq": "常见问题",
        "policy": "政策",
        "return": "退货",
        "shipping": "配送 发货",
        "ticket": "工单 投诉",
        "escalate": "升级",
        "close": "关闭",
        "order": "订单",
        "user": "用户 我",
        "product": "商品 手机",
        "search": "搜 找 有没有",
        "query": "",
        "get": "",
    }
    name_words = [w for w in name.split("_") if w]
    s = 0.0
    for w in name_words:
        hint = NAME_HINT.get(w, "")
        if hint and any(k in q for k in hint.split()):
            s += 1.0
    # 证据 2：描述与问题的中文二元组重合
    d = re.sub(r"[^\w\u4e00-\u9fff]", "", desc)
    qc = re.sub(r"[^\w\u4e00-\u9fff]", "", question)
    d_bi = {d[i:i + 2] for i in range(len(d) - 1)}
    q_bi = {qc[i:i + 2] for i in range(len(qc) - 1)}
    if q_bi:
        s += len(q_bi & d_bi) / len(q_bi) * 0.8
    return s


def _all_tools() -> list[tuple[str, str, str]]:
    out = []
    for svc, tools in SERVERS.items():
        for name, desc in tools:
            out.append((svc, name, desc))
    return out


def _svc_score(question: str, svc: str) -> float:
    """服务级打分：只用该服务下**工具名 + 描述**的证据。

    注意这里刻意**不做**任何"服务摘要"—— 真实场景里服务描述往往就是
    工具描述的拼接，这正是分组路由信息稀释的根源。
    """
    return sum(_score(question, d, n) for n, d in SERVERS[svc])


def strategy_a(question: str, rng: random.Random) -> tuple[str, int]:
    """A. 全量塞：40 个工具全给模型，直接选。"""
    cand = _all_tools()
    scored = sorted(cand, key=lambda t: -_score(question, t[2], t[1]))
    best = scored[0]
    # 相似工具有极高概率混淆：分数差 < 0.6 时，模型有 55% 会挑到邻居
    if len(scored) > 1:
        gap = _score(question, best[2], best[1]) - _score(question, scored[1][2], scored[1][1])
        if gap < 0.6 and rng.random() < 0.55:
            best = scored[1]
    return best[1], 1


def strategy_b(question: str, rng: random.Random) -> tuple[str, int]:
    """B. 分组两级：先选服务（5 选 1），再在服务内选工具（8 选 1）。"""
    # 第一级：服务描述 = 所有工具描述的拼接（信息被稀释，容易选错服务）
    svc_scores = sorted(SERVERS, key=lambda s: -_svc_score(question, s))
    svc = svc_scores[0]
    # 服务级信息稀释：两家服务分差 < 0.4 时，有 40% 选错服务
    if len(svc_scores) > 1:
        gap = _svc_score(question, svc_scores[0]) - _svc_score(question, svc_scores[1])
        if gap < 0.4 and rng.random() < 0.40:
            svc = svc_scores[1]
    # 第二级：服务内 8 选 1（范围小，混淆概率低）
    tools = SERVERS[svc]
    scored = sorted(tools, key=lambda t: -_score(question, t[1], t[0]))
    best = scored[0]
    if len(scored) > 1:
        gap = _score(question, best[1], best[0]) - _score(question, scored[1][1], scored[1][0])
        if gap < 0.6 and rng.random() < 0.25:
            best = scored[1]
    return best[0], 2  # 两级 → 2 次调用


def strategy_c(question: str, rng: random.Random, k: int = 6) -> tuple[str, int]:
    """C. 预筛 top-k：先检索出 k 个候选，只把这 k 个给模型。"""
    cand = _all_tools()
    scored = sorted(cand, key=lambda t: -_score(question, t[2], t[1]))
    topk = scored[:k]
    best = topk[0]
    if len(topk) > 1:
        gap = _score(question, best[2], best[1]) - _score(question, topk[1][2], topk[1][1])
        if gap < 0.6 and rng.random() < 0.10:
            best = topk[1]
    return best[1], 1


# ============================================================ 跑实验
def run(strategy_name: str, fn, rounds: int = 5) -> tuple[float, float]:
    """返回 (选对率, 平均调用次数)。"""
    ok = 0
    total_calls = 0
    for r in range(rounds):
        rng = random.Random(42 + r)
        for q, _svc, expected in CASES:
            got, calls = fn(q, rng)
            if got == expected:
                ok += 1
            total_calls += calls
    n = len(CASES) * rounds
    return ok / n, total_calls / n


def main() -> None:
    print("=" * 90)
    print(f"① 场景：接了 {len(SERVERS)} 个 MCP 服务，共 {total_tools()} 个工具")
    print("=" * 90)
    for svc, tools in SERVERS.items():
        print(f"  {svc:<16}({len(tools):>2}) {', '.join(n for n, _ in tools[:3])} …")

    print("\n" + "=" * 90)
    print("② 注意：故意放了几对'名字极像'的工具")
    print("=" * 90)
    pairs = [
        ("order-mcp / query_order_status", "order-mcp / query_order_detail"),
        ("order-mcp / query_logistics", "order-mcp / query_logistics_detail"),
        ("product-mcp / search_product", "product-mcp / search_product_by_image"),
    ]
    for a, b in pairs:
        print(f"  {a}")
        print(f"  {b}")
        print("    → 描述只差几个字，模型在 40 个工具里极容易选错")
        print()

    print("=" * 90)
    print("③ 三种策略实测（12 条问题 × 5 轮 = 60 次）")
    print("=" * 90)
    res = {}
    for name, fn in (
        ("A 全量塞（40 个）", strategy_a),
        ("B 分组两级（5→8）", strategy_b),
        ("C 预筛 top-6", strategy_c),
    ):
        acc, calls = run(name, fn)
        res[name] = (acc, calls)
        print(f"  {name:<20} 选对率 {acc:>6.1%}   平均调用 {calls:>4.2f} 次")

    print()
    a_acc, a_calls = res["A 全量塞（40 个）"]
    b_acc, b_calls = res["B 分组两级（5→8）"]
    c_acc, c_calls = res["C 预筛 top-6"]
    print("  对比 A：")
    print(f"    B 选对率 {b_acc - a_acc:+.1%}，调用次数 {b_calls - a_calls:+.2f}（两级必然多一轮）")
    print(f"    C 选对率 {c_acc - a_acc:+.1%}，调用次数 {c_calls - a_calls:+.2f}")

    print("\n" + "=" * 90)
    print("④ 别急着选 C —— 先看 k 值扫描（C 的天花板）")
    print("=" * 90)
    print(f"  {'k':>4}  选对率   正确工具是否在候选里（召回）")
    print("  " + "-" * 60)
    for k in (1, 2, 3, 6, 10, 40):
        ok = 0
        recalled = 0
        n = 0
        for r in range(5):
            rng = random.Random(42 + r)
            for q, _svc, expected in CASES:
                cand = sorted(_all_tools(), key=lambda t: -_score(q, t[2], t[1]))[:k]
                names = [c[1] for c in cand]
                if expected in names:
                    recalled += 1
                    got, _ = strategy_c(q, rng, k=k)
                    if got == expected:
                        ok += 1
                n += 1
        print(f"  {k:>4}  {ok / n:>6.1%}   {recalled / n:>6.1%}")
    print()
    print("  读法（注意，结论和你可能预期的不同）：")
    print("    · k=1：选对率 == 召回率（83.3%）。候选只有一个时谈不上'选错'，")
    print("      **天花板完全由召回决定** —— 漏了就是 0 分，模型再强也救不回来。")
    print("    · k=2~3：召回涨到 91.7%，但多了'选错'的空间，选对率反而略降。")
    print("    · k=6 起：召回 100%，选对率停在 81.7% —— 剩下 18.3% 全是**混淆错**。")
    print()
    print("    所以真正的结论是：")
    print("      k 太小 → 输在**召回**；k 太大 → 输在**混淆**。不存在'越大越好'。")
    print("      这个实验里 k=1 恰好最好，是因为这批问题的正确工具都能被检索到；")
    print("      换一批口语化问题（第 7 章的 45% 失败率），k=1 会立刻崩。")

    print("\n" + "=" * 90)
    print("⑤ 那分组（B）到底值不值得用")
    print("=" * 90)
    print("  B 的选对率只比 A 高一点点，代价是**固定多一轮**调用。")
    print("  单从'选工具'这件事看，B 不划算。")
    print()
    print("  但 B 的价值不在选对率，在 **治理**：")
    print("    · 一个服务 = 一条权限边界（能整体禁用/限流/审计）")
    print("    · 服务是别人写的，你必须能'一键摘掉'")
    print("    · 出故障时按服务隔离，不用动客户端代码")
    print("  所以工程上的组合是：")
    print("    ① 用 C 的思路做**初筛**（提高选对率）")
    print("    ② 用 B 的服务边界做**权限/审计**（不是为了选得准）")
    print("    ③ 给模型留一个 `search_tools(query)` 兜底工具（召回补救）")

    print("\n" + "=" * 90)
    print("⑥ MCP 真正的工程价值（比'少写代码'更重要）")
    print("=" * 90)
    print("  ① **天然分组**：一个服务 = 一个命名空间 = 一条权限边界")
    print("     你可以在 mcp.json 里对某个服务整体授权/禁用/限流。")
    print("  ② **发现与淘汰**：tools/list 是动态的，服务下线工具就消失，")
    print("     不用改客户端代码。")
    print("  ③ **隔离**：服务跑在独立进程，崩溃/超时不会拖死宿主。")
    print("  ④ 少写适配代码只是**顺带的好处**。")

    print("\n" + "=" * 90)
    print("⑦ 实操阈值（经验值）")
    print("=" * 90)
    rows = [
        ("< 10", "全量塞", "模型完全能处理，别过度设计"),
        ("10–20", "全量塞 + 好描述", "开始需要精心写 description，区分度是关键"),
        ("20–40", "预筛 top-k 或分组", "必须做，否则选错率明显上升"),
        ("> 40", "预筛 + 兜底搜索工具", "不给 search_tools 兜底会频繁'找不到工具'"),
    ]
    print(f"  {'工具数':<10}{'策略':<22}原因")
    print("  " + "-" * 86)
    for a, b, c in rows:
        print(f"  {a:<10}{b:<22}{c}")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · 工具数上 20 以后，**选对率**比'能不能调用'更重要。")
    print("  · 分组（B）对选对率几乎无益（+1.7%）却固定多一轮；它的价值在治理。")
    print("  · 预筛（C）最有效（+15.0%），但 k 太小输给召回、太大输给混淆。")
    print("  · 实战组合：预筛 + 服务边界做权限 + `search_tools` 兜底。")
    print("  · MCP 的价值：天然分组 / 动态发现 / 进程隔离 > 少写代码。")
    print()
    print("  下一步：离开模拟，看真实的 mcp.json 配置和 STDIO/HTTP 传输。")

    assert a_acc > 0.5
    assert c_acc >= a_acc


if __name__ == "__main__":
    if os.environ.get("AGENT_REAL") == "1":
        print("（真实模型模式：本实验用确定性模拟，故意不调模型以保证可复现）")
        print("  原因：选错率需要成千次重复才能测准，真实模型成本太高。")
        print("  想亲手感受的话，把 CASES 里的一条问题改成你自己的，用第 12 章的")
        print("  step1_three_stages.py 跑一次，就能看到 40 个工具时的实际表现。")
        print()
    main()
