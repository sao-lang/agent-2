"""第 8 章配套入口（转发到 learn/mini_agent/run.py）。

mini_agent 是跟着全书生长的主线，不属于某一章，所以拆开后放在 learn/ 下：

    learn/mini_agent/run.py          装配入口、可改常量、CLI、兼容门面
    learn/mini_agent/core/           循环 / 分派 / 守卫 / 状态（干净核心）
    learn/mini_agent/demo/orders/    示例 1：电商退货客服（可整体换掉）
    learn/mini_agent/regression.py   离线验收脚本（改动后跑，不花 key）

本文件只保留章节目录里的旧入口，让下面两条命令仍然可用（正文与旧脚本不用改）：

    python code/knowledge/ch08_runaway/mini_agent.py
    python code/knowledge/ch08_runaway/mini_agent.py --base-url http://127.0.0.1:8899/v1 --api-key sk-mock

验证手册 REPL 里的 m.Answer / m.fingerprint / m.trim_tool_content / m.CLAUSE_TEXT
也照旧可取。**读代码请去 learn/mini_agent/run.py**，这里没有逻辑。
"""

from __future__ import annotations

import sys
from pathlib import Path

_LEARN = Path(__file__).resolve().parents[3] / "learn" / "mini_agent"
if str(_LEARN) not in sys.path:
    sys.path.insert(0, str(_LEARN))

from run import *        # noqa: F401,F403  —— 转发全部门面名字
from run import main     # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
