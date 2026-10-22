"""第 32 章 step4：SQL 守卫 —— 为什么"只看是不是 SELECT 开头"一定被绕过（离线）。

运行：
    python code/ch31_guardrails/step4_sql_guard.py

上一级的痛点：工具名登记好了，但模型真正生成的是**一整条 SQL 字符串**。
这一级做什么：用同一批 SQL，分别过"前缀检查"和"三层检查"，看漏了什么。

核心事实：`WITH x AS (DELETE ...) SELECT * FROM x` 以 WITH 开头，
只查前缀的守卫会直接放行 —— 而它删了表。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.guardrails import SQLGuard  # noqa: E402

ATTACKS = [
    ("直接删", "DELETE FROM orders WHERE id=1"),
    ("多语句", "SELECT * FROM orders; DROP TABLE users"),
    ("系统表", "SELECT * FROM mysql.user"),
    ("读文件", "SELECT LOAD_FILE('/etc/passwd')"),
    ("行锁", "SELECT * FROM orders WHERE id=1 FOR UPDATE"),
    ("CTE 藏删除", "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x"),
    ("拖库", "SELECT SLEEP(10)"),
    ("元数据", "SELECT * FROM information_schema.tables"),
    ("union 拖全表", "SELECT id FROM orders UNION SELECT password FROM users"),
]

NORMAL = [
    "SELECT id, amount FROM orders WHERE user_id=42",
    "SELECT SUM(amount) FROM orders WHERE created_at > '2026-01-01'",
    "SELECT * FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE user_id=42) LIMIT 50",
    "WITH t AS (SELECT user_id, COUNT(*) c FROM orders GROUP BY user_id) SELECT * FROM t ORDER BY c DESC",
]


def prefix_only(sql: str) -> bool:
    """最常见的错误实现：只看开头是不是 SELECT/WITH。"""
    return not sql.strip().lower().startswith(("select", "with", "explain"))


def main() -> None:
    guard = SQLGuard(max_rows=1000, default_limit=100,
                     allowed_tables={"orders", "order_items", "users"})

    print("=" * 84)
    print("同一批 SQL，两种检查")
    print("=" * 84)
    print(f"{'攻击手法':<14}{'前缀检查':<12}{'三层检查':<12}SQL")
    print("-" * 84)
    prefix_miss = []
    for label, sql in ATTACKS:
        blocked_prefix = prefix_only(sql)
        d = guard.check(sql)
        p_mark = "拦" if blocked_prefix else "漏"
        c_mark = "拦" if d.blocked else "漏"
        print(f"{label:<14}{p_mark:<12}{c_mark:<12}{sql[:42]}")
        if not blocked_prefix and d.blocked:
            prefix_miss.append((label, sql, d.rule))

    print("\n" + "=" * 84)
    print("★ 前缀检查漏掉的，正是最危险的那一条")
    print("=" * 84)
    for label, sql, rule in prefix_miss:
        head = sql.strip().split()[0].upper()
        print(f"  [{label}]")
        print(f"    SQL：{sql}")
        print(f"    前缀检查：以 {head} 开头 -> 放行")
        print(f"    三层检查：命中 {rule} -> 拦截")

    print("\n" + "=" * 84)
    print("三层检查分别在做什么")
    print("=" * 84)
    print("  ① 语法白名单：只允许 SELECT / WITH / EXPLAIN 开头")
    print("     拦得住：DELETE / UPDATE 开头的语句")
    print("     拦不住：WITH ... DELETE（以 WITH 开头）")
    print()
    print("  ② 关键字扫描：语句里出现 insert/update/delete/drop/... 就拒")
    print("     拦得住：CTE 里藏的删除、多语句里的 DROP")
    print("     拦不住：危险函数（需要第 ③ 层）")
    print()
    print("  ③ 危险模式：系统表、读写文件、SLEEP、多语句")
    print("     拦得住：读 /etc/passwd、探测元数据、把库拖垮")

    print("\n" + "=" * 84)
    print("正常 SQL 必须能过（否则你的功能就用不了）")
    print("=" * 84)
    for sql in NORMAL:
        d = guard.check(sql)
        mark = "拦" if d.blocked else "过"
        print(f"  {mark}  {sql[:60]}")
        if not d.blocked:
            print(f"      → 自动补 LIMIT：{guard.enforce(sql)[-40:]}")

    print("\n" + "=" * 84)
    print("⚠️ 必须说清的边界：它防的不是 SQL 注入")
    print("=" * 84)
    print(f"  {'威胁':<26}{'该用什么防'}")
    print("  " + "-" * 60)
    print(f"  {'模型生成 DROP TABLE':<26}{'本章的 SQLGuard'}")
    print(f"  {'用户输入拼接进 SQL':<26}{'参数化查询（SQLGuard 管不了）'}")
    print()
    print("  Agent 场景的危险在于：模型生成的是**完整 SQL 字符串**，")
    print("  参数化查询用不上，只能靠语法层拦截 ——")
    print("  而语法层一定有漏网之鱼。")
    print()
    print("  所以必须双层：")
    print("    应用层 SQLGuard（拦明显坏的）")
    print("      +")
    print("    数据库层**只读账号**（拦一切意外的）")
    print()
    print("  只靠应用层 = 赌自己的正则没有漏洞。")


if __name__ == "__main__":
    main()
