# V1.10 Runtime Context Governance

V1.10 为数学自学平台的每轮学习 turn 增加 Runtime Context Governance。它只编排并审计上下文，不拥有或改写学习事实。

## 状态

| Issue | 状态 | 已交付 |
| --- | --- | --- |
| #125 | 已完成 | `context_governance` overview、`LearningTurnContext` 引用、TeachingTrace expert evidence |
| #126 | 已完成 | Evidence priority、non-clippable KT facts 与 clipped / omitted 审计 |
| #127 | 已完成 | Intent-specific mounted / skipped / blocked tool decisions |
| #128 | 已完成 | Selected-only、脱敏的 response / LLM context package |
| #129 | 已完成 | 专家侧 Context Governance overview 与工具/裁剪审计 |
| #130 | 已完成 | 三类数学学习 intent 的 governance demo 闭环 |
| #131 | 已完成 | default fallback、仓库安全与 V1.10 文档收口 |

## 不变边界

- KT / DGEKT facts 是掌握度、薄弱点、预测概率和遗忘风险的权威来源。
- RAG 只支持数学讲解和 citation，不能覆盖 KT / DGEKT facts。
- 学生记忆只影响教学策略和表达，不能修改学习事实。
- Runtime Context Governance 与 LearningTurnContext 只保存引用和审计摘要，不能写 progress、KT/DGEKT、RAG、memory 或 LearningContextLayer。
- 默认 local fallback 保持可运行；真实 DGEKT、Mem0 和 RAG provider 均为显式 opt-in。

## 版本边界

V1.10 是 Runtime Context Governance 与条件工具挂载版本：每轮明确记录看什么、裁什么、挂什么，以及未来 response / LLM 可消费的脱敏 context package。它不要求真实 DGEKT checkpoint、Mem0、VikingDB、OpenViking、真实 LLM 或完整 ASSISTments2017 数据。

V1.11 才处理生产 readiness、真实 provider 连续验证和内部试用 gate。V1.10 的 provider readiness 仅影响 mounted/skipped/fallback 的只读审计，绝不写入学习状态。

## #125 验证

```bash
python3 -m pytest backend/tests/test_runtime_e2e_safety.py -q
```

## #126 验证

`context_governance` 标准化输出 `evidence_priority_rules`、`non_clippable_evidence`、budget policy 和每个 selected / clipped / omitted 资产的原因。实际排序与预算裁剪仍由 LearningContextLayer 的单一 `priority_budget_summary` 策略执行。

```bash
python3 -m pytest backend/tests/test_runtime_e2e_safety.py backend/tests/test_learning_context.py -q
```

## #127 验证

Runtime 为每个工具输出 `mounted`、`skipped` 或 `blocked` 及稳定原因。`answer_submission` 保留 KT/DGEKT 与当前题目讲解证据；`next_step_advice` 保留 KT、推荐、RAG 和记忆的 observation；概念讲解不挂载答题诊断工具，只在有可用证据时使用 RAG 或记忆。Provider readiness 只影响 observation、fallback 和跳过原因，不能写入学习状态。

```bash
python3 -m pytest backend/tests/test_runtime_tool_registry.py -q
```

## #128 验证

`response_context_package` 是未来 response generator / LLM 的唯一结构化上下文入口：仅包括 KT/DGEKT authoritative facts 与 selected task/RAG/memory evidence，明确每类 authority boundary，排除 debug evidence、工具日志、provider raw payload 和未选资产。禁用与删除的记忆不会进入 package；package 只读，不能回写学习状态。

```bash
python3 -m pytest backend/tests/test_runtime_e2e_safety.py backend/tests/test_runtime_tool_registry.py -q
python3 -m compileall -q backend/app/runtime
```

## #129 验证

Dashboard 仅消费后端标准化的 `context_governance` overview：展示 budget、selected/clipped evidence 数、priority rules、mounted/skipped/blocked 工具和中文原因。治理详情位于专家侧 TeachingTrace 面板；学生主回答不展示 debug evidence、工具日志或 provider raw response。

```bash
cd frontend && npm test -- --run
cd frontend && npm run build
```

## #130 验证

`answer_submission`、`next_step_advice` 和 `general_chat` / 概念讲解均产生 governance overview 与 response context package，但工具集合不同：做题保留 KT/DGEKT，下一步建议保留三类观测，概念讲解跳过答题诊断。学生回答不暴露治理或 debug 内容。

```bash
python3 -m pytest backend/tests/test_v11_demo_flow.py -q
```

## #131 最终验收

V1.10 保持默认 local fallback：不需要真实 DGEKT checkpoint、Mem0、VikingDB、OpenViking、真实 LLM 或完整 ASSISTments2017 数据。RAG、Memory、provider readiness、tool mount 与 Context Governance 均只读，不会覆盖 KT/DGEKT facts 或写入 progress。

```bash
python3 -m pytest backend/tests -q
cd frontend && npm test -- --run
cd frontend && npm run build
python3 scripts/check_repository_safety.py
git diff --check
```

最终结果：后端 `207 passed, 4 skipped`；前端 `20 passed`；repository safety `0` violations。跳过项是明确 opt-in 的 live provider smoke，不影响默认 local fallback。
