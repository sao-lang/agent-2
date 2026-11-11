# 任务单：Harness 框架多版本残留清零（单版本收敛）

> 把本文件全文作为提示词发给新会话即可开工。

---

你是本仓库的维护 Agent。上一轮已把 44 项接线断点全部修复并升版判据（v1.2，commit `952cf8e`）。
本轮任务：**消灭框架内全部多版本残留**——每一处残留合并成一个完整的最新的版本；
如果有多套实现，只保留最合理的一套（合并方向已定为 **保留 v3 线**，见下）。
范围严格封闭，不要重新发散审计。

## 基线（开工前先验证，勿重算）

- 仓库根：`C:/Users/30895/Desktop/agent-2`，分支 `harness-only`，HEAD = `952cf8e`
- `python tools/verify_harness.py` → `GATE OK`（快照一致 + 338 unittest 全绿 + 冒烟通过）
- `python tools/audit_harness.py --check docs/harness/audit-report.json` → `CHECK OK`（判据 v1.2）
- 权威文档：`docs/harness/AUDIT-断点-重复实现-版本说法统计.md`（§2 多份实现、§4.3 合并处方、
  §6.5 backlog BL-1~BL-7 就是本轮清单）；`docs/harness/CHANGELOG.md` 记录代际变更

## 残留清单与合并方向（只做这些）

1. **Actor 双实现**：`parts/actor.py`（v1：resilience/model_call 插点）vs
   `parts/actor_v2.py`（v2：propose/execute/review + usage 落账）。
   合并为单一 `parts/actor.py`：以 v2 的 propose/execute/review 语义为主体，
   保留 v1 的 resilience 与 model_call 插点能力；删 `actor_v2.py`，更新全部引用。
2. **策略类两代**：`parts/body/{react,workflow,pe}.py`（v1，`next_step(state,ctx)`
   自含记账）vs `parts/policy/policies.py`（v2，转发 `scope.actor.propose`）。
   合并到 `parts/policy/policies.py`；**先把 pe 版的 replan + `budget.replans`
   能力移植进去**，再退役 `parts/body/*` 策略类（BL-1）。
3. **legacy 桥**：`kernel/legacy.py` 的 `run_legacy`/`LegacyProgram`/`CallbackRunner`
   是 v2 兼容桥。退役它，`Harness.run` 改为直连 `Runtime`/`interpret`（v3 通用解释器）；
   `run_stages` 四段链能力保留（v1 执行已走它）。
4. **装配线两条**：v1 线（`assembly/agent.py` 的 `Agent`、`assembly/build.py` 的
   `build/AgentConfig`、`assembly/presets.py`）vs v3 线（`assembly/harness.py` 的
   `Harness`/`build_harness`、`assembly/config.py` 的 `HarnessConfig`、
   `assembly/fpresets.py`）。**只保留 v3 线**；v1 Agent 独有能力（retrieval/memory/
   knowledge/validator/tracer/resilience 等槽位）凡被测试或冒烟依赖的，并入
   `HarnessConfig`/`Harness` 槽位；退役 v1 三件套（BL-2/BL-3）。顶层 `__init__.py`
   只导出 v3 入口。
5. **Tracer-事件双轨**（BL-4）：统一到 `RunEvent`+EventSink；退役 `TraceEvent`+
   3 Tracer span 制（`JsonlTracer` 的事件格式断言一并迁移）。
6. **代际标识清除**：`name="agent_v1"`、`name="legacy"`、`LegacyProgram`、
   代码内严格代际词注释（strict 口径当前 ≈80 行/32 文件）随上述合并一并清除（BL-5）。
7. **测试双轨断言改造**（BL-7）：`test_replacement.py`、`test_compat.py`、
   `test_core.py`、`test_assembly.py`、`test_presets.py`、`test_supplement.py` 等
   绑死 v1 API 的测试，随单版本 API 迁移断言（迁移到 v3 入口的等价行为）。

## 硬约束（违反即视为失败）

- 每完成一组改动立刻跑 `python tools/verify_harness.py`，**GATE OK 才能进下一组**；
  禁止批量改完再跑。每阶段报告：改了哪些文件、为什么、门禁结果。
- 338 个 unittest 必须全绿。允许随单版本 API 迁移测试断言（v1 入口 → v3 入口的
  等价行为），但**禁止删除、跳过、放宽测试来凑绿**；退役兼容壳时，其对应测试
  一并迁移并在变更清单里显式记录，保持等价覆盖。若某测试本质是「验证 v1 线存在」
  （如 test_compat 的兼容性测试），随壳退役而迁移为「v3 等价行为」断言，并记录。
- 改 `src/` 必然导致 `--check` 报「代码指纹变化」：预期行为，按提示执行一次
  `python tools/audit_harness.py --json docs/harness/audit-report.json` 重生成快照
  并记录。版本说法命中数下降是修复效果，不算判据漂移。
- **判据升版只做一次，放在全部合并之后**：显式升 `AUDIT_SPEC_VERSION`（v1.2 → v1.3）
  → 按 §6.5 流程更新锚点（断点态锚点此时应为修复/合并态）→ 重生成快照 →
  更新 AUDIT 文档状态 → 跑门禁。
- 不得即兴新增审计判据或新断点。发现疑似新问题 → 登记 §6.5 backlog，不即时处理。
- 不改 `docs/plan/` 下任何 PatchPilot 文档，不改 `.workbuddy/` 下的记忆文件。
- 若单轮无法完成：停在**阶段边界**、保持 `GATE OK`，把剩余条目登记进 §6.5 backlog
  并报告进度（沿用 BL 编号续接），便于下个对话续接。

## 建议推进顺序（每组一个门禁点）

1. Actor 合并（风险最低、是后续两组的依赖）
2. 策略类合并（依赖 Actor 单一化）
3. legacy 桥退役（依赖 1/2 的统一执行线）
4. 装配线收敛（最大件：v1 Agent 槽位并入 HarnessConfig + 顶层测试迁移）
5. Tracer-事件统一
6. 代际标识清除
7. 判据升版 v1.3 + AUDIT/CHANGELOG 更新 + 终验

## 最终交付

1. `GATE OK` + `CHECK OK`（判据 v1.3），快照与代码一致，338 tests 全绿（等价迁移后）。
2. 变更清单：每处残留的合并结果（保留哪套、吸收了哪些能力、删了哪些文件）、
   退役壳与对应测试的迁移记录、收敛后的目录结构。
3. AUDIT 文档 §0.2 与 §6.5 更新：BL-1~BL-7 逐条标注「已完成」或「剩余+原因」；
   CHANGELOG 增补单版本收敛条目。
4. 若有条目确实无法在本轮完成，明确列出原因与替代方案，禁止静默跳过。
