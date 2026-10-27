"""一次多轮任务的成本拆解：钱花在哪一环。

token 数由真实词表算出来（messages 渲染成 chat 模板后数一遍），不是编的常数；
**单价是示例值，不是任何厂商的实时报价**，只用来说明定价结构：输入与输出不同价、
缓存读比输入便宜、缓存写比输入贵。

换厂商时这一节的算法不变，把 PRICES 换成对方的价格表即可。
"""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")

CHAT_TEMPLATE = "<|im_start|>{role}\n{content}<|im_end|>\n"
REPLY_PRIMER = "<|im_start|>assistant\n"

# 示例价格（元 / 千 token）。相对关系按主流厂商的常见结构设定，数值本身不是实测。
PRICES = {
    "input": 0.0020,        # 普通输入
    "cached_read": 0.0002,  # 命中缓存前缀的输入，约为普通输入的 1/10
    "cached_write": 0.0025, # 写入缓存前缀，约为普通输入的 1.25 倍
    "output": 0.0080,       # 输出，约为普通输入的 4 倍
}

SYSTEM = (
    "你是退货客服，只处理退货相关问题。判断依据只有下面这份政策，"
    "信息不足时结论填 null 并说明缺什么。\n"
    "政策：签收后 7 天内可申请退货；商品需未拆封；定制商品、生鲜、已激活电子设备不支持退货。"
)

TOOL_RESULT = '{"status": "已签收", "signed_days_ago": 3, "opened": false, "custom": false}'


@dataclass
class Round:
    prompt: int
    cached: int
    completion: int


def render(message: dict) -> str:
    """单条消息在服务端口径下的文本。"""
    return CHAT_TEMPLATE.format(role=message["role"], content=message["content"])


def prompt_tokens(messages: list[dict]) -> int:
    return len(ENC.encode("".join(render(m) for m in messages) + REPLY_PRIMER))


def cached_prefix(prev: list[dict], cur: list[dict]) -> int:
    """两轮之间从头开始完全相同的部分。

    缓存只命中这一段：一旦某条消息变了，它后面的全部失效。
    """
    total = 0
    for before, after in zip(prev, cur):
        if before != after:
            break
        total += len(ENC.encode(render(before)))
    return total


def cost(prompt: int, cached: int, completion: int, write: bool = False) -> dict[str, float]:
    """分四段计：普通输入、缓存读、缓存写、输出。

    `write` 表示这一轮的前缀要新写进缓存：第 1 轮，或者前缀刚被改过的那一轮。
    增量部分的写入没算进来——它和"前缀是否稳定"无关，不影响这一节的结论。
    """
    plain = prompt - cached
    return {
        "input": plain / 1000 * PRICES["input"],
        "cached_read": cached / 1000 * PRICES["cached_read"],
        "cached_write": (prompt if write else 0) / 1000 * PRICES["cached_write"],
        "output": completion / 1000 * PRICES["output"],
    }


def build_rounds(system_breaks: bool = False) -> list[Round]:
    """构造四轮对话的 messages，并记录每轮的口径。"""
    turns: list[list[dict]] = []
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "订单 A1001 三天前签收，未拆封，能退吗？"},
    ]
    turns.append(messages)

    messages = messages + [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "get_order", "arguments": '{"order_id": "A1001"}'}}]},
        {"role": "tool", "content": TOOL_RESULT},
    ]
    turns.append(messages)

    messages = messages + [
        {"role": "assistant", "content": "可以退：签收 3 天，未拆封，属普通商品。"},
        {"role": "user", "content": "那定制商品呢？已经签收了还能退吗"},
    ]
    if system_breaks:
        # 第 3 轮改一句系统提示：前缀从这里断掉，后面的缓存全部失效
        messages = [{"role": "system", "content": SYSTEM + "\n语气要简洁。"}] + messages[1:]
    turns.append(messages)

    messages = messages + [
        {"role": "assistant", "content": "定制商品不支持退货，签收后也不支持。"},
        {"role": "user", "content": "好的，那退款多久到账"},
    ]
    turns.append(messages)

    rounds: list[Round] = []
    for i, cur in enumerate(turns):
        prev = turns[i - 1] if i else None
        cached = cached_prefix(prev, cur) if prev else 0
        rounds.append(Round(prompt=prompt_tokens(cur), cached=cached,
                            completion=40 + i * 6))
    return rounds


def total_of(rounds: list[Round], use_cache: bool) -> float:
    """一轮一轮累加。不用缓存时，既不命中也不写入。"""
    total = 0.0
    for r in rounds:
        cached = r.cached if use_cache else 0
        total += sum(cost(r.prompt, cached, r.completion,
                          write=use_cache and cached == 0).values())
    return total


def main() -> None:
    rounds = build_rounds()
    broken = build_rounds(system_breaks=True)

    print("=" * 84)
    print("一、示例价格（元 / 千 token）：不是任何厂商的实时报价")
    print("=" * 84)
    base = PRICES["input"]
    for name, price in PRICES.items():
        print(f"  {name:<14}{price:>10.4f}   是普通输入的 {price / base:.2f} 倍")

    print()
    print("=" * 84)
    print("二、四轮任务的成本拆解（token 数由 tiktoken 现算）")
    print("=" * 84)
    print(f"{'轮':>3}{'prompt':>8}{'命中缓存':>9}{'输出':>6}"
          f"{'输入':>9}{'缓存读':>9}{'缓存写':>9}{'输出':>9}{'合计':>10}")
    print("-" * 84)
    grand = 0.0
    for i, r in enumerate(rounds, 1):
        c = cost(r.prompt, r.cached, r.completion, write=(r.cached == 0))
        s = sum(c.values())
        grand += s
        print(f"{i:>3}{r.prompt:>8}{r.cached:>9}{r.completion:>6}"
              f"{c['input']:>9.5f}{c['cached_read']:>9.5f}{c['cached_write']:>9.5f}"
              f"{c['output']:>9.5f}{s:>10.5f}")
    print("-" * 84)
    print(f"{'合计':>3}{sum(r.prompt for r in rounds):>8}{sum(r.cached for r in rounds):>9}"
          f"{sum(r.completion for r in rounds):>6}{'':>9}{'':>9}{'':>9}{'':>9}{grand:>10.5f}")

    in_tok = sum(r.prompt for r in rounds)
    out_tok = sum(r.completion for r in rounds)
    print()
    print(f"  输入 token {in_tok}，输出 token {out_tok}，输出只占 "
          f"{out_tok / (in_tok + out_tok):.1%}")

    parts = {"input": 0.0, "cached_read": 0.0, "cached_write": 0.0, "output": 0.0}
    for r in rounds:
        for k, v in cost(r.prompt, r.cached, r.completion, write=(r.cached == 0)).items():
            parts[k] += v
    print()
    print("  按项目拆：")
    for k, v in parts.items():
        print(f"    {k:<14}{v:>9.5f}  {v / grand:>6.1%}")
    print(f"  输出占成本的 {parts['output'] / grand:.1%}，"
          f"占 token 总量的 {out_tok / (in_tok + out_tok):.1%}")

    print()
    print("=" * 84)
    print("三、缓存值不值得用：单轮与多轮的对比")
    print("=" * 84)
    with_cache = total_of(rounds, use_cache=True)
    no_cache = total_of(rounds, use_cache=False)
    print(f"  四轮，用缓存：  {with_cache:.5f}")
    print(f"  四轮，不用缓存：{no_cache:.5f}   （用缓存省了 {(1 - with_cache / no_cache):.1%}）")

    only_first = [rounds[0]]
    print(f"  只跑一轮，用缓存：  {total_of(only_first, use_cache=True):.5f}"
          f"  比不用缓存（{total_of(only_first, use_cache=False):.5f}）贵 "
          f"{(total_of(only_first, use_cache=True) / total_of(only_first, use_cache=False) - 1):.1%}")
    print("  写入比普通输入贵，只有后续能复用时才回本。")

    print()
    print("=" * 84)
    print("四、前缀被改一句之后")
    print("=" * 84)
    print(f"{'轮':>3}{'prompt':>8}{'命中缓存':>9}   说明")
    print("-" * 84)
    for i, r in enumerate(broken, 1):
        note = "前缀未变" if r.cached else "前缀刚改过，本轮全部按普通输入计费"
        if i == 1:
            note = "第 1 轮没有前缀可命中，整段写入缓存"
        if i == 4:
            note = "新前缀已建立，重新命中"
        print(f"{i:>3}{r.prompt:>8}{r.cached:>9}   {note}")
    print()
    print(f"  改一句系统提示后：{total_of(broken, use_cache=True):.5f}"
          f"  （原来 {with_cache:.5f}，多了 "
          f"{(total_of(broken, use_cache=True) / with_cache - 1):.1%}）")

    print()
    print("=" * 84)
    print("五、同一个 usage，三张价格表")
    print("=" * 84)
    want = {"input": in_tok, "output": out_tok}
    tables = {
        "便宜档": {"input": 0.0004, "output": 0.0016},
        "中档": {"input": 0.0020, "output": 0.0080},
        "贵档": {"input": 0.0100, "output": 0.0300},
    }
    for name, p in tables.items():
        x = want["input"] / 1000 * p["input"] + want["output"] / 1000 * p["output"]
        print(f"  {name:<6} 输入 {p['input']}/千  输出 {p['output']}/千"
              f"  这次任务成本 {x:>9.5f}")
    print("  同一个 usage，换一张价格表差 "
          f"{tables['贵档']['input'] / tables['便宜档']['input']:.0f} 倍。usage 不是成本。")


if __name__ == "__main__":
    main()
