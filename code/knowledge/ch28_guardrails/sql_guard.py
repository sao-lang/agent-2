"""SQL 守卫：黑名单漏在哪，只读连接拦在哪，词法白名单误杀在哪。

真的建一个 SQLite 库并在上面执行：先让三条绕过语句在可写连接上生效（伤害是
真的），再在只读连接上重跑同一批语句（引擎拒绝）。不联网。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

DB = Path("_sql_demo.db").resolve()

# 三条"看起来不像写操作"的语句
BYPASS = [
    ("WITH ... DELETE", "WITH x AS (SELECT 1) DELETE FROM orders"),
    ("注释开头", "/* 查询 */ DELETE FROM orders"),
    ("堆叠语句", "SELECT 1; DROP TABLE orders"),
]

NAIVE_BLACKLIST = ("delete", "drop", "update", "insert", "truncate", "alter")


def blacklist_ok(sql: str) -> str | None:
    """最常见的一版：看语句开头是不是写操作的动词。"""
    head = sql.strip().split()[0].lower()
    if head in NAIVE_BLACKLIST:
        return f"以 {head} 开头"
    return None


def token_allowlist(sql: str) -> str | None:
    """白名单：只允许 select / with 开头，且不允许出现写动词。"""
    head = sql.strip().split()[0].lower()
    if head not in ("select", "with"):
        return f"首词不是 select/with：{head}"
    if re.search(r"\b(delete|drop|update|insert|alter|attach)\b", sql, re.I):
        return "语句中出现写动词"
    return None


def build_db() -> None:
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount INTEGER)")
    conn.executemany("INSERT INTO orders (amount) VALUES (?)", [(100,), (200,), (300,)])
    conn.commit()
    conn.close()


def rows(path: Path, readonly: bool) -> int:
    uri = f"file:{path.as_posix()}?mode=ro" if readonly else str(path)
    conn = sqlite3.connect(uri, uri=readonly)
    try:
        return conn.execute("SELECT count(*) FROM orders").fetchone()[0]
    finally:
        conn.close()


def main() -> None:
    build_db()
    print("=== 1. 三条绕过语句，黑名单判什么 ===")
    for label, sql in BYPASS:
        print(f"  {label:<12} {sql}")
        print(f"    黑名单：{'拒绝 ' + blacklist_ok(sql) if blacklist_ok(sql) else '放行'}")

    print()
    print("=== 2. 可写连接上真的执行第一条（WITH ... DELETE）===")
    before = rows(DB, readonly=False)
    conn = sqlite3.connect(DB)
    conn.execute(BYPASS[0][1])
    conn.commit()
    conn.close()
    after = rows(DB, readonly=False)
    print(f"  执行前 orders 行数 {before}，执行后 {after}")

    print()
    print("=== 3. 只读连接上重跑同一批语句 ===")
    for label, sql in BYPASS:
        uri = f"file:{DB.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.execute(sql)
            print(f"  {label:<12} 执行成功（不该发生）")
        except sqlite3.Error as e:
            print(f"  {label:<12} {type(e).__name__}: {e}")
        finally:
            conn.close()

    print()
    print("=== 4. 词法白名单：挡住写动词，但会误杀 ===")
    for sql in (BYPASS[0][1], BYPASS[1][1], "SELECT 'DELETE' AS word",
                "SELECT * FROM orders WHERE note = 'update later'"):
        why = token_allowlist(sql)
        print(f"  {sql}")
        print(f"    {'拒绝 ' + why if why else '放行'}")

    build_db()
    DB.unlink()
    print()
    print("=== 5. 引擎层还有一道：Python 驱动只允许单条语句 ===")
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(BYPASS[2][1])
    except sqlite3.Error as e:
        print(f"  execute() 堆叠语句 -> {type(e).__name__}: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
