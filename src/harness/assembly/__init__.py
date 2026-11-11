"""装配层（SPEC M15）：配置校验、spec 解析、Harness、预设。"""

from harness.assembly.config import (
    LAYER_FACTORIES,
    BackendSpec,
    HarnessConfig,
    StoreSpec,
    build_harness,
    validate,
    validate_layers,
)
from harness.assembly.harness import Harness
from harness.assembly.registry import (
    BACKENDS,
    GUARDRAILS,
    MODELS,
    PROGRAMS,
    STORE_SLOTS,
    parse_spec,
    register_program,
    resolve,
)

__all__ = [
    "Harness",
    "HarnessConfig",
    "StoreSpec",
    "BackendSpec",
    "build_harness",
    "validate",
    "validate_layers",
    "LAYER_FACTORIES",
    "parse_spec",
    "resolve",
    "MODELS",
    "BACKENDS",
    "STORE_SLOTS",
    "GUARDRAILS",
    "PROGRAMS",
    "register_program",
]
