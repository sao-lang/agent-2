"""第 41 章 step3：镜像分层与健康检查 —— 用"真跑一遍模拟构建"算出三种写法的代价。

运行：
    python code/ch42_integration/step3_docker.py

为什么不在脚本里调 docker？
因为绝大多数读者（包括写这本书时）手边不一定有 Docker Desktop，
而"分层为什么会变慢"这件事**完全可以用纯 Python 模拟出来**，而且数字更可控。
真实 Dockerfile 在 examples/full-stack/ 里，那部分需要 docker 才能跑。

模拟的三个模型：
  · 层缓存：某一层的输入 hash 变了 → 这一层和它之后所有层都要重建
  · 镜像大小：每层新增的字节累加（安装包只进镜像一次）
  · 健康检查：依赖服务就绪前，Agent 进程启动会失败
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ================================================================ 镜像层模型
@dataclass
class Layer:
    name: str
    # 这一层"新增"的字节数（真实 Docker 里是 diff 层的大小）
    size_bytes: int
    # 这一层"读取"的输入——任何一个变了就要重建这一层以及之后所有层
    inputs: tuple[str, ...] = ()
    build_seconds: float = 1.0
    cached: bool | None = None


def build(layers: list[Layer], changed: set[str], verbose: bool = False) -> tuple[float, int]:
    """返回 (构建耗时秒, 镜像总字节)。changed 里的 key 表示"这次改了什么"。"""
    total_s = 0.0
    total_b = 0
    invalid_from = len(layers)
    for i, ly in enumerate(layers):
        hit = not any(k in changed for k in ly.inputs)
        # 一旦某层失效，后面全部失效（这是 Docker 最容易被忽视的规则）
        if not hit:
            invalid_from = min(invalid_from, i)
        ly.cached = i < invalid_from
        if not ly.cached:
            total_s += ly.build_seconds
        total_b += ly.size_bytes
        if verbose:
            print(f"      {'CACHED' if ly.cached else 'REBUILD'}  {ly.name:<28} {ly.size_bytes / 1e6:>7.1f} MB")
    return total_s, total_b


def mb(n: int) -> str:
    return f"{n / 1e6:.0f} MB"


# ================================================================ 三种 Dockerfile 写法
def bad_layers() -> list[Layer]:
    """写法 A（新手最常见）：一次性 COPY 全部，再装依赖。"""
    return [
        Layer("FROM python:3.12", 150_000_000, ()),
        Layer("COPY . /app", 2_000_000, ("src",)),
        Layer("RUN pip install -r req.txt", 620_000_000, ("src",), 95.0),
    ]


def ok_layers() -> list[Layer]:
    """写法 B：先 COPY requirements.txt 装依赖，再 COPY 源码。"""
    return [
        Layer("FROM python:3.12", 150_000_000, ()),
        Layer("COPY requirements.txt", 1_200, ("req",)),
        Layer("RUN pip install -r req.txt", 620_000_000, ("req",), 95.0),
        Layer("COPY . /app", 2_000_000, ("src",)),
    ]


def best_layers() -> list[Layer]:
    """写法 C：多阶段构建 + slim 基础镜像 + 只拷产物。

    · builder 阶段装编译器，runtime 阶段只留 site-packages
    · pip cache 在 runtime 层清掉
    """
    return [
        Layer("FROM python:3.12-slim", 45_000_000, ()),
        Layer("COPY requirements.txt", 1_200, ("req",)),
        Layer("RUN pip install --prefix=/install", 560_000_000, ("req",), 95.0),
        Layer("COPY --from=builder /install", 240_000_000, ("req",), 3.0),
        Layer("COPY . /app", 2_000_000, ("src",)),
        Layer("RUN rm -rf /install/*.dist-info & clear", 0, ("req",), 1.0),
    ]


def merged_layers() -> list[Layer]:
    """写法 C'：多阶段 + slim + **合并 COPY --from 与收尾**。

    对照 C 你就明白了：`COPY --from=builder /install` 和 `RUN rm ...`
    分成两层 → docker 为同一个 240MB 目录打两次快照，镜像反而更大。
    合成一层后才真正瘦下来。
    """
    return [
        Layer("FROM python:3.12-slim", 45_000_000, ()),
        Layer("COPY requirements.txt", 1_200, ("req",)),
        Layer("RUN pip install --prefix=/install (builder)", 560_000_000, ("req",), 95.0),
        Layer("COPY --from=builder + rm caches", 122_000_000, ("req",), 4.0),
        Layer("COPY app /app", 2_000_000, ("src",)),
    ]


def demo_layers() -> None:
    print("① 镜像分层：改一行 Python 代码要等多久")
    print()

    # 注：多层 COPY 会让 docker 对同一个 240MB 目录打两次快照 → 镜像反而更大。
    # 正确写法是把 install 和 COPY --from 合成一层（见 examples/full-stack/Dockerfile）。
    variants = [
        ("A 一次性 COPY", bad_layers()),
        ("B 先装依赖", ok_layers()),
        ("C 多阶段（层写错）", best_layers()),
        ("C' 多阶段（合并层）", merged_layers()),
    ]
    for label, layers in variants:
        s, b = build(layers, changed={"src"})
        print(f"   {label:<20} 改源码后重建 {s:>6.1f}s   镜像 {mb(b):>8}")

    # 对照真实尺寸：很多人镜像 1.9GB 是因为同时装了 torch + 把模型打进镜像
    _, naive_b = build(bad_layers(), changed=set())
    _, best_b = build(merged_layers(), changed=set())
    real_naive = naive_b + 900_000_000 + 250_000_000  # torch + 模型文件
    print()
    print(f"   典型新手镜像 {mb(real_naive)}（含 torch 900MB + 模型 250MB）→ {mb(best_b)}："
          f"砍掉 {(1 - best_b / real_naive) * 100:.0f}%")
    print(f"   只算 Python 依赖这一层：{mb(naive_b)} → {mb(best_b)}，砍掉 {(1 - best_b / naive_b) * 100:.0f}%")
    print()
    print("   逐层明细（写法 B，改源码）：")
    build(ok_layers(), changed={"src"}, verbose=True)
    print()
    print("   逐层明细（写法 A，改源码）：")
    build(bad_layers(), changed={"src"}, verbose=True)
    print()

    print("   💥 失败实验：把 .env 也 COPY 进去")
    print("   · .env 里的密钥被烘焙进镜像层 → docker history 能看到明文")
    layers = ok_layers() + [Layer("COPY .env /app/.env", 800, ("env",))]
    build(layers, changed=set(), verbose=True)
    print("   · 就算后来删掉（RUN rm .env），旧层还在 —— 镜像里能捞回来")
    print()


def demo_size_breakdown() -> None:
    print("② 镜像为什么 2 GB：把体积算给你看")
    items = [
        ("python:3.12 基础镜像", 150_000_000),
        ("pip 装的所有依赖", 620_000_000),
        ("torch（如果你不小心装了 CPU 版）", 900_000_000),
        ("模型文件误打进镜像", 250_000_000),
        ("源码与静态资源", 2_000_000),
    ]
    total = sum(s for _, s in items)
    for name, s in items:
        print(f"   {name:<34}{s / 1e6:>7.0f} MB  {s / total * 100:>5.1f}%")
    print(f"   {'合计':<34}{total / 1e6:>7.0f} MB")
    print()
    print("   → 前三项占 87%。能砍的：slim 基础镜像、去掉 torch（不需要就别装）、")
    print("     模型文件用 volume 挂载或启动时下载")
    print()


# ================================================================ 健康检查
@dataclass
class Service:
    name: str
    boot_seconds: float
    healthy_after: float = 0.0
    started_at: float | None = None
    state: str = "pending"
    log: list[str] = field(default_factory=list)


def demo_healthcheck() -> None:
    print("③ 健康检查：depends_on 只保证「容器起来了」，不保证「能用了」")
    db = Service("postgres", boot_seconds=0.0, healthy_after=2.0)
    # postgres 容器 1.0 秒就 "running"，但真正能接受连接要 2.0 秒
    db.started_at = 0.0
    db.state = "running"

    agent_boot = 0.0  # Agent 启动时立刻要连 DB 建表
    t = agent_boot
    print(f"   t=0.0s  docker compose up：postgres 容器状态 = {db.state}")
    print(f"   t={t:.1f}s  agent 启动 → 尝试连 DB 建表")
    if t < db.healthy_after:
        print(f"   t={t:.1f}s  ❌ 连接被拒（DB 还要 {(db.healthy_after - t):.1f}s 才能接受连接）")
        print("           容器退出 → depends_on 默认不会重试 → 整个服务起不来")
    print()
    print("   修法一：healthcheck + condition: service_healthy")
    print("           agent 会等到 pg_isready 成功才启动")
    print("   修法二：agent 内部重试（更稳，因为 DB 也可能中途重启）")
    print()

    # 重试版本
    attempts = 0
    t = 0.0
    while t < 5.0:
        attempts += 1
        if t >= db.healthy_after:
            print(f"   重试版：第 {attempts} 次（t={t:.1f}s）连接成功 ✅")
            break
        print(f"   重试版：第 {attempts} 次（t={t:.1f}s）失败，等 1s 再试")
        t += 1.0
    print()


def demo_graceful_shutdown() -> None:
    print("④ 优雅关闭：SIGTERM 时 Agent 手里有任务怎么办")
    print("   docker stop 默认等 10 秒然后 SIGKILL。")
    print("   如果一个长任务要跑 40 秒：")
    for strategy, result in [
        ("直接退出", "任务丢了，且没有 checkpoint → 用户重跑要重头再来"),
        ("等 10 秒（默认）", "被 SIGKILL，同上"),
        ("收到 SIGTERM 后写 checkpoint，然后退出", "重启后从 checkpoint 续跑，用户无感"),
        ("收到 SIGTERM 后拒新请求 + 等当前任务（stop_grace_period: 60s）", "任务完整跑完"),
    ]:
        print(f"   · {strategy:<48} → {result}")
    print()


def main() -> None:
    demo_layers()
    demo_size_breakdown()
    demo_healthcheck()
    demo_graceful_shutdown()


if __name__ == "__main__":
    main()
