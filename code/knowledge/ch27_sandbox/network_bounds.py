"""网络边界的判定：协议、主机名字面、解析出来的地址。

运行：python code/knowledge/ch27_sandbox/network_bounds.py
解析器是注入的固定表，不发真实 DNS 查询，也不发真实请求。
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"https"}
ALLOWED_SUFFIXES = (".example.com",)

# 注入的解析表：主机名 -> 地址列表。真实系统换成 socket.getaddrinfo。
RESOLVE_TABLE = {
    "api.example.com": ["93.184.216.34"],
    "intra.example.com": ["10.0.0.7"],
    "rebind.example.com": ["169.254.169.254"],
    "unknown.example.com": [],
}


def ip_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if addr.is_loopback:
        return f"地址是回环：{addr}"
    if addr.is_link_local:
        return f"地址是链路本地：{addr}"
    if addr.is_private:
        return f"地址是私有地址：{addr}"
    if addr.is_reserved or addr.is_multicast or addr.is_unspecified:
        return f"地址是保留段：{addr}"
    return None


def parse_host(host: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address | str, str]:
    """返回 (地址或主机名, "ip" | "name")。十进制整数形式按 IPv4 处理。"""
    if host.isdigit():
        return ipaddress.ip_address(int(host)), "ip"
    try:
        return ipaddress.ip_address(host), "ip"
    except ValueError:
        return host, "name"


def check_url(url: str) -> str | None:
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
    addrs = RESOLVE_TABLE.get(host, [])
    if not addrs:
        return "解析失败（按拒绝处理）"
    for a in addrs:
        why = ip_blocked(ipaddress.ip_address(a))
        if why:
            return f"{host} 解析到 {a}：{why}"
    return None


ATTEMPTS = [
    "https://api.example.com/v1/orders",
    "http://api.example.com/v1/orders",
    "https://intra.example.com/x",
    "https://169.254.169.254/latest/meta-data/",
    "https://2852039166/latest/meta-data/",
    "https://[::1]/latest/meta-data/",
    "https://api.example.com@evil.com/x",
    "https://api.example.com.evil.com/x",
    "https://rebind.example.com/x",
    "https://unknown.example.com/x",
]


def main() -> None:
    print("=== 逐条判定（解析器是注入的固定表，不是真实 DNS）===")
    refused = 0
    for url in ATTEMPTS:
        why = check_url(url)
        if why is None:
            print(f"  {url}")
            print("    放行")
        else:
            refused += 1
            print(f"  {url}")
            print(f"    拒绝：{why}")
    print()
    print(f"=== {len(ATTEMPTS)} 条里放行 {len(ATTEMPTS) - refused} 条，拒绝 {refused} 条 ===")
    print("  <- 放行的那条解析到 93.184.216.34；其余每一条都是一个独立的主机位置")


if __name__ == "__main__":
    main()
