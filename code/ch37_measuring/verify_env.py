"""环境自检：跑通这个再往下学。

用法（在项目根目录）：
    python code/ch37_measuring/verify_env.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import get_settings, make_llm, usage_of  # noqa: E402


def main() -> int:
    s = get_settings()
    print(f"model      : {s.model}")
    print(f"base_url   : {s.base_url}")
    print(f"api_key    : {'已配置' if s.api_key not in ('missing', '') else '缺失'}")

    if s.api_key in ("missing", ""):
        print("\n❌ 请先把 .env-example 复制成 .env 并填入模型配置")
        return 1

    try:
        llm = make_llm()
        resp = llm.invoke("用一句话解释什么是 token。")
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ 调用失败：{type(e).__name__}: {e}")
        print("   常见原因：key 无效 / base_url 写错 / 网络不通 / .env 没被读到")
        return 1

    print(f"\n回复       : {resp.content[:80]}")
    print(f"用量       : {usage_of(resp)}")
    print("\n✅ 环境就绪")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
