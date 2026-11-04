"""架构约束的可执行版本（SPEC §3.3）。

规则：只向内，不向上。
    contracts  ← 谁都不准 import harness
    kernel     → contracts
    parts      → contracts + parts（同层允许，禁止成环）
    impl       → contracts + impl
    assembly   → 任意层
    fp         → contracts + parts + assembly
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "harness"

ALLOWED: dict[str, set[str]] = {
    "contracts": {"contracts"},
    "kernel": {"contracts", "kernel"},
    "parts": {"contracts", "parts"},
    "impl": {"contracts", "impl"},
    "assembly": {"contracts", "kernel", "parts", "impl", "assembly"},
    "fp": {"contracts", "parts", "assembly", "fp"},
    "adapters": {"contracts", "kernel", "parts", "impl", "assembly", "adapters"},
}


def _layer(path: Path) -> str | None:
    rel = path.relative_to(PKG)
    return None if len(rel.parts) == 1 else rel.parts[0]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
        elif isinstance(node, ast.Import):
            found.extend(a.name for a in node.names)
    return found


class ArchitectureTest(unittest.TestCase):
    def test_layers_exist(self):
        for layer in ("contracts", "kernel", "parts", "impl", "assembly"):
            self.assertTrue((PKG / layer).is_dir(), f"缺少分层目录：{layer}")

    def test_dependency_direction(self):
        violations: list[str] = []
        for path in PKG.rglob("*.py"):
            layer = _layer(path)
            if layer not in ALLOWED:
                continue
            for module in _imports(path):
                if not module.startswith("harness."):
                    continue
                target = module.split(".")[1]
                if target not in ALLOWED[layer]:
                    violations.append(f"{path.relative_to(PKG)} -> {module}")
        self.assertFalse(violations, "越界依赖：\n" + "\n".join(violations))

    def test_contracts_zero_dependency(self):
        """契约层零依赖：只允许标准库与自身。"""
        stdlib = set(sys.stdlib_module_names)
        bad: list[str] = []
        for path in (PKG / "contracts").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                mods: list[str] = []
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    mods.append(node.module)
                elif isinstance(node, ast.Import):
                    mods.extend(a.name for a in node.names)
                for m in mods:
                    root = m.split(".")[0]
                    if root == "harness" or root in stdlib:
                        continue
                    bad.append(f"{path.name}: {m}")
        self.assertFalse(bad, "契约层引入了第三方依赖：\n" + "\n".join(bad))

    def test_no_cross_layer_cycle(self):
        graph: dict[str, set[str]] = {k: set() for k in ALLOWED}
        for path in PKG.rglob("*.py"):
            layer = _layer(path)
            if layer not in ALLOWED:
                continue
            for module in _imports(path):
                if module.startswith("harness."):
                    target = module.split(".")[1]
                    if target != layer and target in ALLOWED:
                        graph[layer].add(target)
        for a, targets in graph.items():
            for b in targets:
                self.assertNotIn(a, graph[b], f"层间成环：{a} <-> {b}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
