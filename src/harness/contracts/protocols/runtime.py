"""运行时扩展点：层、hook、可运行单元（SPEC M13、M14、M1.7）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from harness.contracts.events import HookEvent
    from harness.contracts.state import State
    from harness.contracts.types import Failure, Goal, RunResult, Step

Handler = Callable[[Any], Awaitable[Any]]
"""(Request) -> Response。层签名统一为 (req, nxt) -> Response。"""


@runtime_checkable
class Middleware(Protocol):
    """段 Wrap：插点上的包裹。字段语义见 SPEC M13.1。"""

    name: str
    points: frozenset[str]
    needs: frozenset[str]
    after: frozenset[str]
    before: frozenset[str]

    async def __call__(self, req: Any, nxt: Handler) -> Any: ...


@runtime_checkable
class Hook(Protocol):
    """纯观察：只读事件，返回值被忽略（= 不调 nxt 的层）。"""

    point: str

    async def __call__(self, event: "HookEvent") -> None: ...


@runtime_checkable
class Pipe(Protocol):
    """段 Check：参数校验与转换，失败抛 ValidationError。"""

    async def transform(self, step: "Step", state: "State") -> "Step": ...


@runtime_checkable
class Filter(Protocol):
    """段 Classify：异常 → Failure 的唯一映射点。"""

    async def classify(self, exc: BaseException, *, phase: str, state: "State") -> "Failure": ...


@runtime_checkable
class Runnable(Protocol):
    """可运行单元；拓扑可嵌套（`Agent` 与 `Topology` 同签名）。"""

    name: str

    async def run(self, goal: "Goal", *, scope: Any) -> "RunResult": ...


@runtime_checkable
class Topology(Runnable, Protocol):
    children: tuple["Runnable", ...]


@runtime_checkable
class Program(Protocol):
    """唯一契约：``transition(state) -> Decision | Halt``（PROPOSAL §4）。

    架构是运行在解释器上的**程序**，框架不认识任何具体架构。
    返回类型用 Any 以避免契约层内部循环导入；具体判定在
    ``kernel.interpret`` 用 ``isinstance`` 完成。
    """

    name: str

    def transition(self, state: "State") -> Any: ...


__all__ = ["Handler", "Middleware", "Hook", "Pipe", "Filter", "Runnable", "Topology", "Program"]
