#!/usr/bin/env python3
"""读者向检查：抓"压缩之后读者读不懂"的四类问题。

与 lint_prose.py 的分工：lint 管"话说得难听"（AI 味），本脚本管"话说不完整"（锚点缺失）。

四类（对应 WRITING-SPEC 6.1.1）：
    A1 代码失去来源   代码块前最近的散文段没有 `code/...` 或 `.py`；输出块前没有"输出/运行结果"
    A2 并列项悬空     段落以"第一，/一是/首先"开头，但前面没有"…三条："这类总起句
    A3 术语无定义     反引号 API / 驼峰类名首次出现时，附近既无定义句，也无含它的代码块
    A4 指代悬空       "同一份 X"里的 X 在全章没有定义
    A5 章内重复       同一句连发两次，或两段高度相似

用法：
    python docs/check_reader.py 01 02 ...      # 指定章
    python docs/check_reader.py --all          # 全部章
    python docs/check_reader.py --all --quiet  # 只出汇总
"""

from __future__ import annotations

import argparse
import difflib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 卷 1 已定义的通用字段，不要求逐次解释
WHITELIST = {
    "content", "messages", "usage", "finish_reason", "tool_calls", "model",
    "token", "role", "temperature", "max_tokens", "id", "type", "system",
    "user", "assistant", "tool", "tools", "prompt_tokens", "completion_tokens",
    "total_tokens", "choices", "logprobs", "delta", "stop", "length",
    "content_filter", "top_p", "seed", "stream", "json", "true", "false",
    "null", "None", "True", "False", "base_url", "api_key", "client",
    "INDEX", "JSON", "HTTP", "API", "SDK", "URL", "URI", "UUID", "SQL",
    "LLM", "RAG", "Agent", "Prompt", "Token", "Python", "LangChain",
    "openai", "pydantic", "tiktoken", "langchain", "numpy", "pandas",
    "exp", "log", "len", "str", "int", "float", "bool", "list", "dict",
    "float", "print", "range", "zip", "open", "type", "isinstance",
}
CODE_LANGS = {"python", "py", "text", "bash", "json", "sh", "shell", "js", "ts"}


def parse(text: str) -> dict:
    lines = text.replace("\r\n", "\n").split("\n")
    fences = []           # (起始行号, 语言, 结束行号)
    in_f, lang, start = False, "", 0
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith("```"):
            if not in_f:
                in_f, lang, start = True, s[3:].strip().lower(), i
            else:
                in_f = False
                fences.append((start + 1, lang, i + 1))
    return {"lines": lines, "fences": fences}


def in_fence(rng: dict, n: int) -> bool:
    for a, _, b in rng["fences"]:
        if a <= n < b:
            return True
    return False


def prev_prose(rng: dict, ln: int, maxback: int = 10) -> str:
    """向上取最近的非空、非围栏、非表格散文行"""
    lines = rng["lines"]
    for j in range(ln - 2, max(0, ln - 1 - maxback) - 1, -1):
        if in_fence(rng, j + 1):
            break
        t = lines[j].strip()
        if not t:
            continue
        if t.startswith(("|", ">", "#", "---")):
            continue
        return t
    return ""


def _lead(rng: dict, start: int, back: int = 30) -> str:
    """取代码块/输出块上方 nearest 的散文块（最多 3 段，跨过空行）"""
    lines = rng["lines"]
    got, j = [], start - 2
    while j >= 0 and len(got) < 3 and start - j < back:
        if in_fence(rng, j + 1):
            break
        s = lines[j].strip()
        if s and not s.startswith(("|", ">", "#", "---")):
            got.append(s)
        elif s.startswith("#"):
            break
        j -= 1
    return " ".join(reversed(got))


SRC = re.compile(r"code/knowledge/|\b[a-z_][a-z0-9_]*\.py\b|\b\w+\.py\b")
DEMO = re.compile(r"示意|演示|原理|假设|例如|长这样|大约")
BACKREF = re.compile(r"上文|上面|这段|刚才|它的输出|代码的输出")


def check_a1(rng: dict) -> list[str]:
    bad = []
    lines = rng["lines"]
    code_blocks = [(a, b) for a, lang, b in rng["fences"] if lang]
    for start, lang, end in rng["fences"]:
        ctx = _lead(rng, start)
        if lang:
            if not (SRC.search(ctx) or DEMO.search(ctx)):
                bad.append(f"L{start} A1 代码块缺来源/性质标注：…{ctx[-38:]}")
        else:
            # 输出块：① 引导句给文件名 ② 引导句明确指代 ③ 上方 30 行内有代码块且它有来源
            ok = bool(SRC.search(ctx) or BACKREF.search(ctx) or DEMO.search(ctx)
                      or re.search(r"\d+\.\d+ 节.*输出|那份输出|这一节.*输出", ctx))
            if not ok:
                for ca, cb in code_blocks:
                    if cb <= start and start - cb <= 30:
                        cctx = _lead(rng, ca)
                        if SRC.search(cctx) or DEMO.search(cctx):
                            ok = True
                            break
            if not ok:
                bad.append(f"L{start} A1b 输出块无法追溯来源：…{ctx[-38:]}")
    return bad


ORDINALS = ("第一，", "第二，", "第三，", "第四，", "一是", "二是", "三是", "首先", "其一", "其二")
COUNTING = re.compile(r"三|两|几|四|二|一条|条条|点|类|种|个|如下|：$")


def check_a2(text: str) -> list[str]:
    bad = []
    lines = text.split("\n")
    paras = []          # (起始行号, 段落文本)
    cur, start = [], 0
    in_f = False
    for i, l in enumerate(lines, 1):
        if l.strip().startswith("```"):
            in_f = not in_f
        if in_f:
            continue
        if l.strip() == "":
            if cur:
                paras.append((start, "\n".join(cur)))
                cur = []
            continue
        if not cur:
            start = i
        cur.append(l)
    if cur:
        paras.append((start, "\n".join(cur)))

    for idx, (ln, p) in enumerate(paras):
        t = p.strip()
        if not t or t.startswith(("|", ">", "#")):
            continue
        if not t.startswith(ORDINALS):
            continue
        # 往前找最近一段散文
        prev = ""
        for k in range(idx - 1, max(-1, idx - 4), -1):
            q = paras[k][1].strip()
            if q and not q.startswith(("|", ">", "#")):
                prev = q
                break
        if not prev:
            continue
        tail = prev.rstrip("-* ")
        if tail.endswith(("：", ":")) or COUNTING.search(tail[-12:]):
            continue
        bad.append(f"L{ln} A2 并列项悬空（上段结尾：…{prev[-26:]}）")
    return bad


CJK = re.compile(r"[\u4e00-\u9fff]")


EXCLUDE_SUFFIX = ("Error", "Warning", "Exception", "Exit")
PLATFORMS = {
    "LangChain", "LangGraph", "LlamaIndex", "AutoGen", "CrewAI", "OpenAI",
    "Anthropic", "Gemini", "Claude", "Coze", "Dify", "Linux", "POSIX",
    "Windows", "PowerShell", "Docker", "Bash", "SQLite", "Redis", "Kafka",
    "Python", "JavaScript", "TypeScript", "FastAPI", "Flask",
}


def check_a3(rng: dict, text: str) -> list[str]:
    """只查"被当作 API 提到、但全章没有一处代码出现它"的情况。

    排除：异常类（Error/Warning）、平台与框架名、全大写下划线常量、知识点编号（F10）。
    """
    bad = []
    lines = rng["lines"]
    cands = set()
    for m in re.finditer(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)", text):      # 反引号 snake_case
        cands.add(m.group(1))
    for m in re.finditer(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s*\(", text):   # 调用形式
        cands.add(m.group(1))
    for m in re.finditer(r"`([A-Z][A-Za-z0-9]{3,})`", text):              # 反引号 CamelCase
        cands.add(m.group(1))

    in_code = "\n".join("\n".join(lines[a:b - 1]) for a, _, b in rng["fences"])
    for ident in sorted(cands):
        if ident in WHITELIST or ident in PLATFORMS:
            continue
        if ident.endswith(EXCLUDE_SUFFIX):
            continue
        if re.fullmatch(r"[A-Z0-9]{2,}", ident):        # F10 / A1 这类编号
            continue
        if ident in in_code:                            # 代码里出现过 = 有示例
            continue
        pos = text.find(ident)
        ln = text.count("\n", 0, pos) + 1
        bad.append(f"L{ln} A3 提到 API 但全章无示例：{ident}")
    return bad


def check_a4(text: str) -> list[str]:
    bad = []
    for m in re.finditer(r"同一[份个条张]?\s*`([A-Za-z_][A-Za-z0-9_]{2,})`", text):
        ident = m.group(1)
        ln = text.count("\n", 0, m.start()) + 1
        if re.search(rf"class\s+{ident}\b", text):
            continue
        if len(re.findall(rf"`{ident}`", text)) >= 2 or ident in text.split("同一份")[0]:
            continue
        bad.append(f"L{ln} A4 指代悬空：同一份 {ident}（全章无定义）")
    return bad


def check_a5(text: str) -> list[str]:
    bad = []
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    sents = [s.strip() for s in re.findall(r"[^。！？\n]{12,}。", prose)]
    for a, b in zip(sents, sents[1:]):
        if a == b:
            bad.append(f"A5 同句连发：{a[:34]}")
            break
    paras = [p.strip() for p in re.split(r"\n\s*\n", prose)
             if p.strip() and not p.lstrip().startswith(("```", "|", ">", "#"))]
    for i in range(len(paras)):
        for j in range(i + 1, min(i + 12, len(paras))):
            x, y = paras[i], paras[j]
            if min(len(x), len(y)) < 60:
                continue
            r = difflib.SequenceMatcher(None, x, y).ratio()
            if r > 0.75:
                bad.append(f"A5 段落高度相似（{r:.2f}）：{x[:26]}… / {y[:26]}…")
                break
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stems", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    files = sorted(p for p in ROOT.glob("*.md") if re.match(r"^\d{2}-", p.name))
    if args.stems:
        files = [f for f in files if f.name[:2] in args.stems]

    total = 0
    print(f"{'章':<4}{'A1':>4}{'A2':>4}{'A3':>4}{'A4':>4}{'A5':>4}{'合计':>6}")
    for f in files:
        text = f.read_text(encoding="utf-8")
        rng = parse(text)
        issues = (check_a1(rng) + check_a2(text) + check_a3(rng, text)
                  + check_a4(text) + check_a5(text))
        counts = [0] * 5
        for it in issues:
            k = "A1A2A3A4A5".find(it.split(" ")[0][-1] if it.startswith("A") else "A")
            for idx, tag in enumerate(("A1", "A2", "A3", "A4", "A5")):
                if f" {tag} " in it:
                    counts[idx] += 1
        total += len(issues)
        if issues or not args.quiet:
            print(f"{f.name[:2]:<4}" + "".join(f"{c:>4}" for c in counts) + f"{len(issues):>6}")
        if issues and not args.quiet:
            for it in issues[:12]:
                print(f"     {it}")
            if len(issues) > 12:
                print(f"     …还有 {len(issues) - 12} 条")
    print(f"\n合计问题 {total} 条")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
