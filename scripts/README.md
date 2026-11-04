# scripts/ — 构建与检查脚本

本目录集中所有脚本。搬到这里之前，它们散在仓库根目录（`_*.py`）和 `docs/`（构建/检查脚本）里。

**目录职责**：根目录只放章节正文，`docs/` 只放书的结构与规范，`code/` 只放可运行示例，脚本一律在 `scripts/`。

---

## 一、路径约定（改目录前必读）

所有脚本都用同一种方式定位仓库根：

```python
ROOT = Path(__file__).resolve().parent.parent   # 从 scripts/ 上跳两级 = 仓库根
```

所以：

- **必须在仓库根目录运行**，形如 `python scripts/check_nav.py`；在 `scripts/` 里直接 `python check_nav.py` 会找不到 `docs/book.json`。
- `scripts/` 与 `docs/` 是同深度目录，这次搬家没有改动任何一个 `ROOT` 计算。**如果再往下建子目录（如 `scripts/book/`），这 10 个脚本的 `parent.parent` 都要改成 `parent.parent.parent`。**
- 例外：`audit_code.py` 用 `Path(".")`，即依赖当前工作目录。

## 二、两类脚本

| 类别 | 文件 | 用途 | 是否长期保留 |
|---|---|---|---|
| **书流水线** | `gen_book.py`、`check_*.py`、`lint_prose.py`、`audit_*.py`、`trim_*.py` | 生成目录/章首/章末、结构与导航校验、风格与锚点机检、精简施工 | 是，属于构建工具 |
| **写作期小工具** | `_dup.py` `_h2.py` `_meta.py` `_para.py` `_progress.py` `_sec.py` `_stat.py` `_tail.py` `_titles.py` | 写某一章时临时用来统计字数、查重复、列出标题、看段落 | 否，一次性，可随时删 |

## 三、常用命令（都在仓库根执行）

```bash
python scripts/gen_book.py build          # 改完 docs/book.json 后重建 INDEX.md 与各章章首/目录/章末
python scripts/gen_book.py build --dry    # 只看将要发生的改动
python scripts/gen_book.py index          # 只重建 docs/INDEX.md
python scripts/gen_book.py new 33         # 按当前标准创建第 33 章骨架（不覆盖已存在文件）

python scripts/check_nav.py               # 章号/标题/文件名/章首/目录/章末链接/INDEX 同步
python scripts/check_chapters.py --all    # 篇幅、结构、表格、代码块、章号引用
python scripts/check_ch01_12.py           # 前 12 章的机械项
python scripts/check_flow.py 08           # 连贯性（孤儿指代、指向已删表格、空壳小节）
python scripts/check_reader.py 08         # 四类锚点
python scripts/lint_prose.py --all        # 散文风格十项指标

python scripts/trim_all.py --vol1to3      # 一章四检一次跑完（lint / reader / chapters / verify）
python scripts/trim_verify.py 04 --base HEAD
```

## 四、改动本目录时的注意点

1. **`trim_all.py` 会用子进程调用另外四个脚本**，路径写成 `scripts/*.py` 的字面量（第 54–66 行）。改名或再搬目录时，这几处要一起改。
2. **`check_nav.py` 通过 `sys.path.insert` 从同目录 `import gen_book`**，所以这两个文件必须留在同一个目录。
3. **`gen_book.py` 生成 `docs/INDEX.md` 时会写入命令字面量**（`python scripts/gen_book.py index`）。改命令写法的入口在生成器里，不要只手改 `docs/INDEX.md`——下次 `build` 会把旧写法补回来。
