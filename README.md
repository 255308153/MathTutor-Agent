# MathTutor Agent

MathTutor Agent 是一个面向个人学习者的数学学习 Agent。V1 目标不是做通用聊天机器人，而是先跑通一个可演示、可测试、可解释的数学学习闭环：

```text
学习事件 / 学生提问
-> 读取学生状态与长期记忆
-> 检索数学知识与题目解释
-> 知识追踪诊断
-> 规划下一步教学动作
-> 推荐题目 / 讲解 / 复习 / 错因诊断
-> 生成学生可读反馈
-> 记录 TeachingTrace
-> 更新长期学习记忆
```

V1 的一句话定位：

```text
一个基于可解释知识追踪、RAG 和长期学习记忆的数学个人教师 Agent。
```

## V1 范围

V1 优先服务一个学生、一个数学学习场景、一条可审计学习闭环。

包含：

- FastAPI 后端入口。
- MathTutor 事件处理主循环。
- `MockKTStateEngine` 本地知识追踪实现。
- 小型本地数学教学内容集和确定性判题。
- 风险优先的题目推荐与推荐理由。
- 本地 RAG fallback，并预留 VikingDB adapter。
- 本地学生长期记忆，并预留 Mem0 adapter。
- 错因诊断和四类教学动作。
- TeachingTrace，可追踪每次 agent 决策依据。
- React 学习驾驶舱首版。

暂不包含：

- 多学科。
- 班级 / 教师端。
- 移动端。
- 商业级登录、权限和支付。
- 完整 AGI-saber 迁移。
- 真实在线训练 DGEKT / SAFKT。
- 大规模自动题库生成。
- 复杂分布式多 Agent。

## 核心边界

实现时必须保持以下规则：

```text
KT facts are authoritative.
LLM plans are advisory.
Memory can influence strategy, not mastery.
RAG can support explanation, not overwrite prediction facts.
Context can assemble evidence, not decide learning facts.
```

也就是说：

- KT 输出的掌握度、遗忘风险、预测概率和薄弱知识点是权威事实。
- LLM 只给教学表达和策略建议，不覆盖 KT 事实。
- Memory 可以影响讲解风格、复习策略和偏好，不直接改写 mastery。
- RAG 支持解释、证据和题解，不覆盖 prediction facts。
- Context 负责收集和组装证据，不决定或改写 mastery、weak concepts、forgetting risk、prediction probability。

## 目录结构

```text
backend/
  app/
    api/        FastAPI routers
    core/       配置、事件、trace 基础能力
    graph/      MathTutor 主循环编排
    context/    LearningContextLayer 上下文资产、组装与本地 fallback
    kt/         KTStateEngine 接口与 Mock / DGEKT 预留实现
    memory/     学生长期记忆接口与本地实现
    planning/   教学动作规划与推荐
    rag/        知识检索接口、本地 fallback、VikingDB 预留
    schemas/    Pydantic 领域模型
    storage/    本地数据仓储
  tests/        后端测试

data/
  content/      小型数学题库、知识点、题解、错因与策略材料
  local/        本地运行产生的 sqlite / cache，默认不提交
  mapping/      ASSIST2017 canonical mapping 小型 fixture / schema artifact
  rag/          本地 RAG 文档

docs/           中文架构、开发和演示文档
frontend/       React 学习驾驶舱
```

## 本地启动

建议使用 Python 3.11+。

```bash
cd /Users/lqc/Downloads/MathTutor-Agent
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

启动后端：

```bash
uvicorn backend.app.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

预期返回：

```json
{"status":"ok"}
```

启动 React 学习驾驶舱：

```bash
cd frontend
npm install
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173
```

前端开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。如果后端使用其他地址，可设置：

```bash
VITE_MATHTUTOR_API_BASE=http://127.0.0.1:8000 npm run dev
```

## 一分钟演示路径

1. 默认 mock 模式启动后端：`uvicorn backend.app.main:app --reload`。
2. 启动前端：`cd frontend && npm run dev`。
3. 打开 `http://127.0.0.1:5173`，页面会自动请求“我下一步应该练什么？”。
4. 看“今日建议”“推荐题”“薄弱概念”“遗忘风险”，确认 Agent 给出下一步练习。
5. 在第一道推荐题输入一个错误答案并提交，查看错因诊断、概念状态变化和新的推荐题。
6. 再对下一道推荐题输入正确答案，查看巩固反馈和后续推荐。
7. 展开 `TeachingTrace`、`RAG 引用`、`模型证据`，检查 KT facts、RAG 来源、planner decision 和 attribution evidence。

V1.2 DGEKT 演示路径：

```bash
export MATHTUTOR_KT_ENGINE=dgekt
export MATHTUTOR_DGEKT_DATASET=assist2017
export MATHTUTOR_DGEKT_CHECKPOINT_PATH=/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/KnowledgeTracing/model/runs/20260707_222733/save2017model.pkl
export MATHTUTOR_DGEKT_DATASET_DIR=/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/Dataset/assist2017
export MATHTUTOR_DGEKT_Q_MATRIX_PATH=/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/Dataset/H/2017.csv
uvicorn backend.app.main:app --reload
```

然后按同一条 dashboard 路径完成“下一步建议 -> 推荐题 -> 提交答案 -> 状态变化 -> TeachingTrace / 模型证据”。DGEKT 模式下，`模型证据` 会显示 engine、checkpoint provenance、prediction facts、DGEKT attribution、Top path、Path strength 和 Key history。若 checkpoint / 数据 / 映射缺失，后端会返回可读错误，前端会在页面顶部展示。

V1.2 演示验收点：

- 答题提交由服务端本地内容集确定性判题，不依赖 LLM 记答案。
- 答对 / 答错后都会返回新的推荐题，便于连续演示。
- TeachingTrace 使用学生可读主流程 + 专家证据层，研究者可以看到 KT / RAG / memory / recommendation evidence。
- 默认 mock 模式保留 V1.1 演示；显式 `MATHTUTOR_KT_ENGINE=dgekt` 才会加载真实 checkpoint。
- DGEKT 模式会产出真实 checkpoint prediction probability，并把 prediction facts / attribution evidence 注入 TeachingTrace。
- 推荐题、题解、错因和 citation 仍使用本地 demo 数据；demo 题会带稳定 ASSIST2017 smoke 映射，便于 dashboard 走通真实 DGEKT 推理，但它不是完整 ASSISTments2017 内容导入。

## V1.3 ASSIST2017 canonical mapping

V1.3 第一块地基是把 MathTutor 本地题目 / 知识点和 ASSIST2017 的 question、concept、Q-matrix 建立可审计映射。当前提交的是小型 fixture，不是全量 ASSISTments2017 导入。

已提交的小型文件：

- `data/mapping/assist2017_q_matrix.fixture.csv`：6 行 × 4 列的 Q-matrix fixture。
- `data/mapping/assist2017_curated_metadata.fixture.json`：人工整理的 question / concept / teaching_type / provenance 元数据。
- `data/mapping/assist2017_canonical_mapping.fixture.json`：由 Q-matrix 和 curated metadata 生成的 canonical artifact。

重新生成 artifact：

```bash
python -m backend.app.mapping.build_assist2017_mapping \
  --q-matrix data/mapping/assist2017_q_matrix.fixture.csv \
  --metadata data/mapping/assist2017_curated_metadata.fixture.json \
  --teaching-content data/content/demo_teaching_content.json \
  --rag-docs data/rag/demo_knowledge.json \
  --output data/mapping/assist2017_canonical_mapping.fixture.json
```

命令会输出 coverage 诊断，包含 mapped questions、mapped concepts、missing questions、missing concepts、missing teaching content 和 missing RAG docs。`ContentRepository` 会优先读取该 artifact，为本地题目补充 `assist2017_question_id`、`assist2017_concept_id` 和 Q-matrix reference；artifact 缺失时回退到 V1.2 的顺序 smoke id，默认 mock 模式不依赖 DGEKT 文件。

本地全量数据建议放在 Git 外部路径，或放在 `data/local/` 下。不要提交 ASSIST2017 全量 train/test、checkpoint、`.pkl`、生成模型文件、全量大型 mapping 输出；只提交小型 fixture、schema、代码和文档。

### V1.3 mapped teaching content

#21 起，推荐题会把 canonical mapping 后的教学内容随推荐结果返回，字段包括稳定 `question_id`、学生可读 `stem`、`answer`、`explanation`、`concept_name`、`difficulty`、`teaching_type`、`canonical_mapping`、`provenance` 和 `content_availability`。`standard_answer` 仍是服务端内容集字段，不作为同名字段暴露；答题提交时后端会重新读取本地内容集做确定性判题，不信任客户端传入的判题事实。

推荐排序会轻微优先选择已具备 curated ASSIST2017 question/concept/Q-matrix 对齐的题，避免 DGEKT 或诊断对象只停留在内部 ID。未映射题仍可作为本地 fallback，但会在 `canonical_mapping.source = local_sequence_fallback` 和 `content_availability` 中显式暴露。若题干、标准答案或解析缺失，API 返回可读 fallback / error，并在 TeachingTrace 中保留缺口，不能静默伪造教学内容。

### V1.3 canonical RAG alignment

#22 起，本地 RAG fallback 会把 `data/rag/demo_knowledge.json` 中的 concept notes、question explanations、mistake patterns 和 learning strategies 对齐到 canonical `question_id` / `concept_id`。文档 schema 支持 `assist2017_question_id`、`assist2017_concept_id`、`canonical_mapping`、`provenance` 和 `coverage`；小型 JSON fixture 不需要手写全部字段，`LocalKnowledgeRAG` 会在读取时根据 `data/mapping/assist2017_canonical_mapping.fixture.json` 做 runtime enrichment。

`rag_sources`、`assembled_context.normalized_context.knowledge_resource`、TeachingTrace 和 dashboard RAG 引用都会显示引用对应的真实 question / concept。RAG 缺失时只产生 evidence gap，不伪造知识资源，也不能覆盖 KT facts。

### V1.3 visible evidence gaps

#24 起，API 和 dashboard 会把 V1.3 常见数据缺口归一为可读 `error_records` / `evidence_gaps`，而不是崩溃、静默降级或伪造证据。当前分类包括：

- `missing_mapping`：事件缺少 canonical / ASSIST2017 question 或 concept 映射，或与 Q-matrix 不一致。
- `missing_content`：题干、标准答案或解析缺失；缺少标准答案时只记录未判题答案，不写 KT facts。
- `missing_rag_citation`：RAG 未找到 canonical question / concept 对齐的知识资源。
- `unsupported_dgekt_target`：显式 DGEKT target 超出 ASSIST2017 / Q-matrix 支持范围。
- `scorer_failure`：DGEKT attribution scorer 或运行时证据生成失败。

`state_summary.error_records` 面向 API 和 dashboard 顶部提示；`TeachingTrace` 的 `load_context` / `diagnose` metadata 与 `teaching_trace_summary.expert_evidence.evidence_gaps` 面向研究者审计。partial attribution 会继续显示 `partial_evidence=true` 和 `partial_evidence_reason`，不会伪装为完整路径证据。

### V1.3 end-to-end acceptance path

#25 的验收路径是同一 canonical concept 贯穿完整学习闭环：

```text
next-step advice
-> mapped recommendation
-> answer submission
-> DGEKT diagnosis
-> RAG explanation / citation
-> mistake diagnosis
-> attribution evidence
-> TeachingTrace
```

本地默认测试使用小型 fake DGEKT runtime 和 fixture Q-matrix，不读取真实 checkpoint。smoke case 锁定 `q_frac_001` / `c_fraction_addition`：推荐题返回 ASSIST2017 Q3 / C2、答错后 DGEKT 产生 `prediction_probability=0.2`、RAG citation 指向同一题或知识点、错因诊断指向同一 concept，TeachingTrace 的 `diagnose` / `context_assemble` / `plan` 会同时展示 attribution chain、knowledge_resource、selected canonical target 和 memory evidence gap。

真实 checkpoint 演示仍需显式设置 `MATHTUTOR_KT_ENGINE=dgekt` 与本地 ASSIST2017 路径；大数据、checkpoint、`.pkl` 和生成 artifact 不提交 Git。

## V1.4 LearningContextLayer 最小切片

V1.4 新增最小 LearningContextLayer，用来统一组织本轮学习事件需要的上下文资产。它不是新的学习事实来源，也不是 VikingDB / OpenViking Runtime；默认使用本地内存 fallback，不需要 Mem0、VikingDB、OpenViking 或外部 provider 凭据。

当前最小能力：

- `ContextAsset` 支持 `student_memory`、`knowledge_resource`、`task_state`、`tool_observation`、`trace_reference` 五类资产。
- `InMemoryContextAssetStore` 只保存上下文引用、摘要、检索和组装记录，不作为 runtime state 唯一真相。
- next-step advice / answer submission 主链路会在 KT 诊断之后组装 `assembled_context`，并写入 TeachingTrace expert evidence。
- `assembled_context.authoritative_kt_facts` 只引用 KT 输出，context assets 不能覆盖 KTDiagnosis、mastery、weak_concepts、forgetting_risk 或 prediction_probability。

V1.4 #29 / #35 进一步让“下一步建议”真实消费 normalized context：

- `student_memory` 会把已有偏好、重复错因、有效策略和学习目标标准化到 `assembled_context.normalized_context.student_memory`，并生成“参考学生偏好 / 参考重复错因 / 参考有效策略”等 included reason。
- `knowledge_resource` 会把本地 RAG 的 concept note、question explanation、mistake pattern、learning strategy 标准化到 `assembled_context.normalized_context.knowledge_resource`，推荐理由和 TeachingTrace 可显示“参考相关知识资源”。
- 新用户没有记忆时不创建假的 memory asset，而是在 `assembled_context.evidence_gaps` 标记“无可用记忆”。
- RAG 没命中时不伪造 knowledge_resource，也不覆盖 KT facts，而是在 evidence gaps 标记“RAG 未找到相关知识资源”。
- planner / recommender / response 读取 `assembled_context` 中的 normalized context，不直接调用 Mem0、VikingDB、OpenViking 或 provider SDK。

V1.4 #30 让 `answer_submitted` 路径也生成可审计上下文快照：

- `task_state` asset 记录 pending question、submitted answer、grading result 和 next action，`source_ref` 指向本轮 event / progress / trace。
- `tool_observation` asset 记录 KT diagnosis、RAG retrieval、mistake diagnosis 和 recommendation candidates；KT 快照会标记 `source=kt`、`trace_id`、`generated_at`、`freshness=fresh`。
- `trace_reference` asset 串联本轮检索来源、planner decision 和 memory update 来源。
- TeachingTrace expert evidence 会展示 selected / omitted context assets；例如正确作答或未判题时，错因诊断 asset 会以 omitted reason 出现。
- 这些资产只是审计快照和引用路径，不能替代 progress store、LearningEvent、KTDiagnosis、RAG 或 memory store 作为 runtime 真相。

V1.4 #31 增强 context retrieval / assembly 的可解释取舍：

- `retrieve_assets()` 支持按 `asset_type`、`student_id`、`session_id`、`concept_id`、`question_id`、`source_type`、`freshness` 和最低 `confidence` 过滤。
- 排序优先考虑当前 question / concept、当前 session、上下文优先级、freshness 和 confidence；同等条件下使用更新时间保持稳定。
- `assemble_context()` 会按预算选择资产，输出 `budget_used`、`budget_limit`、`compression_summary`，并在 `asset_summaries` 标记 `selection_status`、`included_reason`、`excluded_reason` 和 `budget_cost`。
- evidence gaps 会区分 `student_memory` 缺失、`knowledge_resource` 缺失、`stale_task_state`、`low_confidence_observation`、`provider_failure` 和 `context_budget`。
- 优先级保持为 KT facts first，其后是 current task/tool snapshots、student memory、knowledge resource、trace reference；KT facts 不进入可裁剪资产预算。

V1.4 #32 让 dashboard 在 TeachingTrace expert evidence 中展示上下文证据：

- `上下文证据` 面板会显示 selected / omitted context assets、asset type、source、summary、included_reason / excluded_reason、freshness、confidence、预算和压缩策略。
- `student_memory` 标为 Memory evidence，`knowledge_resource` 标为 RAG citation，`tool_observation` 标为 Tool snapshot，`task_state` 和 `trace_reference` 只作为上下文引用展示。
- evidence gap 和预算裁剪会可见；没有 context asset 时显示 fallback，但推荐卡、答题输入和学生回复仍按主学习流程运行。
- dashboard 只消费后端返回的 `assembled_context` / `context_assets`，不直接访问 Mem0、VikingDB、OpenViking 或任何 provider SDK，也不会把 context evidence 写回 mastery / risk。

V1.4 #33 收口了 LearningContextLayer 端到端验收：

- 后端 smoke 覆盖 `next-step advice -> assembled_context -> recommendation / response -> answer_submitted -> task_state / tool_observation / trace_reference -> TeachingTrace`。
- 同一个 canonical concept / question 会出现在 KT facts、student_memory、knowledge_resource、推荐理由、`assembled_context` 和 TeachingTrace 证据中。
- 测试会故意在 student memory 中放入 mastery / prediction_probability 伪事实，验证 context 不能覆盖 KTDiagnosis、mastery、weak_concepts、forgetting_risk 或 prediction_probability。
- 前端 smoke 验证 dashboard 能展示答题提交后追加的 task / tool / trace context evidence，同时不改变推荐卡、答题输入和学生回复主流程。
- 本地验收不需要 Mem0、VikingDB、OpenViking 或外部 provider 凭据；后续 provider adapter 只能替换存储 / 检索后端，不能成为学习事实来源。

推荐的本地验收命令：

```bash
python3 -m pytest backend/tests
cd frontend && npm test -- --run
cd frontend && npm run build
```

## V1.5 ASSISTments2017 导入与安全护栏

V1.5 引入 ASSISTments2017 imported artifact 生产线，但默认运行仍是轻量 demo/mock：

- `MATHTUTOR_ASSIST2017_DATASET_MODE=demo`：默认模式，只使用提交的小型 demo / fixture，不读取完整 ASSISTments2017。
- `MATHTUTOR_CONTENT_SOURCE=demo`、`MATHTUTOR_RAG_SOURCE=demo`、`MATHTUTOR_KT_ENGINE=mock`：默认后端和默认测试路径，不需要 checkpoint、Mem0、VikingDB/OpenViking。
- `MATHTUTOR_CONTENT_SOURCE=imported` + `MATHTUTOR_CONTENT_IMPORT_PATH=.../content_import.json`：显式读取导入教学内容 artifact。
- `MATHTUTOR_RAG_SOURCE=imported` + `MATHTUTOR_RAG_ARTIFACT_PATH=.../rag_documents.json`：显式读取导入 RAG artifact。
- `MATHTUTOR_ASSIST2017_DATASET_MODE=full`：仅用于本地全量数据构建，必须显式配置 source rows、Q-matrix 和输出目录。

可提交的小型 V1.5 测试资产只有：

```text
data/import/assist2017_source.fixture.csv
data/mapping/*.fixture.csv
data/mapping/*.fixture.json
data/imported/assist2017_fixture/*.json
```

全量 ASSISTments2017 推荐放在 Git 外部路径，例如：

```text
/Users/lqc/data/assist2017/
/Users/lqc/Downloads/assist2017-full/
```

如果临时放在仓库内，只能放在默认忽略的 `data/local/`、`data/raw/`、`data/full/` 或 `data/import/assist2017/`。不要提交 raw train/test、checkpoint、`.pkl`、`.pt`、`.pth`、`.ckpt`、`.safetensors`、cache、`dist/`、`build/`、`node_modules/` 或全量 generated artifacts。

构建小型 fixture artifact：

```bash
python3 -m backend.app.importing.build_assist2017_artifacts \
  --dataset-mode fixture \
  --output-dir data/imported/assist2017_fixture \
  --generated-at 2026-07-09T00:00:00+00:00
```

构建本地 full artifact 时必须显式传入本地路径，并建议输出到 ignored 目录：

```bash
python3 -m backend.app.importing.build_assist2017_artifacts \
  --dataset-mode full \
  --source-rows /Users/lqc/data/assist2017/source_rows.csv \
  --q-matrix /Users/lqc/data/assist2017/q_matrix.csv \
  --output-dir data/local/assist2017_full_artifacts
```

提交前可运行仓库护栏：

```bash
python3 scripts/check_repository_safety.py
```

该脚本会检查当前 Git tracked 文件中是否混入 raw train/test、checkpoint、cache/build 输出或非 fixture generated artifact。

## V1.3 / V1.4 已知限制与下一阶段优先级

当前仍是本地可演示版本：

- `MockKTStateEngine` 仍是默认引擎，用来保证 V1.1 演示不依赖大模型文件。
- `DGEKTStateEngine` 只在显式配置时加载本地 ASSIST2017 checkpoint；checkpoint 和原始数据不提交 Git。
- Demo 内容集现在优先读取 V1.3 canonical mapping fixture；未映射题仍回退到 dashboard smoke id。当前 fixture 只覆盖小样本，不等同完整题库语义对齐。
- 推荐题已返回 mapped teaching content、provenance 和缺失内容诊断；当前仍只覆盖 demo 内容集和小型 mapping fixture，全量 ASSISTments2017 题干 / 答案 / 解析需要后续导入。
- RAG 文档已 runtime 对齐 canonical question / concept，但当前 demo 知识库仍是精选小样本；coverage 会显式标记 `question`、`concept`、`global` 或未映射缺口。
- Attribution evidence 当前是在线 partial evidence：`dgekt_online_graph_proxy_scorer` 会基于 recent history、canonical / Q-matrix target、weak concept proxy 输出 `key_history`、`top_paths`、`path_strength`、`relation_strength`、`relation_source`、`weak_concept_hit` 和 `partial_evidence_reason`。它没有运行原 DGEKT 离线 path scorer，因此不能解读为完整双图归因。
- 学生长期记忆默认是本地内存实现，服务重启后不会持久化。
- RAG 使用本地 JSON fallback，不是生产向量库。
- 前端是单学习者演示驾驶舱，没有登录、权限和班级管理。
- LearningContextLayer E2E 当前覆盖 demo canonical question / concept 和小型本地 context assets，尚未接入真实 Mem0 / VikingDB / OpenViking provider adapter。
- 当前 mapping 已知缺口会通过 coverage 诊断显式暴露：fixture 中仍有缺失 question、缺失 concept、缺失 teaching content 和缺失 RAG doc，用于驱动后续 V1.3 导入切片。

下一阶段真实集成优先级：

1. `ASSISTments2017` 完整内容导入：建立题目、知识点、历史作答和 RAG 文档的稳定语义映射。
2. 原 DGEKT explainability 离线结果接入：把 `attribution_paths.csv` / `key_history.csv` 级别证据接入 `AttributionEvidence`，替换当前 online partial scorer 的代理关系强度。
3. `Mem0` adapter：把本地 memory store 替换成可持久化的学生长期记忆。
4. `VikingDB` adapter：把本地 RAG JSON fallback 替换成可扩展向量检索。

## 测试与检查

```bash
python -m compileall backend/app
pytest
ruff check .
cd frontend && npm test && npm run build
```

当前基线要求：

- 健康检查测试通过。
- Python 编译检查通过。
- React smoke test 和生产构建通过。
- 新增功能应优先补最小可验证测试。

## 环境变量

复制 `.env.example` 为 `.env` 后按需调整：

```bash
cp .env.example .env
```

默认约定：

- `MATHTUTOR_ENV=development`：本地开发环境。
- `MATHTUTOR_DB_URL=sqlite:///./data/local/mathtutor.sqlite`：本地 sqlite。
- `MATHTUTOR_VECTOR_BACKEND=chroma`：本地向量检索 fallback。
- `MATHTUTOR_LLM_PROVIDER=mock`：V1 先用 mock / 规则化响应跑通闭环。
- `MATHTUTOR_LLM_MODEL`：真实 LLM 模型名，mock 模式可留空。
- `MATHTUTOR_OPENAI_API_KEY`：真实 LLM key，本地 mock 模式可留空。
- `MATHTUTOR_ASSIST2017_DATASET_MODE=demo`：默认数据模式；`fixture` 用于构建提交的小型 fixture，`full` 仅用于显式本地全量构建。
- `MATHTUTOR_ASSIST2017_FULL_SOURCE_ROWS_PATH`：本地 full source rows CSV 路径，默认留空。
- `MATHTUTOR_ASSIST2017_FULL_Q_MATRIX_PATH`：本地 full Q-matrix 路径，默认留空。
- `MATHTUTOR_ASSIST2017_FULL_ARTIFACT_DIR`：本地 full artifact 输出目录，建议指向 `data/local/...` 或 Git 外部路径。
- `MATHTUTOR_CONTENT_SOURCE=demo`：默认教学内容仓库；`imported` 需要显式配置 `MATHTUTOR_CONTENT_IMPORT_PATH`。
- `MATHTUTOR_CONTENT_IMPORT_PATH`：导入 `content_import.json` 路径，默认留空，缺失时不会静默 fallback。
- `MATHTUTOR_RAG_SOURCE=demo`：默认本地 RAG；`imported` 需要显式配置 `MATHTUTOR_RAG_ARTIFACT_PATH`。
- `MATHTUTOR_RAG_ARTIFACT_PATH`：导入 `rag_documents.json` 路径，默认留空，缺失时不会静默 fallback。
- `MATHTUTOR_KT_ENGINE=mock`：默认 KT 引擎；保持 V1.1 演示不依赖真实 checkpoint。
- `MATHTUTOR_KT_ENGINE=dgekt`：显式启用真实 DGEKT 配置校验。
- `MATHTUTOR_DGEKT_DATASET=assist2017`：V1.2 当前支持的真实数据集。
- `MATHTUTOR_DGEKT_CHECKPOINT_PATH`：本地 ASSIST2017 checkpoint 路径。已验证 checkpoint 示例：`/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/KnowledgeTracing/model/runs/20260707_222733/save2017model.pkl`。
- `MATHTUTOR_DGEKT_DATASET_DIR`：ASSIST2017 数据目录，需包含 `assist2017_pid_train.csv` 和 `assist2017_pid_test.csv`。
- `MATHTUTOR_DGEKT_Q_MATRIX_PATH`：Q-matrix / incidence matrix 文件，例如原始 DGEKT 工程的 `Dataset/H/2017.csv`。
- `MATHTUTOR_RUN_DGEKT_SMOKE=1`：显式运行本地真实 checkpoint smoke test；默认测试不会读取大模型。

大 checkpoint 和原始数据文件不提交到 Git，只通过本地路径或环境变量引用。默认 mock 模式不会读取上述 DGEKT 文件。

DGEKT checkpoint 读取说明：

- adapter 期望 checkpoint 是包含 `epoch`、`model_state_dict`、`optimizer_state_dict`、`auc`、`acc` 的字典。
- 推理模型只加载 `model_state_dict` 并进入 `eval()`；`optimizer_state_dict` 仅作为 checkpoint 完整性验证，不参与预测。
- PyTorch 2.6+ 默认 `weights_only=True` 会拒绝该历史 checkpoint 中的 numpy 标量 metadata；本项目仅在显式启用 `MATHTUTOR_KT_ENGINE=dgekt` 且用户信任本地文件时使用 `weights_only=False`。
- DGEKT 输入转换读取最近已判题的 `answer_submitted` 事件，使用 payload 中的 `assist2017_question_id` / `dgekt_question_id` 构造原 DGEKT one-hot 序列；concept 来自 `assist2017_concept_id` / `dgekt_concept_id` 或 Q-matrix。映射缺失或与 Q-matrix 不一致时会明确失败，不返回伪结果。
- DGEKT 诊断会把模型预测规范化为 `KTDiagnosis.prediction_probability`、weak concept proxy 和 forgetting risk proxy；推荐器和 TeachingTrace 读取这些 KT facts，但 RAG / Memory 不会覆盖它们。
- DGEKT attribution evidence 会进入 `AttributionEvidence` 和 TeachingTrace expert evidence：`prediction_probability` 是模型预测答对概率，`raw_model_target` 记录 DGEKT 使用的 ASSIST2017 question / concept，`mapped_teaching_content` 记录映射后的 MathTutor 教学内容，`key_history` 是最近进入 DGEKT 序列的已判题交互，`top_paths` 记录 history question 到 target question 的 Q-matrix 概念关系、`path_strength` / `relation_strength` / `relation_source`、`weak_concept_hit` 和 `partial_evidence_reason`。`diagnose` 阶段 TeachingTrace 会额外写入 `attribution_chain`，展示 raw model target -> mapped teaching content -> attribution evidence。当前在线 adapter 尚未运行原工程离线 path scorer，因此这些路径标注为 partial evidence，不能解读为完整双图归因。

## Agent 工作方式

后续实现优先从 GitHub issue 开始：

1. 选择当前未完成且依赖已满足的最小 issue。
2. 阅读 issue 描述、验收点和相关文档。
3. 做到可运行、可测试、可演示，而不是只提交代码骨架。
4. 更新 README、开发文档或用户可见中文文案。
5. 运行相关测试。
6. 提交 git commit。
7. 如可行，推送到 GitHub，并在对应 issue 留完成说明。

每个 PR / commit 都应说明覆盖了哪些验收点，未覆盖的点必须明确留在 issue 中。

更多架构细节见 [docs/V1_ARCHITECTURE.md](docs/V1_ARCHITECTURE.md)，开发细节见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。
