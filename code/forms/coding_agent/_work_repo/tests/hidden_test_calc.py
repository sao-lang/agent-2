import sys
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
