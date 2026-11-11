#!/usr/bin/env python3
"""Harness 机械统计审计器（零第三方依赖，输出确定）。

复现统计：
    python tools/audit_harness.py
    python tools/audit_harness.py --json docs/harness/audit-report.json
校验快照是否仍与代码一致：
    python tools/audit_harness.py --check docs/harness/audit-report.json

设计约定（决定「完整」的边界，改这里就等于改口径）：
  * 文件集固定：CODE = src/harness/**/*.py；DOCS = docs/harness/*.md 且排除
    文件名以 AUDIT- 开头的审计报告自身；TESTS = tests/**/*.py。
  * 所有判据是本文件里的常量（正则 / AST 规则 / 锚点表 / 人工条目表），
    不含任何时间戳、随机数、模型判断或环境变量。
  * 输出 JSON 使用 sort_keys + 固定缩进，两次运行字节一致。
  * code_fingerprint 覆盖全部 CODE 文件，用于证明快照对应哪一份代码；
    代码一变，--check 会明确报「指纹变化」而不是笼统说数字不同。

能承诺什么：
  * 封闭域内的统计（文件、行数、正则命中、同名定义、悬空导出、占位标记、
    锚点命中）是穷尽且可复现的 —— 遍历全部文件，逐行可核对。
  * 不能承诺「框架所有功能断点都被找齐」。MANUAL_ITEMS 是人工判定的
    稳定索引，脚本只固定它的数量、分级与证据锚点有效性，不重算结论。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = ROOT / "src" / "harness"
DOCS_DIR = ROOT / "docs" / "harness"
TESTS_DIR = ROOT / "tests"
SNAPSHOT_DEFAULT = DOCS_DIR / "audit-report.json"

AUDIT_SPEC_VERSION = "1.4"

# ---------------------------------------------------------------- 口径常量

# 三档口径逐层扩展；全部大小写敏感，显式枚举，不用 IGNORECASE。
RE_STRICT = re.compile(r"\b(?:v|V)[123](?:\.\d+)?\b")
RE_WIDE = re.compile(r"\b(?:v|V)[123](?:\.\d+)?\b|legacy|Legacy|LEGACY")
RE_FULL = re.compile(
    r"\b(?:v|V)[123](?:\.\d+)?\b|legacy|Legacy|LEGACY"
    r"|兼容|SUPPLEMENT|M15|版本|version|Version|VERSION"
    r"|schema_version|SCHEMA_VERSION|contracts_version|__version__"
)
RE_V31 = re.compile(r"v3\.1|SUPPLEMENT")
RE_CONSTANT = re.compile(
    r"^\s*(?:__version__|contracts_version|SCHEMA_VERSION)\s*=\s*(.+?)\s*$"
    r"|^\s*name\s*=\s*[\"'](?:agent_v1|legacy)[\"']\s*$",
    re.MULTILINE,
)
RE_PLACEHOLDER = re.compile(r"TODO|FIXME|XXX|暂未|未接|待补|未实现")
RE_NOT_IMPL = re.compile(r"NotImplementedError")
RE_ADAPTER = re.compile(r"_adapter\(")

VERSION_SCOPES = {
    "strict": RE_STRICT,
    "wide": RE_WIDE,
    "full": RE_FULL,
}

# 证据锚点：文件相对路径 -> (正则, present/absent)。
# 每条人工判定至少挂一个锚点；锚点失效说明代码已变、结论需重审。
ANCHORS: dict[str, tuple[str, str, str]] = {
    "layers_dead": ("src/harness/assembly/config.py", r"harness\.layers\s*=\s*tuple\(", "present"),
    "layer_factories": ("src/harness/assembly/config.py", r"LAYER_FACTORIES\s*=\s*\{", "present"),
    "layer_fn": ("src/harness/assembly/config.py", r"def _layer_fn\(", "present"),
    "validate_layers": ("src/harness/assembly/config.py", r"def validate_layers\(", "present"),
    "auto_layers": ("src/harness/assembly/config.py", r"def _auto_layers\(", "present"),
    "harness_config": ("src/harness/assembly/config.py", r"class HarnessConfig", "present"),
    "new_runtime": ("src/harness/assembly/harness.py", r"def new_runtime\(", "present"),
    "with_auto_layers": ("src/harness/assembly/harness.py", r"with_auto_layers\(program\)", "present"),
    "counter_wired": ("src/harness/assembly/harness.py", r"counter=self\.token_counter", "present"),
    "dry_run": ("src/harness/assembly/harness.py", r"async def dry_run\(", "present"),
    "no_tokens_10": ("src/harness/kernel/effects.py", r'["\']tokens["\']\s*:\s*10 if effect\.kind', "absent"),
    "effects_stages": ("src/harness/kernel/effects.py", r"async def _stages\(", "present"),
    "model_drop_usage": ("src/harness/kernel/effects.py", r'["\']output["\']\s*:\s*reply', "present"),
    "failure_contract": ("src/harness/kernel/stage.py", r"class Failure", "absent"),
    "no_total_tokens": ("src/harness/parts/policy/policies.py", r"total_tokens", "absent"),
    "usage_total_v2": ("src/harness/parts/actor.py", r"usage_total\(usage\)", "present"),
    "no_v1_double_count": ("src/harness/assembly/harness.py", r'["\']_usage["\']\s*:\s*\{["\']calls["\']\s*:\s*1', "absent"),
    "budget_forward": ("src/harness/parts/budget.py", r"from harness\.contracts\.types import Budget", "present"),
    "budget_contract": ("src/harness/contracts/types.py", r"class Budget", "present"),
    "quota_field": ("src/harness/contracts/types.py", r"quota:\s*dict\[str,\s*int\]", "present"),
    "split": ("src/harness/contracts/types.py", r"def split\(", "present"),
    "budget_view": ("src/harness/contracts/types.py", r"def view\(", "present"),
    "check_identity": ("src/harness/parts/guard.py", r"async def check_identity\(", "present"),
    "no_hasattr_feed": ("src/harness/parts/guardrail/streaming.py", r'hasattr\(g,\s*["\']feed["\']\)', "absent"),
    "no_feed_impl": ("src/harness/parts/guardrail/detectors.py", r"def feed\(", "absent"),
    "run_point_declared": ("src/harness/parts/guardrail/layer.py", r'["\']model_call["\'],\s*["\']run["\']', "present"),
    "run_point_executed": ("src/harness/assembly/harness.py", r'resolve\(program\.layers,\s*["\']run["\']\)', "present"),
    "legacy_model_resp": ("src/harness/assembly/harness.py", r"ModelResponse\(reply=reply,", "present"),
    "points": ("src/harness/kernel/chain.py", r'["\']run["\'],\s*["\']step["\'],\s*["\']model_call["\'],\s*["\']tool_call["\']', "present"),
    "sandbox_local": ("src/harness/assembly/registry.py", r'["\']local["\']\s*:\s*_local_sandbox', "present"),
    "openai_selfreg": ("src/harness/adapters/openai.py", r'_registry\.MODELS\[["\']openai["\']\]', "present"),
    "fake_model": ("tests/support.py", r"class FakeModel", "present"),
    "budget_metadata": ("src/harness/parts/delivery.py", r'state\.data\.get\(["\']budget["\']', "present"),
    "schema_version": ("src/harness/contracts/state.py", r"SCHEMA_VERSION\s*=\s*2", "present"),
    "pkg_version": ("src/harness/__init__.py", r'__version__\s*=\s*["\']0\.3\.0["\']', "present"),
    "tiktoken": ("src/harness/parts/tokens.py", r"class TiktokenCounter", "present"),
    "structured": ("src/harness/parts/structured.py", r"class StructuredModel", "present"),
    "resilience": ("src/harness/parts/resilience.py", r"class Resilience", "present"),
    "max_qps": ("src/harness/parts/resilience.py", r"max_qps", "present"),
    "budget_layer": ("src/harness/parts/middleware/builtin.py", r"def budget_layer\(", "present"),
    "delivery_protocol": ("src/harness/contracts/protocols/governance.py", r"class Delivery", "present"),
    "null_durability": ("src/harness/parts/durability.py", r"class NullDurability", "present"),
    "commit_usage": ("src/harness/kernel/interpret.py", r"state\.add_usage\(", "present"),
    "commit_spends_budget": ("src/harness/kernel/interpret.py", r"budget\.spend\(", "present"),
}

# 人工判定条目的稳定索引：(ID, 类别, 级别, 锚点名)。
# 脚本只固定数量/分级/锚点有效性；结论正文在 AUDIT 文档 §1。
MANUAL_ITEMS: tuple[tuple[str, str, str, str], ...] = (
    ("B01", "装配", "高", "layers_dead"),
    ("B02", "装配", "高", "layer_factories"),
    ("B03", "装配", "中", "validate_layers"),
    ("B04", "装配", "高", "auto_layers"),
    ("B05", "装配", "高", "harness_config"),
    ("B06", "装配", "高", "new_runtime"),
    ("B07", "装配", "高", "sandbox_local"),
    ("B08", "装配", "高", "openai_selfreg"),
    ("B09", "装配", "低", "layer_factories"),
    ("B10", "装配", "中", "layer_fn"),
    ("B11", "装配", "低", "layer_factories"),
    ("B12", "装配", "低", "layer_factories"),
    ("M01", "计量", "高", "no_tokens_10"),
    ("M02", "计量", "高", "model_drop_usage"),
    ("M03", "计量", "高", "no_v1_double_count"),
    ("M04", "计量", "中", "commit_spends_budget"),
    ("M05", "计量", "中", "legacy_model_resp"),
    ("M06", "计量", "高", "fake_model"),
    ("M07", "计量", "中", "fake_model"),
    ("M08", "计量", "中", "counter_wired"),
    ("M09", "计量", "中", "budget_layer"),
    ("M10", "计量", "低", "budget_metadata"),
    ("C01", "契约", "高", "quota_field"),
    ("C02", "契约", "高", "check_identity"),
    ("C03", "契约", "中", "max_qps"),
    ("C04", "契约", "高", "no_feed_impl"),
    ("C05", "契约", "中", "delivery_protocol"),
    ("C06", "契约", "低", "delivery_protocol"),
    ("C07", "契约", "高", "run_point_executed"),
    ("C08", "契约", "中", "structured"),
    ("C09", "契约", "中", "budget_view"),
    ("C10", "契约", "高", "null_durability"),
    ("G01", "治理", "高", "with_auto_layers"),
    ("G02", "治理", "中", "dry_run"),
    ("G03", "治理", "中", "new_runtime"),
    ("G04", "治理", "中", "no_v1_double_count"),
    ("G05", "治理", "高", "new_runtime"),
    ("G06", "治理", "高", "effects_stages"),
    ("G07", "治理", "中", "counter_wired"),
    ("F01", "默认实现", "中", "fake_model"),
    ("F02", "默认实现", "高", "sandbox_local"),
    ("F03", "默认实现", "高", "null_durability"),
    ("F04", "默认实现", "高", "openai_selfreg"),
    ("F05", "默认实现", "中", "fake_model"),
)


# ---------------------------------------------------------------- 采集


def collect_files() -> dict[str, list[Path]]:
    code = sorted(CODE_DIR.rglob("*.py"))
    docs = sorted(p for p in DOCS_DIR.glob("*.md") if not p.name.startswith("AUDIT-"))
    tests = sorted(TESTS_DIR.rglob("*.py")) if TESTS_DIR.exists() else []
    return {"code": code, "docs": docs, "tests": tests}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def hit_lines(text: str, pattern: re.Pattern[str]) -> int:
    return sum(1 for line in text.splitlines() if pattern.search(line))


def version_stats(files: dict[str, list[Path]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for scope, pattern in VERSION_SCOPES.items():
        per_code = {rel(p): hit_lines(read_text(p), pattern) for p in files["code"]}
        per_docs = {rel(p): hit_lines(read_text(p), pattern) for p in files["docs"]}
        out[scope] = {
            "code": {
                "lines": sum(per_code.values()),
                "files": sum(1 for n in per_code.values() if n),
                "per_file": {k: v for k, v in sorted(per_code.items()) if v},
            },
            "docs": {
                "lines": sum(per_docs.values()),
                "files": sum(1 for n in per_docs.values() if n),
                "per_file": {k: v for k, v in sorted(per_docs.items()) if v},
            },
        }
    v31_code = {rel(p): hit_lines(read_text(p), RE_V31) for p in files["code"]}
    v31_docs = {rel(p): hit_lines(read_text(p), RE_V31) for p in files["docs"]}
    out["v31_supplement"] = {
        "code_lines": sum(v31_code.values()),
        "code_files": sum(1 for n in v31_code.values() if n),
        "docs_lines": sum(v31_docs.values()),
        "per_file": {k: v for k, v in sorted(v31_code.items()) if v},
    }
    constants: list[dict[str, str]] = []
    for p in files["code"]:
        for i, line in enumerate(read_text(p).splitlines(), 1):
            if RE_CONSTANT.search(line):
                constants.append({"file": rel(p), "line": i, "text": line.strip()})
    out["constants"] = sorted(constants, key=lambda d: (d["file"], d["line"]))
    return out


def parse_modules(files: list[Path]) -> tuple[dict[str, ast.Module], list[dict[str, str]]]:
    modules: dict[str, ast.Module] = {}
    errors: list[dict[str, str]] = []
    for p in files:
        try:
            modules[rel(p)] = ast.parse(read_text(p), filename=rel(p))
        except SyntaxError as exc:
            errors.append({"file": rel(p), "error": f"{type(exc).__name__}: {exc.msg}"})
    return modules, errors


def top_level_defs(tree: ast.Module) -> list[tuple[str, str, int, list[str]]]:
    """返回 (kind, name, lineno, fields)；fields 为类体内的注解字段名。"""
    result = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            fields = []
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                        fields.append(sub.target.id)
            result.append((kind, node.name, node.lineno, fields))
    return result


def duplicate_defs(modules: dict[str, ast.Module]) -> dict[str, object]:
    locations: dict[str, list[dict[str, object]]] = defaultdict(list)
    for fname, tree in modules.items():
        for kind, name, lineno, fields in top_level_defs(tree):
            locations[name].append(
                {"file": fname, "line": lineno, "kind": kind, "fields": sorted(fields)}
            )
    groups = {
        name: sorted(items, key=lambda d: (d["file"], d["line"]))
        for name, items in sorted(locations.items())
        if len(items) >= 2
    }
    return {"groups": groups, "group_count": len(groups)}


def bound_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
    return names


def dangling_all(modules: dict[str, ast.Module]) -> list[dict[str, object]]:
    out = []
    for fname, tree in modules.items():
        declared: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            declared.append(elt.value)
        if not declared:
            continue
        missing = sorted(set(declared) - bound_names(tree))
        if missing:
            out.append({"file": fname, "declared": len(declared), "dangling": missing})
    return sorted(out, key=lambda d: d["file"])


def shim_candidates(modules: dict[str, ast.Module], files: list[Path]) -> list[dict[str, object]]:
    out = []
    line_counts = {rel(p): len(read_text(p).splitlines()) for p in files}
    for fname, tree in modules.items():
        doc = ast.get_docstring(tree) or ""
        reasons = []
        if "兼容壳" in doc:
            reasons.append("docstring_mentions_compat")
        others = [
            n for n in tree.body
            if not isinstance(n, (ast.Import, ast.ImportFrom, ast.Assign))
            and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                     and isinstance(n.value.value, str))
        ]
        if not others and line_counts[fname] <= 15:
            reasons.append("only_imports_and_all")
        if reasons:
            out.append({"file": fname, "lines": line_counts[fname], "reasons": sorted(reasons)})
    return sorted(out, key=lambda d: d["file"])


def reference_counts(modules: dict[str, ast.Module]) -> Counter:
    """静态可见引用：Name / Attribute / import alias。不含字符串常量与注释。"""
    counts: Counter = Counter()
    for tree in modules.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                counts[node.id] += 1
            elif isinstance(node, ast.Attribute):
                counts[node.attr] += 1
            elif isinstance(node, ast.alias):
                counts[node.name.split(".")[0]] += 1
                if node.asname:
                    counts[node.asname] += 1
    return counts


def zero_reference_candidates(
    modules: dict[str, ast.Module], tests_text: str
) -> dict[str, object]:
    counts = reference_counts(modules)
    defs: dict[str, list[str]] = defaultdict(list)
    for fname, tree in modules.items():
        for _kind, name, lineno, _fields in top_level_defs(tree):
            defs[name].append(f"{fname}:{lineno}")
    zero = {
        name: {
            "definitions": sorted(locs),
            "static_refs_in_code": counts[name],
            "text_hits_in_tests": len(re.findall(rf"\b{re.escape(name)}\b", tests_text)),
        }
        for name, locs in sorted(defs.items())
        if counts[name] == 0
    }
    return {
        "note": "启发式：仅统计静态可见引用；getattr/注册表字符串/动态 import 不可见",
        "count": len(zero),
        "items": zero,
    }


def placeholders(files: list[Path], modules: dict[str, ast.Module]) -> dict[str, object]:
    todo: list[dict[str, object]] = []
    not_impl: list[dict[str, object]] = []
    passes: list[dict[str, object]] = []
    adapter_calls = 0
    for p in files:
        text = read_text(p)
        fname = rel(p)
        for i, line in enumerate(text.splitlines(), 1):
            if RE_PLACEHOLDER.search(line):
                todo.append({"file": fname, "line": i, "text": line.strip()})
            if RE_NOT_IMPL.search(line):
                not_impl.append({"file": fname, "line": i, "text": line.strip()})
        adapter_calls += len(RE_ADAPTER.findall(text))
    for fname, tree in modules.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Pass):
                passes.append({"file": fname, "line": node.lineno})
    return {
        "todo_like": todo,
        "not_implemented_error": not_impl,
        "pass_statements": sorted(passes, key=lambda d: (d["file"], d["line"])),
        "adapter_placeholder_calls": adapter_calls,
    }


def anchors_check() -> dict[str, object]:
    results = []
    cache: dict[str, str] = {}
    for key, (path, pattern, expect) in sorted(ANCHORS.items()):
        if path not in cache:
            f = ROOT / path
            cache[path] = read_text(f) if f.exists() else ""
        found = bool(re.search(pattern, cache[path], re.MULTILINE))
        ok = found if expect == "present" else not found
        results.append(
            {"id": key, "file": path, "expect": expect, "found": found, "ok": ok}
        )
    failed = [r["id"] for r in results if not r["ok"]]
    return {
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": failed,
        "results": results,
    }


def manual_summary(anchors: dict[str, object]) -> dict[str, object]:
    levels = Counter(item[2] for item in MANUAL_ITEMS)
    cats = Counter(item[1] for item in MANUAL_ITEMS)
    ok_ids = {r["id"] for r in anchors["results"] if r["ok"]}  # type: ignore[index]
    broken = sorted({item[3] for item in MANUAL_ITEMS} - ok_ids)
    return {
        "note": "人工判定条目的稳定索引；结论正文见 AUDIT 文档 §1，脚本不重算结论",
        "total": len(MANUAL_ITEMS),
        "by_level": dict(sorted(levels.items())),
        "by_category": dict(sorted(cats.items())),
        "anchor_ids": sorted({item[3] for item in MANUAL_ITEMS}),
        "broken_anchor_ids": broken,
        "items": [
            {"id": i, "category": c, "level": lv, "anchor": a}
            for i, c, lv, a in MANUAL_ITEMS
        ],
    }


def fingerprint(files: list[Path]) -> str:
    h = hashlib.sha256()
    for p in files:
        h.update(rel(p).encode("utf-8"))
        h.update(b"\0")
        h.update(read_text(p).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def build_report() -> dict[str, object]:
    files = collect_files()
    modules, parse_errors = parse_modules(files["code"])
    tests_text = "\n".join(read_text(p) for p in files["tests"])
    anchors = anchors_check()
    return {
        "meta": {
            "audit_spec_version": AUDIT_SPEC_VERSION,
            "generator": "tools/audit_harness.py",
            # 判据自身也纳入校验：改了正则/锚点/条目表而忘记升版与重生成，--check 会失败。
            "generator_sha256": hashlib.sha256(
                Path(__file__).resolve().read_bytes()
            ).hexdigest(),
            "deterministic": True,
            "scope": {
                "code": "src/harness/**/*.py",
                "docs": "docs/harness/*.md (排除 AUDIT-*.md)",
                "tests": "tests/**/*.py",
            },
            "regex": {k: v.pattern for k, v in VERSION_SCOPES.items()},
            "no_timestamp_no_randomness": True,
        },
        "scope": {
            "code_files": len(files["code"]),
            "doc_files": len(files["docs"]),
            "test_files": len(files["tests"]),
            "doc_lines": {rel(p): len(read_text(p).splitlines()) for p in files["docs"]},
            "doc_total_lines": sum(len(read_text(p).splitlines()) for p in files["docs"]),
            "code_fingerprint_sha256": fingerprint(files["code"]),
        },
        "parse_errors": parse_errors,
        "versions": version_stats(files),
        "duplicate_defs": duplicate_defs(modules),
        "dangling_all": dangling_all(modules),
        "shims": shim_candidates(modules, files["code"]),
        "zero_reference_candidates": zero_reference_candidates(modules, tests_text),
        "placeholders": placeholders(files["code"], modules),
        "anchors": anchors,
        "manual_findings": manual_summary(anchors),
    }


def dumps(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def print_summary(r: dict[str, object]) -> None:
    s = r["scope"]
    v = r["versions"]
    print("Harness 机械统计（由 tools/audit_harness.py 生成）")
    print(f"  代码文件 {s['code_files']} / 文档 {s['doc_files']}（{s['doc_total_lines']} 行）/ 测试 {s['test_files']}")
    print(f"  code_fingerprint {str(s['code_fingerprint_sha256'])[:16]}…")
    for scope in ("strict", "wide", "full"):
        c, d = v[scope]["code"], v[scope]["docs"]
        print(f"  版本说法[{scope:6}] 代码 {c['lines']:4} 行 / {c['files']:2} 文件  "
              f"文档 {d['lines']:4} 行 / {d['files']:2} 文件")
    v31 = v["v31_supplement"]
    print(f"  v3.1/SUPPLEMENT   代码 {v31['code_lines']} 行 / {v31['code_files']} 文件")
    print(f"  同名定义组 {r['duplicate_defs']['group_count']}  "
          f"悬空 __all__ {len(r['dangling_all'])}  "
          f"兼容壳候选 {len(r['shims'])}  "
          f"零引用候选 {r['zero_reference_candidates']['count']}")
    ph = r["placeholders"]
    print(f"  TODO类 {len(ph['todo_like'])}  NotImplementedError {len(ph['not_implemented_error'])}  "
          f"pass {len(ph['pass_statements'])}  占位工厂调用 {ph['adapter_placeholder_calls']}")
    a = r["anchors"]
    print(f"  证据锚点 {a['passed']}/{a['total']} 通过，失败：{a['failed'] or '无'}")
    m = r["manual_findings"]
    print(f"  人工判定条目 {m['total']}（{m['by_level']}），失效锚点：{m['broken_anchor_ids'] or '无'}")
    if r["parse_errors"]:
        print(f"  !! AST 解析失败 {len(r['parse_errors'])} 个文件")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Harness 机械统计审计器")
    ap.add_argument("--json", type=Path, help="把报告写入 JSON 文件")
    ap.add_argument("--check", type=Path, help="与已有快照比对，不一致返回 1")
    args = ap.parse_args()

    report = build_report()
    text = dumps(report)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text, encoding="utf-8")
        try:
            shown = args.json.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            shown = str(args.json.resolve())
        print(f"已写入 {shown}")
    if args.check:
        if not args.check.exists():
            print(f"快照不存在：{args.check}")
            return 1
        old = args.check.read_text(encoding="utf-8")
        if old == text:
            print("CHECK OK：当前代码与快照完全一致（字节级）")
            return 0
        try:
            old_obj = json.loads(old)
        except json.JSONDecodeError:
            print("CHECK FAIL：快照不是合法 JSON")
            return 1
        new_obj = json.loads(text)
        diffs = []
        for key in sorted(set(old_obj) | set(new_obj)):
            if old_obj.get(key) != new_obj.get(key):
                diffs.append(key)
        old_fp = (old_obj.get("scope") or {}).get("code_fingerprint_sha256")
        new_fp = (new_obj.get("scope") or {}).get("code_fingerprint_sha256")
        if old_fp != new_fp:
            print("!! 代码指纹已变化：源码被改动过，快照需重新生成")
        old_gen = (old_obj.get("meta") or {}).get("generator_sha256")
        new_gen = (new_obj.get("meta") or {}).get("generator_sha256")
        if old_gen != new_gen:
            print("!! 判据指纹已变化：审计脚本被改动过，快照需重新生成")
        print(f"CHECK FAIL：差异字段 {diffs}")
        return 1
    if not args.json:
        print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
