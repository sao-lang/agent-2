"""审批分级：同一组工具调用，按两个判据（可逆、影响范围）分成四级。

不联网。判据是声明式的：写在动作的定义上，而不是留在审批人的经验里。
四级的分法让"自动执行"成为默认，让"要人点头"只出现在真正需要的格子里。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Action:
    tool: str
    what: str
    reversible: bool
    scope: str          # self / team / global / external


ACTIONS = [
    Action("read_file", "读 src/app.py", True, "self"),
    Action("write_file", "写临时目录 build/tmp/out.json", True, "self"),
    Action("run_tests", "跑 pytest", True, "self"),
    Action("write_file", "改 src/app.py", True, "team"),
    Action("git_commit", "提交到本地分支", True, "team"),
    Action("rollback", "回滚上次迁移（有快照）", True, "team"),
    Action("call_api", "调外部汇率 API", True, "external"),
    Action("write_config", "改生产配置（有快照）", True, "global"),
    Action("send_email", "给客户发一封邮件", False, "external"),
    Action("delete_rows", "删掉 30 天前的订单", False, "global"),
    Action("deploy", "发布到生产环境", False, "global"),
]

LEVELS = {
    1: "自动执行",
    2: "执行后留存，可回滚",
    3: "事前审批（单人）",
    4: "事前审批（双人）+ 冷却期",
}


def level(a: Action) -> int:
    if a.scope == "self" and a.reversible:
        return 1
    if not a.reversible and a.scope in ("global", "external"):
        return 4
    if not a.reversible or a.scope in ("global", "external"):
        return 3
    return 2


def reason(a: Action) -> str:
    lv = level(a)
    if lv == 1:
        return "只影响本次会话的中间产物"
    if lv == 2:
        return "别人看得见，但可回滚"
    if lv == 3:
        if a.reversible:
            return "影响面大，但可回滚"
        return "不可逆，影响面限于团队"
    return "不可逆且影响面超出团队"


def pad(text: str, width: int) -> str:
    """按显示宽度补齐（一个汉字算两格）。"""
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    print("=== 1. 十一个动作的分级 ===")
    print("  " + pad("工具", 14) + pad("动作", 30) + pad("可逆", 6) + pad("范围", 10) + "级别")
    for a in ACTIONS:
        lv = level(a)
        print("  " + pad(a.tool, 14) + pad(a.what, 30)
              + pad("是" if a.reversible else "否", 6) + pad(a.scope, 10)
              + f"L{lv} {LEVELS[lv]}")

    print()
    print("=== 2. 每一级各几个，理由是什么 ===")
    for lv in (1, 2, 3, 4):
        items = [a for a in ACTIONS if level(a) == lv]
        print(f"  L{lv} {LEVELS[lv]}：{len(items)} 个")
        for a in items:
            print(f"    {pad(a.what, 30)}<- {reason(a)}")

    print()
    print("=== 3. 只改一个字段，级别会落到哪 ===")
    for scope in ("self", "team", "global", "external"):
        a = Action("write_file", "改文件", True, scope)
        print(f"  可逆 + {pad(scope, 10)}L{level(a)}")
    for scope in ("team", "global", "external"):
        a = Action("write_file", "改文件", False, scope)
        print(f"  不可逆 + {pad(scope, 10)}L{level(a)}")
    print("  <- 两个字段把十一种动作分成四块，没有一格需要人凭经验判断")


if __name__ == "__main__":
    main()
