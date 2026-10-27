"""上下文窗口被输入挤满时，`finish_reason` 在哪一步变成 `length`。

服务端是脚本化的（`fake_server`）：它按 OpenAI 兼容格式回放，但"能生成多少"不是
常数——它用真实词表算出本次 prompt 的 token 数，再拿窗口减去它，剩下的才是输出
空间。所以输入越长，输出越短，到某一段开始被截断，再长下去输出变成空字符串。

两种服务端行为都存在：严格的一类按 `prompt + max_tokens > 窗口` 直接拒绝（调用方
本地预检能对上）；宽松的一类按剩余空间静默截断（就变成 `finish_reason=length`）。
这里让脚本化后端走第二种，把"输出被吃掉"这一步显示出来；第一种在最后一节用预检
函数单独演示。
"""

from __future__ import annotations

import tiktoken

from fake_server import chat_completion, client_for, scripted_server

ENC = tiktoken.get_encoding("cl100k_base")

WINDOW = 1024          # 输入与输出共用的上限
RESERVE = 64           # 调用方给模板开销留的余量
MAX_TOKENS_FIXED = 512 # 对照用的写死值

SYSTEM = "你是退货政策助手，只回答政策条文范围内的问题。"

QUESTION = "按下面这些条款，订单 A1001（签收 3 天、未拆封）能不能退？给结论和依据。"

DOCS = [
    "条款 1：自签收次日起 7 个自然日内，买家可以无理由申请退货；申请需在订单页提交，"
    "并填写退货原因。该 7 日为自然日，不以工作日计算，遇节假日不顺延；签收时间以物流"
    "签收记录为准，代收视为签收。超期申请需经客服人工审核，审核结论不代表本条款改变。",

    "条款 2：申请退货的商品应当保持未拆封状态，商品本体、包装、配件、赠品、说明书"
    "需一并寄回；缺少任一项时，仓库有权拒收，退回运费由买家承担。商品外包装的封条"
    "破损、序列号被涂改、保修卡缺失，均视为已拆封，按已拆封处理。",

    "条款 3：定制类商品、生鲜易腐类商品、已激活的电子设备、已拆封的个护用品不支持"
    "无理由退货；确有质量问题的，按售后维修或换货流程处理。定制类商品指按买家提供的"
    "尺寸、材质、图案生产的商品，包括刻字、印花、改尺寸三类；生鲜类以商品页标注为准。",

    "条款 4：退货运费由买家承担；因商品质量问题、发错货、漏发导致的退货，运费由"
    "商家承担，买家可凭快递单据在退货完成后申请报销。报销金额以实际支付的快递费为"
    "上限，不含保价费与包装费；到付件一律拒收，因此产生的二次运费由买家承担。",

    "条款 5：退款在仓库签收并质检通过后 3 个工作日内原路退回；原支付渠道已失效的，"
    "退款转为账户余额，可用于后续下单，不支持提现。使用优惠券、积分、礼品卡支付的"
    "订单，对应部分按原形式退回，有效期不顺延；组合支付按各渠道实付金额分别退回。",

    "条款 6：超过 7 日但在 15 日内的，可以申请换货而非退货；换货商品需保留原包装与"
    "全部配件，且同一订单仅支持一次换货。换货产生的往返运费由买家承担，质量问题除外；"
    "换货商品无库存时，转为退货处理，退款按条款 5 执行。",

    "条款 7：同一买家账号 30 日内申请退货超过 5 次的，需人工审核；审核期间退货申请"
    "挂起，不计入 7 日时限。恶意退货、空包退货、以旧换新的，平台有权拒绝后续申请并"
    "保留追责权利；判定依据为仓库质检记录与开箱视频。",

    "条款 8：本政策自发布之日起生效，由平台售后部门负责解释；与商品页单独说明冲突时，"
    "以商品页说明为准。政策修订不影响修订前已提交的退货申请，修订后的申请按新版本执行。",
]

# 服务端"生成"的固定答案：一段结论加五条依据。它的长度决定从哪一步开始放不下。
ANSWER = (
    "结论：可以退货。订单 A1001 签收 3 天，仍在 7 个自然日内；商品未拆封，符合"
    "未拆封要求；不属于定制、生鲜、已激活电子设备等排除类目。\n"
    "依据：\n"
    "1. 条款 1 规定自签收次日起 7 个自然日内可无理由退货，本单签收 3 天，在期限内。\n"
    "2. 条款 2 要求商品保持未拆封并寄回全部配件，本单未拆封，符合要求。\n"
    "3. 条款 3 列出的排除类目为定制、生鲜、已激活电子设备、已拆封个护用品，本单均不属于。\n"
    "4. 条款 4 规定退货运费由买家承担，本单无质量问题，运费需买家自理。\n"
    "5. 条款 5 规定退款在质检通过后 3 个工作日内原路退回，请保留原支付渠道可用。\n"
    "注意：提交申请时需在订单页填写退货原因，并按条款 2 一并寄回包装、配件与赠品。"
)

CHAT_TEMPLATE = "<|im_start|>{role}\n{content}<|im_end|>\n"
REPLY_PRIMER = "<|im_start|>assistant\n"


def server_prompt_tokens(messages: list[dict]) -> int:
    """服务端口径：模板文本加特殊标记，比本地数 content 多一些。"""
    text = "".join(CHAT_TEMPLATE.format(role=m["role"], content=m["content"]) for m in messages)
    return len(ENC.encode(text + REPLY_PRIMER))


def local_tokens(messages: list[dict]) -> int:
    """调用方本地能算的部分：只数 content。"""
    return sum(len(ENC.encode(m["content"])) for m in messages)


def dynamic_max_tokens(messages: list[dict]) -> int:
    """按本地估算给输出上限：窗口减去本地估算的输入，再留一点余量。"""
    return max(0, WINDOW - RESERVE - local_tokens(messages))


def preflight(prompt_tokens: int, max_tokens: int) -> tuple[str, int]:
    """严格服务端的判据：prompt + max_tokens 超过窗口就拒绝。

    返回 (判定, 这次最多能生成多少)。
    """
    if prompt_tokens + max_tokens > WINDOW:
        return "会被拒", max(0, WINDOW - prompt_tokens)
    return "可以发", max_tokens


def trim_to_fit(docs: list[str], budget: int) -> tuple[list[str], list[str]]:
    """按从早到晚的顺序丢文档，直到输入放得下。budget 是留给输入的 token 数。"""
    kept = list(docs)
    dropped: list[str] = []

    while kept and sum(len(ENC.encode(d)) for d in kept) > budget:
        dropped.append(kept.pop(0))

    return kept, dropped


def trim_by_score(docs: list[tuple[str, int, float]], budget: int) -> list[str]:
    """按分数从低到高丢；每项是 (名字, token 数, 分数)。"""
    kept = sorted(docs, key=lambda d: d[2], reverse=True)
    total = sum(t for _, t, _ in kept)
    dropped: list[str] = []

    while kept and total > budget:
        name, t, _ = kept.pop()          # 分数最低的那一段
        total -= t
        dropped.append(name)
    return dropped


def build(n: int) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": QUESTION + "\n\n" + "\n".join(DOCS[:n])},
    ]


def main() -> None:
    want = len(ENC.encode(ANSWER))

    def respond(index: int, body: dict) -> dict:
        prompt = server_prompt_tokens(body["messages"])
        room = max(0, WINDOW - prompt)                  # 窗口减输入，剩下的才是输出空间
        cap = min(body["max_tokens"], room)
        ids = ENC.encode(ANSWER)[:cap]
        reason = "stop" if cap >= want else "length"
        return chat_completion(content=ENC.decode(ids), finish_reason=reason,
                               usage=(prompt, len(ids)))

    print("=" * 100)
    print(f"窗口 {WINDOW}，完整答案需要 {want} token，输出上限按剩余空间动态算（留 {RESERVE} 余量）")
    print("=" * 100)

    with scripted_server(respond) as base_url:
        client = client_for(base_url)

        print(f"{'条款数':>4}{'本地 content':>13}{'动态上限':>9}{'服务端 prompt':>15}"
              f"{'剩余空间':>10}{'实际生成':>9}{'finish_reason':>15}")
        print("-" * 100)

        for n in range(1, len(DOCS) + 1):
            messages = build(n)
            limit = dynamic_max_tokens(messages)
            reply = client.chat.completions.create(
                model="demo-model", messages=messages, max_tokens=limit)
            prompt = reply.usage.prompt_tokens
            print(f"{n:>4}{local_tokens(messages):>13}{limit:>9}{prompt:>15}"
                  f"{WINDOW - prompt:>10}{reply.usage.completion_tokens:>9}"
                  f"{reply.choices[0].finish_reason:>15}")

        print()
        print("=" * 100)
        print("被截断的那一次，丢的是答案的哪一段")
        print("=" * 100)
        messages = build(6)
        limit = dynamic_max_tokens(messages)
        reply = client.chat.completions.create(
            model="demo-model", messages=messages, max_tokens=limit)
        got = reply.choices[0].message.content or ""
        print(f"  完整答案末 50 字：{ANSWER[-50:]!r}")
        print(f"  实际到手末 50 字：{got[-50:]!r}")
        print(f"  完整答案 {want} token，到手 {reply.usage.completion_tokens} token，"
              f"丢了 {want - reply.usage.completion_tokens} token")

        print()
        print("=" * 100)
        print("再长一段：输出空间归零")
        print("=" * 100)
        messages = build(8)
        limit = dynamic_max_tokens(messages)
        reply = client.chat.completions.create(
            model="demo-model", messages=messages, max_tokens=limit)
        print(f"  动态上限 {limit}，服务端 prompt {reply.usage.prompt_tokens}，"
              f"内容 {reply.choices[0].message.content!r}，"
              f"finish_reason {reply.choices[0].finish_reason}")

    print()
    print("=" * 100)
    print("要让完整答案放得下，得丢哪些条款")
    print("=" * 100)
    budget = WINDOW - want - RESERVE
    print(f"  给输入留的预算：{WINDOW} - {want}（答案） - {RESERVE}（余量） = {budget}")
    print(f"  八段条款共 {sum(len(ENC.encode(d)) for d in DOCS)} token")
    kept, dropped = trim_to_fit(DOCS, budget)
    for d in DOCS:
        mark = "保留" if d in kept else "丢弃"
        print(f"    {mark}  {d[:22]}…  {len(ENC.encode(d)):>4} token")
    print(f"  丢弃 {len(dropped)} 段，剩余 {sum(len(ENC.encode(d)) for d in kept)} token")

    # 每段条款与问题相关的程度：7 天期限、未拆封、排除类目最要紧
    scores = [1.0, 2.0, 3.0, 4.0, 3.0, 2.0, 1.0, 1.0]
    ranked = [(d[:14] + "…", len(ENC.encode(d)), s) for d, s in zip(DOCS, scores)]
    by_score = trim_by_score(ranked, budget)
    print(f"  改成按分数丢，丢的是：{by_score}")

    print()
    print("=" * 100)
    print("输出上限的三种算法，对着同一个严格服务端")
    print("=" * 100)
    print(f"  模板开销按 {34} token 计（两条消息），所以本地算出的 prompt 都是偏小的")
    for prompt, local in ((400, 366), (700, 666), (900, 866)):
        print(f"  prompt 实际 {prompt}，本地数出来 {local}")
        plans = (
            ("写死 512", MAX_TOKENS_FIXED),
            ("按本地不留余量", max(0, WINDOW - local)),
            ("按本地留 64 余量", max(0, WINDOW - local - RESERVE)),
        )
        for label, limit in plans:
            verdict, room = preflight(prompt, limit)
            print(f"    {label:<16}max_tokens={limit:>4}  合计 {prompt + limit:>5}"
                  f"  {verdict}（最多生成 {room}）")


if __name__ == "__main__":
    main()
