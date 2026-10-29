"""校验一条退货结论与两个数字是否一致。

用法：
  python check.py '{"order_id":"A1001","signed_days_ago":3,"window_days":7,"conclusion":"可退","clause":"第四条"}'

退出码 0 表示一致，1 表示不一致。这个脚本不调用模型，只做算术与字段检查。
"""

from __future__ import annotations

import json
import sys

REQUIRED = ("order_id", "signed_days_ago", "window_days", "conclusion")


def check(record: dict) -> list[str]:
    """返回问题清单；空清单表示通过。"""
    missing = [k for k in REQUIRED if record.get(k) in (None, "")]
    if missing:
        return [f"缺字段：{','.join(missing)}"]
    days, window = record["signed_days_ago"], record["window_days"]
    if not isinstance(days, int) or not isinstance(window, int):
        return ["signed_days_ago 与 window_days 必须是整数"]
    expect = "可退" if days <= window else "不可退"
    problems = []
    if record["conclusion"] != expect:
        problems.append(
            f"结论与数字矛盾：{days} 与 {window} 应为{expect}，写的是 {record['conclusion']}"
        )
    if not record.get("clause"):
        problems.append("没有引用条款")
    return problems


def main() -> int:
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    problems = check(json.loads(raw))
    if problems:
        print("FAIL " + "；".join(problems))
        return 1
    print("PASS 结论与数字一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
