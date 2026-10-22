"""第 34 章 step1：Agent 拿到 shell 之后，第一件事通常是去读 /etc/passwd（离线）。

运行：
    python code/ch34_sandbox/step1_why_boundary.py

上一级的痛点：无（这是起点）。
这一级做什么：用一批**真实的越界路径**做对照，证明两件事：
  1. "字符串黑名单"永远防不住（`..`、软链接、绝对路径）
  2. 唯一可靠的做法是**白名单 + 解析后的真实路径**

本文件不真的读敏感文件（读到会拒绝并记录），只演示判定逻辑。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.sandbox import SandboxPolicy, check_path  # noqa: E402

# 一次 Agent 尝试访问的路径（前几行是"正当"的，后面是越界）
ATTEMPTS = [
    ("正常读工作区", "notes/order.md"),
    ("正常写工作区", "output/result.txt"),
    ("相对路径穿越", "../../etc/passwd"),
    ("中段穿越", "a/b/../../../etc/passwd"),
    ("绝对路径", "/etc/shadow"),
    ("Windows 盘符", "C:/Windows/System32/config/SAM"),
    ("UNC 路径", "\\\\server\\share\\secret.txt"),
    ("伪装成工作区", "./notes/../../../../etc/hosts"),
]

# 一个"看起来很努力"的黑名单：覆盖了常见写法
BAD_BLACKLIST = ("..", "/etc/", "c:/windows", "\\\\", "/shadow", "/passwd", "%2e")


def naive_blacklist(path: str) -> bool:
    """最常见的错误实现：出现这些子串就拦。

    它能拦住所有**字面**上的越界写法，但拦不住一切"解析之后才越界"的路径。
    """
    low = path.lower()
    return any(k in low for k in BAD_BLACKLIST)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "workspace"
        (work / "notes").mkdir(parents=True)
        (work / "notes" / "order.md").write_text("订单 A12345", encoding="utf-8")

        # 造一个指向外部的软链接（模拟"攻击者提前埋好"）
        link = work / "escape"
        try:
            link.symlink_to(Path(tmp).parent if Path(tmp).parent.exists() else Path("/"), target_is_directory=True)
        except (OSError, NotImplementedError):
            link = None  # Windows 上可能需要管理员权限，跳过

        policy = SandboxPolicy(workdir=work)

        print("=" * 84)
        print("同一批路径，黑名单 vs 白名单")
        print("=" * 84)
        print(f"工作区：{work}")
        print(f"黑名单：{BAD_BLACKLIST}\n")
        print(f"{'场景':<18}{'路径':<40}{'黑名单':<10}{'白名单'}")
        print("-" * 84)

        leaks = []
        for label, raw in ATTEMPTS:
            by_black = not naive_blacklist(raw)
            ok, _detail = check_path(raw, policy, "read")
            mark = "放行" if by_black else "拦"
            print(f"{label:<18}{raw[:38]:<40}{mark:<10}{'放行' if ok else '拦'}")
            if by_black and not ok:
                leaks.append((label, raw))

        if link:
            ok, detail = check_path("escape/etc/passwd", policy, "read")
            print(f"{'软链接逃逸':<18}{'escape/etc/passwd':<40}{'放行':<10}{'放行' if ok else '拦'}")
            if not ok:
                leaks.append(("软链接逃逸", detail))

        print("\n" + "=" * 84)
        print("★ 黑名单漏掉了什么")
        print("=" * 84)
        for label, raw in leaks:
            print(f"  - [{label}] {raw}")
        print()
        print("  注意：这份黑名单已经写得相当『努力』了（连 %2e 都想着拦），")
        print("  它拦住了全部字面越界。剩下那条漏网的，是**软链接**——")
        print("  路径里一个可疑字符都没有：`escape/etc/passwd`。")
        print()
        print("  这就是黑名单的根本问题：它只能判断**字符串长什么样**，")
        print("  而越界是**文件系统解析之后**才发生的事。")
        print("  白名单只需要回答一个问题：**它解析之后，是不是还在工作区里？**")

        print("\n" + "=" * 84)
        print("白名单为什么可靠：它检查的是**解析后的真实路径**")
        print("=" * 84)
        print("  判定只有两步：")
        print("    1. 相对路径 → 拼到工作区；")
        print("    2. resolve() 展开 `..` 和软链接 → 用 relative_to() 判断是否在工作区内。")
        print()
        print("  代码只有 6 行：")
        print("      p = Path(path)")
        print("      if not p.is_absolute():")
        print("          p = policy.workdir / p")
        print("      resolved = p.resolve()          # 关键：展开软链接与 ..")
        print("      if not _is_within(resolved, roots):")
        print("          return False")
        print()
        print("  resolve() 是唯一无法被字符串技巧骗过的操作——")
        print("  因为它是**文件系统在帮你展开**，而不是你在猜。")

        print("\n" + "=" * 84)
        print("⚠️ 但仍有一个前提：白名单本身要选对")
        print("=" * 84)
        print("  如果工作区被设成 `/` 或 `C:\\`，上面的检查全部形同虚设。")
        print("  所以工作区必须是**进程启动时就固定下来的一个空目录**，")
        print("  并且**不能由模型或用户指定**。")


if __name__ == "__main__":
    main()
