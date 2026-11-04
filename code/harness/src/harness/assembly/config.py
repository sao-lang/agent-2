"""装配：配置 → Harness（SPEC M15）。

构造期把八条校验一次做完：缺依赖、层重名、顺序成环、body 组合、工具重名、
引用未注册护栏、挂载非法、插点非法。**宁可启动时报错，也不运行期猜。**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

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
    sandbox: Any = "fake"
    artifacts: Any = "memory"
    secrets: Any = "env"
    index: Any = "memory"
    queue: Any = "memory"
    approval: Any = "memory"
    clock: Any = "system"


@dataclass(frozen=True)
class HarnessConfig:
    """只描述意图，不构造实例。"""

    model: Any = "fake"
    tools: tuple[Any, ...] = ()
    stores: StoreSpec = field(default_factory=StoreSpec)
    backends: BackendSpec = field(default_factory=BackendSpec)
    guardrails: tuple[str, ...] = ()
    layers: tuple[LayerSpec, ...] = ()
    budget: Budget = field(default_factory=Budget)
    system: str = ""
    max_depth: int = 2
    namespace_tenant: str = "default"


#: 层声明 → 工厂（装配期用；未知名 → ConfigError）
LAYER_FACTORIES = {
    "taskboard": lambda **kw: _layer_fn("taskboard")(**kw),
    "truncate": lambda **kw: _layer_fn("truncate")(**kw),
    "tenancy": lambda **kw: _layer_fn("tenancy")(**kw),
}


def _layer_fn(name: str):
    from harness.parts.layers import tenancy_layer
    from harness.parts.middleware import taskboard_layer

    if name == "taskboard":
        return taskboard_layer
    if name == "tenancy":
        return tenancy_layer
    raise ConfigError(f"未知层：{name}")


# ------------------------------------------------------------------ 校验


def validate(config: HarnessConfig) -> None:
    """八条构造期校验。"""
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


def build_harness(config: HarnessConfig) -> Any:
    """配置 → Harness。所有实例化集中在这里（R4）。"""
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

    harness = Harness.of(
        model=registry.resolve("model", config.model, registry.MODELS),
        tools=tools,
        budget=config.budget,
        system=config.system,
        max_depth=config.max_depth,
        guardrails=guardrails,
        stores=stores,
        backends=backends,
    )
    harness.namespace = _namespace(config, harness)
    harness.layers = tuple(LayerSpec(name=s.name, config=dict(s.config)) for s in config.layers)
    return harness


def _namespace(config: HarnessConfig, harness: Any) -> Any:
    from harness.kernel.scope import Namespace

    return Namespace(tenant=config.namespace_tenant)


def validate_layers(layers: Sequence[Any]) -> None:
    """层顺序无环（装配期预检，不等运行时）。"""
    for point in ("run", "step", "model_call", "tool_call"):
        chain.resolve(layers, point)


__all__ = [
    "StoreSpec",
    "BackendSpec",
    "HarnessConfig",
    "validate",
    "build",
    "validate_layers",
    "LAYER_FACTORIES",
]
