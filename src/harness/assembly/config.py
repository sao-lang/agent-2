"""装配：配置 → Harness（SPEC M15）。

构造期把校验一次做完：缺依赖、层重名、顺序成环、body 组合、工具重名、
引用未注册护栏、挂载非法、插点非法。声明的层在装配期实例化，运行期并入
program —— 不再只保存 `LayerSpec` 声明数据。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from harness.assembly import registry
from harness.contracts.errors import ConfigError
from harness.contracts.types import Budget, LayerSpec
from harness.kernel import chain


@dataclass(frozen=True)
class StoreSpec:
    """五个存储各一个槽，互不牵连（换记忆介质只改一行）。"""

    durability: Any = "memory"
    session: Any = "memory"
    messages: Any = "memory"
    memory: Any = "memory"
    idempotency: Any = "memory"


@dataclass(frozen=True)
class BackendSpec:
    """八个执行/供应后端各一个槽。"""

    fs: Any = "memory"
    sandbox: Any = "local"
    artifacts: Any = "memory"
    secrets: Any = "env"
    index: Any = "memory"
    queue: Any = "memory"
    approval: Any = "memory"
    clock: Any = "system"


@dataclass(frozen=True)
class HarnessConfig:
    """只描述意图，不构造实例。"""

    #: None = 不注入模型（合法：纯计算/工作流程序；model 效应运行期显式报错）。
    model: Any = None
    tools: tuple[Any, ...] = ()
    stores: StoreSpec = field(default_factory=StoreSpec)
    backends: BackendSpec = field(default_factory=BackendSpec)
    guardrails: tuple[str, ...] = ()
    layers: tuple[LayerSpec, ...] = ()
    budget: Budget = field(default_factory=Budget)
    system: str = ""
    max_depth: int = 2
    namespace_tenant: str = "default"
    #: 全局终止护栏：任何程序都必须能停下来。
    max_transitions: int = 64
    # ---- 接线槽位：原先没有配置入口，导致 Guard / Pipe / Filter /
    #      事件出口 / 精确计数器 / 检查点存储 / 反射器只能手工改对象 ----
    guard: Any = None
    pipes: tuple[Any, ...] = ()
    filter: Any = None
    sink: Any = None
    sinks: tuple[Any, ...] = ()
    token_counter: Any = None
    checkpoint_store: Any = None
    reflector: Any = None
    #: 具名程序，经 registry.PROGRAMS 解析（消费程序注册表）。
    program: str = ""
    #: 通用存储名，经 registry.STORES 解析（消费存储注册表）。
    store: str = ""


def build_layer(name: str, **config: Any) -> Any:
    """唯一的层实例化入口：装配期与 `Program.from_spec` 共用同一张工厂表。"""
    factory = _layer_fn(name)
    allowed = _accepted_kwargs(factory)
    kwargs = config if allowed is None else {k: v for k, v in config.items() if k in allowed}
    return factory(**kwargs)


#: 层声明 → 工厂（**唯一**的层工厂表；装配期调用，Program.from_spec 复用）。
LAYER_FACTORIES = {
    "taskboard": lambda **kw: build_layer("taskboard", **kw),
    "truncate": lambda **kw: build_layer("truncate", **kw),
    "tenancy": lambda **kw: build_layer("tenancy", **kw),
    "budget": lambda **kw: build_layer("budget", **kw),
    "trace": lambda **kw: build_layer("trace", **kw),
    "checkpoint": lambda **kw: build_layer("checkpoint", **kw),
    "approval": lambda **kw: build_layer("approval", **kw),
    "idempotency": lambda **kw: build_layer("idempotency", **kw),
    "validate": lambda **kw: build_layer("validate", **kw),
    "context": lambda **kw: build_layer("context", **kw),
    "audit": lambda **kw: build_layer("audit", **kw),
    "retrieval": lambda **kw: build_layer("retrieval", **kw),
    "memory_recall": lambda **kw: build_layer("memory_recall", **kw),
    "memory_write": lambda **kw: build_layer("memory_write", **kw),
    "input_guard": lambda **kw: build_layer("input_guard", **kw),
    "output_guard": lambda **kw: build_layer("output_guard", **kw),
}


def _layer_fn(name: str) -> Callable[..., Any]:
    """按名字取层工厂；局部 import 避免装配期成环。"""
    from harness.parts.capability import truncate_layer
    from harness.parts.guardrail import input_guard_layer, output_guard_layer
    from harness.parts.layers import (
        audit_layer,
        memory_recall_layer,
        memory_write_layer,
        retrieval_layer,
        tenancy_layer,
    )
    from harness.parts.middleware import (
        approval_layer,
        budget_layer,
        checkpoint_layer,
        context_layer,
        idempotency_layer,
        taskboard_layer,
        trace_layer,
        validate_layer,
    )

    table: dict[str, Callable[..., Any]] = {
        "taskboard": taskboard_layer,
        "truncate": truncate_layer,
        "tenancy": tenancy_layer,
        "budget": budget_layer,
        "trace": trace_layer,
        "checkpoint": checkpoint_layer,
        "approval": approval_layer,
        "idempotency": idempotency_layer,
        "validate": validate_layer,
        "context": context_layer,
        "audit": audit_layer,
        "retrieval": retrieval_layer,
        "memory_recall": memory_recall_layer,
        "memory_write": memory_write_layer,
        "input_guard": input_guard_layer,
        "output_guard": output_guard_layer,
    }
    if name not in table:
        raise ConfigError(f"未知层：{name}；可用：{sorted(table)}")
    return table[name]


class _NullSink:
    """声明了观测层但未配置 sink 时的空出口（观测失败不得影响运行）。"""

    async def emit(self, event: Any) -> None:
        return None


def _accepted_kwargs(fn: Callable[..., Any]) -> set[str] | None:
    """返回工厂可接受的关键字名；有 **kwargs 时返回 None（全部接受）。"""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):  # pragma: no cover - 内置可调用对象
        return None
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
        return None
    return {p.name for p in params}


# ------------------------------------------------------------------ 校验


def validate(config: HarnessConfig) -> None:
    """构造期校验。"""
    # 1 挂载点
    for slot, spec in _backend_items(config.backends):
        if slot == "fs":
            name, arg, extra = registry.parse_spec(spec, kind="fs")
            if name == "local" and not arg:
                raise ConfigError("fs=local 必须给路径：fs='local:/work'")
    # 2 护栏已注册
    for name in config.guardrails:
        if name not in registry.GUARDRAILS:
            raise ConfigError(f"未知护栏：{name}；可用：{sorted(registry.GUARDRAILS)}")
    # 3 工具名唯一
    names = [getattr(t, "__name__", getattr(getattr(t, "spec", None), "name", str(t)))
             for t in config.tools]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ConfigError(f"工具重名：{sorted(dupes)}")
    # 4 层声明合法
    for layer_spec in config.layers:
        if layer_spec.name not in LAYER_FACTORIES:
            raise ConfigError(f"未知层：{layer_spec.name}；可用：{sorted(LAYER_FACTORIES)}")
    # 5 存储/后端可解析
    for slot, spec in _store_items(config.stores):
        registry.resolve(slot, spec, registry.STORE_SLOTS[slot])
    for slot, spec in _backend_items(config.backends):
        registry.resolve(slot, spec, registry.BACKENDS[slot])
    # 6 预算非负
    if config.budget.tokens <= 0 or config.budget.calls <= 0:
        raise ConfigError("预算必须为正数")
    # 7 深度合法
    if config.max_depth < 0:
        raise ConfigError("max_depth 不能为负")
    # 8 命名空间非空
    if not config.namespace_tenant:
        raise ConfigError("namespace_tenant 不能为空")
    # 9 解释器全局终止护栏必须为正
    if config.max_transitions <= 0:
        raise ConfigError("max_transitions 必须为正数")
    # 10 具名程序与通用存储必须已注册（两个注册表都要有消费方）
    if config.program and config.program not in registry.PROGRAMS:
        raise ConfigError(f"未知程序：{config.program}；可用：{sorted(registry.PROGRAMS)}")
    if config.store and config.store not in registry.STORES:
        raise ConfigError(f"未知存储：{config.store}；可用：{sorted(registry.STORES)}")


def _store_items(stores: StoreSpec) -> Iterable[tuple[str, Any]]:
    return [
        ("durability", stores.durability),
        ("session", stores.session),
        ("messages", stores.messages),
        ("memory", stores.memory),
        ("idempotency", stores.idempotency),
    ]


def _backend_items(backends: BackendSpec) -> Iterable[tuple[str, Any]]:
    return [
        ("fs", backends.fs),
        ("sandbox", backends.sandbox),
        ("artifacts", backends.artifacts),
        ("secrets", backends.secrets),
        ("index", backends.index),
        ("queue", backends.queue),
        ("approval", backends.approval),
        ("clock", backends.clock),
    ]


# ------------------------------------------------------------------ 构造


def _layer_context(config: HarnessConfig, harness: Any, guardrails: tuple,
                   stores: dict, backends: dict) -> dict[str, Any]:
    """声明层的默认能力注入：装配期把 Harness 持有的部件喂给工厂。"""
    return {
        "budget": config.budget,
        "sink": config.sink if config.sink is not None else _NullSink(),
        "store": stores.get("durability"),
        "artifacts": backends.get("artifacts"),
        "guardrails": guardrails,
        "reflector": config.reflector,
        "knowledge": backends.get("index"),
        "memory": stores.get("memory"),
        "channel": backends.get("approval"),
        "clock": backends.get("clock"),
        "ns": harness.namespace,
        "system": config.system,
        "expected_tenant": config.namespace_tenant,
    }


def _instantiate_layers(config: HarnessConfig, harness: Any, guardrails: tuple,
                        stores: dict, backends: dict) -> tuple[Any, ...]:
    """把 `LayerSpec` 声明变成真正的 `Layer` 实例（B01/B02/B04）。"""
    context = _layer_context(config, harness, guardrails, stores, backends)
    out: list[Any] = []
    for spec in config.layers:
        factory = _layer_fn(spec.name)
        merged = {**context, **dict(spec.config)}
        allowed = _accepted_kwargs(factory)
        kwargs = merged if allowed is None else {k: v for k, v in merged.items() if k in allowed}
        out.append(factory(**kwargs))
    return tuple(out)


def layers_from_specs(specs: Sequence[Any], **context: Any) -> tuple[Any, ...]:
    """`ProgramSpec.layers` → 运行形态；与装配期共用 `build_layer`。"""
    out: list[Any] = []
    for spec in specs:
        if spec.name not in LAYER_FACTORIES:
            raise ConfigError(f"未知层：{spec.name}；可用：{sorted(LAYER_FACTORIES)}")
        out.append(build_layer(spec.name, **{**context, **dict(spec.config)}))
    return tuple(out)


def build_harness(config: HarnessConfig) -> Any:
    """配置 → Harness。所有实例化集中在这里（R4）。

    测试替身不进框架包：离线测试请用 tests/support.py 的 FakeModel，
    经 ``harness.model = ...`` 注入或 ``Harness.of(model=...)`` 直构。
    """
    from harness.assembly.harness import Harness
    from harness.parts.tools import as_tool

    validate(config)

    tools = [as_tool(t) for t in config.tools]
    backends = {slot: registry.resolve(slot, spec, registry.BACKENDS[slot])
                for slot, spec in _backend_items(config.backends)}
    stores = {slot: registry.resolve(slot, spec, registry.STORE_SLOTS[slot])
              for slot, spec in _store_items(config.stores)}
    guardrails = tuple(registry.resolve("guardrail", name + "", registry.GUARDRAILS)
                       for name in config.guardrails)

    sinks = tuple(config.sinks) + ((config.sink,) if config.sink is not None else ())
    harness = Harness.of(
        model=(registry.resolve("model", config.model, registry.MODELS)
               if config.model is not None else None),
        tools=tools,
        budget=config.budget,
        system=config.system,
        max_depth=config.max_depth,
        guardrails=guardrails,
        stores=stores,
        backends=backends,
        max_transitions=config.max_transitions,
        guard=config.guard,
        pipes=tuple(config.pipes),
        filter=config.filter,
        sinks=sinks,
        token_counter=config.token_counter,
        checkpoint_store=config.checkpoint_store,
        reflector=config.reflector,
    )
    harness.namespace = _namespace(config, harness)
    harness.auto_layers = _auto_layers(config, harness, guardrails, stores)
    harness.layers = tuple(_instantiate_layers(config, harness, guardrails, stores, backends))
    # 装配期预检：层顺序成环 / 同插点重名，不再留到运行时。
    validate_layers(tuple(harness.auto_layers) + tuple(harness.layers))
    if config.program:
        harness.default_program = registry.resolve("program", config.program, registry.PROGRAMS)
    if config.store:
        harness.default_store = registry.resolve("store", config.store, registry.STORES)
    return harness


def _auto_layers(config: HarnessConfig, harness: Any, guardrails: tuple,
                 stores: dict) -> tuple:
    """由能力派生出该默认挂上的层；声明通道之外，能力自带层也在这里接线。"""
    layers: list[Any] = []
    if guardrails:
        from harness.parts.guardrail import input_guard_layer, output_guard_layer

        layers.append(input_guard_layer(guardrails=guardrails, sink=config.sink))
        layers.append(output_guard_layer(guardrails=guardrails, sink=config.sink))
    store = stores.get('durability')
    if store is not None:
        from harness.parts.middleware import checkpoint_layer

        layers.append(checkpoint_layer(store=store))
    if config.sink is not None:
        from harness.parts.layers import audit_layer
        from harness.parts.middleware import trace_layer

        layers.append(trace_layer(sink=config.sink, clock=harness.backends.get("clock")))
        layers.append(audit_layer(sink=config.sink))
    if config.reflector is not None:
        from harness.parts.middleware import validate_layer

        layers.append(validate_layer(reflector=config.reflector, budget=config.budget))
    return tuple(layers)


def _namespace(config: HarnessConfig, harness: Any) -> Any:
    from harness.kernel.scope import Namespace

    return Namespace(tenant=config.namespace_tenant)


def validate_layers(layers: Sequence[Any]) -> None:
    """层顺序无环（装配期预检，不等运行时）。遍历全部插点。"""
    for point in chain.POINTS:
        chain.resolve(layers, point)


__all__ = [
    "StoreSpec",
    "BackendSpec",
    "HarnessConfig",
    "validate",
    "validate_layers",
    "LAYER_FACTORIES",
]
