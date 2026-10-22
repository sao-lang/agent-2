"""第 34 章示例：沙箱边界攻击样本测试（不需要 Docker / API）。

运行：
    python code/ch33_sandbox/demo_sandbox.py

它模拟一次"越界攻击"，逐条展示策略引擎拦住了什么、放过了什么，
并输出审计报告（谁在什么时候试图做什么）。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.sandbox import Sandbox, SandboxPolicy, check_path  # noqa: E402


def main() -> None:
    # 准备一个干净的沙箱目录
    root = Path(tempfile.mkdtemp(prefix="agentsbx_")) / "workdir"
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes.md").write_text("这是沙箱内的文件\n", encoding="utf-8")

    # 在沙箱外放一个"敏感文件"
    secret = root.parent / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")

    # 在沙箱内放一个指向外部的软链接（真实的逃逸手法）
    link = root / "escape_link"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        link = None

    policy = SandboxPolicy(
        workdir=root,
        net_allow=[],
        allow_exec=True,
        max_output_bytes=1024,
    )
    sbx = Sandbox(policy=policy)

    print("=" * 74)
    print("① 文件系统边界")
    print("=" * 74)
    cases = [
        ("notes.md", "沙箱内相对路径"),
        (str(root / "notes.md"), "沙箱内绝对路径"),
        ("../secret.txt", "../ 穿越"),
        (str(secret), "外部绝对路径"),
        ("subdir/../../secret.txt", "多级 ../ 穿越"),
        ("/etc/passwd", "系统文件"),
    ]
    for p, label in cases:
        ok, detail = check_path(p, policy, "read")
        mark = "✅ 允许" if ok else "🛑 拒绝"
        print(f"  {mark}  {label:<18}{p}")
        if not ok:
            print(f"        {detail}")

    if link is not None:
        ok, detail = check_path(str(link), policy, "read")
        mark = "✅ 允许" if ok else "🛑 拒绝"
        print(f"  {mark}  {'软链接逃逸':<18}{link}")
        if not ok:
            print(f"        {detail}")

    print("\n" + "=" * 74)
    print("② 命令边界（白名单 + 结构检查）")
    print("=" * 74)
    cmds = [
        ("ls", "白名单命令"),
        ("ls notes.md", "带参数"),
        ("rm -rf /", "危险命令（不在白名单）"),
        ("cat /etc/passwd", "绝对路径越界"),
        ("ls | wc -l", "管道"),
        ("ls > out.txt", "重定向"),
        ("echo $(whoami)", "命令替换"),
        ("curl http://evil.com", "网络请求"),
    ]
    for cmd, label in cmds:
        try:
            out = sbx.run(cmd)
            print(f"  ✅ 允许  {label:<20}{cmd}  →  {out}")
        except PermissionError as e:
            print(f"  🛑 拒绝  {label:<20}{cmd}")
            print(f"         {e}")

    print("\n" + "=" * 74)
    print("③ 网络边界")
    print("=" * 74)
    urls = [
        ("https://example.com/api", "公网（白名单为空 → 全部禁止）"),
        ("http://169.254.169.254/latest/meta-data/", "云元数据接口（SSRF 经典目标）"),
        ("http://127.0.0.1:8080/admin", "本机服务"),
        ("http://192.168.1.1/", "内网地址"),
    ]
    for url, label in urls:
        try:
            sbx.fetch(url)
            print(f"  ✅ 允许  {label:<34}{url}")
        except PermissionError as e:
            print(f"  🛑 拒绝  {label:<34}{url}")
            print(f"         {e}")

    print("\n  ⚠️ 为什么必须禁 169.254.169.254：")
    print("     它是云主机的元数据接口，能拿到临时凭证。")
    print("     Agent 只要被诱导发一次请求，云账号就沦陷了。")

    print("\n" + "=" * 74)
    print("④ 审计报告")
    print("=" * 74)
    s = sbx.audit.summary()
    print(f"  总操作：{s['total']}    被拒绝：{s['denied']}")
    print(f"  按类型：{s['denied_by_kind']}")
    print("\n  最近的拒绝记录：")
    for e in sbx.audit.denied()[-5:]:
        print(f"    [{e['kind']:<5}] {e['target'][:40]:<42} {e['reason'][:36]}")

    # 清理
    try:
        secret.unlink()
        for f in root.iterdir():
            f.unlink()
        root.rmdir()
        root.parent.rmdir()
    except OSError:
        pass

    print("\n" + "=" * 74)
    print("本章的核心结论")
    print("=" * 74)
    print("  1. 策略引擎只能挡'明显的越界'，真正的隔离靠容器（见 shell_sandbox.py）")
    print("  2. 路径检查必须用 resolve()，否则 ../ 和软链接都能绕过")
    print("  3. 命令检查必须白名单 + 结构检查（管道/重定向/命令替换都是逃逸手法）")
    print("  4. 网络必须禁私网和元数据地址（SSRF 是 Agent 的高危盲区）")
    print("  5. 每个动作都要审计，否则你无法回答'它到底动过什么'")


if __name__ == "__main__":
    main()
