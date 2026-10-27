"""网络边界：出站请求允许去哪。

不联网。真实系统在这一步要做 DNS 解析，示例把解析器做成可注入的参数，
用一张固定地址表代替 socket.getaddrinfo —— 这样同一份判定逻辑离线可跑，
也说明了为什么解析必须注入：判定要能在不联网的情况下被测。
"""

from __future__ import annotations

import ipaddress
from typing import Callable
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"https"}
ALLOWED_SUFFIXES = (".example.com",)

# 明确不允许去的地方：内网、回环、链路本地（云元数据地址就在这一段）
BLOCKED_NETS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10",
    "::1/128", "fc00::/7",
)]


def parse_host(host: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address | str, str]:
    """把主机写成 IP 的几种形式都归成 IP；其余当域名。"""
    h = host.strip("[]")                      # [::1] -> ::1
    try:
        return ipaddress.ip_address(h), "ip"
    except ValueError:
        pass
    if h.isdigit():                           # 十进制整数形式的 IPv4
        return ipaddress.ip_address(int(h)), "ip"
    return h.lower(), "name"


def ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    for net in BLOCKED_NETS:
        if net.version == ip.version and ip in net:
            return f"地址在禁止段 {net}"
    return None


def check_url(url: str, resolve: Callable[[str], list[str]]) -> str | None:
    """返回 None 表示放行，否则返回拒绝原因。"""
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        return f"协议不允许：{parts.scheme or '（空）'}"
    if "@" in parts.netloc:
        return "netloc 含 userinfo，前面的域名不是真正的主机"
    host = parts.hostname or ""
    if not host:
        return "没有主机名"

    parsed, kind = parse_host(host)
    if kind == "ip":
        return ip_blocked(parsed)

    if not host.endswith(ALLOWED_SUFFIXES):
        return f"域名不在白名单：{host}"

    # 域名过了白名单还不算完：它解析出来的地址才决定实际去哪里
    addrs = resolve(host)
    if not addrs:
        return "解析失败（按拒绝处理）"
    for a in addrs:
        why = ip_blocked(ipaddress.ip_address(a))
        if why:
            return f"{host} 解析到 {a}：{why}"
    return None


# 演示用的解析表（真实系统换成 socket.getaddrinfo，其余不变）
FAKE_DNS = {
    "api.example.com": ["93.184.216.34"],
    "intra.example.com": ["10.0.0.7"],
    "rebind.example.com": ["169.254.169.254"],
}


def resolve(host: str) -> list[str]:
    return FAKE_DNS.get(host, [])


CASES = [
    "https://api.example.com/v1/orders",
    "http://api.example.com/v1/orders",
    "https://intra.example.com/x",
    "https://169.254.169.254/latest/meta-data/",
    "https://2852039166/latest/meta-data/",
    "https://api.example.com@evil.com/x",
    "https://api.example.com.evil.com/x",
    "HTTPS://api.example.com/v1/orders",
    "https://rebind.example.com/x",
    "https://unknown.example.com/x",
]


def main() -> None:
    print("=== 1. 逐条判定（解析器是注入的固定表，不是真实 DNS）===")
    for url in CASES:
        why = check_url(url, resolve)
        print(f"  {url}")
        print(f"    {'放行' if why is None else '拒绝：' + why}")

    print()
    print("=== 2. 朴素的字符串检查在哪几条上与解析后判定不一致 ===")
    for url in CASES:
        naive = url.startswith("https://api.example.com")
        strict = check_url(url, resolve) is None
        if naive != strict:
            kind = "漏放" if naive else "误伤"
            print(f"  {kind}  {url}")
            print(f"    字符串前缀：{'放行' if naive else '拒绝'}   "
                  f"解析后判定：{'放行' if strict else '拒绝'}")
    print("  <- 两条漏放（userinfo 伪装、后缀追加），一条误伤（大写协议头）")


if __name__ == "__main__":
    main()
