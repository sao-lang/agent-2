# 第 3 章 token 计量、成本与上下文窗口

> **知识点**：A4 token 计量口径，A5 成本结构，A6 窗口溢出
> **交付**：可运行脚本
> **组件**：无（本章为后续组件提供计量基础）
> **读完应当能回答**：一次调用的成本由什么决定，窗口装不下时应该丢什么。

## 3.1 token 计量

token 是模型处理文本的最小单位。它不是字符，也不是字。同一个词在不同词表下可能切成不同数量的 token。

计量的用途有三个：估算容量、计算成本、判断窗口是否够用。三个用途对精度的要求不同。

### 估算与真实值的偏差

运行 `code/ch03_tokens/step1_estimate.py`。脚本使用 `tiktoken` 的真实分词结果作为基准，对比两种估算口径。

| 文本类型 | 真实 token | 字符数 | 偏差 | 汉字1/英文4 | 偏差 |
|---|---|---|---|---|---|
| 中文 | 26 | 25 | -4% | 23 | -12% |
| 长中文 | 67 | 61 | -9% | 57 | -15% |
| 英文 | 10 | 53 | +430% | 13 | +30% |
| 代码 | 18 | 69 | +283% | 17 | -6% |
| 混合 | 15 | 43 | +187% | 17 | +13% |

偏差 = 估算 / 真实 − 1。

三项观察：

- **字符数口径不可用。** 对英文和代码高估数倍。
- **经验公式的偏差方向随文本类型变化。** 中文低估，英文高估，代码接近。
- **不存在对所有文本都准的固定公式。** 偏差的来源是分词粒度，而粒度取决于词表。

### 同一文本在不同词表下的计数

| 词表 | 长中文样本的 token 数 |
|---|---|
| `cl100k_base` | 67 |
| `o200k_base` | 49 |

差异来自词表大小与切分方式。因此在跨厂商对比成本时，除单价外还需确认计数口径。

**结论**：估算只用于事前粗判。计费与预算必须使用服务端返回的 `usage`。

### 一个可直接使用的 token 计量器

下面的代码提供三个能力：按真实词表计数、按测算准、按窗口判断能否装下。

```python
"""token 计量器：本地估算 + 服务端校准 + 窗口记账。"""

from __future__ import annotations

from dataclasses import dataclass


class TokenMeter:
    """优先使用服务端返回的 usage，缺失时才回落到本地估算。"""

    def __init__(self, encoding: str = "cl100k_base") -> None:
        import tiktoken

        self.enc = tiktoken.get_encoding(encoding)
        self._calibration: float | None = None

    def count(self, text: str) -> int:
        """本地计数。词表与服务端一致时，误差主要来自消息结构开销。"""
        return len(self.enc.encode(text))

    def count_messages(self, messages: list[dict], overhead: int = 4) -> int:
        """按消息计数，加上每条消息的结构开销。"""
        return sum(self.count(m["content"]) + overhead for m in messages) + 2

    def calibrate(self, local: int, actual: int) -> None:
        """用一次真实调用的 usage 校准本地估算。"""
        if local > 0:
            self._calibration = actual / local

    def estimate(self, text: str) -> int:
        """用于预算的估算值。已校准时优先使用校准系数。"""
        raw = self.count(text)
        if self._calibration is None:
            return raw
        return round(raw * self._calibration)


@dataclass
class WindowBudget:
    window: int              # 模型窗口上限
    reserve_output: int      # 为输出预留
    system_tokens: int       # 系统消息
    tool_tokens: int = 0     # 工具定义

    @property
    def available(self) -> int:
        """可用于对话历史的 token 数。"""
        return self.window - self.reserve_output - self.system_tokens - self.tool_tokens

    def fits(self, history_tokens: int) -> bool:
        return history_tokens <= self.available

    def overflow(self, history_tokens: int) -> int:
        """超出量。未超出返回 0。"""
        return max(0, history_tokens - self.available)
```

使用方式：

```python
meter = TokenMeter()
budget = WindowBudget(window=128_000, reserve_output=4_000,
                      system_tokens=meter.count_messages([system_msg]),
                      tool_tokens=meter.count(json.dumps(tools)))

history = meter.count_messages(messages)
if not budget.fits(history):
    messages = trim(messages, budget.overflow(history))

resp = call_model(...)
meter.calibrate(local=history, actual=resp["usage"]["prompt_tokens"])
```

三个设计要点：

- **`calibrate` 用真实值修正估算。** 一次调用之后，后续估算会向服务端口径靠拢。
- **`WindowBudget.available` 先扣输出预留。** 这是第 1 章 `finish_reason=length` 的前置防线。
- **`fits` 与 `overflow` 分开。** 调用方可以先判断、再决定裁剪多少，不需要自己算两次。

## 3.2 成本结构

一次调用的成本由输入、输出两部分构成，两者单价不同。部分厂商对重复前缀提供缓存折扣。

运行 `code/ch03_tokens/step2_cost.py`。脚本使用的单价是构造值，用于展示计算结构。

### 输入与输出的占比

| 场景 | 输入 | 输出 | 输出成本占比 |
|---|---|---|---|
| 短输入长输出 | 500 | 1500 | 92% |
| 长输入短输出 | 8000 | 300 | 13% |
| 等长 | 2000 | 2000 | 80% |

输出占比高时，控制输出长度比压缩输入更有效；输入占比高时相反。

### 多轮对话的输入增长

对话历史每轮完整重发，输入量随轮次累加。

| 轮次 | 累计输入 | 本轮成本 | 累计成本 |
|---|---|---|---|
| 1 | 400 | 0.002400 | 0.002400 |
| 3 | 1200 | 0.004000 | 0.009600 |
| 6 | 2400 | 0.006400 | 0.026400 |

第 6 轮的输入是第 1 轮的 6 倍。累计成本增长快于轮次增长。

### 缓存命中

| 轮次 | 无缓存 | 有缓存 | 差额 |
|---|---|---|---|
| 2 | 0.003200 | 0.002600 | 0.000600 |
| 4 | 0.004800 | 0.003000 | 0.001800 |
| 6 | 0.006400 | 0.003400 | 0.003000 |

缓存命中的条件是前缀完全一致。任何一处改动都会使该位置之后的内容全部失效。

## 3.3 上下文窗口

窗口是一次请求能容纳的 token 上限，输入与输出共用。

### 记账方法

```
可用输入 = 窗口上限 − 输出预留 − 系统消息 − 工具定义
```

输出预留必须预先扣除。若不扣除，请求在生成阶段超出上限，表现为 `finish_reason` 为 `length`，或请求被服务端拒绝。

运行 `code/ch03_tokens/step3_window.py` 的第一段，脚本演示了包含与不包含输出预留的两种记账方式。

### 溢出时的裁剪

| 策略 | 丢失内容 | 保留部分 |
|---|---|---|
| 丢弃最早 | 开头的对话，通常包含任务前提与约束 | 最近的上下文完整 |
| 保留首尾丢中间 | 中段对话，可能是关键约束所在 | 开头结尾都在 |
| 逐条截断 | 每条末尾几个字 | 条数不变，内容不完整 |

脚本第二段在预算 150 token 下执行三种策略：丢弃最早后首条为第 6 轮；保留首尾后首条仍为第 1 轮；逐条截断保留了全部 16 条，但内容被截成残句。

三种策略丢失的内容不同，没有一种能保证关键信息不丢。按长度裁剪无法判断内容重要程度。

因此**必须避免依赖裁剪来保护关键信息**。系统约束与工具定义放在独立的、不参与裁剪的位置；需要长期保留的事实存入状态，而不是留在对话历史里。

## 3.4 更换 Provider 会变的四件事

同一段代码换用不同厂商，以下四项会变化。不同步会导致统计与判断出错。

| 项目 | 变化内容 | 不同步的后果 |
|---|---|---|
| token 口径 | 词表不同，同一段文本计数不同 | 预算与实际用量不一致，成本报表失真 |
| `finish_reason` 取值 | 取值集合与命名不同，部分厂商增加自定义值 | 截断判断失效，半截内容被当作完整结果 |
| 工具调用格式 | 参数为 JSON 字符串或对象，并行调用的表达方式不同 | 解析失败，或多工具调用被丢弃 |
| 缓存命中规则 | 前缀匹配粒度、最小可缓存长度、有效期不同 | 命中率与预期不符，成本估算错误 |

这四项应在适配层统一，而不是散落在业务代码中。适配层的结构不在本章范围内，第 5 章实现工具调用时会涉及。

## 3.5 本章建立的四件事

1. **token 计数取决于词表。** 估算有偏差且方向不定，计费与预算使用服务端 `usage`。
2. **成本由输入和输出两部分构成，单价不同。** 优化方向取决于哪部分占比更高。
3. **窗口记账必须预留输出。** 裁剪无法判断内容重要性，关键信息不能放在可裁剪的位置。
4. **更换 Provider 会改变四项行为。** 这四项需要在适配层统一。

## 3.6 边界

以下情况不在本章范围内：

- **具体厂商的定价与缓存政策**：随厂商与时间变化，需查阅当期文档。
- **批量接口的计价方式**：通常有独立折扣，计算结构不同。
- **多模态输入的计量**：图像与音频按不同规则计数。
- **本地部署的成本核算**：按算力与折旧计算，不按 token 计费。
- **`usage` 缺失时的处理**：部分服务在流式响应中分批返回用量，需要单独处理，见第 30 章。

## 3.7 复现

运行 `step1_estimate.py`，把 `SAMPLES` 中的文本替换为你自己的业务文本，观察两种口径的偏差。

若偏差方向与表格不同，说明该文本的字符构成与样本差异较大。这一点本身就是结论：**在自己的语料上，固定公式的偏差无法预先推断。**

## 3.8 下一章

本章给出的是计量。下一章讨论提示词：同样一次调用，怎么写要求才能让输出可检查，以及改动后如何验证没有变坏。
