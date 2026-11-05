"""离线回归：逐字对基线，并验证"关掉一个开关只有一件事消失"。

**这不是运行时代码，是改完代码后的验收脚本。** 它不替代 run.py：
run.py 让你真的跑一次（花钱、看输出），regression.py 让你在离线状态下
确认"行为一点没变"。

    python learn/mini_agent/regression.py

不联网、不花 key：在线程里起 code/knowledge/ch08_runaway/mock_openai.py 的
剧本服务（生长路线「保命习惯 2：回归必须能离线跑」）。

基线数字是拆分前那一个 544 行单文件版本实测出来的，拆分后必须逐项对上；
对不上就是改的时候动了行为，不是"重构完成"。加例子（demo/<场景>/）不用改这里；
只有核心语义变了才需要更新基线，而更新基线必须说明为什么。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOCK_PATH = ROOT / "code" / "knowledge" / "ch08_runaway" / "mock_openai.py"

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import run as ma  # noqa: E402  —— ma = mini_agent 的装配层（run.py）


# ── 加载章节目录里的剧本服务（复用，不复制一份）──────────────────────────────
def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mock = _load("mock_openai_regression", MOCK_PATH)
server = ThreadingHTTPServer(("127.0.0.1", 0), mock.Handler)
URL = f"http://127.0.0.1:{server.server_address[1]}/v1"
threading.Thread(target=server.serve_forever, daemon=True).start()

PASS, FAIL = [], []


def check(label: str, got, want) -> None:
    if got == want:
        PASS.append(label)
        print(f"  PASS  {label}")
    else:
        FAIL.append(label)
        print(f"  FAIL  {label}\n        期望 {want!r}\n        实际 {got!r}")


def play(scenario: str, **kw):
    """跑一次，返回 (status, stats 的十个数字, 打印出来的结果行)。"""
    mock.ACTIVE_PLAN = mock.PLANS[scenario]()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        status, _answer, stats = ma.run(
            base_url=URL, api_key="sk-mock", model="mock", verbose=True, **kw
        )
    lines = buf.getvalue().splitlines()
    summary = next((ln for ln in lines if ln.strip().startswith("结果：")), "")
    numbers = (
        stats.steps, stats.tool_calls, stats.prompt_tokens, stats.completion_tokens,
        stats.total_tokens, stats.duplicate_blocked, stats.arg_errors,
        stats.schema_retries, stats.truncated, stats.trimmed, stats.repeated_result,
    )
    return status, numbers, summary


# ── 一、五种基线跑法：状态 + 全部计数 + 结果行逐字 ──────────────────────────
BASELINE = [
    ("good 正常路径", "good", {},
     "ANSWERED", (10, 7, 1700, 355, 2055, 1, 1, 1, 1, 1, 0),
     "  结果：status=ANSWERED 步数=10 工具调用=7 token=1700+355=2055 "
     "重复拦截=1 参数错误=1 结构化重试=1 截断=1 裁剪=1 结果重复=0"),
    ("stall 重复调用", "stall", {},
     "STALLED", (3, 3, 300, 120, 420, 2, 0, 0, 0, 0, 0),
     None),
    ("result 换参数打转", "result", {},
     "STALLED", (3, 3, 300, 120, 420, 0, 0, 0, 0, 0, 2),
     None),
    ("budget 成本击穿", "good", {"max_prompt_tokens": 100},
     "BUDGET", (3, 2, 180, 80, 260, 0, 0, 0, 0, 0, 0),
     None),
    ("max_steps 步数到顶", "good", {"max_steps": 2},
     "MAX_STEPS", (2, 2, 180, 80, 260, 0, 0, 0, 0, 0, 0),
     None),
]

print("=== 一、拆分前的五种基线 ===")
for label, scenario, kw, want_status, want_numbers, want_line in BASELINE:
    status, numbers, line = play(scenario, **kw)
    check(f"{label} / status", status, want_status)
    check(f"{label} / 计数", numbers, want_numbers)
    if want_line is not None:
        check(f"{label} / 结果行逐字", line, want_line)


# ── 二、四个开关：关掉只应该消失一件事 ─────────────────────────────────────
# 注意两种指纹是**互补**的：只关掉一个，另一个会接管同一个失控，
# 状态仍是 STALLED，但停止原因换了。要看"跑到上限"得两个一起关。
print("\n=== 二、开关实验（两种指纹互补）===")
status, numbers, _ = play("stall", no_dedupe=True)
check("--no-dedupe：重复拦截归零", numbers[5], 0)
check("--no-dedupe：结果指纹接管，仍判空转", status, "STALLED")
check("--no-dedupe：停止原因换成结果重复", numbers[10], 2)

status, numbers, _ = play("result", no_result_dedupe=True)
check("--no-result-dedupe：结果重复归零", numbers[10], 0)
check("--no-result-dedupe：请求指纹接管，仍判空转", status, "STALLED")
check("--no-result-dedupe：停止原因换成重复请求", numbers[5], 2)

status, numbers, _ = play("stall", no_dedupe=True, no_result_dedupe=True)
check("两种指纹一起关：只能靠步数上限停", status, "MAX_STEPS")
check("两种指纹一起关：跑满 12 步", numbers[0], 12)
check("两种指纹一起关：两个计数都归零", (numbers[5], numbers[10]), (0, 0))

status, numbers, _ = play("good", no_trim=True)
check("--no-trim：主路径结论不变", status, "ANSWERED")
check("--no-trim：token 不变（mock 按步计价）", numbers[2:5], (1700, 355, 2055))
check("--no-trim：只有裁剪计数消失", numbers[9], 0)
check("--no-trim：其它计数不变", numbers[5:9] + numbers[10:], (1, 1, 1, 1, 0))

status, numbers, _ = play("good", max_prompt_tokens=100, no_budget=True)
check("--no-budget：预算闸门不再拦", status, "ANSWERED")
check("--no-budget：仍跑完 10 步", numbers[0], 10)

# 关掉请求指纹后，同一个 get_order 会真的执行两次，结果指纹替它亮一次
status, numbers, _ = play("good", no_dedupe=True)
check("两种指纹互补：关请求指纹后结果指纹亮起", status, "ANSWERED")
check("两种指纹互补：重复拦截=0", numbers[5], 0)
check("两种指纹互补：结果重复=1", numbers[10], 1)


# ── 三、验证手册 REPL 的门面与单函数（手法 R）───────────────────────────────
print("\n=== 三、兼容门面与单函数 ===")
for name in ("Answer", "to_feedback", "fingerprint", "trim_tool_content",
             "CLAUSE_TEXT", "TOOLS", "SYSTEM_PROMPT", "run", "main"):
    check(f"m.{name} 仍可取", hasattr(ma, name), True)

a = ma.fingerprint("get_order", '{"order_id":"A1002"}')
b = ma.fingerprint("get_order", '{ "order_id" : "A1002" }')
check("B4 键序不同归一后相同（sort_keys）", a == b, True)
check("B5 293 字 → 211 字", len(ma.trim_tool_content(ma.CLAUSE_TEXT)), 211)
check("B5 limit=20 → 32 字", len(ma.trim_tool_content(ma.CLAUSE_TEXT, 20)), 32)
check("A10 合法答复能构造", ma.Answer.model_validate_json(
    '{"conclusion":"不可退","signed_days_ago":9,"window_days":7,'
    '"clause":"P-7","shipping_fee":9.0,"next_step":"请走质量通道"}'
).conclusion, "不可退")
check("A8 六要素标题仍在", sum(
    1 for line in ma.SYSTEM_PROMPT.splitlines()
    if line.startswith("# ") and line[2:] in {"角色", "任务", "约束", "示例", "输出格式", "反例"}
), 6)

# ── 四、章节目录里的旧入口（转发）仍然能跑 ─────────────────────────────────
print("\n=== 四、旧命令与旧 REPL 入口 ===")
old_path = ROOT / "code" / "knowledge" / "ch08_runaway" / "mini_agent.py"
mock.ACTIVE_PLAN = mock.PLANS["good"]()
proc = subprocess.run(
    [sys.executable, str(old_path), "--base-url", URL, "--api-key", "sk-mock",
     "--model", "mock", "--quiet"],
    capture_output=True, text=True, cwd=ROOT,
)
check("旧命令退出码 0", proc.returncode, 0)
check("旧命令仍给出结构化答复", '"conclusion": "不可退"' in proc.stdout, True)

old = _load("old_mini_agent_entry", old_path)
for name in ("Answer", "fingerprint", "trim_tool_content", "CLAUSE_TEXT", "run"):
    check(f"旧 REPL 入口 m.{name} 仍可取", hasattr(old, name), True)

# 验证手册现在用的新路径（按文件路径加载，不是包导入）
new = _load("new_mini_agent_entry", ROOT / "learn" / "mini_agent" / "run.py")
for name in ("Answer", "fingerprint", "trim_tool_content", "CLAUSE_TEXT", "run"):
    check(f"手册新 REPL 路径 m.{name} 可取", hasattr(new, name), True)

server.shutdown()
print(f"\n合计：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败项：" + "、".join(FAIL))
raise SystemExit(1 if FAIL else 0)
