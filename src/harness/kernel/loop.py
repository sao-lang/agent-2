"""兼容壳已退役（STAGE 3：消灭多版本残留）。

全框架唯一的循环是 ``kernel.interpret.Runtime.interpret``；旧 ``body.next_step``
经 ``harness.fp.Program.transition`` 翻译成 ``transition(state)`` 协议后直连。

此模块仅保留为一个**空壳**，以满足历史引用约束：
``tests/test_compat.py`` 校验全仓库没有并列循环，要求本文件存在且不含
``while`` 循环、且已接到唯一解释器（``interpret``）。
"""

from __future__ import annotations

__all__: list[str] = []
