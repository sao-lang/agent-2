"""四种失控的触发脚本与信号，以及指纹与裁剪两个修法。

不联网。模型与工具都是脚本化的：四种失控各自对应一段触发脚本，跑完打印每一步的信号。
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------- 指纹

def naive_fingerprint(name: str, arguments: str) -> str:
    """不规范化：直接拿原文比。"""
    return f"{name}::{arguments}"


def fingerprint(name: str, arguments: str) -> str:
    """先规范化再比较：键序、空白都不该影响结果。"""
    try:
        normalized = json.dumps(
            json.loads(arguments), sort_keys=True, separators=(",", ":")
        )
    except json.JSONDecodeError:
        normalized = arguments.strip()
    return f"{name}::{normalized}"


# ---------------------------------------------------------------- 裁剪

def trim_tool_messages(messages: list[dict], keep_chars: int) -> list[dict]:
    """只压 tool 消息的正文，保留头尾，中间插入截断标记。"""
    out = []
    for m in messages:
        if m["role"] == "tool" and len(m["content"]) > keep_chars:
            head = m["content"][: keep_chars // 2]
            tail = m["content"][-keep_chars // 4:]
            cut = len(m["content"]) - len(head) - len(tail)
            m = dict(m, content=f"{head}\n...[截断 {cut} 字符]...\n{tail}")
        out.append(m)
    return out


# ---------------------------------------------------------------- 四种失控

def runaway() -> list[str]:
    """失控一：无限循环。每步都是新参数，没有任何重复，只能靠上限停。"""
    log = []
    for step in range(1, 6):
        log.append(f"步 {step}: 调 get_logs(service=s{step})  -> 结果为空")
    return log


def repeat() -> list[str]:
    """失控二：重复调用。同一个查询反复发，参数一字不差。"""
    log = []
    for step in range(1, 6):
        log.append(f"步 {step}: 调 get_logs(service=api)  -> 同一份日志")
    return log


def explode() -> list[str]:
    """失控三：上下文爆炸。每步回灌一整份日志，历史线性膨胀。"""
    log = []
    total = 0
    for step in range(1, 6):
        payload = {"lines": ["x" * 40 for _ in range(200)]}
        size = len(json.dumps(payload, ensure_ascii=False))
        total += size
        log.append(f"步 {step}: 回灌 {size} 字符，历史累计 {total}")
    return log


def cost_break() -> list[str]:
    """失控四：成本击穿。步数不多，但每步都重发全部历史。"""
    log = []
    total = 0
    for step in range(1, 6):
        prompt = 1000 * step          # 历史越长，prompt 越大
        total += prompt
        log.append(f"步 {step}: prompt={prompt}  累计={total}")
    return log


def main() -> None:
    for title, log in [
        ("一、无限循环", runaway()),
        ("二、重复调用", repeat()),
        ("三、上下文爆炸", explode()),
        ("四、成本击穿", cost_break()),
    ]:
        print(f"=== {title} ===")
        for line in log:
            print("  " + line)
        print()

    print("=== 指纹：同一组参数，两种写法 ===")
    a = '{"service": "api", "level": "error"}'
    b = '{"level":"error","service":"api"}'
    print(f"  原文比较：{naive_fingerprint('get_logs', a) == naive_fingerprint('get_logs', b)}")
    print(f"  规范化后：{fingerprint('get_logs', a) == fingerprint('get_logs', b)}")
    print(f"  指纹值：{fingerprint('get_logs', a)}")

    print()
    print("=== 裁剪：一次截断前后的字符数 ===")
    messages = [
        {"role": "system", "content": "你是运维助手。"},
        {"role": "user", "content": "帮我查一下 api 服务最近的错误。"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "get_logs", "arguments": '{"service":"api"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "L" * 400},
        {"role": "user", "content": "那再看一下 db 服务。"},
    ]
    before = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
    trimmed = trim_tool_messages(messages, keep_chars=80)
    after = sum(len(json.dumps(m, ensure_ascii=False)) for m in trimmed)
    print(f"  裁剪前 {before} 字符，裁剪后 {after} 字符")
    print(f"  tool 正文从 {len(messages[3]['content'])} 压到 {len(trimmed[3]['content'])}")
    print(f"  保留了头尾：{trimmed[3]['content'][:12]!r} ... {trimmed[3]['content'][-8:]!r}")


if __name__ == "__main__":
    main()
