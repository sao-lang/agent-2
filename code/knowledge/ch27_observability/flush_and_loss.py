"""为什么 span 必须落盘：缓冲到最后再写，进程一死就全没了。

不联网。同一批 11 条 span，两种写法各跑一次，在第 7 条时模拟进程被杀：
  buffer    全部攒在内存里，退出时统一写
  streaming 每产生一条就追加 + flush
之后从文件里统计"还能还原多少条"。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from trace_tree import Span, build_run

WORK = Path("_flush_demo").resolve()
CRASH_AT = 7


class Collector:
    def __init__(self, path: Path, mode: str) -> None:
        self.path = path
        self.mode = mode
        self.buffer: list[Span] = []

    def emit(self, span: Span) -> None:
        if self.mode == "streaming":
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(span), ensure_ascii=False) + "\n")
                f.flush()
        else:
            self.buffer.append(span)

    def shutdown(self) -> None:
        """正常退出时才会走到这里。"""
        with self.path.open("a", encoding="utf-8") as f:
            for s in self.buffer:
                f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")


def read_count(path: Path) -> tuple[int, int]:
    ok = bad = 0
    if not path.exists():
        return 0, 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
            ok += 1
        except json.JSONDecodeError:
            bad += 1
    return ok, bad


def run_case(mode: str) -> None:
    path = WORK / f"{mode}.jsonl"
    c = Collector(path, mode)
    spans = build_run()
    emitted = 0
    for i, s in enumerate(spans):
        if i == CRASH_AT:
            break                      # 进程在这里被杀，后面的代码不执行
        c.emit(s)
        emitted += 1
    # 正常退出才会 flush 缓冲；崩溃时这一步不会发生
    if mode == "streaming":
        c.shutdown()
    ok, bad = read_count(path)
    print(f"  {mode:<10} 已产生 {emitted} 条，文件里可解析 {ok} 条，坏行 {bad} 条")


def main() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()

    print(f"=== 1. 在第 {CRASH_AT + 1} 条 span 产生前杀进程 ===")
    print(f"  这次运行共 {len(build_run())} 条 span")
    run_case("buffer")
    run_case("streaming")

    print()
    print("=== 2. 坏行是怎么来的，又要怎么处理 ===")
    partial = WORK / "partial.jsonl"
    partial.write_text('{"trace_id": "abc", "span_id": "s1", "parent_id": null, '
                       '"name": "run", "kind": "run", "start_ms": 0, "end_ms": 1}\n'
                       '{"trace_id": "abc", "span_id": "s2", "par',
                       encoding="utf-8")
    ok, bad = read_count(partial)
    print(f"  两条记录，一条完整一条写了一半：可解析 {ok}，坏行 {bad}")

    print()
    print("=== 3. 三种'写到哪里'的取舍 ===")
    for where, risk in (("进程内存", "进程退出即丢，等于没有"),
                        ("本地文件", "换机器就找不到"),
                        ("对象存储 / 数据库", "每条一次写，延迟更高")):
        print(f"  {where:<18}{risk}")

    shutil.rmtree(WORK)


if __name__ == "__main__":
    main()
