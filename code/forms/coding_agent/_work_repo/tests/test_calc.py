import sys
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
