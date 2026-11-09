"""通用解释器方案 · 可运行样张（不接入 src/harness）。

运行：
    cd code/harness
    PYTHONPATH=. python -m proposals.demo
"""

from proposals.contracts import Decision, Effect, Halt, Layer, State
from proposals.interpreter import Limits, Runtime

__all__ = ["State", "Effect", "Decision", "Halt", "Layer", "Runtime", "Limits"]
