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
export MATHTUTOR_DGEKT_DATASET=assist2017
export MATHTUTOR_DGEKT_CHECKPOINT_PATH=/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/KnowledgeTracing/model/runs/20260707_222733/save2017model.pkl
export MATHTUTOR_DGEKT_DATASET_DIR=/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/Dataset/assist2017
export MATHTUTOR_DGEKT_Q_MATRIX_PATH=/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/Dataset/H/2017.csv
uvicorn backend.app.main:app --reload
```

前端仍按同一条 dashboard 路径操作。DGEKT 模式下应在 `模型证据` 看到 engine、checkpoint provenance、prediction facts、DGEKT attribution、Top path、Path strength 和 Key history。

V1.3 端到端验收路径：

```text
下一步建议 -> mapped 推荐题 -> 答题提交 -> DGEKT diagnosis -> RAG 解释
-> 错因诊断 -> attribution evidence -> TeachingTrace
```

本地 CI 不读取真实 checkpoint，而是用 fake DGEKT runtime、fixture Q-matrix 和 `q_frac_001` / `c_fraction_addition` smoke case 验证链路。验收点包括：

- 推荐题携带 canonical mapping、ASSIST2017 Q3 / C2、Q-matrix reference 和 content provenance。
- 答错后 `KTDiagnosis.prediction_probability`、`weak_concepts`、`forgetting_risks` 仍来自 DGEKT / KT engine。
- RAG citation、mistake diagnosis、attribution `key_history`、`top_paths`、TeachingTrace `selected_canonical_targets` 都能看到同一 canonical concept。
- 新用户没有长期记忆时，`assembled_context.evidence_gaps` 显示“无可用记忆”，不伪造 memory asset。

可单独运行：

```bash
python3 -m pytest backend/tests/test_kt_engine_config.py::test_v13_dgekt_e2e_smoke_keeps_one_canonical_concept_across_learning_path -q
```

V1.3 / V1.4 已知限制：

- `MockKTStateEngine` 仍是默认引擎，用来保证 V1.1 演示不依赖 checkpoint。
- `DGEKTStateEngine` 只在显式配置时加载本地 ASSIST2017 checkpoint；大模型和原始数据只通过本地路径引用。
- Demo 内容集优先读取 V1.3 canonical mapping fixture；未映射题会生成稳定 ASSIST2017 smoke question id，确保 dashboard 能走通 DGEKT 推理，但这不是完整 ASSISTments2017 内容语义对齐。
- Attribution evidence 当前是在线 partial evidence，没有运行原 DGEKT 离线 path scorer。
- 本地 memory store 默认进程内保存，服务重启后不保留长期记忆。
- 本地 RAG 使用 JSON fallback，citation 形状稳定但不是生产向量库。
- 前端仅用于单学习者演示，不包含登录、班级和教师端。

下一阶段真实集成优先级：

1. `ASSISTments2017` 完整内容导入：补齐题目、知识点、历史作答、题解和错因文档映射。
2. 原 DGEKT explainability scorer 在线化：接入完整 top attribution paths / key history scorer 输出。
3. `Mem0` adapter：将本地学生记忆替换为可持久化检索记忆。
4. `VikingDB` adapter：将本地 JSON RAG fallback 替换成向量检索。

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

开发节奏：

- 小改动先运行相关单测。
- 改动核心主循环、schema、KT、RAG、memory 或 API 后运行 `pytest`。
- 改动 React 学习驾驶舱后运行 `cd frontend && npm test && npm run build`。
- 每个 issue 收口前至少运行 Python 编译检查和相关测试。
- 新功能必须补可验证测试，除非 issue 明确只改文档。

## 4.1 ASSIST2017 canonical mapping workflow

V1.3 的 mapping 地基位于：

```text
backend/app/mapping/
data/mapping/
```

核心 artifact schema 覆盖：

- ASSIST2017 `question_id`
- ASSIST2017 `concept_id`
- MathTutor `concept_id` / `concept_name`
- `teaching_type`
- Q-matrix row / concept column reference
- source provenance
- 关联 RAG doc ids

当前提交的小型 fixture：

```text
data/mapping/assist2017_q_matrix.fixture.csv
data/mapping/assist2017_curated_metadata.fixture.json
data/mapping/assist2017_canonical_mapping.fixture.json
```

重新生成并打印 coverage 诊断：

```bash
python -m backend.app.mapping.build_assist2017_mapping \
  --q-matrix data/mapping/assist2017_q_matrix.fixture.csv \
  --metadata data/mapping/assist2017_curated_metadata.fixture.json \
  --teaching-content data/content/demo_teaching_content.json \
  --rag-docs data/rag/demo_knowledge.json \
  --output data/mapping/assist2017_canonical_mapping.fixture.json
```

诊断字段：

| 字段 | 含义 |
| --- | --- |
| `mapped_questions` / `mapped_question_count` | artifact 中已有 canonical mapping 的 ASSIST2017 question。 |
| `mapped_concepts` / `mapped_concept_count` | artifact 中已有 canonical mapping 的 ASSIST2017 concept。 |
| `missing_questions` | Q-matrix 中存在但 curated metadata 未覆盖的 question 行。 |
| `missing_concepts` | Q-matrix 中出现但 concept metadata 未覆盖的 concept 列。 |
| `missing_teaching_content` | artifact 指向但本地教学内容集缺失的 MathTutor question。 |
| `missing_rag_docs` | artifact 指向但本地 RAG JSON 缺失的 doc id。 |

本地全量 ASSIST2017 文件放置建议：

- checkpoint、`.pkl`、原始 train/test 和全量 Q-matrix 放在 Git 外部路径，使用环境变量引用。
- 若需要临时放到仓库内，放在 `data/local/`，该目录默认不提交。
- 不要提交全量 ASSIST2017 train/test、大型 generated mapping、checkpoint、`.pkl`、`.pt`、`.pth` 或生成模型文件。

当前已知缺口：

- fixture 只覆盖少量 demo question / concept，用于验证 schema、builder 和诊断流程。
- fixture 故意保留缺失 question、缺失 concept、缺失 teaching content 和缺失 RAG doc，方便测试 coverage 报告。
- 全量 semantic import、完整题解 / RAG 文档补齐、真实 attribution path scorer 接入仍属于后续 V1.3 issue。

边界要求保持不变：

- `MockKTStateEngine` 是默认模式；不读取 checkpoint 或全量 ASSIST2017 文件。
- `DGEKTStateEngine` 只在显式设置 `MATHTUTOR_KT_ENGINE=dgekt` 时启用。
- KT facts 是权威事实；RAG 和 Memory 只能影响解释、偏好和策略，不能覆盖 KT mastery / risk / prediction facts。

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
- VikingDB / OpenViking 后续只能作为 ContextAssetStore 或知识检索的可选后端能力，不能替代 MathTutor runtime。

当前最小主链路：

```text
load_context -> diagnose -> context_assemble -> plan -> generate_response -> memory_update
```

`context_assemble` 阶段会输出：

- `context_assets`：五类资产中的本轮候选和选中资产。
- `assembled_context`：带 `authoritative_kt_facts`、`normalized_context`、asset summaries、evidence gaps、evidence refs、budget / compression metadata 的上下文包。
- `context_record`：本地组装记录，方便审计本轮 context 是怎样被纳入 trace 的。

V1.4 #29 / #35 的 next-step advice 个性化规则：

- `student_memory` 只来自 `StudentMemoryStore.search()` 已返回的本地记忆，不新增 Mem0 provider 依赖。
- `knowledge_resource` 只来自 `KnowledgeRAG.search()` 已返回的本地 RAG 结果，不新增 VikingDB / OpenViking provider 依赖。
- `assembled_context.normalized_context.student_memory` 会区分 preference、repeated_mistake、effective_strategy、goal，并给出 included_reason。
- `assembled_context.normalized_context.knowledge_resource` 会区分 concept_note、question_explanation、mistake_pattern、learning_strategy，并保留 source / doc_type。
- `assembled_context.evidence_gaps` 显式记录“无可用记忆”和“RAG 未找到相关知识资源”；缺失时不伪造 `student_memory` 或 `knowledge_resource` asset。
- planner / recommender / response 只能通过 `assembled_context` 读取 normalized context。它们不能直接调用 Mem0、VikingDB、OpenViking 或外部 provider SDK。
- 推荐理由可以展示“参考学生偏好”“参考相关知识资源”等 context included_reason，也可以展示 gap reason，但 mastery、weak_concepts、forgetting_risk、prediction_probability 仍只来自 KT。

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
- `attribution_evidence`：DGEKT attribution evidence，包含 `prediction_probability`、`raw_model_target`、`mapped_teaching_content`、`scorer`、`top_paths`、`key_history`、`weak_concepts`。DGEKT 在线 adapter 当前输出带 `partial_evidence=true` 的可审计 partial evidence。
- `rag_sources`：RAG 文档引用。
- `student_memories`：本轮读取到的长期记忆。
- `planner_decision`：TeachingPlanner 的 selected action、mistake diagnosis 和证据。
- `recommendations`：推荐题、分数、分数因子和理由。

DGEKT attribution evidence 约定：

1. 保持 `KTStateEngine.explain_prediction(progress, target_question_id)` 接口不变。
2. DGEKT adapter 返回 `AttributionEvidence`，其中 `prediction_probability` 与 `diagnose` 的预测概率一致。
3. `key_history` 放最近进入 DGEKT one-hot 序列的已判题交互，包括 MathTutor question、ASSIST2017 question、正确性、序列位置和 concept 映射。
4. `top_paths` 放 history question 到 target question 的可审计 partial path：history / target question、history / target concept、Q-matrix concept relation strength、question relation strength、recency strength、`path_strength` / `path_weight`、`relation_strength`、`relation_source`。
5. `weak_concept_hit` 和 `weak_concept_evidence` 只说明该 path 命中了 DGEKT 诊断出的薄弱概念 proxy，不能反向改写 `KTDiagnosis.weak_concepts`。
6. `diagnose` 阶段 TeachingTrace 会记录 `attribution_chain`，按 raw model target -> mapped teaching content -> attribution evidence 串联研究者可审计链路。
7. 当前在线 adapter 没有运行原 DGEKT 工程的离线 path scorer / graph path CSV，因此 `top_paths` 必须标注 `partial_evidence=true`、`evidence_status=partial`、`partial_evidence_reason` 和 limitations，不能伪装成完整双图归因。
8. `prediction_probability` 与 `weak_concepts` 仍是 KT facts，RAG / Memory 不得覆盖。

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
  "assist2017_question_id": null,
  "assist2017_concept_id": 2,
  "canonical_mapping": {
    "concept_id": "c_fraction_addition",
    "assist2017_concept_id": 2,
    "source": "assist2017_curated_metadata.fixture.json"
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

`data/rag/demo_knowledge.json` 保持小型可读 fixture，可以只手写 `doc_id`、`doc_type`、`title`、`content`、`source`、`concept_id`、`question_id` 和 `keywords`。`LocalKnowledgeRAG` 读取时会根据 `data/mapping/assist2017_canonical_mapping.fixture.json` 做 runtime enrichment，补齐 ASSIST2017 id、Q-matrix reference、provenance 和 coverage；未映射时 `coverage.coverage_type` 会标记为 `unmapped_question` 或 `unmapped_concept` 并带 `missing_reason`。

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
- 支持 `assist2017_question_id` / `assist2017_concept_id` 过滤。
- 返回 `title`、`source`、`content`、`score`、canonical mapping、provenance 和 coverage，供 response、TeachingTrace、LearningContextLayer 和 dashboard 引用。

主循环接入：

- `load_context` 阶段会读取 RAG context。
- 普通知识问答按学生消息检索。
- 答题提交按 `question_id` / `concept_id` 检索题解和错因。
- 下一步建议检索概念说明和学习策略。
- 学生回答中会附简短 `参考：title（source）` citation。
- TeachingTrace 记录 `rag_query`、`rag_filters` 和 canonical `rag_sources`，包括 `question_id`、`concept_id`、`assist2017_question_id`、`assist2017_concept_id` 和 coverage。
- dashboard 的 `RAG 引用` 区会显示引用对应的真实题目 / 知识点，例如 `题 q_frac_001 · 知识点 c_fraction_addition · ASSIST2017 Q3 · C2`。

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
| `missing_mapping` | `missing_question_id` / `missing_mapping` | `load_context` / `diagnose` | 缺 ASSIST2017 / canonical mapping，或 concept 与 Q-matrix 不一致。 | 补 mapping artifact 或修正事件 payload。 |
| `missing_content` | `missing_standard_answer` / `missing_teaching_content` | `load_context` | 题干、标准答案或解析缺失；标准答案缺失时不能确定性判题。 | 补 `data/content/demo_teaching_content.json` 或外部内容导入。 |
| `missing_rag_citation` | `missing_rag_citation` | `load_context` | RAG 未召回 canonical question / concept 对齐文档。 | 补 `data/rag/demo_knowledge.json` 或放宽过滤条件。 |
| `unsupported_dgekt_target` | `unsupported_dgekt_target` | `diagnose` | 显式 DGEKT target 超出 ASSIST2017 / Q-matrix 支持范围。 | 检查 target question id 和 Q-matrix 行。 |
| `scorer_failure` | `scorer_failure` | `diagnose` | attribution scorer 运行失败。 | 检查 scorer 输入、checkpoint、Q-matrix 或回退到 partial evidence。 |

这些记录是诊断与审计信息，不是新的学习事实来源。KT facts 仍只能来自 `KTDiagnosis`；RAG / Memory / Context 不能覆盖 mastery、weak concepts、forgetting risk 或 prediction probability。

后续替换为 Chroma / VikingDB：

1. 保持 `KnowledgeRAG.search(query, filters, limit)` 接口不变。
2. 保持文档 metadata 字段语义不变。
3. adapter 内部负责向量召回和 metadata filter。
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

后续替换为 Mem0：

1. 保持 `StudentMemoryStore` 接口不变。
2. Mem0 adapter 负责持久化、语义检索和去重。
3. adapter 返回仍映射为 `StudentMemory`。
4. memory refinery 可以生成 reflection，但不能写 KT facts。

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
- `provenance` / `canonical_mapping`：推荐题返回的来源与 ASSIST2017 / Q-matrix 对齐信息。

确定性判题规则：

- `answer_submitted` 进入主循环后，服务端会根据 `question_id` 读取内容集标准答案。
- 客户端传入的 `is_correct`、`correct_answer`、`concept_id` 等判题字段会被清理，避免覆盖服务端事实。
- 如果 `standard_answer` 缺失，API 返回 `record_ungraded_answer` 和中文 `errors`，不会把未判题答案写成 KT facts。
- 判题结果写回 learning event payload，再交给 `MockKTStateEngine` 更新 progress。
- 正确路径会提高 mastery、降低 forgetting risk，并走 `reinforce_mastery`。
- 错误路径会降低 mastery、提高 forgetting risk，写入 `error_records` / `review_queue`，并走 `review_answer`。

推荐题 canonical teaching content：

- `RiskPrioritizedRecommender` 从 `ContentRepository.public_question()` 获取推荐题公开快照，包含 `question_id`、`stem`、`answer`、`explanation`、`concept_name`、`difficulty`、`teaching_type`、`content_availability`、`provenance` 和 `canonical_mapping`。
- 已具备 curated ASSIST2017 question/concept/Q-matrix 对齐的题会获得轻量 `canonical_alignment` 排序因子，优先于仅有 `local_sequence_fallback` 的 smoke id。
- TeachingTrace 的 plan 阶段会记录 `selected_canonical_targets`，用于核对推荐题、KTDiagnosis 和 trace 是否指向同一 canonical question / concept。
- 当前覆盖范围仍是小型 demo 内容集 + `data/mapping/assist2017_canonical_mapping.fixture.json`。全量 ASSISTments2017 题干、答案、解析、RAG 文档导入不得直接提交大文件，应放在 Git 外部或 `data/local/`。

替换为 ASSISTments2017 / DGEKT 数据时：

1. 保持 `question_id`、标准答案、知识点、难度、解析、错因、RAG 文档 ID 的字段语义不变。
2. 将 ASSISTments skill / problem 映射到 `concept_id` 与 `question_id`。
3. 将 DGEKT 需要的历史序列特征放在 adapter 内部，不泄漏到 API payload。
4. 保持核心边界：KT facts authoritative，内容集和 RAG 不能覆盖 KT prediction facts。
5. 先让 adapter 产出同样的 public question / grade result，再替换推荐器和 KT engine。

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
| `MATHTUTOR_KT_ENGINE` | `mock` | KT 引擎选择。默认 `mock`，显式设为 `dgekt` 才会验证并加载真实 DGEKT 配置。 |
| `MATHTUTOR_DGEKT_DATASET` | `assist2017` | DGEKT 数据集名；V1.2 当前只支持 `assist2017`。 |
| `MATHTUTOR_DGEKT_CHECKPOINT_PATH` | 空 | 本地 ASSIST2017 DGEKT checkpoint 路径，例如 `/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/KnowledgeTracing/model/runs/20260707_222733/save2017model.pkl`。大模型文件只通过本地路径引用，不提交 Git。 |
| `MATHTUTOR_DGEKT_DATASET_DIR` | 空 | ASSIST2017 数据目录，例如原始工程中的 `Dataset/assist2017`，需包含 `assist2017_pid_train.csv` 和 `assist2017_pid_test.csv`。 |
| `MATHTUTOR_DGEKT_Q_MATRIX_PATH` | 空 | DGEKT Q-matrix / incidence matrix 文件，例如原始工程中的 `Dataset/H/2017.csv`。 |
| `MATHTUTOR_RUN_DGEKT_SMOKE` | `0` | 设为 `1` 时启用本地真实 checkpoint smoke test；默认测试不依赖大模型文件。 |

## 13. 数据目录约定

```text
data/
  content/      小型数学教学内容集：题目、知识点、答案、题解、错因、策略。
  mapping/      ASSIST2017 canonical mapping 小型 fixture 与 schema artifact。
  rag/          本地 RAG 文档和可检索片段。
  local/        sqlite、cache、临时索引等本地运行产物，不提交。
```

当前策略：

- 先用本地 JSON / sqlite / 内存实现跑通 V1 闭环。
- `MockKTStateEngine` 是默认 KT 实现。
- `DGEKTStateEngine` 只有在 `MATHTUTOR_KT_ENGINE=dgekt` 时启用；启动或首次构造时会检查 checkpoint、ASSIST2017 train/test 数据和 Q-matrix / incidence matrix，缺失时给出明确环境变量修复提示。
- DGEKT / SAFKT 只通过稳定接口接入，不把 PyTorch checkpoint、数据路径或矩阵细节泄漏到 API、planner、recommender 或前端。
- V1.2 的 DGEKT adapter 会读取 checkpoint 字典中的 `epoch`、`model_state_dict`、`optimizer_state_dict`、`auc`、`acc`，但推理只加载 `model_state_dict`，不会依赖 optimizer 状态。
- 已验证本地 checkpoint provenance：epoch 26，AUC 0.7866464407565317，ACC 0.728796544573157。adapter 加载后会进入 `eval()` 模式，并通过 `diagnostics` / KT evidence 暴露 engine metadata。
- PyTorch 2.6+ 将 `torch.load` 默认改为 `weights_only=True`，该历史 checkpoint 内含 numpy 标量 metadata；adapter 在显式启用 DGEKT 且用户信任本地 checkpoint 时使用 `weights_only=False` 读取。不要对未知来源 checkpoint 使用该配置。
- MathTutor 到 DGEKT 的输入转换规则：
  - `recent_events` 中已判题的 `answer_submitted` 会转换为 ASSIST2017 序列，最多保留最近 50 步。
  - 题目映射优先读取 payload 的 `assist2017_question_id`，其次读取 `dgekt_question_id`，也支持 `assist2017:<id>` 形式。
  - 正确性来自服务端判题后的 `is_correct`，正确编码到前 3162 维，错误编码到后 3162 维，保持原 DGEKT OneHot 规则。
  - concept 映射优先读取 `assist2017_concept_id` / `dgekt_concept_id`；未提供时由 Q-matrix 对应题目行推导第一个 concept。
  - 如果题目 ID 不能映射为 ASSIST2017 整数、超出 1..3162、Q-matrix 缺题、题目没有 concept，或显式 concept 与 Q-matrix 不一致，会抛出明确映射错误，不返回伪诊断。
- 当前支持范围：V1.2 只支持本地 ASSIST2017 checkpoint + `Dataset/assist2017` + `Dataset/H/2017.csv`。小型 demo 内容集仍使用自己的 `question_id`，系统会为 dashboard smoke 生成稳定 ASSIST2017 question id 并随事件传入 DGEKT；这只证明真实 checkpoint 推理链路可运行，不代表完整 ASSISTments2017 内容语义导入。
- DGEKT prediction facts 规范化：
  - `diagnose` 会在 `eval()` / `no_grad` 下读取 ensemble logits，输出 numeric `prediction_probability`。
  - `prediction_probability < 0.6` 会生成 weak concept proxy，`1 - prediction_probability >= 0.4` 会生成 forgetting risk proxy。
  - 如果事件同时带有 MathTutor `concept_id` / `concept_name`，weak/risk facts 使用 MathTutor 概念 ID，推荐器可直接参与现有 risk-prioritized ranking。
  - TeachingTrace 的 `diagnose` 阶段会记录 `kt_engine`、`kt_engine_diagnostics` 和 `prediction_facts`；`KTDiagnosis.metadata` 包含 DGEKT model provenance 和 inference input 摘要。
  - RAG 和 StudentMemory 仍只影响解释、偏好和策略，不覆盖 DGEKT 产生的 mastery / risk / prediction facts。
- DGEKT attribution evidence 规范化：
  - `explain_prediction` 返回 `AttributionEvidence.prediction_probability`、`raw_model_target`、`mapped_teaching_content`、`scorer`、`top_paths`、`key_history`、`weak_concepts`，并注入 TeachingTrace expert evidence。
  - `key_history` 反映最近已判题交互对本次 DGEKT 输入序列的贡献，包括 ASSIST2017 question / concept、正确性、序列位置、MathTutor concept 和可读摘要。
  - `top_paths` 记录 history question 到 target question 的可审计路径摘要，包括 Q-matrix concept relation、question relation、recency strength、`path_strength`、`relation_strength`、`relation_source=q_matrix_recent_history_proxy`、`weak_concept_hit` 和 `partial_evidence_reason`。
  - 当前实现是在线 partial attribution：没有读取原工程离线 `attribution_paths.csv` / `key_history.csv` scorer 输出，因此每条 path 都标注 `partial_evidence=true` 和 `evidence_status=partial`，研究者可审计但不能当作完整双图归因。
- 本地 memory 是默认实现，Mem0 adapter 后续接入。
- 本地 RAG fallback 是默认实现，VikingDB adapter 后续接入。

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
