"""第 2 章 step4：用真实调用校准估算——把"我猜"变成"我量"（需要 API key）。

运行：
    python code/ch02_token/step4_real_usage.py

上一级的痛点（step3）：所有估算都是纸上推演，你不知道自己的模型到底怎么分词。
                     不同厂商的分词器差别很大——同一段中文，DeepSeek 和 GPT 可能差 40%。

这一级做什么：发 5 次真实请求，把响应里的 usage 和我们的估算逐个对比，
             算出一个**只属于你这个模型**的校准系数，然后用它反推：

  · 1 个汉字到底是多少 token
  · 你的窗口能装多少字
  · 一次调用到底多少钱（走 meter.py 的账本口径）

⚠️ 需要 .env 里配好 OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME。
   总花费约 ¥0.001，可以放心跑。没配模型时会**自动降级**为离线演示。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.meter import Meter, price_of, usage_of  # noqa: E402
from common.settings import get_settings, make_llm  # noqa: E402

PROBES: list[tuple[str, str]] = [
    ("中文短句", "退款要几天？"),
    ("中文长句", "签收后7天内，商品未拆封且不影响二次销售的，可申请无理由退货。"),
    ("英文长句", "Items may be returned within 7 days of delivery if unopened and resalable."),
    ("中英混排", "退款周期 refund period 是 7 天，超过 7 days 需要人工审核（manual review）。"),
    ("代码 / JSON", '{"order_id":"A12345","status":"refund_pending","amount":299.0}'),
]


def local_est(text: str) -> int:
    """本书口径：汉字 0.7、其余 /4。和第 1 章 step2 完全一致。"""
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


def offline_demo(model: str) -> None:
    """没有 API key 时的降级路径：用经验分词率模拟一次真实的 usage 偏差。"""
    print("⚠️ 未检测到可用模型（.env 里的 OPENAI_API_KEY 仍是 missing），走离线演示。")
    print("   下面用「1 汉字 = 0.9 token」这个偏保守的经验值模拟真实的 usage 偏差。\n")
    print(f"{'样本':<12}{'本地估算':>10}{'模拟真实':>10}{'偏差':>9}   真实/估算")
    print("-" * 66)
    sims: list[tuple[str, int, int]] = []
    for name, text in PROBES:
        cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        est = local_est(text)
        # 模拟：汉字按 0.9、非汉字按 1/3.2 计（比本书口径更悲观）
        sim = int(cn * 0.9 + (len(text) - cn) / 3.2) + 1
        sims.append((name, est, sim))
        print(f"{name:<12}{est:>10}{sim:>10}{sim - est:>+9}   {sim / est:>8.2f}x")
    print("-" * 66)
    total_est = sum(e for _, e, _ in sims)
    total_sim = sum(s for _, _, s in sims)
    print(f"{'合计':<12}{total_est:>10}{total_sim:>10}{total_sim - total_est:>+9}   {total_sim / total_est:>8.2f}x")
    print(f"\n→ 校准系数 = {total_sim / total_est:.2f}（真实 / 估算）")
    print("  以后估算你都要乘这个系数，否则预算一定会少留余量。")

    pin, pout = price_of(model)
    if pin:
        cost = total_sim / 1e6 * pin
        print(f"\n这 5 次输入共 {total_sim} token → 按 {model} 单价约 ¥{cost:.8f}")
    print("\n（想跑真实数据：把 .env 里填上可用的 API key 与 base_url，重跑本脚本。）")


def main() -> None:
    s = get_settings()
    model = s.model

    print("=" * 78)
    print(f"用真实调用校准 token 估算（模型：{model}）")
    print("=" * 78)

    if s.api_key in ("", "missing", "ollama"):
        if s.api_key == "ollama":
            print("检测到 ollama：本地模型不计费，但 usage 依然能校准分词。\n")
        else:
            offline_demo(model)
            return

    llm = make_llm(temperature=0.0, max_tokens=8)
    meter = Meter()

    print(f"{'样本':<12}{'真实input':>10}{'本地估算':>10}{'偏差':>9}   真实/估算")
    print("-" * 78)
    pairs: list[tuple[int, int]] = []
    for name, text in PROBES:
        try:
            with meter.track(model, step=name) as rec:
                resp = llm.invoke(text)
                u = usage_of(resp)
                rec.input_tokens = u["input_tokens"]
                rec.output_tokens = u["output_tokens"]
                rec.cached_tokens = u["cached_tokens"]
        except Exception as e:  # noqa: BLE001 —— 教学脚本要能容错并给出可执行提示
            print(f"{name:<12}  调用失败：{type(e).__name__}: {e}")
            print("\n  → 检查 .env：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
            print("  → 或改用 Ollama：ollama serve && ollama pull qwen2.5:7b")
            return
        real = rec.input_tokens
        est = local_est(text)
        pairs.append((est, real))
        print(f"{name:<12}{real:>10}{est:>10}{real - est:>+9}   {real / est:>8.2f}x")

    print("-" * 78)
    total_est = sum(e for e, _ in pairs)
    total_real = sum(r for _, r in pairs)
    ratio = total_real / total_est
    print(f"{'合计':<12}{total_real:>10}{total_est:>10}{total_real - total_est:>+9}   {ratio:>8.2f}x")

    print("\n" + "=" * 78)
    print("校准结果（这三个数字，就是本章要你带走的）")
    print("=" * 78)
    cn_total = sum(sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff") for _, t in PROBES)
    chars_total = sum(len(t) for _, t in PROBES)
    print(f"  ① 1 个汉字 ≈ {total_real / cn_total:.2f} token"
          f"（{cn_total} 个汉字消耗 {total_real} token，含英文/符号的影响）")
    print(f"  ② 1 个字符 ≈ {total_real / chars_total:.2f} token（中英混排口径）")
    print(f"  ③ 校准系数 = {ratio:.2f}  ← 以后用「本地估算 × {ratio:.1f}」做预算\n")

    for label, cap in (("8K", 8_000), ("32K", 32_000), ("128K", 128_000)):
        cn_capacity = int(cap / (total_real / cn_total))
        print(f"  窗口 {label:<5} 最多能装约 {cn_capacity:>7,} 个纯汉字")

    print("\n" + "=" * 78)
    print("钱的账（走 common/meter.py，和第 39 章同一口径）")
    print("=" * 78)
    summary = meter.summary()
    pin, pout = price_of(model)
    print(f"  调用 {summary['calls']} 次")
    print(f"  输入 {summary['input_tokens']} token × {pin} 元/百万 = ¥{summary['input_tokens'] / 1e6 * pin:.8f}")
    print(f"  输出 {summary['output_tokens']} token × {pout} 元/百万 = ¥{summary['output_tokens'] / 1e6 * pout:.8f}")
    print(f"  合计 ¥{summary['cost']:.8f}")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  · **每个模型的分词率都不一样**。本脚本跑出来的系数只对你这个模型有效。")
    print("  · 换模型时，重新跑一遍这个脚本，把系数写进你的配置——")
    print("    这是第 25 章上下文预算能算准的前提。")
    print("  · 真实 usage 和估算的差距通常落在 ±25% 以内。"
          "如果你的估算偏了 2 倍，说明口径用错了（比如把字符当 token）。")

    assert total_real > 0


if __name__ == "__main__":
    main()
