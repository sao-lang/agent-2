# 第 54 章 装配：把 tools / MCP / skills 装进一个 Harness

> 第 11–14 章你有了零件：Agent 循环、工具调用、MCP、Skill 的使用。
> 这一章是**全书倒数第二个能力段**的正面回答：这些零件**怎么装进一台能跑的 Harness**，
> 并且证明它真的能跑、能测、能定位问题。

---

## 54.0 先对齐术语

| 术语 | 一句话解释 | 本章在哪用 |
|---|---|---|
| Harness | 包在模型外面的那层工程骨架，负责加载、执行、拦截、记录 | 全章 |
| Registry | 工具登记处，统一管理本地工具和 MCP 工具 | 54.2 |
| SkillLoader | 技能加载器，按 L1/L2/L3 三层按需读 | 54.2 / 54.3 |
| Guard | 安全检查层，每次工具调用前都要过 | 54.2 |
| Loop | 循环本身，含最大步数与终止条件 | 54.2 |
| Trace | 每一步的记录，排查问题的唯一依据 | 54.2 |
| 命名空间前缀 | 给工具名加服务名前缀，如 `order-mcp__query_order_status` | 54.5 |
| 收窄 | 用 skill 的 `allowed-tools` 把可见工具数降下来 | 54.5 |
| 装配故障 | 装错了但程序不报错，只在运行多久后才暴露 | 54.6 |
| 差分判据 | 正确配置必须通过、错误配置必须失败 | 54.7 |
| 验收清单 | 一组可自动跑的断言，能进 CI | 54.7 |
| 最小回归测试集 | 不需要模型、不需要网络就能跑的核心检查 | 54.7 |
| 遗留 token | 上一轮留在上下文里的内容，会导致上下文单调增长 | 54.6 |

---

## 54.1 先看具体的坏事："都能跑"不等于"装配对了"

很多人写完 Harness 的验证方式是：跑一个 demo，看到输出合理，就算完事。

跑 `code/ch54_assembly/step2_assembly_faults.py`，你会看到四种装配错误：

```
四种装配错误，共同点：**都不会让程序崩溃**
  错误装配 → 程序能跑 → 测试能过 → 上线几天后才发现
  正确装配 → 边界清晰 → 指标可测 → 出问题能定位
```

这四行是本章的核心。装配错误的可怕之处不是它会崩，而是**它安静地工作，直到某天出事**。

> 💥 **失败实验**
> 打开 `step1_min_harness.py`，把 `Guard.check()` 改成永远返回 `None`。
> 重跑，四个用例**全部"成功"**——包括"帮我删掉这个用户"。
> 输出会变成 `已删除 u1`，而不是 `操作被拦截`。
> 没有任何异常、没有任何警告。这就是装配错误的样子。

---

## 54.2 五层：每一层只做一件事

`code/ch54_assembly/step1_min_harness.py` 是一个约 200 行的可跑 Harness。

```
Registry（工具从哪来）
  → SkillLoader（流程按需加载）
    → Guard（安全检查）
      → Loop（循环 + 终止条件）
        → Trace（记录每一步）
```

实跑输出的层清单：

```
Registry      工具从哪来             7 个（本地 5 + MCP 2）
SkillLoader   流程按需加载            L1 目录 3 个技能
Guard         危险动作拦截            delete/drop/truncate 一律拦
Loop          循环与终止条件           max_steps=5
Trace         每一步都可查            request/decide/call/blocked/stop
```

### 为什么必须分五层

如果全写在一个函数里，会有三个后果：

1. **换不掉**：想从本地工具换成 MCP，得改整个函数
2. **测不了**：想单独验证"危险动作被拦"，得跑到循环深处
3. **看不见**：出问题时不知道是工具错了、流程错了、还是拦截错了

分层之后，每一层都能单独替换：

| 想换 | 只改 | 其他层 |
|---|---|---|
| 工具来源（本地 → MCP） | `Registry` | 不动 |
| 技能存储（文件 → 数据库） | `SkillLoader` | 不动 |
| 安全策略（硬编码 → 策略文件） | `Guard` | 不动 |
| 日志后端（控制台 → OpenTelemetry） | `Trace` | 不动 |

**这就是 Harness 的意义：不是把代码写在一起，是把边界划清楚。**

### 逐层看关键点

**① Registry：必须记来源**

```python
@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable
    source: str = "local"     # ← 这一行别省
```

`source` 字段看起来可有可无，但出事时它是你唯一能定位的东西。第 54.6 节会用一个具体场景说明。

**② SkillLoader：L1 只读头部**

```python
def _scan(self):
    for md in sorted(self.root.glob("*/SKILL.md")):
        meta, _ = self._parse(md.read_text())    # ← 这里只取 meta，不取 body
        if meta.get("name") and meta.get("description"):
            self.metas.append(SkillMeta(...))
```

注意 `_` 那个占位符：**扫目录时不解析正文**。第 14 章说过，这是渐进式加载成立的前提。

**③ Guard：每次调用前都过**

```python
def check(self, name, args) -> str | None:
    if name in self.denied:
        return f"工具 {name} 在禁用名单"
    if any(k in name for k in ("delete", "drop", "truncate")):
        return f"工具 {name} 是危险动作，需人工审批"
    return None
```

返回 `None` 表示放行，返回字符串表示拒绝理由。这个约定很重要——它让"为什么被拦"可以直接展示给用户。

**④ Loop：必须有上限**

`max_steps=5` 不是随便定的。第 11 章讲过循环的四个终止条件，这是最硬的那一个。

**⑤ Trace：结构化，不是 print**

```python
trace.add("decide", step=1, tool="git_diff")
trace.add("call", tool="git_diff", result="diff(staged): +12 -3 ...")
```

结构化记录才能被机器分析。`print` 出来的东西只能人眼看。

### 跑四个真实请求

```
用户：帮我 review 这个改动
  skill: code-review   可见工具: 2
  结果:  src/user.py: 第 42 行有删除逻辑
  trace:
   1. [request] msg=帮我 review 这个改动
   2. [skill_loaded] name=code-review, chars=516, tools=2
   3. [decide] step=1, tool=git_diff
   4. [call] tool=git_diff, result=diff(staged): +12 -3 in src/user.py
   5. [decide] step=2, tool=read_file
   6. [call] tool=read_file, result=src/user.py: 第 42 行有删除逻辑
   7. [stop] reason=计划执行完毕
```

```
用户：帮我删掉这个用户
  skill: None   可见工具: 7
  结果:  操作被拦截：工具 delete_user 是危险动作，需人工审批
  trace:
   1. [request] msg=帮我删掉这个用户
   2. [skill_loaded] name=无, chars=0, tools=7
   3. [decide] step=1, tool=delete_user
   4. [blocked] tool=delete_user, reason=工具 delete_user 是危险动作，需人工审批
   5. [stop] reason=计划执行完毕
```

注意第二条的 `skill: None`——危险请求没命中任何技能，所以**全部 7 个工具都可见**。这就是为什么 Guard 必须独立于 SkillLoader：技能能收窄工具集，但不能代替安全检查。

---

## 54.3 核心机制：Skills 的渐进式加载

这是 SkillLoader 这一层的核心机制，也是**「Harness 到底怎么加载 skills」的正面回答**。

> 第 14 章讲了"怎么挑一个 Skill 来用"（使用者视角）。
> 这一节讲"加载器凭什么能做到按需"（实现者视角）。
> 两者看的是同一批文件，但问题不同：**第 14 章问"选哪个"，这里问"怎么只读该读的"。**

### 一句话

> **渐进式加载就是三步文件读取：先只读每个 Skill 的头部，命中后再读正文，正文提到资源时最后才读资源。**

### 最小例子：不装任何框架，30 行就够

💻 运行：`python code/ch14_skills/step2_progressive_loader.py`

这个脚本把"加载器"压到最小——只有 `glob` + 正则切 frontmatter + `read_text` 三件事：

```python
from pathlib import Path
import re

def read_meta(md: Path) -> dict:
    """L1：只切出 frontmatter，正文根本不读。"""
    text = md.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta

def scan(root: Path) -> list[dict]:
    """扫目录：只拿 name + description，这就是常驻上下文的那部分。"""
    out = []
    for md in sorted(root.glob("*/SKILL.md")):
        meta = read_meta(md)                      # ← 只读头部
        if meta.get("name") and meta.get("description"):
            out.append({"name": meta["name"], "desc": meta["description"], "path": md})
    return out

def load_body(skill: dict) -> str:
    """L2：命中之后才读全文，并去掉 frontmatter。"""
    text = skill["path"].read_text(encoding="utf-8")
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.S).strip()
```

**就这三件事。** 所有"技能目录""按需加载""上下文不爆"的说法，底层都是这三个函数。
真实实现里 `read_meta` 会换成 `yaml.safe_load`，`scan` 会换成带缓存的版本，`load_body` 会加上 token 计数——
但**结构完全一样**。

### 跑出来是什么样

脚本 ① 的输出（真实运行结果）：

```
① L1 扫描：只读 frontmatter，发现 3 个技能
  code-review   v1.2.0     48 token
  deploy        v2.0.1     42 token
  perf          v1.0.0     45 token

  L1 常驻成本合计：137 token
```

三个技能，常驻成本 137 token。作为对照，② 把它们**全部正文**也塞进去：

```
② 对照：如果把所有技能正文都塞进去
  全塞：137 + 848 = 985 token
  L1 only：137 token
  → L1 是全塞的 14%，省 86%
```

**这一步就是渐进式加载的全部原理：18% 的功能占 14% 的成本，剩下 86% 靠"命中才付"。**

看 ③ 的真实对话：

```
用户：帮我 review 一下这个改动
  → 命中 code-review（L2 加载正文 342 token）
  → 本次上下文 = L1 137 + 正文 342 = 479 token

用户：把这个服务部署到 staging
  → 命中 deploy（L2 加载正文 275 token）
  → 本次上下文 = L1 137 + 正文 275 = 412 token

用户：今天天气怎么样
  → 没命中任何技能，只用 L1（137 token）
```

注意最后一句：**没命中时只付 137 token。** 这就是"技能再多也不怕"的真正原因——
不是技能写得短，是**没用到的技能根本不进上下文**。

④ 把 5 句话加起来算总账：

```
全塞：每句 985 token × 5 句 = 4925 token
渐进：1533 token
→ 省 69%
```

单句最坏省 0%（每个请求都命中），最好省 86%（一个都没命中），平均下来 69%。

### 三层图

```
┌─────────────────────────────────────────────────┐
│ L1 元数据（常驻）                                 │
│   name + description                            │
│   ~30 token / 个 × N 个技能                      │
│   每一轮请求都在系统提示词里                       │
└─────────────────────────────────────────────────┘
                    │ 模型判断"要用哪个"
                    ▼
┌─────────────────────────────────────────────────┐
│ L2 正文（命中才加载）                             │
│   SKILL.md 的 ## 步骤 / ## 输出格式 ...          │
│   ~300 token / 个                               │
│   只加载命中的那一个                             │
└─────────────────────────────────────────────────┘
                    │ 正文里提到"跑脚本 X"
                    ▼
┌─────────────────────────────────────────────────┐
│ L3 资源（执行时才读）                             │
│   scripts/*.py, references/*.md, templates/*     │
│   按需，通常 >1k token                           │
│   读完可丢                                       │
└─────────────────────────────────────────────────┘
```

### 每一层的成本

| 层级 | 内容 | 何时加载 | 量级 |
|---|---|---|---|
| L1 元数据 | name + description | 常驻上下文，每轮都在 | ~30 token/个 |
| L2 正文 | SKILL.md 的步骤部分 | 命中技能时才读入 | ~300 token/个 |
| L3 资源 | 脚本/模板/参考资料 | 执行时才读，读完可丢 | 按需，常 >1k |

### 一次请求里发生了什么

```
① 扫 skills/ 目录，把 name + description 放进系统提示词（L1，常驻）
② 模型看到 L1，判断"要不要用某个技能"
③ 要用 → 调 load_skill(name) → 读全文 → 注入本轮上下文（L2）
④ 技能正文里若提到脚本/模板 → 执行时才读（L3）
⑤ 本轮结束，L2/L3 的内容可以丢弃（下轮重新判断）
```

**第 ⑤ 步是很多人搞错的地方**：如果把加载过的正文一直留在上下文里，几轮下来又变回"全塞"了。渐进式加载的前提是**不跨轮保留**。

### 为什么是三层，不是两层

如果只有"元数据 + 正文"两层，那些带着脚本和模板的复杂技能会把正文撑爆。

举个真实例子：一个"生成周报"的 Skill，正文只有 20 行，但它引用了：

- `references/周报模板.md`（800 字）
- `scripts/collect_data.py`（150 行代码）
- `references/去年周报示例.md`（2000 字）

如果这些都在 L2，这个技能一加载就是 3000+ token。但实际执行时，可能只需要模板，不需要脚本；或者只需要脚本，不需要去年示例。**L3 就是把"要不要读"再推迟一次**。

### ⚠️ 一个必须知道的坑：加载器只做"读取"，不做"判断"

新手最常见的误解是：*"我写了 description，加载器就会用它的关键词去匹配用户输入。"*

**不会。** 加载器的 `pick()` 里有一行注释写得很清楚：

```python
def pick(self, user_msg: str) -> SkillMeta | None:
    """判断触发哪个技能（真实实现交给模型；这里用触发词模拟）。"""
```

本仓库的脚本用「当用户说 A、B、C 时用」这句话里的词做**字符串包含匹配**，只是因为这样能离线跑、能稳定复现。
真实 Harness 里这一步**是模型自己读 L1 目录后决定**的——你无法预测它读到哪一句会决定加载。

这带来两个直接后果：

| 后果 | 说明 |
|---|---|
| **description 的写法直接决定命中率** | 它不是给人看的注释，是**唯一喂给模型的门牌**（第 14 章 14.4） |
| **触发不稳定时，先查 L1，不要改加载器代码** | 90% 的"技能不生效"是 description 没写触发条件，不是加载器有 bug |

> 💥 **失败实验**
> 把 `skills/perf/SKILL.md` 的 description 从
> `排查性能问题，量化变慢程度并定位瓶颈。当用户说变慢、超时、卡顿、延迟高、P99 飙高时用。不适用于功能开发。`
> 改成 `性能排查技能。`
> 重跑 `step2_progressive_loader.py` 的 ⑤：
>
> ```
> 坏①    0 / 5 句能触发   性能排查技能。…
> ```
>
> **注意：加载器一行代码都没改，技能也确实被扫到了（L1 里有它、算了 token），但它永远读不到正文。**
> 这就是"装配错误不报错"在 skills 上的版本：**技能存在、成本照付、功能为零。**

### ✏️ 停下来想一想

L1 常驻、不跨轮保留、命中才读——这三条合起来就能省 86%。
那**为什么不在第一轮就把所有技能正文读一遍，缓存起来，后面直接用？**

想清楚这个问题，你就懂了"上下文成本"和"磁盘 IO 成本"根本不是一回事：
缓存在内存/磁盘里是免费的，**放进上下文里每一轮都要重新付钱**。
下文的 54.6 ④ 给出了这个错误做法的实测曲线（6 轮从 653 涨到 3,233）。

---


## 54.4 案例：Harness 里的 skills 目录长什么样

> 这一节可以跳过。它把渐进式加载放到真实项目结构里看。

一个真实项目的 skills 目录大概是：

```
skills/
├── code-review/
│   ├── SKILL.md
│   └── references/
│       └── 常见反模式清单.md
├── deploy/
│   ├── SKILL.md
│   └── scripts/
│       └── check_canary.py
├── incident/
│   ├── SKILL.md
│   └── references/
│       ├── 复盘模板.md
│       └── 依赖拓扑.md
└── refund/
    ├── SKILL.md
    └── references/
        └── 退款政策.md
```

> 本仓库里的实例就是 `code/ch14_skills/skills/`（只有 L1 + L2 两层，
> 因为这三个示范技能都不带脚本和参考资料）。真实项目一般三层都用上。

启动时 Harness 做的事：

```python
# 每次请求开始时
metas = scan_skills("skills/")           # L1，只读 frontmatter
system_prompt += render_catalog(metas)   # name + description 进提示词

# 模型决定加载某个技能时
skill = load_skill(metas["deploy"])      # L2，读全文
context += skill.body

# 正文提到 scripts/check_canary.py 时
code = read(skill.path.parent / "scripts/check_canary.py")  # L3
```

几个实践细节：

- **frontmatter 要校验**：缺 `description` 的技能直接跳过并告警，不要静默失败
- **L1 要限长**：description 超过 200 字符时告警，否则 30 个技能就把提示词撑爆
- **记录加载日志**：哪个请求加载了哪个技能、多少 token，这是排查"为什么不生效"的唯一依据
- **技能也要版本号**：改流程时升版本，出问题能回滚

> 📎 想把这个目录跑起来看真实效果？它就在本仓库里：
> `code/ch14_skills/skills/`（code-review / deploy / perf 三个技能），
> 由 `code/ch14_skills/step2_progressive_loader.py` 扫描并加载。
> 第 54 章后面所有脚本都复用这批文件，没有第二个技能目录。

---


## 54.5 三个关键设计

### ① 每层可单独替换

这是分层的直接好处，54.2 的表格已经说明。补充一个具体例子：

假设下周你要把工具从本地改成 MCP，改动只有：

```python
# 之前
registry.register(Tool("query_order_status", ..., lambda oid: ...))

# 之后
registry.register_mcp("order-mcp", tools_list, handlers)
```

`SkillLoader` / `Guard` / `Loop` / `Trace` 一行都不用改。

### ② 工具名带来源前缀

```python
name=f"{server_name}__{spec['name']}"    # order-mcp__query_order_status
```

实跑的工具清单：

```
git_diff                      [local]
read_file                     [local]
run_test                      [local]
deploy_instance               [local]
delete_user                   [local]
order-mcp__query_order_status [mcp:order-mcp]
order-mcp__apply_refund       [mcp:order-mcp]
```

两个好处：

- **不重名**：两个 MCP 服务都有 `query` 时不会冲突
- **可追溯**：日志里一眼看出是谁提供的

### ③ skill 的 allowed-tools 收窄工具集

```
用户：帮我 review 这个改动
  skill: code-review   可见工具: 2
```

`code-review` 的 frontmatter 写了 `allowed-tools: read_file, git_diff`，所以可见工具从 7 个降到 2 个。

回顾第 13 章的结论：**工具数越少，选对率越高**。这里就是那个结论的落地方式——不是全局删工具，而是**按任务收窄**。

> 💥 **失败实验**
> 把 `step1_min_harness.py` 的 `run()` 里这段注释掉：
> ```python
> narrowed = [n for n in self.registry.tools if any(a in n for a in allowed)]
> tool_count = len(narrowed) if narrowed else tool_count
> ```
> 重跑，`可见工具` 会从 2 变成 7。
> **请求依然能跑对**，但你已经悄悄丢掉了第 13 章那个 +15% 的选对率提升。
> 这就是 54.1 说的"装配错误不报错"。

---

## 54.6 四种装配故障

`code/ch54_assembly/step2_assembly_faults.py` 逐个演示。

### ① 工具不分组

```
正确装配          可见工具  2 个
① 工具不分组       可见工具 12 个
```

后果不会立刻显现：当前这个请求照样跑对。但第 13 章实测过，工具数上去以后选对率明显下降。

排查方向：**打印模型实际看到的 manifest 长度**。超过 20 条就要警惕。

### ② Guard 在循环外

这是最危险的一种。

```
模型想依次调用：['git_diff', 'delete_user', 'user-mcp__delete_account']

正确装配          拦截 2 个，**放行危险 0 个** []
      [call] git_diff(local)
      [blocked] delete_user(local)
      [blocked] user-mcp__delete_account(mcp:user-mcp)
② Guard 在循环外    拦截 0 个，**放行危险 2 个** ['delete_user', 'user-mcp__delete_account']
      [call] git_diff(local)
      [call] delete_user(local)
      [call] user-mcp__delete_account(mcp:user-mcp)
```

错误装配下，`delete_user` 和 `delete_account` **都被执行了**。

为什么说最危险？因为**第一次确实被拦了**（`git_diff` 是第 1 步，被检查了）。如果测试用例只验证"危险操作会被拦"、且用例里危险操作在第 1 步，测试会**通过**。

真实项目里这等价于「用了几天才发现有张表被删了」。

修法：**Guard 必须在每一次工具调用前跑，不是每轮跑一次。**

### ③ trace 不记来源

```
正确装配：
    [call] git_diff(local)
    [call] order-mcp__query_order_status(mcp:order-mcp)
    [call] user-mcp__get_profile(mcp:user-mcp)

③ trace 无来源：
    [call] git_diff
    [call] order-mcp__query_order_status
    [call] user-mcp__get_profile
```

第二个日志里，工具名恰好带了服务前缀，所以你还能猜出来。但如果两个服务都暴露了 `query` 呢？

真正的坑在于：**MCP 服务是别人写的**。当 `order-mcp` 返回了错误数据，你要先花时间**猜**是哪个服务的锅——因为你没记。

### ④ L2 跨轮保留

```
轮次                正确装配         L2 跨轮保留
----------------------------------------
第 1 轮           653             653
第 2 轮           653           1,169
第 3 轮           653           1,685
第 4 轮           653           2,201
第 5 轮           653           2,717
第 6 轮           653           3,233
```

正确装配每轮恒定 653（L1 137 + 当前技能正文 516）。跨轮保留则每轮 +516。

这个 bug 最难发现，因为**前几轮完全正常**。等到上下文塞满，表现是"突然变笨"，而你还在改提示词。

> 💥 **失败实验**（这个实验会推翻你自己的假设）
> 把 `step3_acceptance.py` 的 `check_context_stable()` 改成：
> ```python
> ok = (last == first) if h.unload_l2 else (last > first)
> ```
> 这正是我第一版写的。看起来没问题——"卸载就恒定、不卸载就增长"。
> 但跑起来你会发现：**L2 跨轮保留的配置也 PASS 了**。
>
> 因为你把"配置对不对"和"现象是什么"混在同一个表达式里了。
> 正确写法只有一句：`stable = (last == first)`。
> 检查项要验证**性质本身**，不要替错误配置开脱。

---

## 54.7 把验收做成 CI

`code/ch54_assembly/step3_acceptance.py` 把上面四种故障变成可自动跑的断言。

### 五条检查

| 检查项 | 判据 | 正确装配 |
|---|---|---|
| ① 工具收窄 | 有 skill 时可见工具 < 全量 | 全量 7 → 可见 2 |
| ② Guard 在循环内 | 第 2 步起的危险工具也被拦 | 拦截 2/2 |
| ③ trace 带来源 | 每条 call 都有 source | 缺来源 0 条 |
| ④ 上下文恒定 | 第 6 轮 == 第 1 轮 | 653 → 653 |
| ⑤ 步数上限 | 上限存在、有限、能截断 | max_steps=5 |

实跑：

```
A. 正确装配
  检查项                 结果      详情
  --------------------------------------------------
  ① 工具收窄              PASS    全量 7 → 可见 2
  ② Guard 在循环内        PASS    拦截 2/2 个危险调用
  ③ trace 带来源         PASS    2 次调用，缺来源 0 条
  ④ 上下文恒定             PASS    第1轮 653 → 第6轮 653
  ⑤ 步数上限              PASS    max_steps=5，计划 5 步实际执行 5 步

  5 / 5 通过
```

### 差分判据：光"正确通过"不够

只验证"正确配置通过"是不够的——一个永远返回 PASS 的检查也能通过。

必须同时验证"错误配置失败"：

```
B. 逐个装错，看检查能不能抓到
  装错方式              失败的检查项                        结果
  ----------------------------------------------------------------------
  工具不分组             ① 工具收窄                        ✓ 抓到
  Guard 在循环外        ② Guard 在循环内                  ✓ 抓到
  trace 无来源         ③ trace 带来源                   ✓ 抓到
  L2 跨轮保留           ④ 上下文恒定                       ✓ 抓到
  无步数上限             ⑤ 步数上限                        ✓ 抓到

  5 种装错，抓到 5 种。正确装配 5/5 通过。
```

**两个条件都满足，这套检查才算可信。**

### 为什么值得进 CI

| 理由 | 说明 |
|---|---|
| 不需要模型 | 纯逻辑断言，不花 token，不引入随机性 |
| 毫秒级 | 每次提交都能跑，不拖慢流水线 |
| 差分判据 | 正确必须全过 + 错误必须失败，两条都验证 |
| 防回归 | 新人改 Harness 时误删 Guard，CI 立刻红 |

> 💥 **失败实验**
> 把 `check_step_limit()` 的判据从
> `bounded = 0 < h.max_steps <= 10` 改成 `bounded = h.max_steps > 0`。
> 重跑，`无步数上限`（`max_steps=99`）就**抓不到了**。
> 因为 99 满足"大于 0"，但它等于没有上限。
> **写检查时最容易犯的错，是判据太松。**

---

## 54.8 最少可跑的例子

```powershell
$env:PYTHONPATH="code"
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\ch54_assembly\step1_min_harness.py
.venv\Scripts\python.exe code\ch54_assembly\step2_assembly_faults.py
.venv\Scripts\python.exe code\ch54_assembly\step3_acceptance.py
```

全部离线，不需要 API Key。`step1` 依赖 `code/ch14_skills/skills/` 下的技能文件。

`step3` 那句 `assert` 是关键：

```python
assert n_good == len(CHECKS), f"正确装配应全部通过，实际 {n_good}/{len(CHECKS)}"
assert caught == len(faults), f"应抓到全部 {len(faults)} 种装错，实际 {caught}"
```

这两行就是"这套检查自己可信"的证明。**改 Harness 之后如果这两个 assert 挂了，说明你把某条边界弄丢了。**

---

## 54.9 练习

**练习 1（改代码，5 分钟）**
在 `code/ch14_skills/skills/` 下加一个新技能 `refund`，`allowed-tools` 写 `apply_refund, query_order_status`。
要求：(a) `step2_progressive_loader.py` 扫描时能看到它、L1 token 增加约 40；
(b) `step1_min_harness.py` 里请求"我要退款"时能命中它，且可见工具降到 2 个。
验收：两处输出都变了你才算做完——**只改目录不改 Harness，是新人最常犯的错**。

**练习 2（观察，10 分钟）**
把 `step1` 的 `Guard.check()` 里 `("delete", "drop", "truncate")` 改成只有 `("delete",)`。
重跑四个用例，观察 `user-mcp__delete_account` 会不会被放行。
再回答一句：这证明了"黑名单式 Guard"的根本问题是什么？

**练习 3（改加载器，20 分钟）**
`step2_progressive_loader.py` 里 `token_of()` 用 0.95 估中文 token 数。
把它换成"真数一遍字符"（`len(text)`），重跑 ②：
L1 占比会从 14% 变成多少？省的比例会变成多少？
再想一句：**为什么换成更"准"的算法后，结论方向完全没变？**

<details>
<summary>参考</summary>

因为 L1 和全塞是**同一把尺子量的两堆文本**，缩放系数会同时作用在分子分母上，
比值近似不变。这告诉你：**做对比实验时，绝对数值可以不准，只要口径一致。**
但反过来——如果 L1 用一套算法、全塞用另一套，你算出的 86% 就是假的。

</details>

**练习 4（故障注入，15 分钟，💥）**
模拟 54.6 ④ 的"L2 跨轮保留"。改 `step2_progressive_loader.py` 的 ③，加一个累加器：

```python
carried = 0
for q in QUERIES:
    carried += body_tokens          # 命中一次就永远留在上下文里
    print(f"本次上下文 = L1 {l1} + 已加载 {carried} = {l1 + carried} token")
```

连跑 6 轮（把 `QUERIES` 里前面几句重复 6 次），记录第 1 轮和第 6 轮的 token。
它应该和 54.6 ④ 那条曲线形状一致：**前几轮看起来"只多了一点"，第 6 轮才是灾难。**

**练习 5（设计）**
给你的项目写第 6 条装配检查。要求：能抓到一种前面五条抓不到的装错方式。
提示：想想"工具超时"、"一个请求触发两个 skill"、"trace 里 call 出现在 decide 之前"这几类。

<details>
<summary>参考方向</summary>

- **工具超时**：构造一个 sleep 3 秒的工具，断言 Guard 在 1 秒内切断
- **技能冲突**：请求同时命中两个技能，断言只加载一个且有告警
- **trace 顺序**：断言每条 `call` 前面必有一条 `decide`
- **黑名单漏网**（练习 2 的延伸）：断言 `truncate_*` / `drop_*` 也被拦

</details>

---

## 54.10 速查表

| 想做的事 | 做法 |
|---|---|
| 工具登记 | `registry.register(Tool(...))`，必填 `source` |
| MCP 工具登记 | `registry.register_mcp(server, tools_list, handlers)`，自动加前缀 |
| 加载技能 | `SkillLoader(root)` 扫目录，`pick()` 判断，`load()` 读正文 |
| 安全检查 | `guard.check(name, args)`，返回 `None` 放行 |
| 记录步骤 | `trace.add(kind, **kw)`，结构化 |
| 收窄工具 | skill frontmatter 的 `allowed-tools` |
| 工具重名 | 直接抛异常，不要静默覆盖 |
| 上下文必恒定 | L2 每轮卸载，只留 L1 |

装配验收清单（抄进你的项目）：

```
[ ] 有 skill 时工具数必须收窄，并在日志里打印实际可见数
[ ] Guard 在每一次工具调用前执行，不是每轮一次
[ ] 每条工具调用日志都带 source（local / mcp:服务名）
[ ] 每轮上下文 token 数应恒定，不能单调增长
[ ] max_steps 有上限，且超限时记录停止原因
[ ] 工具重名时直接报错，不要静默覆盖
```

---

## 54.11 自测：你真的懂了吗

**Q1** Harness 为什么必须分层？说两个具体好处。

<details>
<summary>参考</summary>
① 可替换：换工具来源只改 Registry，其他层不动；
② 可测：能单独验证"危险动作被拦"，不用跑到循环深处。
另外还有可观测：出问题能定位是哪一层。
</details>

**Q2** 为什么 Guard 不能放在循环外面（每轮只查一次）？

<details>
<summary>参考</summary>
因为一轮里可能调多个工具。只查第一次，第 2 步起的危险操作就完全没检查。
本章实测：错误装配放行了 `delete_user` 和 `delete_account` 两个危险调用。
</details>

**Q3** trace 里为什么要记 `source`？

<details>
<summary>参考</summary>
因为 MCP 服务是别人写的，出错时你必须知道是哪个服务提供的工具。
不记 source 就得靠猜，两个服务同名工具时根本无法区分。
</details>

**Q4** 什么叫"差分判据"？为什么只验证"正确配置通过"不够？

<details>
<summary>参考</summary>
差分判据 = 正确配置必须全过 + 错误配置必须失败。
只验证前者的话，一个永远返回 PASS 的假检查也能"通过"，抓不到任何问题。
</details>

**Q5** `max_steps=99` 为什么应该被判为"没有上限"？

<details>
<summary>参考</summary>
因为它实际上不会截断任何合理长度的计划，等价于没有限制。
本章的判据是 `0 < max_steps <= 10`，而 `> 0` 太松——失败实验里正是改松后漏抓了。
</details>

**Q6** 上下文"每轮恒定"和"逐轮增长"分别对应哪种实现？

<details>
<summary>参考</summary>
恒定 = L2 每轮卸载，只保留 L1（正确做法）。
增长 = L2 跨轮保留，逐轮累积（渐进式加载失效，最终退化成"全塞"）。
本章实测：跨轮保留在 6 轮后从 653 涨到 3,233。
</details>

---

## 54.12 案例：一次真实的装配翻车

> 这一节可以跳过。它把本章的四条故障放进一个真实故事里。

某团队上线了客服 Agent。三周后发现问题。

**症状**：用户投诉"它有时候会乱回答，而且越来越笨"。

**排查过程**：

1. 先看 trace。发现日志里只有工具名，没有来源。
   → **故障 ③**。花了两天才确定是 `product-mcp` 返回了过期库存。

2. 再看上下文长度。发现会话越长，token 越多，从 800 涨到 12000。
   → **故障 ④**。L2 没卸载，加载过的 skill 正文全留着。

3. 再看工具清单。发现一次塞了 34 个工具。
   → **故障 ①**。skill 的 `allowed-tools` 写了，但代码里没用。

4. 最后看安全。发现一个月前有一次 `delete_address` 被调用。
   → **故障 ②**。Guard 在循环外，第一个工具是查询（放行），第二个危险操作没检查。

**修复**：

| 故障 | 修法 | 验证 |
|---|---|---|
| ③ | 工具名加 `mcp:server__` 前缀 | 检查每条 trace 有 source |
| ④ | L2 每轮卸载 | 断言第 6 轮 == 第 1 轮 |
| ① | 接上 `allowed-tools` | 断言可见工具 < 全量 |
| ② | Guard 移进循环 | 断言第 2 步危险工具也被拦 |

**数字变化**：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 平均上下文 token | 6,400 | 1,100 |
| 投诉率 | 3.1% | 0.4% |
| 定位问题平均耗时 | 2 天 | 20 分钟 |

**最大的教训**：这四个 bug 全都没报错，全是"能跑"的。它们的共同点是**缺少断言**——不是缺代码，是缺"证明代码对"的东西。

---

## 54.13 可选补课：Harness 和框架的关系

你可能会问：LangChain / LangGraph 不是已经提供这些了吗？

| | 手写 Harness（本章） | 框架（42 章起） |
|---|---|---|
| 五层边界 | 你自己设计 | 框架预设 |
| 出问题 | 你知道每一行 | 要读框架源码 |
| 快速搭原型 | 慢 | 快 |
| 长期维护 | 边界清晰就好改 | 依赖框架升级 |

结论：**先手写一遍，再用框架**。手写过你才知道框架替你做了什么、省掉了哪一层、代价是什么。这也是本书把框架放到第 42 章之后的原因。

一句话：框架不是替你思考，是替你做重复劳动。你得先知道该思考什么。

---

## 54.14 沉淀：这一章你该记住的

**一个机制（本章新增的全节）**

Skills 的**渐进式加载三层**：L1 元数据常驻（137 token / 3 个技能，占"全塞"的 14%）
→ L2 正文命中才读 → L3 资源执行时才读，**且不跨轮保留**。
实跑 5 句话：全塞 4,925 token，渐进式 1,533 token，**省 69%**。

**一个结构**

五层：Registry → SkillLoader → Guard → Loop → Trace。每层的边界要清楚。

**一个原则**

**装配错误不报错。** 所以验收必须是断言，不是"跑个 demo 看看"。

**一个判据**

差分判据：正确配置必须全过 **且** 错误配置必须失败。两个都验证才算可信。

**一个数字**

L2 跨轮保留 6 轮后上下文从 653 涨到 3,233（+395%）。

**把本章装进 Harness**

这一章本身就是"装进 Harness"。到这里第一阶段结束：

| 部分 | 章 | 你有了 |
|---|---|---|
| 概念 | 01–10 | LLM / token / 提示词 / RAG / 检索 |
| Agent | 11–14 | Agent 零件 / 工具 / MCP / Skill 的使用 |
| 能力 | 16–41 | 可控 / 可信 / 敢做 / 可运营 / 可测量 |

这一章处在**最后一个能力段**（54–56）的入口：装配进 Harness。
第 55 章讲故障复盘，第 56 章把全书能力汇成一张体检表。

> 回到你最初的问题："harness 里怎么加载 skills / mcp / tools？"
>
> 完整答案现在有了：
> - **tools**：`Registry.register()`，写在代码里或从 MCP 发现
> - **MCP**：`mcp.json` 声明 → Client 连接 → `tools/list` → `register_mcp()` 批量登记
> - **skills**：`SkillLoader._scan()` 读 L1（只切 frontmatter）→ `pick()` 判断 → `load()` 读 L2 → 资源按需读 L3（54.3）
> - **收窄**：skill 的 `allowed-tools` 决定这次请求能看到哪些工具（54.5 ③）
> - **不跨轮保留**：L2 用完就丢，否则上下文单调涨（54.6 ④）

---

## 54.15 本章验收

跑完三个脚本，检查这五件事：

**① 正确装配 5/5 通过**

`step3` 的 A 段应该是 `5 / 5 通过`。

**② 5 种装错全部被抓**

`step3` 的 B 段应该是 `5 种装错，抓到 5 种`。
如果漏掉了某个，说明对应检查的判据太松——这正是 54.7 失败实验讲的坑。

**③ 你能说出渐进式加载省了多少、为什么省**

`code/ch14_skills/step2_progressive_loader.py` 的 ② 应该输出：

```
→ L1 是全塞的 14%，省 86%
```

而 ④ 的 5 句话总账应该是 `全塞 4925 token / 渐进 1533 token / 省 69%`。
**两个数字都要能解释**：86% 是"一句话都没命中"的极限，69% 是"3/5 命中"的真实均值。
如果你的实现只能背出 86%，说明你没意识到"命中时省 0%"这件事。

**④ 你能解释"为什么跨轮保留最难发现"**

因为**前几轮完全正常**。看 `step2` 的 ④ 表格：第 1 轮 653 → 第 2 轮 1169，看起来只是"多了一点"，到第 6 轮才 3233。

**⑤ 你能说出四种故障各缺什么断言**

| 故障 | 缺的断言 |
|---|---|
| ① 工具不分组 | 可见工具数 < 全量 |
| ② Guard 在循环外 | 第 2 步危险工具也被拦 |
| ③ trace 无来源 | 每条 call 有 source |
| ④ L2 跨轮保留 | 第 6 轮 token == 第 1 轮 |

五件事都能独立完成，这一章就过了。到这里，你已经有一个**能跑、能测、能定位问题**的 Harness。

---

**下一章预告**：第 55 章 故障复盘方法论。装配好的东西总会在某个深夜出一次事故，
这一章教你把一次事故变成一条**可回归的用例**，而不是一份没人看的道歉邮件。
