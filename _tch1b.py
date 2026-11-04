import hashlib
import re
from pathlib import Path

P = Path("01-一次调用的四个字段.md")

EDITS = [
    (
        "输出里能读出的第一件事是：**请求里只有四类东西，全部由调用方决定。** 一次调用涉及三方，调用方代码、SDK、服务端，分清三方各管什么，排错方向才有依据。",
        "输出里能读出的第一件事是：**请求里只有四类东西，全部由调用方决定。** 一次调用涉及三方，出问题时先确定属于哪一行，再动手。",
    ),
    (
        "\n\n第三列是这张表的用处：先确定问题属于哪一行，再动手。把服务端返回的 `length` 当成 SDK 的问题去升级依赖，或把自己的参数错误当成服务端问题去换服务商，都是跳过这一步的后果。",
        "",
    ),
]


def fences(text: str) -> list[str]:
    return re.findall(r"```.*?```", text, flags=re.S)


def main() -> None:
    text = P.read_text(encoding="utf-8")
    before = [hashlib.sha256(f.encode()).hexdigest() for f in fences(text)]
    for i, (old, new) in enumerate(EDITS):
        if text.count(old) != 1:
            print(f"EDIT #{i} 匹配 {text.count(old)} 次")
            raise SystemExit(1)
        text = text.replace(old, new)
    after = [hashlib.sha256(f.encode()).hexdigest() for f in fences(text)]
    assert before == after, "代码/输出块变化"
    P.write_text(text, encoding="utf-8")
    print("ok")


main()
