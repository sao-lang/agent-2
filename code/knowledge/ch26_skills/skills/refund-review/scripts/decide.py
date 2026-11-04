"""退货判定引擎：输入一条记录，输出结论、理由码与条款。

用法：
    python decide.py '{"order_id":"A1001","signed_days_ago":3,"category":"普通","unopened":true}'
    echo '{...}' | python decide.py

退出码：0 判定成立；1 输入不全；2 记录自相矛盾。
"""

from __future__ import annotations

import json
import sys

WINDOWS = {
    "普通": (7, "P-7"),
    "生鲜": (1, "P-9"),
    "定制": (0, "P-12"),
}
QUALITY_WINDOW = (15, "P-15")


def decide(record: dict) -> tuple[dict, int]:
    order_id = record.get("order_id")
    days = record.get("signed_days_ago")
    category = record.get("category", "普通")
    quality = bool(record.get("quality_issue"))
    unopened = record.get("unopened", True)

    if not order_id:
        return {"conclusion": "待定", "reason_code": "MISSING_ORDER_ID", "detail": "缺订单号"}, 1
    if days is None:
        return {"conclusion": "待定", "reason_code": "NOT_SIGNED", "detail": "订单未签收，无签收天数"}, 1
    if not isinstance(days, int) or days < 0:
        return {"conclusion": "待定", "reason_code": "BAD_DAYS", "detail": "签收天数必须是非负整数"}, 2

    if quality:
        window, clause = QUALITY_WINDOW
        ok = days <= window
        code = "QUALITY_WITHIN" if ok else "QUALITY_EXPIRED"
    else:
        window, clause = WINDOWS.get(category, WINDOWS["普通"])
        if category == "定制":
            ok, code = False, "CUSTOM_NO_REASON"
        elif category == "生鲜":
            ok = days <= window
            code = "FRESH_WITHIN" if ok else "FRESH_EXPIRED"
        elif not unopened:
            ok, code = False, "OPENED_USED"
        else:
            ok = days <= window
            code = "WITHIN" if ok else "EXPIRED"

    return {
        "order_id": order_id,
        "category": category,
        "signed_days_ago": days,
        "window_days": window,
        "clause": clause,
        "conclusion": "可退" if ok else "不可退",
        "reason_code": code,
        "detail": f"第 {days} 天 / 窗口 {window} 天（{clause}）",
    }, 0


def main() -> int:
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    record = json.loads(raw)
    result, code = decide(record)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
