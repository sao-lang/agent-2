"""第 34 章 step3：四条边界里，网络和资源最容易被忘（离线）。

运行：
    python code/ch33_sandbox/step3_network_and_resource.py

上一级的痛点：命令白名单挡住了结构绕过，但**跑起来的进程能干什么**还没限制。
这一级做什么：补上两条最容易漏的边界 ——
              · 网络：默认断网 + 白名单（尤其要禁云元数据地址）
              · 资源：超时、输出截断（否则一条命令就能拖垮服务）

这两个都不是"安全"问题，而是**可用性**问题：
  一个能访问 169.254.169.254 的 Agent，能把你的云凭证发出去；
一个 `yes` 命令，能在 10 秒内占满磁盘。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.sandbox import SandboxPolicy, check_url  # noqa: E402

URLS = [
    ("公司文档", "https://docs.example.com/policy"),
    ("正常 API", "https://api.example.com/v1/order/1"),
    ("本机服务", "http://localhost:8080/admin"),
    ("环回地址", "http://127.0.0.1:6379/"),
    ("云元数据", "http://169.254.169.254/latest/meta-data/iam/"),
    ("内网段", "http://10.0.0.5:9200/_cat/indices"),
    ("家用段", "http://192.168.1.1/admin"),
    ("172 私网", "http://172.20.0.10:8500/v1/agent/self"),
    ("未登记域名", "https://evil.example.net/collect"),
]


def main() -> None:
    allow = ["example.com", "api.example.com"]
    policy = SandboxPolicy(net_allow=allow)

    print("=" * 84)
    print("① 网络边界：白名单 + 私网/元数据黑名单")
    print("=" * 84)
    print(f"白名单：{allow}\n")
    print(f"{'用途':<14}{'URL':<44}{'判定'}")
    print("-" * 84)
    for label, url in URLS:
        ok, detail = check_url(url, policy)
        note = "放行" if ok else f"拦（{detail}）"
        print(f"{label:<14}{url[:42]:<44}{note}")

    print("\n" + "=" * 84)
    print("★ 169.254.169.254 是什么")
    print("=" * 84)
    print("  它是 AWS / 阿里云 / 腾讯云等平台的**元数据服务**地址。")
    print("  在云主机上，不带任何凭证访问它，就能拿到实例的角色临时凭证：")
    print()
    print("    GET http://169.254.169.254/latest/meta-data/iam/security-credentials/")
    print()
    print("  而 Agent 最容易被诱导去做的事就是『帮我访问这个链接总结一下』。")
    print("  → 所以私网段和 169.254 必须在**代码里硬禁**，不能只靠白名单。")

    print("\n" + "=" * 84)
    print("② 资源边界：超时与输出截断")
    print("=" * 84)
    with tempfile.TemporaryDirectory():
        # 一个"看起来正常"的命令，实际会不停输出
        cmd = [sys.executable, "-c", "import sys\nwhile True: sys.stdout.write('x'*4096)"]
        limit_sec, limit_bytes = 1.5, 65_536

        t0 = time.perf_counter()
        captured = 0
        timed_out = False
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            assert proc.stdout is not None
            while True:
                if time.perf_counter() - t0 > limit_sec:
                    proc.kill()
                    timed_out = True
                    break
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                captured += len(chunk)
                if captured >= limit_bytes:      # 超过上限就截断（真实实现还会 kill 进程）
                    proc.kill()
                    break
            proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError) as e:
            timed_out = True
            print(f"  （执行异常：{type(e).__name__}）")

        elapsed = time.perf_counter() - t0
        print(f"  跑一个『一直输出』的命令，带 {limit_sec}s 超时：")
        print(f"    实际耗时：{elapsed:.2f}s")
        print(f"    是否触发超时：{'是' if timed_out else '否（输出先达到上限）'}")
        print(f"    累计读到：{captured:,} 字节（已按 max_output_bytes={limit_bytes:,} 截断）")

    print("\n  → 两个数字决定了这件事：")
    print(f"     max_seconds      = {limit_sec}（超时直接 kill）")
    print(f"     max_output_bytes = {limit_bytes:,}（超过就截断）")

    print("\n" + "=" * 84)
    print("③ 四条边界的完整清单")
    print("=" * 84)
    print(f"  {'维度':<10}{'默认值':<12}{'要防的事'}")
    print("  " + "-" * 72)
    print(f"  {'文件系统':<10}{'空工作区':<12}{'读凭证 / 改系统文件 / 软链接逃逸'}")
    print(f"  {'网络':<10}{'全断':<12}{'外传数据 / 访问云元数据 / 打内网'}")
    print(f"  {'执行':<10}{'禁止':<12}{'任意代码执行 / 管道串联'}")
    print(f"  {'资源':<10}{'有时限':<12}{'无限输出 / 死循环 / 内存炸弹'}")
    print()
    print("  ⚠️ 应用层能做的是『挡住明显的错误』。")
    print("     真正的隔离靠容器：只读挂载、--network=none、非 root、cgroup 限额。")
    print("     下一级给出可直接用的 Docker 沙箱脚本。")

    print("\n" + "=" * 84)
    print("结论")
    print("=" * 84)
    print("  边界不是一道门，是四个方向的围墙。缺任何一个方向，")
    print("  其他三个都白做 —— 因为攻击者只需要一个出口。")


if __name__ == "__main__":
    main()
