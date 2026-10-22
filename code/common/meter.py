"""第 57 章产出：调用计量器。

它回答三个问题：
  1. 这次调用花了多少 token（分别是多少）
  2. 花了多少钱（按模型单价换算）
  3. 等了多久（首字延迟 TTFT 与总延迟分开）

后面章节几乎所有工程决策都建立在这些数字上：
  第 34 章的成本报表、第 35 章的延迟瀑布、第 44 章的评测报表。
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator


# ---- 单价表：单位是「元 / 百万 token」 -------------------------------------
# 只用于教学演示，请按你实际使用的模型价格修改。
# 关键不是数字准，而是"有成本归因"这个动作。
PRICING: dict[str, tuple[float, float]] = {
    # model_name_prefix: (input_price_per_1m, output_price_per_1m)
    "deepseek-chat": (2.0, 8.0),
    "deepseek-reasoner": (4.0, 16.0),
    "qwen-plus": (0.8, 2.0),
    "qwen-max": (2.4, 9.6),
    "gpt-4o-mini": (1.1, 4.4),
    "ollama": (0.0, 0.0),  # 本地模型不花钱，但电费和显存占用是真的
}


def price_of(model: str) -> tuple[float, float]:
    for prefix, price in PRICING.items():
        if model.startswith(prefix):
            return price
    return (0.0, 0.0)


@dataclass
class CallRecord:
    """一次模型调用的完整账本。"""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0  # 命中上下文缓存的 token，通常便宜很多
    ttft_ms: float = 0.0
    total_ms: float = 0.0
    retries: int = 0
    error: str | None = None
    step: str = ""

    @property
    def cost(self) -> float:
        pin, pout = price_of(self.model)
        return (self.input_tokens - self.cached_tokens) / 1e6 * pin + self.output_tokens / 1e6 * pout

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["cost"] = round(self.cost, 6)
        return d


@dataclass
class Meter:
    """进程级计量器。

    设计上有意做成"可导出"的：
    - summary() 给命令行看
    - dump() 给报表/评测脚本读
    - reset() 让每章示例互不污染
    """

    records: list[CallRecord] = field(default_factory=list)

    @contextmanager
    def track(self, model: str, step: str = "") -> Iterator[CallRecord]:
        """包住一次模型调用。

        用法：
            with meter.track("deepseek-chat", step="plan") as rec:
                resp = llm.invoke(...)
                rec.input_tokens = resp.usage_metadata["input_tokens"]
        """
        rec = CallRecord(model=model, step=step)
        t0 = time.perf_counter()
        try:
            yield rec
        except Exception as e:  # noqa: BLE001 —— 计量器必须能吃下一切异常
            rec.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            rec.total_ms = (time.perf_counter() - t0) * 1000
            self.records.append(rec)

    def add(self, rec: CallRecord) -> None:
        self.records.append(rec)

    def summary(self) -> dict[str, Any]:
        ok = [r for r in self.records if r.error is None]
        failed = [r for r in self.records if r.error is not None]
        return {
            "calls": len(self.records),
            "failed_calls": len(failed),
            "input_tokens": sum(r.input_tokens for r in self.records),
            "output_tokens": sum(r.output_tokens for r in self.records),
            "cost": round(sum(r.cost for r in self.records), 6),
            "retries": sum(r.retries for r in self.records),
            # P95 延迟：只看成功的调用，失败调用的延迟没有参考意义
            "p95_latency_ms": round(_p95([r.total_ms for r in ok]), 1),
            "avg_ttft_ms": round(sum(r.ttft_ms for r in ok) / len(ok), 1) if ok else 0.0,
        }

    def by_step(self) -> dict[str, dict[str, float]]:
        """按 `step` 分组：{环节: {calls, cost, input_tokens, output_tokens}}。

        第 57 章的练习 1 要求"知道哪一步占总成本 60% 以上"，
        第 35 章的归因报表也建立在同一份数据上——所以放在这里，全书的示例共用。
        """
        out: dict[str, dict[str, float]] = {}
        for r in self.records:
            s = out.setdefault(r.step or "-", {"calls": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0})
            s["calls"] += 1
            s["cost"] = round(s["cost"] + r.cost, 6)
            s["input_tokens"] += r.input_tokens
            s["output_tokens"] += r.output_tokens
        return out

    def dump(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps([r.as_dict() for r in self.records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def reset(self) -> None:
        self.records.clear()


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return s[idx]


def usage_of(resp: Any) -> dict[str, int]:
    """从 LangChain 的 AIMessage 里稳妥地抠出 usage。

    不同厂商字段名不一致，这里做统一：
    优先 usage_metadata（LangChain 标准化过的），退回 response_metadata.token_usage。
    """
    um = getattr(resp, "usage_metadata", None) or {}
    if um:
        return {
            "input_tokens": um.get("input_tokens", 0) or 0,
            "output_tokens": um.get("output_tokens", 0) or 0,
            "cached_tokens": (um.get("input_token_details") or {}).get("cache_read", 0) or 0,
        }
    tu = (getattr(resp, "response_metadata", None) or {}).get("token_usage") or {}
    return {
        "input_tokens": tu.get("prompt_tokens", 0) or 0,
        "output_tokens": tu.get("completion_tokens", 0) or 0,
        "cached_tokens": tu.get("prompt_cache_hit_tokens", 0) or 0,
    }
