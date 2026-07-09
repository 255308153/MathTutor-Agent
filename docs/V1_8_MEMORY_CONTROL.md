# MathTutor Agent V1.8 学生记忆控制

本文档说明 V1.8「学生记忆查看、禁用与清理控制」模块的用户流程、API / provider 行为、安全规则和验收 gate。该模块是 V1.8 内部正式试用准入的一部分，但不等于完整 V1.8 内部正式试用已经完成。

## 1. 模块定位

V1.8 记忆控制让学生可以在学习驾驶舱中查看自己的长期记忆，并对单条记忆执行禁用、重新启用或删除。控制结果只影响这条记忆是否进入后续检索、上下文资产和推荐策略，不改变 KT facts。

核心边界保持不变：

```text
KT facts are authoritative.
Offline attribution explains prediction, not overwrite prediction facts.
Memory can influence strategy, not mastery.
RAG can support explanation, not overwrite prediction facts.
Context can assemble evidence, not decide learning facts.
```

也就是说，长期记忆可以影响讲解风格、偏好、复习策略和推荐理由，但不能改写 mastery、prediction probability、weak concepts 或 forgetting risk。

## 2. 学生端流程

学习驾驶舱的「长期记忆」面板支持：

1. 刷新记忆列表：读取当前学生的可见长期记忆，展示摘要、类型、来源、新鲜度、启用状态、证据和 provenance。
2. 查看详情：点击某条记忆后，右侧详情区展示该记忆的公开字段；raw provider payload、embedding、SDK debug response、secret 等字段不会下传。
3. 禁用记忆：禁用后记忆仍可在只读列表中看到，但默认学习检索和 context assembly 会排除它。
4. 重新启用记忆：重新允许该记忆参与后续检索、context assets 和策略推荐。
5. 删除记忆：删除后普通列表、详情、检索和后续 context assembly 都不再返回该记忆；provider 不支持 hard delete 时，adapter 只能在 provider metadata tombstone 成功后才把本地 tombstone 标为成功。

disabled memory 会作为 omitted context asset 记录排除原因；deleted memory 不进入 active context asset 集合。两者都不能影响 KTDiagnosis 或 progress facts。

## 3. API contract

记忆控制 API 位于 FastAPI `/api` 下：

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| `GET` | `/api/students/{student_id}/memories` | 返回学生可见长期记忆列表，默认包含 enabled / disabled，不包含 deleted。 |
| `GET` | `/api/students/{student_id}/memories/{memory_id}` | 返回单条记忆详情；deleted 或不存在返回 404。 |
| `POST` | `/api/students/{student_id}/memories/{memory_id}/disable` | 禁用单条记忆，并记录 actor / reason。 |
| `POST` | `/api/students/{student_id}/memories/{memory_id}/enable` | 重新启用单条记忆，并记录 actor / reason。 |
| `DELETE` | `/api/students/{student_id}/memories/{memory_id}` | 删除或 tombstone 单条记忆，并记录 actor / reason。 |

控制请求体：

```json
{
  "actor": "student",
  "reason": "学生在记忆控制面板中禁用该记忆。"
}
```

Provider 操作失败时，查看、禁用、启用和删除 API 返回 recoverable `503`，`detail` 使用结构化字段：

```json
{
  "code": "provider_timeout",
  "category": "provider_timeout",
  "provider": "mem0",
  "operation": "memory_control",
  "message": "mem0 memory_control failed: provider timed out",
  "recoverable": true,
  "actionable_hint": "provider timed out; local flow continues without waiting for provider evidence"
}
```

前端会把 `message` 和 `actionable_hint` 展示给学生 / 操作者。普通学习事件流仍走降级路径：provider control 失败不能中断 `/api/events`，也不能伪造控制成功。

## 4. Provider 模式

| 模式 | 记忆控制行为 | 默认性 |
| --- | --- | --- |
| `local_fallback` | 使用进程内 `InMemoryStudentMemoryStore`；list/get/disable/enable/delete 全部可运行；默认 demo/mock 走这条路径。 | 默认。 |
| `fake_provider` | 使用无网络、无密钥 fake provider，复用同一套 control contract tests，模拟 provider-backed memory 但只返回稳定领域模型。 | 仅测试 / adapter 开发显式启用。 |
| `live_provider` / Mem0 | 显式启用 `Mem0StudentMemoryStore`；write/search 保持可恢复 fallback，控制/删除失败返回结构化 recoverable error，不伪造成功。 | opt-in，非默认。 |

Mem0 仍是 opt-in provider：

```bash
export MATHTUTOR_MEMORY_PROVIDER_MODE=live_provider
export MATHTUTOR_MEM0_API_KEY=...
```

默认 `local_fallback` 不需要 Mem0 SDK、API key 或网络。Mem0 live control smoke 还需要显式设置：

```bash
export MATHTUTOR_RUN_MEM0_LIVE_SMOKE=1
```

未设置 smoke 开关或缺少 API key 时，live smoke 默认 skip。默认 backend/frontend 测试不得依赖 Mem0、VikingDB、OpenViking、真实 checkpoint 或 full data。

## 5. 失败处理与边界

Provider 查看或控制失败时：

- API 返回结构化 recoverable `503`，不泄露 provider credential、secret、raw payload 或 embedding。
- 前端保留原列表状态，并展示可恢复提示。
- 学习事件 `/api/events` 继续运行；缺少 provider memory 时只记录 provider evidence gap。
- Mem0 control failure 不改变 provider 侧状态，也不在本地伪造 disabled / deleted。
- Mem0 delete 只有在 hard delete 成功，或 metadata tombstone update 成功后，才把本地 tombstone 视为成功。

Context 和 KT 边界：

- disabled memory 不进入 selected `student_memory` context assets。
- deleted memory 不进入 active context assets。
- memory evidence 中即使包含 `mastery_by_concept`、`prediction_probability`、`weak_concepts` 或 `forgetting_risks` 字段，也只能作为普通 evidence 被展示或清洗，不能覆盖 KTDiagnosis。
- `assembled_context.authoritative_kt_facts` 必须与 KTDiagnosis 一致。

## 6. 安全禁提交规则

提交前必须保持 repository safety 通过，禁止提交：

- provider credentials、API keys、tokens、secrets、`.env`。
- raw provider payload、provider caches、SDK debug dumps。
- generated vector indexes、Chroma / FAISS / provider index 产物。
- raw datasets、full ASSISTments2017 train/test、full generated artifacts。
- checkpoints 和模型文件：`.pkl`、`.pt`、`.pth`、`.ckpt`、`.safetensors`。
- `dist/`、`build/`、`node_modules/`、缓存目录和临时产物。

检查命令：

```bash
python3 scripts/check_repository_safety.py
git diff --check
```

`violation_count` 必须为 `0`。

## 7. 子 issue 覆盖

| issue | PR | 覆盖能力 |
| --- | --- | --- |
| [#88](https://github.com/255308153/MathTutor-Agent/issues/88) | [#93](https://github.com/255308153/MathTutor-Agent/pull/93) | 学生记忆只读查看与记忆控制面板。 |
| [#89](https://github.com/255308153/MathTutor-Agent/issues/89) | [#94](https://github.com/255308153/MathTutor-Agent/pull/94) | 学生记忆禁用 / 启用与上下文排除。 |
| [#90](https://github.com/255308153/MathTutor-Agent/issues/90) | [#95](https://github.com/255308153/MathTutor-Agent/pull/95) | 学生记忆清理与安全删除。 |
| [#91](https://github.com/255308153/MathTutor-Agent/issues/91) | [#96](https://github.com/255308153/MathTutor-Agent/pull/96) | Provider parity、失败降级与 KT / context 边界测试。 |
| [#92](https://github.com/255308153/MathTutor-Agent/issues/92) | 本收口 PR | 中文文档、最终验收记录和父 PRD 汇总评论。 |

## 8. V1.8 记忆控制 gate

本模块满足 V1.8 内部正式试用 gate 中的「学生记忆可查看、可禁用、可重新启用、可清理」要求，并保持默认 local fallback 可运行、Mem0 opt-in、安全禁提交和核心事实边界。

完整 V1.8 仍需要继续完成：

- provider health。
- 持久化学习状态。
- TeachingTrace 持久化。
- 连续学习反馈闭环。

因此，#92 合并只代表 V1.8 记忆控制 gate 完成，不代表完整 V1.8 内部正式试用全部完成。

## 9. 最终验收命令

每次收口前运行：

```bash
python3 -m pytest backend/tests
cd frontend && npm test -- --run
cd frontend && npm run build
python3 scripts/check_repository_safety.py
git diff --check
```

2026-07-09 本地验收结果：

| 命令 | 结果 |
| --- | --- |
| `python3 -m pytest backend/tests` | 通过，166 passed，4 skipped。skipped 项为显式 opt-in 的真实 checkpoint / full offline evidence / Mem0 live smoke / provider live smoke。 |
| `cd frontend && npm test -- --run` | 通过，1 个 test file / 15 tests passed。 |
| `cd frontend && npm run build` | 通过，Vite production build 成功；`frontend/dist/` 为 ignored build output，不提交。 |
| `python3 scripts/check_repository_safety.py` | 通过，`violation_count=0`。 |
| `git diff --check` | 通过，无 whitespace error。 |
