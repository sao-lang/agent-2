"""有 / 无仓库地图的对照：token 与成功率。

不联网。任务表固定（6 个改动需求），策略是"先找文件再读"。
没有地图时，只能靠关键词搜索猜文件；关键词与文件名不一致时就会猜错。
有地图时，先花一次调用读地图（约 90 tokens），之后直接读目标文件。

运行：python code/forms/coding_agent/repo_map.py
"""

from __future__ import annotations

import repo_fixture
from tools import Repo

MAP = """仓库地图
src/calc.py                统计：total / average（测试 tests/test_calc.py）
src/report.py              报表：summarize，依赖 calc.average
src/format.py              格式化：money
tests/test_calc.py         3 个可见测试
tests/hidden_test_calc.py  2 个隐藏测试"""

TASKS = [
    ("把平均值改成保留两位", "平均值", "src/calc.py"),
    ("报表摘要的格式调一下", "报表摘要", "src/report.py"),
    ("average 在空列表时的行为", "average", "src/calc.py"),
    ("金额格式化成两位小数", "money", "src/format.py"),
    ("total 改成支持浮点", "total", "src/calc.py"),
    ("结果四舍五入到两位", "四舍五入", "src/calc.py"),
]


def guess_file(repo: Repo, keyword: str) -> tuple[str, int]:
    """没有地图时的找法：搜关键词，取第一条命中所在的文件。"""
    result = repo.search(keyword)
    hits = str(result)
    if hits == "没有命中":
        return "src/format.py", result.tokens         # 猜一个最像"格式化"的文件
    return hits.splitlines()[0].split(":")[0], result.tokens


def run_task(repo: Repo, keyword: str, target: str, use_map: bool) -> tuple[int, bool]:
    tokens = 0
    if use_map:
        tokens += int(len(MAP) * 0.6)
        got = target
    else:
        tokens += repo.list_tree().tokens
        got, t = guess_file(repo, keyword)
        tokens += t
    tokens += repo.read_file(got).tokens
    return tokens, got == target


def main() -> None:
    repo = Repo(repo_fixture.ensure())

    print("=== 1. 六个任务，两种找法 ===")
    print(f"    {'任务':<24}{'无地图':<12}{'有地图':<12}")
    total_plain = total_map = 0
    wins_plain = wins_map = 0
    for name, keyword, target in TASKS:
        tp, okp = run_task(repo, keyword, target, use_map=False)
        tm, okm = run_task(repo, keyword, target, use_map=True)
        total_plain += tp
        total_map += tm
        wins_plain += int(okp)
        wins_map += int(okm)
        print(f"    {name:<24}{('命中' if okp else '找错'):<12}{('命中' if okm else '找错'):<12}"
              f"  {tp:>4}/{tm:<4} tokens")

    print()
    print("=== 2. 汇总 ===")
    print(f"    无地图：成功率 {wins_plain}/6  总 {total_plain} tokens")
    print(f"    有地图：成功率 {wins_map}/6  总 {total_map} tokens")

    print()
    print("=== 3. 地图本身的成本 ===")
    print(f"    地图 {len(MAP)} 字符，约 {int(len(MAP) * 0.6)} tokens；六个任务各读一次，"
          f"共 {6 * int(len(MAP) * 0.6)} tokens")
    print(f"    它省下的是'猜错文件再重读'的成本：无地图时六次里 {6 - wins_plain} 次找错")

    print()
    print("=== 4. 什么时候地图不划算 ===")
    print("    关键词与文件名高度一致时（如 money -> format.py），搜索一次就够")
    print("    仓库只有三五个文件时，list_tree 本身就是地图")


if __name__ == "__main__":
    main()
