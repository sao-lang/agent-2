# 前 12 章重构契约（v11）

> 本文件是一次性施工说明，不是书稿。写前 12 章的所有人（包括子代理）都必须先读它，
> 以及 `OUTLINE.md` 第四、六节与 `docs/WRITING-SPEC.md` 全文。
>
> 目标：把第 0–12 章按 `docs/PLAN-v11.md` 的结构重排，并补上真实技术栈示例，
> 让读者第二天能照着学、照着跑。

---

## 一、目标结构（本轮只动第 0–12 章）

| 章 | 文件 | 卷 | 知识点 | 示例目录 |
|---|---|---|---|---|
| 0 | `00-agent的差别.md` | 起点 | — | `code/knowledge/ch00_start/` |
| 1 | `01-一次调用的四个字段.md` | 1 一次调用 | A1 A2 | `code/knowledge/ch01_call/` |
| 2 | `02-模型为什么编为什么忘.md` | 1 | A3 A7 | `code/knowledge/ch02_generation/` |
| 3 | `03-token成本与上下文窗口.md` | 1 | A4 A5 A6 | `code/knowledge/ch03_tokens/` |
| 4 | `04-提示词工程从规则到结构化输出.md` | 1 | A8 A9 | `code/knowledge/ch04_prompt/` |
| 5 | `05-用pydantic定义输出结构.md` | 1 | A8 的契约层（新） | `code/knowledge/ch05_pydantic/` |
| 6 | `06-工具调用模型只会说不会做.md` | 2 最小 agent | B1 | `code/knowledge/ch06_tools/` |
| 7 | `07-最小循环与三种终止.md` | 2 | B2 | `code/knowledge/ch07_loop/` |
| 8 | `08-循环的四种失控.md` | 2 | B3 B4 B5 | `code/knowledge/ch08_runaway/` |
| 9 | `09-LangChain包结构与消息.md` | 3 LangChain（agent 侧） | F1 F2 | `code/knowledge/ch09_lc_basic/` |
| 10 | `10-LangChain组合与解析器.md` | 3 | F3 F4 F5 | `code/knowledge/ch10_lc_compose/` |
| 11 | `11-LangChain工具定义与绑定.md` | 3 | F6 | `code/knowledge/ch11_lc_tools/` |
| 12 | `12-LangChain的Agent与中间件.md` | 3 | F8 F9 F10 | `code/knowledge/ch12_lc_agent/` |

第 13 章以后**本轮不动**。旧第 8–12 章已挪到 `chapters-pending/`，等 v11 全量重排时再归位。

---

## 二、章号引用规则（最容易出错的地方）

第 0–12 章正文里只允许出现**第 0–12 章**的章号。指向第 13 章以后的引用，一律**只写章名，不写编号**：

| 写法 | 例子 |
|---|---|
| 合格 | "后面的「沙箱」一章会处理执行边界" |
| 合格 | "持久化一章里，这个问题变成幂等键放在哪" |
| 不合格 | "第 20 章的沙箱拦的是执行" |
| 不合格 | "第 42 章讲计量" |

章内旧编号 → 新编号（改写旧文时按这张表替换）：

| 旧 | 新 | 主题 |
|---|---|---|
| 5 | 6 | 工具调用 |
| 6 | 7 | 最小循环 |
| 7 | 8 | 四种失控 |
| 8 | 22（本轮不写） | 编排范式 |
| 9 | 23（本轮不写） | 反思与外部裁判 |
| 10 | 24（本轮不写） | 状态 |
| 11 | 25（本轮不写） | 持久化与幂等 |
| 12 | 26（本轮不写） | 能力供给 |
| 27 | 42（本轮不写） | 计量与可观测 |

第 13 章以后的主题，用名字指代：分流、RAG 四环节、切块、向量化、检索质量、上下文装配、长期记忆、知识治理、沙箱、护栏、注入、审批、多智能体、对外形态、交付、计量、RAG 评测、Agent 评测、门禁、成本与复盘。

---

## 三、示例技术栈（本轮最大的改动）

`docs/AUDIT-CODE-GAPS.md` 的结论是：已写章节对第三方库的依赖是 0，需要真实库的章节全部用近似替代。本轮按章补：

| 章 | 必须出现的真实库 | 说明 |
|---|---|---|
| 1 | `openai` SDK | 请求体、响应对象、`model_dump()`、`usage` |
| 2 | `openai` SDK | `temperature`/`top_p` 真实进请求体；采样分布仍是原理演示 |
| 3 | `tiktoken` | 三种文本的真实 token 数；估算误差表 |
| 4 | `openai` SDK + `pydantic` | 五种结构化输出做法各一段真实调用 |
| 5 | `pydantic`、`pydantic-settings` | 校验、错误回灌、schema、配置 |
| 6 | `openai` SDK + `langchain` | 真实 `tools=` 往返；`bind_tools` 对照 |
| 7–8 | 标准库 | 主题是循环语义，不引入库 |
| 9–12 | `langchain` 1.4.7 | 真实 API，逐个参数讲 |

### 3.1 没有 API key 时怎么跑真实 SDK

两个脚本化后端已经写好并通过验证，**每个示例目录复制一份，不跨章 import**：

- `code/knowledge/_common/fake_server.py`：起一个本机 HTTP 服务，按脚本回放 OpenAI 兼容响应；`client_for(base_url)` 返回真实 `openai` 客户端（`httpx.Client(trust_env=False)`，绕过系统代理）。
- `code/knowledge/_common/scripted_chat.py`：给 `ChatOpenAI` 换一个 `httpx.MockTransport`，请求照常编码，响应来自脚本。

复制到章节目录后直接 `from fake_server import scripted_server, chat_completion, tool_call, client_for`。

**硬规定**：

1. 正文里必须写明"脚本化后端，原理演示，不是模型实测"，并给出换真实服务时改哪一行。
2. 不许把脚本里写死的文本说成"模型输出"。
3. 换真实服务的写法要出现在正文：`OpenAI(base_url=..., api_key=...)` / `ChatOpenAI(model=..., api_key=..., base_url=...)`。

### 3.2 运行约定（Windows）

```powershell
$env:PYTHONIOENCODING='utf-8'
python code/knowledge/chNN_xxx/script.py
```

- 依赖已装：`openai`、`langchain` 1.4.7、`tiktoken`、`pydantic`、`langgraph`。
- 无外网、无 API key；`httpx` 默认走系统代理（`127.0.0.1:7897`），本机回环必须 `trust_env=False`，否则 502。
- 脚本自己建临时目录用 `tempfile.mkdtemp()`，不要往 `%TEMP%` 直观写死路径；符号链接不可用，需要硬链接时用 `os.link`。
- 每个脚本必须从仓库根目录单独运行就出全部输出，不留交互输入。

---

## 四、写法硬约束（WRITING-SPEC 的浓缩，违反即返工）

### 4.1 骨架

每章按因果链展开：**缺什么 → 成因 → 怎么补 → 做法对比 → 会怎么坏 → 边界**。六件事都要有，顺序不能倒。

### 4.2 固定三处

1. 章首四行元信息：

```markdown
> **知识点**：A1 一次调用的完整生命周期；A2 `finish_reason` 的取值与分支
> **本章回答**：……
> **示例目录**：`code/knowledge/ch01_call/`
> **读完应当能回答**：……
```

2. 正文后：`## 这一章建立的 N 件事`（N 与条目数一致）。
3. 末尾：`## 下一章`，接下一章的问题，**不写"本章小结"**。

### 4.3 代码与输出

- 每种做法一个**完整可运行**的代码块，后面紧跟它的**真实输出**，再跟一句"这段说明了什么"。
- 代码块必须能单独 `compile()`；不许省略号函数体、裸 `return`。
- 失败案例要贴真实失败输出。
- 正文代码块与 `code/` 里的脚本是同一份代码（允许删掉与本节无关的函数）。

### 4.4 标题

- ≤ 12 字，名词或名词短语，不用比喻、引号强调、emoji、评价词（"最""关键""真正"）。
- 同一章不要所有标题一个句式。
- 标题里的词必须在正文里能找到。

### 4.5 内容红线

| 不许 | 判定 |
|---|---|
| 场景叙事 | 有具体的人、对话、时间点、时长 |
| 把系统说成人 | "模型看见""系统扛住""上下文记住" |
| 无源数字 | 说不出跑在哪一行代码 |
| 同一结论换措辞说三遍 | 删掉一段读者不损失 |
| 平均用力 | 所有小节等长、同结构 |
| 凑字数 | 删掉后读者不损失任何东西 |

主线正文（第 1–8 章）**不得出现**：harness、插点、契约、组件封装、`Harness` 类名。第 9–12 章可以出现 LangChain 的 API 名与类名，但每出现一个都要能回答"它替代的是第几章手写过的什么"。

### 4.6 篇幅

每章正文 **9000–12000 个中文字符**（不含代码块与表格）。计数方法：

```powershell
$env:PYTHONIOENCODING='utf-8'
python -c "import re,sys; t=open(sys.argv[1],encoding='utf-8').read(); t=re.sub(r'```.*?```','',t,flags=re.S); t=re.sub(r'^\|.*$','',t,flags=re.M); print(len(re.findall(r'[\u4e00-\u9fff]',t)))" 01-一次调用的四个字段.md
```

不够就补"为什么必然如此"，不许补背景与复述。

---

## 五、验收清单（提交前逐章过）

- [ ] 章首四行元信息齐全，知识点编号与 OUTLINE 对得上
- [ ] 因果链六件事都在，顺序正确
- [ ] 每个代码块可单独 `compile()`
- [ ] 每个代码块的输出是跑出来的（重跑一遍核对）
- [ ] 章号引用只出现 0–12，或写成章名
- [ ] 标题 ≤ 12 字、名词短语
- [ ] 无红线词：场景叙事、拟人、无源数字
- [ ] 中文字符数在 9000–12000
- [ ] `## 这一章建立的 N 件事` 与 `## 下一章` 都在
- [ ] 示例目录里的脚本能单独跑通

---

## 六、不要碰的东西

- 第 13–31 章文件、`chapters-pending/`、`OUTLINE.md`、`README.md`、`docs/` 下的其他文件
- 其他人的章节目录
- `.git` 操作（提交由主线统一做）
