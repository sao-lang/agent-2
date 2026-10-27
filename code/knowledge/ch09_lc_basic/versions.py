"""第 9 章 9.1：四个包的分工与版本边界。

运行：python code/knowledge/ch09_lc_basic/versions.py
"""

import importlib
import importlib.metadata as md

PACKAGES = ("langchain-core", "langchain", "langchain-openai", "langchain-community")


def installed_versions():
    """每个包的已装版本，以及它对 langchain-core 的版本要求。"""
    rows = []
    for pkg in PACKAGES:
        version = md.version(pkg)
        reqs = [r for r in (md.requires(pkg) or []) if "langchain-core" in r and "extra" not in r]
        rows.append((pkg, version, reqs[0] if reqs else "-"))
    return rows


def who_provides(symbol, modules):
    """在候选模块里找 `symbol` 由谁提供。"""
    found = []
    for module_name in modules:
        module = importlib.import_module(module_name)
        if hasattr(module, symbol):
            found.append(module_name)
    return found


def try_import(module_name, symbol=None):
    """跑一次真正的 import 语句，把失败形态原样打出来。"""
    statement = f"import {module_name}" if symbol is None else f"from {module_name} import {symbol}"
    try:
        exec(statement, {})
        return f"成功：{statement}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    for pkg, version, req in installed_versions():
        print(f"{pkg:<20} {version:<10} 要求 {req}")

    print()
    for symbol, modules in [
        ("init_chat_model", ("langchain.chat_models", "langchain_openai")),
        ("ChatOpenAI", ("langchain.chat_models", "langchain_openai")),
        ("trim_messages", ("langchain_core.messages", "langchain")),
        ("BaseTool", ("langchain_core.tools", "langchain")),
    ]:
        print(f"{symbol:<16} 来自 {who_provides(symbol, modules)}")

    print()
    for module_name, symbol in [
        ("langchain.chains", None),
        ("langchain.memory", None),
        ("langchain.chat_models", "ChatOpenAI"),
        ("langchain.text_splitter", "RecursiveCharacterTextSplitter"),
    ]:
        print(f"{module_name:<24} -> {try_import(module_name, symbol)}")
