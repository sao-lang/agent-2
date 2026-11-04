"""decide.py 的离线单测：覆盖边界日、生鲜、定制、质量问题与缺字段。

运行：python tests/test_decide.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from decide import decide  # noqa: E402

CASES = [
    ("普通第 3 天", {"order_id": "A1001", "signed_days_ago": 3}, "可退", "WITHIN"),
    ("普通第 7 天", {"order_id": "A1001", "signed_days_ago": 7}, "可退", "WITHIN"),
    ("普通第 8 天", {"order_id": "A1002", "signed_days_ago": 8}, "不可退", "EXPIRED"),
    ("普通已拆封", {"order_id": "A1001", "signed_days_ago": 2, "unopened": False}, "不可退", "OPENED_USED"),
    ("生鲜 1 天内", {"order_id": "B2001", "signed_days_ago": 1, "category": "生鲜"}, "可退", "FRESH_WITHIN"),
    ("生鲜 2 天", {"order_id": "B2001", "signed_days_ago": 2, "category": "生鲜"}, "不可退", "FRESH_EXPIRED"),
    ("定制无理由", {"order_id": "C3001", "signed_days_ago": 1, "category": "定制"}, "不可退", "CUSTOM_NO_REASON"),
    ("质量问题第 12 天", {"order_id": "A1002", "signed_days_ago": 12, "quality_issue": True}, "可退", "QUALITY_WITHIN"),
    ("缺签收天数", {"order_id": "A1001"}, "待定", "NOT_SIGNED"),
    ("缺订单号", {"signed_days_ago": 3}, "待定", "MISSING_ORDER_ID"),
]


def main() -> int:
    failed = 0
    for name, record, want, code in CASES:
        result, exit_code = decide(record)
        ok = result["conclusion"] == want and result["reason_code"] == code
        failed += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name:14} 结论={result['conclusion']:3} 理由={result['reason_code']:18} 退出码={exit_code}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
