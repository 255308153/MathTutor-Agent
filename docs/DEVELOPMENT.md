# MathTutor Agent 开发文档

本文档是后续 agent 和开发者的本地开发入口。默认语言为中文；用户可见文案也应优先中文。

## 1. 环境准备

要求：

- Python 3.11+
- pip
- Node.js 20+，用于 React 学习驾驶舱

初始化：

```bash
cd /Users/lqc/Downloads/MathTutor-Agent
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

如果只想快速验证当前代码能否导入，也可以先运行：

```bash
python -m compileall backend/app
```

## 2. 启动后端

本地启动：

```bash
uvicorn backend.app.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

预期输出：

```json
{"status":"ok"}
```

如果使用 `cd backend && uvicorn app.main:app --reload` 也可以启动；仓库根目录启动时优先使用 `backend.app.main:app`。

## 3. 启动 React 学习驾驶舱

前端位于：

```text
frontend/
```

首次安装依赖：

```bash
cd /Users/lqc/Downloads/MathTutor-Agent/frontend
npm install
```

本地启动：

```bash
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173
```

Vite 开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。演示时先启动后端，再启动前端。

一分钟演示路径：

1. 默认 mock 模式启动后端和前端，页面加载后自动发起“我下一步应该练什么？”。
2. 查看“今日建议”“概念状态”“薄弱概念”“遗忘风险”和“推荐题”。
3. 在第一道推荐题输入错误答案并提交，后端会用本地内容集确定性判题。
4. 查看错因诊断、概念状态变化、新推荐题和下一步教学动作。
5. 对下一道推荐题输入正确答案，确认反馈变成巩固掌握，并继续给出推荐。
6. 展开 `TeachingTrace` 查看阶段、actor、学生 / 专家可见性和 evidence refs。
7. 展开 `RAG 引用` 查看引用来源。
8. 展开 `模型证据` 查看 KT diagnosis、planner decision、recommendations 和 attribution evidence。

V1.2 DGEKT dashboard smoke：

```bash
export MATHTUTOR_KT_ENGINE=dgekt
export MATHTUTOR_DGEKT_DATASET=xes3g5m
export MATHTUTOR_DGEKT_CHECKPOINT_PATH=/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/KnowledgeTracing/model/runs/20260707_222733/save2017model.pkl
export MATHTUTOR_DGEKT_DATASET_DIR=/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/Dataset/xes3g5m
export MATHTUTOR_DGEKT_Q_MATRIX_PATH=/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/Dataset/H/2017.csv
uvicorn backend.app.main:app --reload
```

前端仍按同一条 dashboard 路径操作。DGEKT 模式下应在 `模型证据` 看到 engine、checkpoint provenance、prediction facts、DGEKT attribution、Top path、Path strength 和 Key history。V1.6 如需读取原 DGEKT explainability outputs，额外显式配置：

```bash
export MATHTUTOR_DGEKT_CHECKPOINT_ID=dgekt-xes3g5m-fixture-epoch26
export MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR=/path/to/dgekt/offline_evidence_outputs
export MATHTUTOR_DGEKT_CANONICAL_MAPPING_PATH=data/mapping/xes3g5m_canonical_mapping.fixture.json
```

配置后 `模型证据` 需要能区分 `complete/offline`、`partial`、`unavailable` 和 `invalid`，并展示 scorer provenance、gap reason、top paths、key history 和 path ablation。未配置 offline evidence 时，DGEKT 仍只能显示 partial online proxy；不能把 proxy path 当成完整离线归因。

V1.3 端到端验收路径：

```text
下一步建议 -> mapped 推荐题 -> 答题提交 -> DGEKT diagnosis -> RAG 解释
-> 错因诊断 -> attribution evidence -> TeachingTrace
```

本地 CI 不读取真实 checkpoint，而是用 fake DGEKT runtime、fixture KC routes 和 `q_frac_001` / `c_fraction_addition` smoke case 验证链路。验收点包括：

- 推荐题携带 canonical mapping、XES3G5M Q3 / C2、KC routes reference 和 content provenance。
- 答错后 `KTDiagnosis.prediction_probability`、`weak_concepts`、`forgetting_risks` 仍来自 DGEKT / KT engine。
- RAG citation、mistake diagnosis、attribution `key_history`、`top_paths`、TeachingTrace `selected_canonical_targets` 都能看到同一 canonical concept。
- 新用户没有长期记忆时，`assembled_context.evidence_gaps` 显示“无可用记忆”，不伪造 memory asset。

可单独运行：

```bash
python3 -m pytest backend/tests/test_kt_engine_config.py::test_v13_dgekt_e2e_smoke_keeps_one_canonical_concept_across_learning_path -q
```

V1.3 / V1.4 历史限制（V1.5 之前）：

- `MockKTStateEngine` 仍是默认引擎，用来保证 V1.1 演示不依赖 checkpoint。
- `DGEKTStateEngine` 只在显式配置时加载本地 XES3G5M checkpoint；大模型和原始数据只通过本地路径引用。
- Demo 内容集优先读取 V1.3 canonical mapping fixture；未映射题会生成稳定 XES3G5M smoke question id，确保 dashboard 能走通 DGEKT 推理，但这不是完整 XES3G5M 内容语义对齐。
- Attribution evidence 当时只有在线 partial evidence，没有运行原 DGEKT 离线 path scorer；V1.6 已增加显式配置的 offline evidence adapter。
- 本地 memory store 默认进程内保存，服务重启后不保留长期记忆；显式启用 Mem0 adapter 后可持久化。
- 本地 RAG 使用 JSON fallback，citation 形状稳定但不是生产向量库。
- 前端仅用于单学习者演示，不包含登录、班级和教师端。

V1.5 已完成第一项 full-data artifact 生产线；V1.6 已接入 DGEKT offline evidence artifact；V1.7 已接入 opt-in Mem0 长期记忆 adapter 与 VikingDB / OpenViking RAG adapter，但默认仍是本地 fallback。后续真实集成优先级：

1. Mem0 运营控制：学生记忆查看、禁用、清理和 provider health。
2. Provider 失败降级与可观测性：补齐 Mem0、VikingDB / OpenViking live provider 的健康检查、错误提示和恢复路径。
3. 持久化学习状态和 TeachingTrace：支持连续学习会话审计。
4. Full artifact 存储和分发：如果完整 XES3G5M generated artifact 需要跨机器复用，应进入 Git 外部对象存储或发布流程。

前端环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VITE_MATHTUTOR_API_BASE` | 空字符串 | 为空时走 Vite `/api` proxy；部署或非代理模式可设为后端地址。 |

## 4. 测试命令

常用检查：

```bash
python -m compileall backend/app
pytest
ruff check .
cd frontend && npm test && npm run build
```

V1.5 #53 最终验收记录（2026-07-09）：

| 命令 | 结果 |
| --- | --- |
| `python3 -m pytest backend/tests` | 通过，95 passed，1 skipped。skipped 项为真实 DGEKT checkpoint smoke，仍需显式 opt-in。 |
| `cd frontend && npm test -- --run` | 通过，1 个 test file / 6 tests passed。 |
| `cd frontend && npm run build` | 通过，Vite production build 成功；`frontend/dist/` 为 ignored build output，不提交。 |
| `python3 scripts/check_repository_safety.py` | 通过，`violation_count=0`，Git tracked 文件未包含 raw train/test、checkpoint、模型文件、cache/build 输出或 full generated artifact。 |

V1.6 #68 最终验收记录（2026-07-09）：

| 命令 | 结果 |
| --- | --- |
| `python3 -m pytest backend/tests` | 通过，113 passed，2 skipped。skipped 项为真实 checkpoint / full offline evidence smoke，仍需显式 opt-in。 |
| `cd frontend && npm test -- --run` | 通过，1 个 test file / 8 tests passed。 |
| `cd frontend && npm run build` | 通过，Vite production build 成功；`frontend/dist/` 为 ignored build output，不提交。 |
| `python3 scripts/check_repository_safety.py` | 通过，`violation_count=0`，Git tracked 文件未包含 raw train/test、checkpoint、模型文件、cache/build 输出、full generated artifact 或 full explainability outputs。 |

V1.7 provider contract 与 worktree 并发规则：

- 所有 V1.7 子任务必须从最新 `origin/master` 创建独立 git worktree 和独立 `codex/...` 分支；不要在主工作区直接实现，也不要复用其他 issue 的未提交改动。
- Provider mode 固定为 `local_fallback`、`fake_provider`、`live_provider` 三种语义。
- 默认 `MATHTUTOR_MEMORY_PROVIDER_MODE=local_fallback`、`MATHTUTOR_RAG_PROVIDER_MODE=local_fallback`，继续使用进程内 memory store 和本地 JSON RAG，不需要 Mem0、VikingDB、OpenViking、真实 DGEKT checkpoint 或完整 XES3G5M 数据。
- `fake_provider` 是无网络、无密钥的 contract fixture，用于 Mem0 / VikingDB / OpenViking adapter 并发开发。fixture 内部可以模拟 SDK 响应，但向 planner、recommender、API、dashboard 只暴露 `StudentMemory` 和 `RAGSearchResult` 领域模型。
- Memory 的 `live_provider` 是 Mem0 adapter 的显式 opt-in 入口；只有显式设置 `MATHTUTOR_MEMORY_PROVIDER_MODE=live_provider` 且提供 `MATHTUTOR_MEM0_API_KEY` 时才会加载 `mem0ai`。
- RAG 的 `live_provider` 是 VikingDB / OpenViking adapter 的显式 opt-in 入口。必须同时配置 provider、endpoint、collection 和对应 API key；缺配置时会报错，默认不会读取外部服务。
- Live smoke 是双重 opt-in：Mem0 需要 `MATHTUTOR_RUN_MEM0_LIVE_SMOKE=1` 和 `MATHTUTOR_MEM0_API_KEY`；VikingDB / OpenViking 需要 `MATHTUTOR_RUN_VIKING_RAG_SMOKE=1`、endpoint、collection 和对应 API key。任一条件缺失时测试自动 skip，默认 backend/frontend 测试不访问外部 provider。
- VikingDB / OpenViking metadata filter 支持 `doc_type`、`doc_types`、`question_id`、`concept_id`、`xes3g5m_question_id`、`xes3g5m_concept_id`，并兼容 `xes3g5m_*` 别名。若 provider 不支持或只弱支持 metadata filter，adapter 会在规范化为 `RAGSearchResult` 后做确定性 post-filter。
- Mem0 adapter 返回稳定 `StudentMemory`，覆盖 `preference`、`repeated_mistake`、`effective_strategy`、`reflection`，并保留 event source、question / concept、trace、event time、relevance、freshness、source 和 provider provenance。下游不能解析 Mem0 raw response。
- Mem0 写入使用稳定 dedupe key；重复学习事件会更新同一条记忆的 provenance，而不是无界生成重复记忆。
- Provider 只能替换存储 / 检索后端，不能改变学习事实边界：KT facts are authoritative；Offline attribution explains prediction, not overwrite prediction facts；Memory can influence strategy, not mastery；RAG can support explanation, not overwrite prediction facts；Context can assemble evidence, not decide learning facts。

V1.7 core invariants：

```text
KT facts are authoritative.
Offline attribution explains prediction, not overwrite prediction facts.
Memory can influence strategy, not mastery.
RAG can support explanation, not overwrite prediction facts.
Context can assemble evidence, not decide learning facts.
```

V1.7 issue / worktree / PR 收口表：

| 阶段 | issue | 推荐 worktree | branch | PR | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | [#71](https://github.com/255308153/MathTutor-Agent/issues/71) provider contract 骨架与 fake provider | `../MathTutor-Agent-v17-provider-contracts` | `codex/v17-provider-contracts` | [#79](https://github.com/255308153/MathTutor-Agent/pull/79) | 已合并 |
| 2 | [#72](https://github.com/255308153/MathTutor-Agent/issues/72) Mem0 adapter 与跨会话记忆 smoke | `../MathTutor-Agent-v17-mem0-adapter` | `codex/v17-mem0-adapter` | [#81](https://github.com/255308153/MathTutor-Agent/pull/81) | 已合并 |
| 2 | [#73](https://github.com/255308153/MathTutor-Agent/issues/73) VikingDB/OpenViking RAG adapter 与 metadata filter smoke | `../MathTutor-Agent-v17-viking-rag-adapter` | `codex/v17-viking-rag-adapter` | [#80](https://github.com/255308153/MathTutor-Agent/pull/80) | 已合并 |
| 3 | [#74](https://github.com/255308153/MathTutor-Agent/issues/74) provider failure、timeout 与 evidence gap 降级 | `../MathTutor-Agent-v17-provider-gaps` | `codex/v17-provider-gaps` | [#82](https://github.com/255308153/MathTutor-Agent/pull/82) | 已合并 |
| 4 | [#75](https://github.com/255308153/MathTutor-Agent/issues/75) provider-aware context assembly E2E | `../MathTutor-Agent-v17-context-e2e` | `codex/v17-context-e2e` | [#83](https://github.com/255308153/MathTutor-Agent/pull/83) | 已合并 |
| 5 | [#76](https://github.com/255308153/MathTutor-Agent/issues/76) dashboard provider-backed context evidence | `../MathTutor-Agent-v17-dashboard-provider-evidence` | `codex/v17-dashboard-provider-evidence` | [#84](https://github.com/255308153/MathTutor-Agent/pull/84) | 已合并 |
| 5 | [#77](https://github.com/255308153/MathTutor-Agent/issues/77) opt-in 配置、live smoke 与安全护栏 | `../MathTutor-Agent-v17-provider-config-safety` | `codex/v17-provider-config-safety` | [#85](https://github.com/255308153/MathTutor-Agent/pull/85) | 已合并 |
| 6 | [#78](https://github.com/255308153/MathTutor-Agent/issues/78) 中文文档与端到端验收收口 | `../MathTutor-Agent-v17-docs-acceptance` | `codex/v17-docs-acceptance` | 本收口 PR | 随本 PR 合并完成 |

推荐流程：

1. 每个 issue 从最新 `origin/master` 新建独立 worktree 和 `codex/...` 分支。
2. 子 issue 先读 GitHub issue，再实现 acceptance criteria、补测试、运行相关验收。
3. PR 描述必须写明完成内容、测试结果、风险、是否影响默认 local fallback。
4. 只有依赖阶段 PR 合并并确认 `master` 与 `origin/master` 同步后，才创建下一阶段 worktree。
5. #70 作为父 PRD 保持 open；#78 合并后只在 #70 评论覆盖情况、测试结果和剩余风险，不关闭 #70。

Provider 配置和故障诊断：

- 配置缺失：`live_provider` 缺 key、endpoint 或 collection 会抛出明确配置错误；默认 `local_fallback` 保持 demo/mock 可运行。
- `provider_auth_error`：检查 API key、权限、provider 类型和环境变量是否只在本地 `.env` 中配置；失败 evidence 不可信，不写入 mastery。
- `provider_timeout`：检查 endpoint、网络和 timeout；系统继续使用 local/fake evidence，不等待 provider 覆盖 KT facts。
- `provider_empty_result`：provider 返回空结果时不伪造 memory 或 RAG citation；检查 query、metadata filter、namespace 和 collection 内容。
- `provider_schema_mismatch`：provider raw response 无法规范化；检查字段别名、metadata filter、adapter schema 和 SDK 版本。
- `provider_budget_exceeded`：检查 quota、rate limit 和调用预算；系统只使用已拿到的 evidence。

相关单测：

```bash
python3 -m pytest backend/tests/test_provider_contracts.py -q
python3 -m pytest backend/tests/test_mem0_memory_store.py -q
```

V1.7 验收模式：

| 模式 | 命令 / 配置 | 结果或 skip 条件 |
| --- | --- | --- |
| default local | `python3 -m pytest backend/tests`、`cd frontend && npm test -- --run`、`cd frontend && npm run build` | 默认 `local_fallback`，不访问外部 provider，不读取 full data 或 checkpoint。 |
| fake provider | `python3 -m pytest backend/tests/test_provider_contracts.py backend/tests/test_mem0_memory_store.py backend/tests/test_provider_evidence_gaps.py backend/tests/test_learning_context_e2e.py -q` | 无网络、无密钥；验证 fake Mem0、fake VikingDB/OpenViking、provider gap 和 context assembly。 |
| optional live provider smoke | Mem0: `MATHTUTOR_RUN_MEM0_LIVE_SMOKE=1` + `MATHTUTOR_MEM0_API_KEY`；RAG: `MATHTUTOR_RUN_VIKING_RAG_SMOKE=1` + `MATHTUTOR_RAG_PROVIDER_ENDPOINT` + `MATHTUTOR_RAG_PROVIDER_COLLECTION` + provider API key。 | 配置完整才运行；缺任一条件自动 skip，默认验收不能依赖 live provider。 |
| repository safety | `python3 scripts/check_repository_safety.py` | `violation_count=0`；不得提交 credentials、secrets、provider caches、generated vector indexes、raw datasets、checkpoints、`.pkl`、`.pt`、`.pth`、`dist`、`node_modules`。 |

V1.7 #78 最终验收记录（2026-07-09）：

| 命令 | 结果 |
| --- | --- |
| `python3 -m pytest backend/tests` | 通过，149 passed，4 skipped。skipped 项为显式 opt-in 的真实 checkpoint / full offline evidence / Mem0 live smoke / VikingDB 或 OpenViking live smoke。 |
| `cd frontend && npm test -- --run` | 通过，1 个 test file / 9 tests passed。 |
| `cd frontend && npm run build` | 通过，Vite production build 成功；`frontend/dist/` 为 ignored build output，不提交。 |
| `python3 scripts/check_repository_safety.py` | 通过，`violation_count=0`，Git tracked 文件未包含 credentials、secrets、provider caches、generated vector indexes、raw datasets、checkpoints、模型文件、`dist` 或 `node_modules`。 |

V1.7 结论：满足 small expert trial only。内部正式试用仍不得早于 **V1.8**；V1.8 前仍需补齐学生记忆运营控制、live provider health / observability、持久化学习状态、连续学习反馈闭环和更完整的真实数据验收。

## 5. V1.8 记忆控制 gate

V1.8 学生记忆控制的完整说明见 [V1_8_MEMORY_CONTROL.md](V1_8_MEMORY_CONTROL.md)。该模块让 dashboard 支持长期记忆查看、禁用、重新启用和删除，是 V1.8 内部正式试用准入 gate 的一部分。

默认开发路径：

- 不设置 provider env 时继续使用 `local_fallback`，dashboard demo/mock 可运行。
- `fake_provider` 只用于无网络、无密钥的 provider contract 测试。
- Mem0 live provider 必须显式设置 `MATHTUTOR_MEMORY_PROVIDER_MODE=live_provider` 和 `MATHTUTOR_MEM0_API_KEY`；live smoke 还需要 `MATHTUTOR_RUN_MEM0_LIVE_SMOKE=1`。
- disabled memory 不进入 selected `student_memory` context assets；deleted memory 不进入 active context assets。
- 记忆控制只影响策略和上下文，不改写 KTDiagnosis、mastery、prediction probability、weak concepts 或 forgetting risk。

安全规则：

- 不提交 provider credentials、secrets、provider caches、generated vector indexes、raw datasets、checkpoints、`.pkl`、`.pt`、`.pth`、`dist`、`node_modules`。
- 提交前运行 `python3 scripts/check_repository_safety.py`，要求 `violation_count=0`。

V1.8 记忆控制最终验收记录（2026-07-09）：

| 命令 | 结果 |
| --- | --- |
| `python3 -m pytest backend/tests` | 通过，166 passed，4 skipped。 |
| `cd frontend && npm test -- --run` | 通过，1 个 test file / 15 tests passed。 |
| `cd frontend && npm run build` | 通过，Vite production build 成功；`frontend/dist/` 为 ignored build output，不提交。 |
| `python3 scripts/check_repository_safety.py` | 通过，`violation_count=0`。 |
| `git diff --check` | 通过。 |

完整 V1.8 仍未全部完成；后续仍需要 provider health、持久化学习状态、TeachingTrace 持久化和连续学习反馈闭环。

开发节奏：

- 小改动先运行相关单测。
- 改动核心主循环、schema、KT、RAG、memory 或 API 后运行 `pytest`。
- 改动 React 学习驾驶舱后运行 `cd frontend && npm test && npm run build`。
- 每个 issue 收口前至少运行 Python 编译检查和相关测试。
- 新功能必须补可验证测试，除非 issue 明确只改文档。

## 4.1 XES3G5M canonical mapping workflow

V1.3 的 mapping 地基位于：

```text
backend/app/mapping/
data/mapping/
```

核心 artifact schema 覆盖：

- XES3G5M `question_id`
- XES3G5M `concept_id`
- MathTutor `concept_id` / `concept_name`
- `teaching_type`
- KC routes row / concept column reference
- source provenance
- 关联 RAG doc ids

当前提交的小型 fixture：

```text
data/mapping/xes3g5m_kc_routes.fixture.csv
data/mapping/xes3g5m_curated_metadata.fixture.json
data/mapping/xes3g5m_canonical_mapping.fixture.json
```

重新生成并打印 coverage 诊断：

```bash
python -m backend.app.mapping.build_xes3g5m_mapping \
  --kc-routes data/mapping/xes3g5m_kc_routes.fixture.csv \
  --metadata data/mapping/xes3g5m_curated_metadata.fixture.json \
  --teaching-content data/content/demo_teaching_content.json \
  --rag-docs data/rag/demo_knowledge.json \
  --output data/mapping/xes3g5m_canonical_mapping.fixture.json
```

诊断字段：

| 字段 | 含义 |
| --- | --- |
| `mapped_questions` / `mapped_question_count` | artifact 中已有 canonical mapping 的 XES3G5M question。 |
| `mapped_concepts` / `mapped_concept_count` | artifact 中已有 canonical mapping 的 XES3G5M concept。 |
| `missing_questions` | KC routes 中存在但 curated metadata 未覆盖的 question 行。 |
| `missing_concepts` | KC routes 中出现但 concept metadata 未覆盖的 concept 列。 |
| `missing_teaching_content` | artifact 指向但本地教学内容集缺失的 MathTutor question。 |
| `missing_rag_docs` | artifact 指向但本地 RAG JSON 缺失的 doc id。 |

本地全量 XES3G5M 文件放置建议：

- checkpoint、`.pkl`、原始 train/test 和全量 KC routes 放在 Git 外部路径，使用环境变量引用。
- 若需要临时放到仓库内，放在 `data/local/`，该目录默认不提交。
- 不要提交全量 XES3G5M train/test、大型 generated mapping、checkpoint、`.pkl`、`.pt`、`.pth` 或生成模型文件。

当前已知缺口：

- fixture 只覆盖少量 demo question / concept，用于验证 schema、builder 和诊断流程。
- fixture 故意保留缺失 question、缺失 concept、缺失 teaching content 和缺失 RAG doc，方便测试 coverage 报告。
- 全量 semantic import、完整题解 / RAG 文档补齐、真实 attribution path scorer 接入仍属于后续 V1.3 issue。

边界要求保持不变：

- `MockKTStateEngine` 是默认模式；不读取 checkpoint 或全量 XES3G5M 文件。
- `DGEKTStateEngine` 只在显式设置 `MATHTUTOR_KT_ENGINE=dgekt` 时启用。
- KT facts 是权威事实；RAG 和 Memory 只能影响解释、偏好和策略，不能覆盖 KT mastery / risk / prediction facts。

## 4.1.1 V1.5 demo / imported / full 数据切换

默认本地运行和默认测试使用：

```bash
MATHTUTOR_XES3G5M_DATASET_MODE=demo
MATHTUTOR_CONTENT_SOURCE=demo
MATHTUTOR_RAG_SOURCE=demo
MATHTUTOR_KT_ENGINE=mock
```

这条路径不需要完整 XES3G5M、DGEKT checkpoint、Mem0、VikingDB/OpenViking，也不会读取本地 full data。

导入小型 fixture artifact：

```bash
python3 -m backend.app.importing.build_xes3g5m_artifacts \
  --dataset-mode fixture \
  --output-dir data/imported/xes3g5m_fixture \
  --generated-at 2026-07-09T00:00:00+00:00
```

读取 imported artifact 需要显式配置：

```bash
export MATHTUTOR_CONTENT_SOURCE=imported
export MATHTUTOR_CONTENT_IMPORT_PATH=data/imported/xes3g5m_fixture/content_import.json
export MATHTUTOR_RAG_SOURCE=imported
export MATHTUTOR_RAG_ARTIFACT_PATH=data/imported/xes3g5m_fixture/rag_documents.json
```

本地 full data 构建必须显式传入源路径，推荐输出到 ignored 目录：

```bash
python3 -m backend.app.importing.build_xes3g5m_artifacts \
  --dataset-mode full \
  --source-rows /Users/lqc/data/xes3g5m/source_rows.csv \
  --kc-routes /Users/lqc/data/xes3g5m/kc_routes.csv \
  --output-dir data/local/xes3g5m_full_artifacts
```

提交规则：

- 可以提交 `data/import/xes3g5m_source.fixture.csv`、`data/mapping/*.fixture.*`、`data/imported/xes3g5m_fixture/*.json`。
- 不提交 provider credentials、secrets、`.env`、provider cache、generated vector index、raw train/test、checkpoint、`.pkl`、`.pt`、`.pth`、`.ckpt`、`.safetensors`、cache、`dist/`、`build/`、`node_modules/` 或 full generated artifact。
- full data 推荐放在 Git 外部路径；若临时放仓库内，使用 `data/local/`、`data/raw/`、`data/full/` 或 `data/import/xes3g5m/`。
- 提交前运行 `python3 scripts/check_repository_safety.py`，确认 tracked 文件没有禁提交项。

清理方式：

```bash
rm -rf data/local/xes3g5m_full_artifacts
rm -rf frontend/dist .pytest_cache .ruff_cache
rm -rf provider_caches vector_indexes generated_vector_indexes
```

## 4.1.2 V1.5 artifact schema 与 coverage 诊断

`backend.app.importing.xes3g5m_artifacts` 是 V1.5 数据导入 contract 的唯一 Pydantic 定义来源。构建 CLI 写出的文件和 runtime 读取关系如下：

| artifact | schema_version | runtime consumer | 关键字段 |
| --- | --- | --- | --- |
| `canonical_mapping.json` | `xes3g5m-canonical-mapping/v1` | mapping diagnostics / DGEKT target alignment | `questions[].question_id`、`questions[].xes3g5m_question_id`、`questions[].xes3g5m_concept_id`、`kc_routes_reference`、`rag_doc_ids`。 |
| `content_import.json` | `xes3g5m-content-import/v1` | `ImportedTeachingContentRepository` | `questions[].stem`、`standard_answer`、`explanation`、`difficulty`、`mistake_patterns`、`canonical_mapping`、`provenance`、`content_availability`。 |
| `rag_documents.json` | `xes3g5m-rag-documents/v1` | `LocalKnowledgeRAG(documents_path=...)` | `documents[].doc_type`、`concept_id`、`question_id`、XES3G5M ids、`canonical_mapping`、`coverage`、`provenance`。 |
| `coverage_report.json` | `xes3g5m-coverage-report/v1` | reviewer / researcher diagnostics | `summary.mapping`、`summary.content`、`summary.rag`、`summary.kc_routes`、`gaps[]`。 |
| `smoke_dataset.json` | `xes3g5m-smoke-dataset/v1` | API smoke tests | `learning_paths[].canonical_question_id`、`canonical_concept_id`、`steps[]`。 |

所有 artifact 都包含相同结构的 `metadata`：

| 字段 | 含义 |
| --- | --- |
| `generated_at` | 构建时间；fixture 构建可传固定值保证 deterministic diff。 |
| `source_paths` | source rows 和 KC routes 的本地来源。full data 路径可以是 Git 外部路径。 |
| `row_counts` | source rows、valid rows、KC routes question/concept、content question、RAG document 数量。 |
| `coverage_summary` | compact coverage summary，便于 artifact consumer 快速显示。 |
| `validation_errors` | error / warning / info 级导入问题，不能静默吞掉。 |

`coverage_report.json` 的 gap category：

| category | 常见 reason_code | 如何解读 | 处理建议 |
| --- | --- | --- | --- |
| `missing_question_mapping` | `kc_routes_row_without_source_question` | KC routes 有题目行，但 source rows 未导入对应题目。 | 补 source rows 或确认 full data 抽样范围。 |
| `missing_concept_mapping` | `kc_routes_concept_without_source_concept` | KC routes 有 concept 列，但 source rows 没有该 concept metadata。 | 补 concept metadata 或检查 KC routes。 |
| `kc_routes_mismatch` | `question_outside_kc_routes` / `concept_not_in_kc_routes_row` | source row 的 question/concept 与 KC routes 不一致。 | 作为 error 修正源文件；默认 CLI 会失败。 |
| `missing_teaching_content` | `essential_teaching_field_missing` | mapping 成功，但题干、标准答案或解析缺失。 | 补内容；runtime 必须通过 `content_availability` 暴露 partial/missing。 |
| `missing_rag_doc` | `expected_rag_doc_not_generated` | content 期望的 RAG doc 不存在。 | 补 question explanation、mistake pattern、concept note 或 strategy 文档。 |

`summary.mapping.mapped_*` / `unmapped_*` 用于判断 canonical 对齐覆盖；`summary.content.missing_teaching_content` 用于判断教学内容是否完整；`summary.rag.missing_rag_docs` 用于判断 citation 质量；`summary.kc_routes.mismatches` 用于阻断不可信的 KT / DGEKT target alignment。

导入 artifact 不能改变学习事实边界：

- KT facts are authoritative.
- Memory can influence strategy, not mastery.
- RAG can support explanation, not overwrite prediction facts.
- Context can assemble evidence, not decide learning facts.

也就是说，coverage gap、RAG citation、provenance 和 context evidence 只辅助解释与审计；`mastery`、`weak_concepts`、`forgetting_risk`、`prediction_probability` 仍只来自 KT engine。

V1.5 API smoke 可单独运行：

```bash
python3 -m pytest backend/tests/test_xes3g5m_learning_path_smoke.py -q
```

该 smoke 使用 committed imported fixture，验证同一 `canonical_question_id` / `canonical_concept_id` 贯穿推荐 payload、服务端判题、KT facts、RAG citation、`assembled_context` 和 TeachingTrace。默认仍是 `MockKTStateEngine`，不会读取 DGEKT checkpoint。

## 4.2 LearningContextLayer 本地上下文层

V1.4 的 LearningContextLayer 位于：

```text
backend/app/context/
```

它负责把本轮学习事件中已有的学生记忆、RAG 证据、任务状态快照、KT 工具观察和 trace 引用组织成统一的 `ContextAsset`，再压缩成 `assembled_context` 写入 TeachingTrace expert evidence。

核心边界：

```text
Context can assemble evidence, not decide learning facts.
```

也就是说：

- KTDiagnosis、mastery、weak_concepts、forgetting_risk、prediction_probability 仍只来自 KTStateEngine。
- ContextAsset 可以记录 KT 诊断快照，但不能覆盖当前 KT facts。
- ContextAssetStore 只存上下文引用、摘要、检索结果和组装记录，不是 runtime state 的唯一真相。
- 默认实现是 `InMemoryContextAssetStore`，本地测试和开发不需要 Mem0、VikingDB、OpenViking 或外部 provider key。
- VikingDB / OpenViking 只能作为 ContextAssetStore 或知识检索的可选后端能力，不能替代 MathTutor runtime。

当前最小主链路：

```text
load_context -> diagnose -> context_assemble -> plan -> generate_response -> memory_update
```

`context_assemble` 阶段会输出：

- `context_assets`：五类资产中的本轮候选和选中资产。
- `assembled_context`：带 `authoritative_kt_facts`、`normalized_context`、asset summaries、evidence gaps、evidence refs、budget / compression metadata 的上下文包。
- `context_record`：本地组装记录，方便审计本轮 context 是怎样被纳入 trace 的。

V1.4 #29 / #35 的 next-step advice 个性化规则：

- `student_memory` 只来自 `StudentMemoryStore.search()` 已返回的稳定 `StudentMemory`；默认是本地记忆，显式 live provider 时可以来自 Mem0。
- `knowledge_resource` 只来自 `KnowledgeRAG.search()` 已返回的稳定 `RAGSearchResult`；默认是本地 RAG，显式 live provider 时可以来自 VikingDB / OpenViking。
- `assembled_context.normalized_context.student_memory` 会区分 preference、repeated_mistake、effective_strategy、goal，并给出 included_reason。
- `assembled_context.normalized_context.knowledge_resource` 会区分 concept_note、question_explanation、mistake_pattern、learning_strategy，并保留 source / doc_type。
- `assembled_context.evidence_gaps` 显式记录“无可用记忆”和“RAG 未找到相关知识资源”；缺失时不伪造 `student_memory` 或 `knowledge_resource` asset。
- planner / recommender / response 只能通过 `assembled_context` 读取 normalized context。它们不能直接调用 Mem0、VikingDB、OpenViking 或外部 provider SDK。
- 推荐理由可以展示“参考学生偏好”“参考相关知识资源”等 context included_reason，也可以展示 gap reason，但 mastery、weak_concepts、forgetting_risk、prediction_probability 仍只来自 KT。

V1.4 #30 的 `answer_submitted` 上下文快照规则：

- 正确作答、错误作答和未判题作答都会生成 answer-submission 专属 assets。
- `task_state` 记录 pending question、submitted answer、grading result、next action，并用 `source_ref` / `evidence_refs` 指向 progress、event 和 TeachingTrace；它不能作为唯一 runtime state。
- `tool_observation` 记录本轮 KT diagnosis、RAG retrieval、mistake diagnosis、recommendation candidates。KT observation 必须带 `snapshot=true`、`source=kt`、`trace_id`、`generated_at`、`freshness=fresh` 和 `authoritative_snapshot=true`，表示它只是 KT facts 的审计副本。
- RAG 或错因诊断缺失时不伪造结果，而是保留 omitted asset 和 `excluded_reason`，供 TeachingTrace expert evidence 展示。
- `trace_reference` 记录 retrieval refs、planner decision ref 和 memory update source，用来追踪本轮证据路径。
- 代码入口是 `LearningContextLayer.collect_answer_submission_assets()`；主循环只在 planner 之后或未判题 fallback plan 中调用它。

V1.4 #31 的检索、预算和裁剪规则：

- `InMemoryContextAssetStore.search()` 与 `LearningContextLayer.retrieve_assets()` 支持 `asset_types`、`source_types`、`student_id`、`session_id`、`concept_id`、`question_id`、`freshness`、`min_confidence` 和 `intent`。
- 检索排序先看 question / concept 命中，再看 session 命中、asset priority、freshness、confidence 和更新时间，保证同一输入下稳定可复现。
- `assemble_context(token_budget=...)` 只把 selected assets 写入 `normalized_context`；被已有 `excluded_reason` 标记或因预算超限裁剪的资产仍会保留在 `asset_summaries`，供 TeachingTrace 审计。
- `budget_used` / `budget_limit` 是当前本地 fallback 的近似上下文成本，不是模型 tokenizer 精确 token 数；`compression_summary` 会记录策略、候选数、选中数、裁剪数和裁剪理由。
- evidence gap 分类包括 `student_memory`、`knowledge_resource`、`stale_task_state`、`low_confidence_observation`、`provider_failure`、`context_budget`。provider failure 只能作为 gap 透出，不能伪造 memory 或 RAG evidence。
- KT facts 不参与资产预算裁剪，始终通过 `assembled_context.authoritative_kt_facts` 输出。

V1.4 #32 的 dashboard 展示规则：

- 前端类型读取 `context_assets`、`context_asset_selection`、`assembled_context.asset_summaries`、`evidence_gaps`、预算和 `compression_summary`。
- TeachingTrace 的 `上下文证据` 面板只面向 expert evidence，展示 selected context assets、omitted context assets、included_reason、excluded_reason、source、freshness 和 confidence。
- `student_memory`、`knowledge_resource`、`task_state`、`tool_observation`、`trace_reference` 在 dashboard 中用不同标签展示；RAG citation、memory evidence、tool observation snapshot 要能一眼区分。
- Evidence gap 和 `context_budget` 裁剪要可见；没有上下文资产时显示 fallback 文案，但推荐卡、答题输入和学生回复保持简单，不因 context 缺失阻塞学习流程。
- dashboard 不直接调用 Mem0、VikingDB、OpenViking 或 provider SDK，不把 context evidence 写入 mastery、weak_concepts、forgetting_risk 或 prediction_probability。

V1.4 #33 的端到端验收规则：

- 后端 smoke 位于 `backend/tests/test_learning_context_e2e.py`，使用 `InMemoryProgressStore`、`InMemoryStudentMemoryStore` 和 `InMemoryContextAssetStore`，不依赖 Mem0、VikingDB、OpenViking 或外部 provider key。
- 验收链路必须覆盖 next-step advice、KT diagnosis、context assemble、recommendation / response、answer submission、task_state / tool_observation / trace_reference asset、TeachingTrace expert evidence 和 ContextAssetStore assembly record。
- 同一个 canonical concept / question 必须能在 KT weak / forgetting facts、student_memory、knowledge_resource、推荐理由、`assembled_context.normalized_context`、planner selected target 和 TeachingTrace context evidence 中追踪到。
- 测试会把伪造的 mastery / prediction_probability 放进 student memory evidence；期望结果是 KTDiagnosis、state_summary 和 `assembled_context.authoritative_kt_facts` 仍保持 KT 输出，context 只能作为策略证据。
- ContextAssetStore 验收只检查引用、摘要和 assembly record。runtime 真相仍在 progress store、LearningEvent、KTDiagnosis、RAG、memory store 和 TeachingTrace。
- 前端 smoke 位于 `frontend/src/App.test.tsx`，验证答题提交追加的 task / tool / trace 证据能在 dashboard `上下文证据` 面板中看到。

本地收口命令：

```bash
python3 -m pytest backend/tests
cd frontend && npm test -- --run
cd frontend && npm run build
```

## 5. 统一事件 API

V1 后端通过统一事件入口接收聊天消息和学习事件：

```bash
curl -X POST http://127.0.0.1:8000/api/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "s001",
    "student_id": "u001",
    "type": "chat_message",
    "message": "我下一步应该学什么？",
    "payload": {}
  }'
```

答题提交示例：

```bash
curl -X POST http://127.0.0.1:8000/api/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "s001",
    "student_id": "u001",
    "type": "answer_submitted",
    "message": "我选 B",
    "payload": {
      "question_id": "q_frac_001",
      "answer": "B",
      "time_spent": 73
    }
  }'
```

响应包含：

```json
{
  "response": "学生可读中文回复",
  "state_summary": {
    "session_id": "s001",
    "student_id": "u001",
    "intent": "next_step_advice",
    "progress_version": 1,
    "concept_states": [],
    "weak_concepts": [],
    "forgetting_risks": [],
    "next_action": {
      "type": "recommend_next_question",
      "label": "根据薄弱知识点推荐下一步练习"
    },
    "errors": []
  },
  "recommended_questions": [],
  "teaching_trace": [
    {"type": "observation", "stage": "load_context"},
    {"type": "observation", "stage": "diagnose"},
    {"type": "observation", "stage": "plan"},
    {"type": "observation", "stage": "generate_response"}
  ]
}
```

当前推荐来自本地 demo 内容集，答题提交由服务端根据标准答案确定性判题；#5 会进一步接入风险优先排序理由。

## 6. 风险优先推荐

下一步学习建议由确定性推荐器完成，入口在：

```text
backend/app/planning/recommender.py
```

推荐结果包含：

- `question_id`：题目 ID。
- `stem_summary` / `stem`：题干摘要和完整题干。
- `concept`：知识点 ID、中文名和教学类型。
- `difficulty`：题目难度。
- `score`：最终排序分。
- `score_factors`：五类可解释分数因子。
- `reason`：中文推荐理由。

当前五类分数因子：

| 因子 | 作用 | 边界 |
| --- | --- | --- |
| `weak_concept_match` | 优先匹配 KT 诊断出的薄弱知识点。 | 来自 KT diagnosis，推荐器只读取，不改写。 |
| `difficulty_fit` | 选择与当前 mastery 接近、略有挑战的题。 | 使用题目 `difficulty` 和 KT mastery 计算。 |
| `forgetting_urgency` | 遗忘风险越高越优先复习。 | 来自 KT forgetting risk。 |
| `novelty` | 降权最近做过或刚推荐过的题，减少重复。 | 读取 recent_events 和 recommendation_history。 |
| `preference_fit` | 允许学生偏好影响题型或教学类型。 | 只影响排序，不覆盖 mastery / risk。 |

核心边界：

```text
KT 决定学习优先级。
推荐器决定从内容集中选哪道题。
LLM 只负责把推荐理由说得更自然，不能决定最终排序。
```

TeachingTrace 的 `plan` 阶段会记录：

- `candidate_count`：候选题数量。
- `recommendation_candidates`：排序后的前几名候选、分数和分数因子。
- `selected_question_ids`：最终返回的 1-3 道题。

## 7. 错因诊断与教学动作

确定性教学规划器位于：

```text
backend/app/planning/teaching_planner.py
```

规划输入：

- `KTDiagnosis`：薄弱知识点、遗忘风险、预测概率等权威学习事实。
- `teaching_type`：来自内容集的知识点教学类型。
- `RAG context`：概念说明、题解、错因模式、学习策略。
- `LearningEvent`：事件类型、题目、答案、服务端判题结果。

四类教学动作：

| `teaching_type` | 动作类型 | 可见行为 |
| --- | --- | --- |
| `memory` | `quick_review` | 记忆型快速复习，先快速回忆事实，再用短题即时检查。 |
| `concept` | `concept_explain_self_check` | 概念型解释与自我解释检查，先解释概念，再让学生复述关键区别。 |
| `procedure` | `worked_example_steps` | 程序型 worked example 和步骤练习，先展示标准步骤，再让学生补下一步。 |
| `design` | `challenge_reflection` | 综合型挑战与反思，给应用题并要求说明建模思路。 |

错题路径：

- 只在服务端确定性判题为错误时生成 `mistake_diagnosis`。
- 诊断包含 concept-level 信息：`concept_id`、`concept_name`、`teaching_type`。
- 诊断包含 mistake-pattern-level 信息：内容集 `mistake_patterns` 和 RAG `mistake_pattern` 文档。
- planner 会把动作改为 `*_after_mistake`，例如 `worked_example_steps_after_mistake`。

安全边界：

```text
错因诊断只描述可观察证据。
禁止输出“你不认真”“你粗心”“你态度不好”等无证据心理判断。
```

TeachingTrace 的 `plan` 阶段会记录：

- `planner_decision`
- `selected_action`
- `teaching_type`
- `mistake_diagnosis`
- `planner_evidence`

## 8. TeachingTrace 与专家证据

每次 `POST /api/events` 都会返回：

- `trace_id`：本轮事件处理的稳定 trace ID。
- `teaching_trace`：逐阶段事件列表。
- `teaching_trace_summary`：前端和专家审计可直接使用的摘要。

`TeachingTraceEvent` 字段：

| 字段 | 含义 |
| --- | --- |
| `id` | 单条 trace event ID。 |
| `type` | 事件类型，如 `observation`。 |
| `stage` | 阶段，如 `load_context`、`diagnose`、`plan`。 |
| `actor` | 责任模块：`system`、`kt`、`rag`、`memory`、`planner`、`response`。 |
| `visibility` | `student` 表示学生可读解释，`expert` / `debug` 表示专家证据。 |
| `content` | 简短中文说明。 |
| `metadata` | 结构化证据。 |
| `evidence_refs` | 可追溯证据引用，如 RAG source、KT attribution、question ID。 |
| `created_at` | 事件创建时间。 |

`TeachingTraceSummary` 字段：

- `trace_id`
- `session_id`
- `student_id`
- `intent`
- `stages`
- `student_explanation`
- `expert_evidence`
- `invariants`
- `errors`

专家证据层包含：

- `kt_diagnosis`：KT 掌握度、薄弱点、遗忘风险、预测概率等事实。
- `attribution_evidence`：DGEKT attribution evidence，包含 `prediction_probability`、`raw_model_target`、`mapped_teaching_content`、`evidence_status`、`evidence_source`、`scorer`、`top_paths`、`key_history`、`weak_concepts`、`path_ablation` 和 `evidence_gaps`。V1.6 在显式配置 artifact 时可输出 `complete/offline`；未配置、未命中或无效时输出 `partial`、`unavailable` 或 `invalid`，并保留 gap reason。
- `rag_sources`：RAG 文档引用。
- `student_memories`：本轮读取到的长期记忆。
- `planner_decision`：TeachingPlanner 的 selected action、mistake diagnosis 和证据。
- `recommendations`：推荐题、分数、分数因子和理由。

DGEKT attribution evidence 约定：

1. 保持 `KTStateEngine.explain_prediction(progress, target_question_id)` 接口不变。
2. DGEKT adapter 返回 `AttributionEvidence`，其中 `prediction_probability` 与 `diagnose` 的预测概率一致。
3. `key_history` 放进入 DGEKT one-hot 序列的关键历史交互，包括 MathTutor question、XES3G5M question、正确性、序列位置和 concept 映射；offline evidence 命中时来自 `key_history.csv`。
4. `top_paths` 放 history question 到 target question 的可审计 path。offline evidence 命中时来自 `attribution_paths.csv`；未命中时只能使用 recent history + KC routes 的 partial proxy，并标注 `partial_evidence=true`。
5. `weak_concept_hit` 和 `weak_concept_evidence` 只说明该 path 命中了 DGEKT 诊断出的薄弱概念 proxy，不能反向改写 `KTDiagnosis.weak_concepts`。
6. `diagnose` 阶段 TeachingTrace 会记录 `attribution_chain`，按 raw model target -> mapped teaching content -> attribution evidence 串联研究者可审计链路。
7. `path_ablation` 来自 `path_ablation.csv`；缺失、缺列或 numeric 解析失败时 evidence status 必须降为 `invalid` 或 `unavailable`，不能显示为 complete。
8. `evidence_gaps` 固定包含 `missing_artifact`、`missing_column`、`malformed_row`、`invalid_numeric_value`、`duplicate_sample`、`target_not_found`、`canonical_mapping_mismatch`、`checkpoint_provenance_mismatch` 等类别。
9. 只有 `evidence_status=complete` 且 `evidence_source=offline` 可视为完整离线归因；online proxy 必须标注 partial reason 和 limitations。
10. `prediction_probability` 与 `weak_concepts` 仍是 KT facts，offline attribution / RAG / Memory 不得覆盖。

## 9. 数学 RAG

V1 本地 RAG fallback 位于：

```text
backend/app/rag/knowledge_rag.py
data/rag/demo_knowledge.json
```

RAG 文档 schema：

```json
{
  "doc_id": "rag_fraction_addition_basic",
  "doc_type": "concept_note",
  "title": "异分母分数加法：先通分再相加",
  "content": "异分母分数相加时，先找到共同分母...",
  "source": "demo-rag/fraction_addition.md",
  "concept_id": "c_fraction_addition",
  "question_id": null,
  "xes3g5m_question_id": null,
  "xes3g5m_concept_id": 2,
  "canonical_mapping": {
    "concept_id": "c_fraction_addition",
    "xes3g5m_concept_id": 2,
    "source": "xes3g5m_curated_metadata.fixture.json"
  },
  "provenance": {
    "rag_source": "data/rag/demo_knowledge.json",
    "enrichment": "runtime_canonical_mapping"
  },
  "coverage": {
    "coverage_type": "concept",
    "concept_aligned": true
  },
  "keywords": ["分数", "通分", "异分母"]
}
```

`data/rag/demo_knowledge.json` 保持小型可读 fixture，可以只手写 `doc_id`、`doc_type`、`title`、`content`、`source`、`concept_id`、`question_id` 和 `keywords`。`LocalKnowledgeRAG` 读取时会根据 `data/mapping/xes3g5m_canonical_mapping.fixture.json` 做 runtime enrichment，补齐 XES3G5M id、KC routes reference、provenance 和 coverage；未映射时 `coverage.coverage_type` 会标记为 `unmapped_question` 或 `unmapped_concept` 并带 `missing_reason`。

四类知识：

| `doc_type` | 用途 |
| --- | --- |
| `concept_note` | 概念讲解和规则说明。 |
| `question_explanation` | 单题题解，通常绑定 `question_id`。 |
| `mistake_pattern` | 常见错因，供错因诊断和答题反馈引用。 |
| `learning_strategy` | 学习策略，如错题复习和下一步练习建议。 |

检索能力：

- 支持 `doc_type` 单类型过滤。
- 支持 `doc_types` 多类型过滤。
- 支持 `concept_id` 过滤。
- 支持 `question_id` 过滤。
- 支持 `xes3g5m_question_id` / `xes3g5m_concept_id` 过滤。
- 返回 `title`、`source`、`content`、`score`、canonical mapping、provenance 和 coverage，供 response、TeachingTrace、LearningContextLayer 和 dashboard 引用。

主循环接入：

- `load_context` 阶段会读取 RAG context。
- 普通知识问答按学生消息检索。
- 答题提交按 `question_id` / `concept_id` 检索题解和错因。
- 下一步建议检索概念说明和学习策略。
- 学生回答中会附简短 `参考：title（source）` citation。
- TeachingTrace 记录 `rag_query`、`rag_filters` 和 canonical `rag_sources`，包括 `question_id`、`concept_id`、`xes3g5m_question_id`、`xes3g5m_concept_id` 和 coverage。
- dashboard 的 `RAG 引用` 区会显示引用对应的真实题目 / 知识点，例如 `题 q_frac_001 · 知识点 c_fraction_addition · XES3G5M Q3 · C2`。

边界：

```text
RAG 支持解释和 citation。
RAG 不覆盖 KT mastery、weak_concepts、forgetting_risk、prediction_probability。
RAG 缺失时只进入 assembled_context.evidence_gaps，不能伪造 knowledge_resource。
```

### 6.1 V1.3 evidence gap / error model

#24 起，学习事件响应会同时保留兼容字段 `state_summary.errors` 和结构化 `state_summary.error_records`。Dashboard 顶部读取 warning 级 `error_records`，TeachingTrace / 模型证据读取 `teaching_trace_summary.expert_evidence.evidence_gaps` 与 `error_records`。

| category | 常见 code | 阶段 | 含义 | 处理方式 |
| --- | --- | --- | --- | --- |
| `missing_mapping` | `missing_question_id` / `missing_mapping` | `load_context` / `diagnose` | 缺 XES3G5M / canonical mapping，或 concept 与 KC routes 不一致。 | 补 mapping artifact 或修正事件 payload。 |
| `missing_content` | `missing_standard_answer` / `missing_teaching_content` | `load_context` | 题干、标准答案或解析缺失；标准答案缺失时不能确定性判题。 | 补 `data/content/demo_teaching_content.json` 或外部内容导入。 |
| `missing_rag_citation` | `missing_rag_citation` | `load_context` | RAG 未召回 canonical question / concept 对齐文档。 | 补 `data/rag/demo_knowledge.json` 或放宽过滤条件。 |
| `unsupported_dgekt_target` | `unsupported_dgekt_target` | `diagnose` | 显式 DGEKT target 超出 XES3G5M / KC routes 支持范围。 | 检查 target question id 和 KC routes 行。 |
| `scorer_failure` | `scorer_failure` | `diagnose` | attribution scorer 运行失败。 | 检查 scorer 输入、checkpoint、KC routes 或回退到 partial evidence。 |

这些记录是诊断与审计信息，不是新的学习事实来源。KT facts 仍只能来自 `KTDiagnosis`；RAG / Memory / Context 不能覆盖 mastery、weak concepts、forgetting risk 或 prediction probability。

替换为 Chroma / VikingDB / OpenViking 时：

1. 保持 `KnowledgeRAG.search(query, filters, limit)` 接口不变。
2. 保持文档 metadata 字段语义不变，并支持 `doc_type`、`doc_types`、`question_id`、`concept_id`、`xes3g5m_question_id`、`xes3g5m_concept_id`。
3. adapter 内部负责向量召回和 metadata filter；provider 不支持时必须在返回前做确定性 post-filter。
4. 返回结果仍然映射为 `RAGSearchResult`。
5. 不允许 adapter 写入 KT progress 或修改 diagnosis。

## 10. 学生长期记忆

V1 本地 memory fallback 位于：

```text
backend/app/memory/store.py
```

接口 seam：

- `StudentMemoryStore.search(student_id, query, memory_types, limit)`
- `StudentMemoryStore.write(memory)`
- `StudentMemoryStore.list_recent(student_id, limit)`

记忆条目格式：

```json
{
  "memory_id": "mem_xxx",
  "student_id": "u001",
  "memory_type": "preference",
  "content": "学生偏好先练比例相关题。",
  "evidence": {"preferred_concept_id": "c_ratio"},
  "relevance_score": 0.82,
  "freshness": "fresh",
  "source": "local_fallback",
  "provenance": {"source_event": "event:tt_xxx:chat_message"},
  "created_at": "2026-07-07T...",
  "updated_at": "2026-07-07T..."
}
```

支持的 `memory_type`：

| 类型 | 用途 |
| --- | --- |
| `preference` | 学生偏好，如偏好的知识点或教学类型。 |
| `repeated_mistake` | 重复错因和错题证据。 |
| `effective_strategy` | 对该学生有效的练习策略。 |
| `reflection` | 学习反思摘要，后续可由 memory refinery 生成。 |

主循环接入：

- `load_context` 阶段检索学生长期记忆。
- 推荐规划会把 `preference` memory 合并到推荐器 preferences。
- 每轮结束后追加 `memory_update` trace。
- 错题会写入 `repeated_mistake`。
- 正确作答会写入 `effective_strategy`。
- 学生在 payload 中传入 `preferred_teaching_type` 或 `preferred_concept_id` 时会写入 `preference`。

边界：

```text
Memory 影响教学策略、推荐偏好和表达方式。
Memory 不覆盖 KT mastery、weak_concepts、forgetting_risk、prediction_probability。
RAG 提供外部知识证据。
KT state 仍是学习事实来源。
```

Mem0 live provider：

1. 保持 `StudentMemoryStore` 接口不变，下游仍只消费 `StudentMemory`。
2. 设置 `MATHTUTOR_MEMORY_PROVIDER_MODE=live_provider` 且提供 `MATHTUTOR_MEM0_API_KEY` 时加载 Mem0 adapter；默认 `local_fallback` 不需要 Mem0 SDK 或网络。
3. Mem0 adapter 负责持久化、语义检索和稳定 dedupe，返回 relevance、freshness、source 与 provider provenance。
4. adapter 会清洗 Mem0 raw response；`sdk_response`、embedding vector、内部 provider debug 字段不能进入 planner、recommender、API 或 dashboard。
5. memory refinery 可以生成 reflection，但不能写 KT facts。

## 11. Demo 教学内容集

本地 demo 内容集位于：

```text
data/content/demo_teaching_content.json
```

数据结构：

```json
{
  "concept_teaching_type_map": {
    "c_fraction_addition": "procedure"
  },
  "questions": [
    {
      "question_id": "q_frac_001",
      "stem": "计算：1/2 + 1/4 = ?",
      "standard_answer": "3/4",
      "explanation": "先通分到四分之一，1/2 = 2/4，所以 2/4 + 1/4 = 3/4。",
      "concept_id": "c_fraction_addition",
      "concept_name": "异分母分数加法",
      "difficulty": 0.35,
      "mistake_patterns": ["没有通分", "分母直接相加"],
      "rag_doc_ids": ["rag_fraction_addition_basic"]
    }
  ]
}
```

字段约定：

- `question_id`：题目稳定 ID，后续推荐、判题、RAG、UI 都使用它串联。
- `stem`：学生可见题干。
- `standard_answer`：服务端标准答案，后端判题只读取本地内容集中的该字段；推荐题 payload 不使用同名字段。
- `answer`：推荐题 payload 中的标准答案快照，来自 `standard_answer`，用于 #21 验收和可审计 teaching content；客户端提交后仍会由服务端重新读取 `standard_answer` 判题。
- `explanation`：题解，推荐题 payload 会返回该字段；前端当前不主动展示答案 / 解析，后续可用于讲解和 TeachingTrace。
- `concept_id` / `concept_name`：知识点标识和中文名。
- `difficulty`：0-1 难度分，后续推荐排序使用。
- `mistake_patterns`：常见错因，后续错因诊断使用。
- `rag_doc_ids`：关联 RAG 文档 ID。
- `concept_teaching_type_map`：稳定标注知识点教学类型，取值为 `memory`、`concept`、`procedure`、`design`。
- `content_availability`：推荐题返回的内容可用性诊断，包含题干、标准答案、解析是否缺失，以及中文 fallback 信息。
- `provenance` / `canonical_mapping`：推荐题返回的来源与 XES3G5M / KC routes 对齐信息。

确定性判题规则：

- `answer_submitted` 进入主循环后，服务端会根据 `question_id` 读取内容集标准答案。
- 客户端传入的 `is_correct`、`correct_answer`、`concept_id` 等判题字段会被清理，避免覆盖服务端事实。
- 如果 `standard_answer` 缺失，API 返回 `record_ungraded_answer` 和中文 `errors`，不会把未判题答案写成 KT facts。
- 判题结果写回 learning event payload，再交给 `MockKTStateEngine` 更新 progress。
- 正确路径会提高 mastery、降低 forgetting risk，并走 `reinforce_mastery`。
- 错误路径会降低 mastery、提高 forgetting risk，写入 `error_records` / `review_queue`，并走 `review_answer`。

推荐题 canonical teaching content：

- `RiskPrioritizedRecommender` 从 `ContentRepository.public_question()` 获取推荐题公开快照，包含 `question_id`、`stem`、`answer`、`explanation`、`concept_name`、`difficulty`、`teaching_type`、`content_availability`、`provenance` 和 `canonical_mapping`。
- 已具备 curated XES3G5M question/concept/KC routes 对齐的题会获得轻量 `canonical_alignment` 排序因子，优先于仅有 `local_sequence_fallback` 的 smoke id。
- TeachingTrace 的 plan 阶段会记录 `selected_canonical_targets`，用于核对推荐题、KTDiagnosis 和 trace 是否指向同一 canonical question / concept。
- 当前覆盖范围仍是小型 demo 内容集 + `data/mapping/xes3g5m_canonical_mapping.fixture.json`。全量 XES3G5M 题干、答案、解析、RAG 文档导入不得直接提交大文件，应放在 Git 外部或 `data/local/`。

替换为 XES3G5M / DGEKT 数据时：

1. 保持 `question_id`、标准答案、知识点、难度、解析、错因、RAG 文档 ID 的字段语义不变。
2. 将 ASSISTments skill / problem 映射到 `concept_id` 与 `question_id`。
3. 将 DGEKT 需要的历史序列特征放在 adapter 内部，不泄漏到 API payload。
4. 保持核心边界：KT facts authoritative，内容集和 RAG 不能覆盖 KT prediction facts。
5. 先让 adapter 产出同样的 public question / grade result，再替换推荐器和 KT engine。

### 内部正式试用 gate

内部正式试用不得早于 **V1.8**。V1.6 和 V1.7 可以做技术内测或专家试用，但不能被标记为普通内部学习者可连续使用的正式试用版。

版本准入约束：

- V1.6：接入真实 DGEKT offline attribution / checkpoint evidence，仍只做技术内测。
- V1.7：接入 Mem0 长期记忆与 VikingDB / OpenViking RAG adapter，可做小范围专家试用。
- V1.8：同时具备真实 DGEKT evidence、长期记忆、生产级 RAG adapter、持久化学习状态、可解释 TeachingTrace、用户反馈闭环和基础安全护栏后，才允许内部正式试用。

V1.8 验收时必须额外确认：

- 默认 demo/mock 仍可运行，真实数据和 provider adapter 仍通过显式配置启用。
- 学生记忆支持查看、清理和禁用，不把记忆事实直接写成 mastery facts。
- RAG citation、KT facts、Memory preference、Context asset 在 TeachingTrace 中边界清楚。
- 缺题干、缺解析、缺 citation、缺 checkpoint、provider 失败时有可见降级或错误提示，不静默伪造教学内容。
- 至少 3-5 个真实内部用户完成连续学习流程，并留下问题反馈和评估记录。

## 12. 环境变量

从示例文件创建本地配置：

```bash
cp .env.example .env
```

变量说明：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MATHTUTOR_ENV` | `development` | 当前运行环境。 |
| `MATHTUTOR_DB_URL` | `sqlite:///./data/local/mathtutor.sqlite` | 本地状态库。 |
| `MATHTUTOR_VECTOR_BACKEND` | `chroma` | 本地 RAG fallback；后续预留 VikingDB。 |
| `MATHTUTOR_LLM_PROVIDER` | `mock` | V1 优先用 mock / 规则化响应跑通闭环。 |
| `MATHTUTOR_LLM_MODEL` | 空 | 真实 LLM 模型名，mock 模式可留空。 |
| `MATHTUTOR_OPENAI_API_KEY` | 空 | 真实 LLM key，mock 模式可留空。 |
| `MATHTUTOR_MEMORY_PROVIDER_MODE` | `local_fallback` | 学生长期记忆 provider mode。`fake_provider` 使用离线 contract fixture；`live_provider` 显式加载 Mem0 adapter。 |
| `MATHTUTOR_RAG_PROVIDER_MODE` | `local_fallback` | 知识检索 provider mode。`local_fallback` 使用本地 JSON；`fake_provider` 使用离线 VikingDB/OpenViking contract fixture；`live_provider` 显式启用 VikingDB/OpenViking adapter。 |
| `MATHTUTOR_MEM0_API_KEY` | 空 | Mem0 live provider 凭据；默认留空，不提交真实 key。保持默认 mode 时留空会继续使用 local fallback。 |
| `MATHTUTOR_RUN_MEM0_LIVE_SMOKE` | `0` | Mem0 live smoke 显式开关；只有设为 `1` 且提供 API key 时才运行 live smoke。 |
| `MATHTUTOR_VIKINGDB_API_KEY` | 空 | VikingDB live provider 凭据；仅 `MATHTUTOR_RAG_PROVIDER_MODE=live_provider` 且 `MATHTUTOR_RAG_LIVE_PROVIDER=vikingdb` 时需要。 |
| `MATHTUTOR_OPENVIKING_API_KEY` | 空 | OpenViking live provider 凭据；仅 `MATHTUTOR_RAG_PROVIDER_MODE=live_provider` 且 `MATHTUTOR_RAG_LIVE_PROVIDER=openviking` 时需要。 |
| `MATHTUTOR_RAG_LIVE_PROVIDER` | `vikingdb` | RAG live provider 类型，可选 `vikingdb` 或 `openviking`。 |
| `MATHTUTOR_RAG_PROVIDER_ENDPOINT` | 空 | VikingDB/OpenViking 检索 endpoint；默认空，避免无意访问外部 provider。 |
| `MATHTUTOR_RAG_PROVIDER_COLLECTION` | 空 | VikingDB/OpenViking collection / index 名称；live provider 必填。 |
| `MATHTUTOR_RAG_PROVIDER_NAMESPACE` | 空 | 可选 namespace / partition，用于隔离知识资源。 |
| `MATHTUTOR_RAG_PROVIDER_SEARCH_PATH` | `/search` | HTTP live smoke 的检索路径；endpoint 已包含完整路径时可设为空。 |
| `MATHTUTOR_RAG_PROVIDER_SUPPORTS_METADATA_FILTER` | `true` | provider 是否支持 metadata filter；设为 `false` 时 adapter 会扩大召回并做确定性 post-filter。 |
| `MATHTUTOR_RAG_PROVIDER_TIMEOUT_SECONDS` | `5.0` | live provider HTTP 检索超时时间。 |
| `MATHTUTOR_KT_ENGINE` | `mock` | KT 引擎选择。默认 `mock`，显式设为 `dgekt` 才会验证并加载真实 DGEKT 配置。 |
| `MATHTUTOR_DGEKT_DATASET` | `xes3g5m` | DGEKT 数据集名；当前只支持 `xes3g5m`。 |
| `MATHTUTOR_DGEKT_CHECKPOINT_PATH` | 空 | 本地 XES3G5M DGEKT checkpoint 路径，例如 `/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/KnowledgeTracing/model/runs/20260707_222733/save2017model.pkl`。大模型文件只通过本地路径引用，不提交 Git。 |
| `MATHTUTOR_DGEKT_CHECKPOINT_ID` | 空 | 可选 checkpoint provenance ID；用于和 offline evidence artifact 的 `checkpoint_id` 对齐。 |
| `MATHTUTOR_DGEKT_DATASET_DIR` | 空 | XES3G5M 数据目录，例如原始工程中的 `Dataset/xes3g5m`，需包含 `xes3g5m_pid_train.csv` 和 `xes3g5m_pid_test.csv`。 |
| `MATHTUTOR_DGEKT_Q_MATRIX_PATH` | 空 | DGEKT KC routes / incidence matrix 文件，例如原始工程中的 `Dataset/H/2017.csv`。 |
| `MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR` | 空 | 可选 DGEKT offline evidence artifact 目录；必须显式配置才会读取。 |
| `MATHTUTOR_DGEKT_CANONICAL_MAPPING_PATH` | 空 | 可选 canonical mapping artifact 路径；用于校验 offline evidence 的 canonical question/concept。 |
| `MATHTUTOR_RUN_DGEKT_SMOKE` | `0` | 设为 `1` 时启用本地真实 checkpoint smoke test；默认测试不依赖大模型文件。 |
| `MATHTUTOR_RUN_DGEKT_OFFLINE_EVIDENCE_SMOKE` | `0` | 设为 `1` 时启用真实 offline explainability outputs smoke；默认只跑小型 fixture。 |
| `MATHTUTOR_RUN_VIKING_RAG_SMOKE` | `0` | 设为 `1` 时启用 VikingDB/OpenViking live RAG smoke；必须同时配置 endpoint、collection 和 provider API key。 |
| `MATHTUTOR_VIKING_RAG_SMOKE_QUERY` | 空 | 可选 live RAG smoke 查询；为空时测试使用“通分 题解”。 |

## 13. 数据目录约定

```text
data/
  content/      小型数学教学内容集：题目、知识点、答案、题解、错因、策略。
  dgekt/        DGEKT 小型 offline evidence fixture；真实 full outputs 必须放到 Git 外部或 ignored 目录。
  mapping/      XES3G5M canonical mapping 小型 fixture 与 schema artifact。
  rag/          本地 RAG 文档和可检索片段。
  local/        sqlite、cache、临时索引等本地运行产物，不提交。
```

当前策略：

- 先用本地 JSON / sqlite / 内存实现跑通 V1 闭环。
- `MockKTStateEngine` 是默认 KT 实现。
- `DGEKTStateEngine` 只有在 `MATHTUTOR_KT_ENGINE=dgekt` 时启用；启动或首次构造时会检查 checkpoint、XES3G5M train/test 数据和 KC routes / incidence matrix，缺失时给出明确环境变量修复提示。
- DGEKT / SAFKT 只通过稳定接口接入，不把 PyTorch checkpoint、数据路径或矩阵细节泄漏到 API、planner、recommender 或前端。
- V1.2 的 DGEKT adapter 会读取 checkpoint 字典中的 `epoch`、`model_state_dict`、`optimizer_state_dict`、`auc`、`acc`，但推理只加载 `model_state_dict`，不会依赖 optimizer 状态。
- 已验证本地 checkpoint provenance：epoch 26，AUC 0.7866464407565317，ACC 0.728796544573157。adapter 加载后会进入 `eval()` 模式，并通过 `diagnostics` / KT evidence 暴露 engine metadata。
- PyTorch 2.6+ 将 `torch.load` 默认改为 `weights_only=True`，该历史 checkpoint 内含 numpy 标量 metadata；adapter 在显式启用 DGEKT 且用户信任本地 checkpoint 时使用 `weights_only=False` 读取。不要对未知来源 checkpoint 使用该配置。
- MathTutor 到 DGEKT 的输入转换规则：
  - `recent_events` 中已判题的 `answer_submitted` 会转换为 XES3G5M 序列，最多保留最近 50 步。
  - 题目映射优先读取 payload 的 `xes3g5m_question_id`，其次读取 `dgekt_question_id`，也支持 `xes3g5m:<id>` 形式。
  - 正确性来自服务端判题后的 `is_correct`，正确编码到前 3162 维，错误编码到后 3162 维，保持原 DGEKT OneHot 规则。
  - concept 映射优先读取 `xes3g5m_concept_id` / `dgekt_concept_id`；未提供时由 KC routes 对应题目行推导第一个 concept。
  - 如果题目 ID 不能映射为 XES3G5M 整数、超出 1..3162、KC routes 缺题、题目没有 concept，或显式 concept 与 KC routes 不一致，会抛出明确映射错误，不返回伪诊断。
- 当前支持范围：本地 XES3G5M checkpoint + `Dataset/xes3g5m` + `Dataset/H/2017.csv`，以及 V1.6 显式配置的 offline evidence artifact。小型 demo 内容集仍使用自己的 `question_id`，系统会为 dashboard smoke 生成稳定 XES3G5M question id 并随事件传入 DGEKT；这只证明真实 checkpoint 推理链路可运行，不代表完整 XES3G5M 内容语义导入。
- DGEKT prediction facts 规范化：
  - `diagnose` 会在 `eval()` / `no_grad` 下读取 ensemble logits，输出 numeric `prediction_probability`。
  - `prediction_probability < 0.6` 会生成 weak concept proxy，`1 - prediction_probability >= 0.4` 会生成 forgetting risk proxy。
  - 如果事件同时带有 MathTutor `concept_id` / `concept_name`，weak/risk facts 使用 MathTutor 概念 ID，推荐器可直接参与现有 risk-prioritized ranking。
  - TeachingTrace 的 `diagnose` 阶段会记录 `kt_engine`、`kt_engine_diagnostics` 和 `prediction_facts`；`KTDiagnosis.metadata` 包含 DGEKT model provenance 和 inference input 摘要。
  - RAG 和 StudentMemory 仍只影响解释、偏好和策略，不覆盖 DGEKT 产生的 mastery / risk / prediction facts。
- DGEKT attribution evidence 规范化：
  - `explain_prediction` 返回 `AttributionEvidence.prediction_probability`、`raw_model_target`、`mapped_teaching_content`、`evidence_status`、`evidence_source`、`scorer`、`top_paths`、`key_history`、`weak_concepts`、`path_ablation` 和 `evidence_gaps`，并注入 TeachingTrace expert evidence。
  - 显式配置 `MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR` 时，adapter 读取 `diagnosis_cases.json`、`attribution_paths.csv`、`key_history.csv`、`path_ablation.csv` 和 `weak_concepts.csv`。
  - `complete/offline` 需要 sample、student target、checkpoint provenance、canonical question/concept 和 CSV schema 全部匹配。
  - 未配置或未命中时，online proxy 只能输出 `partial` / `unavailable`；缺列、malformed row、numeric 解析失败、重复 sample、checkpoint provenance mismatch 或 canonical mapping mismatch 会输出 `invalid`。
  - `prediction_probability` 和 `weak_concepts` 是 KT facts；offline attribution 解释这些事实，不覆盖这些事实。
- 本地 memory 仍是默认实现；Mem0 adapter 已接入 `live_provider`，但必须显式配置 API key 才启用。
- 本地 RAG fallback 是默认实现；VikingDB / OpenViking adapter 已接入 `live_provider`，但必须显式配置 provider、endpoint、collection 和 API key 才启用。

## 14. V1 不做什么

V1 明确不做：

- 多学科。
- 班级 / 教师端。
- 移动端。
- 商业登录、权限和支付。
- 完整 AGI-saber 迁移。
- 真实在线训练 DGEKT / SAFKT。
- 后台定时推送。
- 自动生成大规模题库。
- 复杂分布式多 Agent。

## 15. 核心实现边界

以下规则优先级高于任何自然语言生成结果：

```text
KT facts are authoritative.
LLM plans are advisory.
Memory can influence strategy, not mastery.
RAG can support explanation, not overwrite prediction facts.
```

具体含义：

- KTStateEngine 输出的 mastery、risk、prediction、weak concepts 和 evidence 是学习诊断事实。
- LLM 可以润色表达、生成提示和总结，但不能改写 KT 事实。
- Memory 可以影响节奏、偏好和教学策略，不直接覆盖 mastery。
- RAG 只提供解释证据，不覆盖 KT prediction facts。

## 16. GitHub Issue 工作流

实现顺序以 GitHub issue 为准，优先选择当前未完成且依赖已满足的最小 issue。

建议流程：

1. 查看 issue 描述和验收点。
2. 找到相关代码和文档。
3. 用最小可运行切片实现功能。
4. 补测试和中文文档。
5. 运行相关检查。
6. 提交 commit。
7. 如可行，push 并在 issue 留完成说明。

完成说明应包含：

- 已完成的验收点。
- 运行过的测试命令。
- 演示方式。
- 如有遗留风险，明确列出。

## 17. 常见排错

### `ModuleNotFoundError: No module named 'backend'`

确认命令在仓库根目录运行，或已安装 editable 包：

```bash
pip install -e ".[dev]"
```

### `ModuleNotFoundError: No module named 'app'`

如果在仓库根目录启动，请使用：

```bash
uvicorn backend.app.main:app --reload
```

如果在 `backend/` 目录启动，请使用：

```bash
uvicorn app.main:app --reload
```

### 端口被占用

换端口启动：

```bash
uvicorn backend.app.main:app --reload --port 8001
```

### 本地数据污染

本地运行产物应放在 `data/local/`。该目录默认不提交，需要重置演示数据时可以删除本地 sqlite 或 cache。

### RAG / LLM 依赖不可用

V1 必须能在本地 fallback 下运行。没有真实向量库、真实 LLM key 或外部服务时，应使用 mock / 本地实现继续完成闭环。
