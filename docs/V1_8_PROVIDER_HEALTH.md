# V1.8 Provider Health 与可观测性

本文档记录 V1.8 Provider Health 模块的最小可运行基线。当前切片覆盖 #99、#100、#101 与 #102：保留简单 liveness，新增只读 provider readiness 合约与学习驾驶舱状态面板，并补齐 Memory / RAG、KT/DGEKT、Content/RAG artifact、LearningContextLayer readiness 诊断，以及 provider gap 安全归一与敏感信息清洗。

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

## #101 KT/DGEKT 与 Artifact Readiness

KT readiness 覆盖两种模式：

| mode | provider | 状态 | 说明 |
| --- | --- | --- | --- |
| `mock` | `mock` | `healthy` | 默认 mock KT 可运行，KT facts 仍是权威学习事实。 |
| `dgekt` | `dgekt` | `healthy` / `degraded` / `unavailable` / `not_configured` | 只有显式启用时检查 checkpoint、dataset、Q-matrix、canonical mapping 与 offline evidence readiness。 |

DGEKT readiness 只做只读配置与 artifact 存在性检查，不加载 checkpoint、不初始化 PyTorch runtime、不访问模型文件内容。输出不会包含本地 checkpoint 路径、dataset 路径、Q-matrix 路径或 offline evidence 目录，只报告缺少的 env 名或 artifact 类别。

关键状态：

- 缺少 `MATHTUTOR_DGEKT_CHECKPOINT_PATH`、`MATHTUTOR_DGEKT_DATASET_DIR` 或 `MATHTUTOR_DGEKT_Q_MATRIX_PATH` 时，组件返回 `not_configured`。
- 已配置路径但本地 artifact 不存在或不完整时，组件返回 `unavailable`。
- DGEKT 核心配置完整但 `MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR` 未配置时，组件返回 `degraded`，并明确标记 offline evidence 为 `partial` readiness，不能伪装成 complete offline evidence。
- 配置了完整 offline evidence fixture / artifact 时，组件可返回 `healthy`；这仍然只是 readiness 诊断，不会覆盖 prediction facts。

Content/RAG artifact readiness 使用同一个 `content_rag_artifact` 组件报告：

| source | provider | 状态 | 说明 |
| --- | --- | --- | --- |
| `content:demo/rag:demo` | `demo_artifacts` | `healthy` | 默认 demo content 与 demo RAG artifact 可运行。 |
| `content:imported/rag:imported` 且路径指向小型 fixture | `fixture_artifacts` | `healthy` | 用于无 full dataset 的 imported/fixture 验证。 |
| `imported` 但缺少导入路径 | `imported_artifacts` | `not_configured` | 返回缺少 `MATHTUTOR_CONTENT_IMPORT_PATH` 或 `MATHTUTOR_RAG_ARTIFACT_PATH`。 |
| 已配置导入路径但 artifact 不存在 | `imported_artifacts` | `unavailable` | 只报告 artifact 类别，不泄漏敏感本地路径。 |

LearningContextLayer readiness 会显示当前是否仍是默认 `local_fallback`，或是否正在组装 provider/imported 证据。它只表达上下文证据组装能力；上游 provider 或 artifact 降级时只保留 evidence gap，不改写 mastery、weak concepts、forgetting risk、prediction probability 或任何 KT facts。

## #102 Provider Gap 安全归一

Provider Health 会复用现有 provider evidence gap 词汇，并把最近一次只读采集到的 provider gap 归一为稳定诊断字段。默认 `/api/provider-health` 不主动访问 Mem0、VikingDB、OpenViking 或 DGEKT live runtime；它只读取当前 provider adapter 已记录的 `last_evidence_gaps`，不会写 memory、progress、context、RAG、TeachingTrace 或 KT state。

当前归一分类：

| gap_type | health status | severity | 说明 |
| --- | --- | --- | --- |
| `provider_failure` | `unavailable` | `error` | provider evidence 当前不可用，本地或 fixture evidence 继续可用。 |
| `provider_timeout` | `unavailable` | `warning` | provider 未在 timeout 内返回 evidence。 |
| `provider_auth_error` | `unavailable` | `error` | provider 凭据或权限不可用，不信任失败 provider evidence。 |
| `provider_empty_result` | `degraded` | `info` | provider 未返回可用记忆或 citation，不伪造 evidence。 |
| `provider_schema_mismatch` | `degraded` | `warning` | provider raw response 无法规范化，malformed evidence 会被丢弃。 |
| `provider_budget_exceeded` | `degraded` | `warning` | quota、rate limit 或预算触发，只使用已取得 evidence。 |

每个归一后的 gap 至少包含 `gap_type`、`code`、`category`、`provider`、`operation`、`status`、`severity`、`recoverable`、`message`、`impact`、`actionable_hint` 与已清洗 `details`。前端状态面板只渲染 gap label、中文 reason/message 与 actionable hint，不展开 raw `details`。

清洗规则：

- 移除 `raw_provider_payload`、`sdk_response`、`embedding`、`embedding_vector`、`vector`、`provider_debug` 等 SDK 噪声字段。
- 移除或清洗 `api_key`、`authorization`、`bearer token`、`credential`、`secret`、`password` 等敏感字段和值。
- 清洗 `/Users/...`、`/tmp/...`、`/private/...`、provider cache、checkpoint、dataset 或 artifact 绝对路径，只保留安全摘要或配置项名称。
- Health 输出只表达诊断，不进入 mastery、prediction facts、RAG citation 权威字段或 active context decision。

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
