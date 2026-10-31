"""在本地生成一个小仓库，供编码 agent 的示例使用。

不联网。仓库里有一个真 bug、三个可见测试、两个隐藏测试，以及若干无关文件。
每次运行都重建，保证示例可复现。

运行：python code/forms/coding_agent/repo_fixture.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).with_name("_work_repo")

CALC = '''"""几个统计函数。"""


def total(values):
    return sum(values)


def average(values):
    return total(values) / (len(values) - 1)
'''

REPORT = '''from src.calc import average


def summarize(rows):
    return f"平均 {average([r['value'] for r in rows]):.2f}"
'''

FORMAT = '''def money(x):
    return f"{x:.2f}"
'''

TEST = '''import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.calc import average, total


def test_average_normal():
    got = average([1, 2, 3])
    assert got == 2.0, f"期望 2.0 实际 {got}"


def test_average_empty():
    got = average([])
    assert got == 0.0, f"期望 0.0 实际 {got}"


def test_total():
    got = total([1, 2, 3])
    assert got == 6, f"期望 6 实际 {got}"


TESTS = [test_average_normal, test_average_empty, test_total]


def main():
    bad = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:                     # noqa: BLE001 测试运行器
            bad += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"{len(TESTS) - bad} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

HIDDEN = '''import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.calc import average


def test_single():
    got = average([5])
    assert got == 5.0, f"期望 5.0 实际 {got}"


def test_symmetric():
    got = average([-1, 1])
    assert got == 0.0, f"期望 0.0 实际 {got}"


TESTS = [test_single, test_symmetric]


def main():
    bad = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:                     # noqa: BLE001 测试运行器
            bad += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"{len(TESTS) - bad} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

README = "# 小仓库\n\nsrc/ 是源码，tests/ 是测试。\n"


def ensure() -> Path:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    (ROOT / "src").mkdir(parents=True)
    (ROOT / "tests").mkdir()
    (ROOT / "src" / "calc.py").write_text(CALC, encoding="utf-8")
    (ROOT / "src" / "report.py").write_text(REPORT, encoding="utf-8")
    (ROOT / "src" / "format.py").write_text(FORMAT, encoding="utf-8")
    (ROOT / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
    (ROOT / "tests" / "hidden_test_calc.py").write_text(HIDDEN, encoding="utf-8")
    (ROOT / "README.md").write_text(README, encoding="utf-8")
    return ROOT


if __name__ == "__main__":
    print(ensure())
