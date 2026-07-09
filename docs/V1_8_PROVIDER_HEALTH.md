# V1.8 Provider Health 与可观测性

本文档记录 V1.8 Provider Health 模块的最小可运行基线。当前切片覆盖 #99 与 #100：保留简单 liveness，新增只读 provider readiness 合约与学习驾驶舱状态面板，并补齐 Memory / RAG provider readiness 诊断。

## API

- `GET /api/health`：保持向后兼容，只返回 `{"status":"ok"}`。
- `GET /api/provider-health`：返回 Provider Health 只读快照，前端“系统状态 / Provider 状态”面板只消费这个后端 API。

Provider Health 响应固定使用以下状态词：

- `healthy`
- `degraded`
- `unavailable`
- `not_configured`

每个组件至少包含：

- `component`
- `display_name`
- `mode`
- `provider`
- `configured`
- `status`
- `severity`
- `recoverable`
- `actionable_hint`
- `evidence_gaps`
- `last_checked_at`

## #99 基线覆盖

默认本地运行不需要 Mem0、VikingDB、OpenViking、真实 DGEKT checkpoint、full ASSISTments2017 数据、generated vector index 或网络访问。默认 `local_fallback / mock / demo` 下，`/api/provider-health` 会展示以下组件均可运行：

| component | 默认 mode/provider | 状态 |
| --- | --- | --- |
| `memory` | `local_fallback` | `healthy` |
| `rag` | `local_fallback` | `healthy` |
| `kt` | `mock` | `healthy` |
| `content_rag_artifact` | `content:demo/rag:demo` / `demo_artifacts` | `healthy` |
| `learning_context` | `local_fallback` / `in_memory_context_layer` | `healthy` |

显式选择 live provider 时，当前基线只做配置字段存在性诊断，不创建 provider adapter、不访问外部网络、不运行 live smoke。

## #100 Memory / RAG Readiness

Memory readiness 覆盖三种模式：

| mode | provider | 默认状态 | 说明 |
| --- | --- | --- | --- |
| `local_fallback` | `local_fallback` | `healthy` | 默认本地长期记忆路径可运行，不需要 Mem0。 |
| `fake_provider` | `fake_mem0_fixture` | `healthy` | 用于 contract / UI 测试，无网络、无密钥也可诊断。 |
| `live_provider` | `mem0` | `healthy` 或 `not_configured` | 只有显式启用时检查 `MATHTUTOR_MEM0_API_KEY` 是否存在。 |

RAG readiness 覆盖三种模式：

| mode | provider | 默认状态 | 说明 |
| --- | --- | --- | --- |
| `local_fallback` | `local_fallback` | `healthy` | 默认本地 RAG 路径可运行，不需要 VikingDB / OpenViking。 |
| `fake_provider` | `fake_vikingdb_fixture` | `healthy` | 用于 contract / UI 测试，无网络、无密钥也可诊断。 |
| `live_provider` | `vikingdb` / `openviking` | `healthy` 或 `not_configured` | 只有显式启用时检查 provider、endpoint、collection 和对应 API key。 |

显式启用 live provider 但配置缺失时，`/api/provider-health` 不会崩溃，也不会把缺失伪装成健康。组件会返回结构化 `evidence_gaps`，其中只包含缺失字段名、provider、operation、中文 reason / message / actionable_hint，不包含凭据值、SDK 原始响应或 provider debug payload。

默认测试和本地 demo 不访问真实 Mem0、VikingDB 或 OpenViking，也不要求 credentials。Provider Health 的缺配置状态只用于诊断与运营可见性；学习事件主流程仍使用可用的本地 fallback 继续运行，不能把 provider 缺失写成 mastery、prediction facts 或学习进度事实。

## 只读边界

Provider Health 只能做诊断与运营可见性。读取 `/api/provider-health` 不能写入或修改：

- memory
- progress
- context assets
- RAG artifacts / indexes
- TeachingTrace
- KT state

核心边界保持不变：

```text
KT facts are authoritative.
Offline attribution explains prediction, not overwrite prediction facts.
Memory can influence strategy, not mastery.
RAG can support explanation, not overwrite prediction facts.
Context can assemble evidence, not decide learning facts.
```

Provider Health 输出不得泄露 credentials、authorization header、raw provider payload、SDK response、embedding、provider debug 字段、敏感本地路径、checkpoint 或模型文件路径。
