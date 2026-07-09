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
- 本地 RAG fallback，以及 opt-in VikingDB / OpenViking adapter。
- 本地学生长期记忆，以及 opt-in Mem0 adapter。
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
Offline attribution explains prediction, not overwrite prediction facts.
Memory can influence strategy, not mastery.
RAG can support explanation, not overwrite prediction facts.
Context can assemble evidence, not decide learning facts.
```

也就是说：

- KT 输出的掌握度、遗忘风险、预测概率和薄弱知识点是权威事实。
- LLM 只给教学表达和策略建议，不覆盖 KT 事实。
- Offline attribution 只解释 DGEKT prediction，不覆盖 prediction facts。
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
    rag/        知识检索接口、本地 fallback、VikingDB / OpenViking adapter
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

然后按同一条 dashboard 路径完成“下一步建议 -> 推荐题 -> 提交答案 -> 状态变化 -> TeachingTrace / 模型证据”。DGEKT 模式下，`模型证据` 会显示 engine、checkpoint provenance、prediction facts、DGEKT attribution、Top path、Path strength 和 Key history。V1.6 起，如果显式配置 offline evidence artifact，还会显示 offline / partial / unavailable / invalid 状态、scorer provenance、path ablation 和 evidence gap。若 checkpoint / 数据 / 映射缺失，后端会返回可读错误，前端会在页面顶部展示。

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

如果临时放在仓库内，只能放在默认忽略的 `data/local/`、`data/raw/`、`data/full/` 或 `data/import/assist2017/`。不要提交 provider credentials、secrets、`.env`、provider cache、generated vector index、raw train/test、checkpoint、`.pkl`、`.pt`、`.pth`、`.ckpt`、`.safetensors`、cache、`dist/`、`build/`、`node_modules/` 或全量 generated artifacts。

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

该脚本会检查当前 Git tracked 文件中是否混入 provider credentials、secrets、`.env`、generated vector indexes、provider caches、raw train/test、checkpoint、模型文件、cache/build 输出或非 fixture generated artifact。

### V1.5 artifact contract

导入命令一次写出 5 个稳定 JSON artifact，后端只通过这些 artifact 或默认 demo fixture 读取内容，不直接从 raw train/test 文件进入 runtime：

| 文件 | schema_version | 用途 |
| --- | --- | --- |
| `canonical_mapping.json` | `assist2017-canonical-mapping/v1` | canonical question/concept 与 ASSISTments2017 question/concept、Q-matrix row/column 的对齐表。 |
| `content_import.json` | `assist2017-content-import/v1` | `ContentRepository` 可读取的题干、标准答案、解析、难度、错因、教学类型、provenance 和 `content_availability`。 |
| `rag_documents.json` | `assist2017-rag-documents/v1` | `KnowledgeRAG` 可读取的 `concept_note`、`question_explanation`、`mistake_pattern`、`learning_strategy` 文档。 |
| `coverage_report.json` | `assist2017-coverage-report/v1` | mapping、content、RAG、Q-matrix 的覆盖率和 gap 诊断。 |
| `smoke_dataset.json` | `assist2017-smoke-dataset/v1` | 固定学习路径 smoke，验证推荐、答题、RAG、Context 和 TeachingTrace 使用同一 canonical question/concept。 |

所有 artifact 都带 `metadata.generated_at`、`metadata.source_paths`、`metadata.row_counts`、`metadata.coverage_summary` 和 `metadata.validation_errors`。`ContentRepository` 读取 imported 内容时只认 `content_import.json`；`KnowledgeRAG` 读取 imported RAG 时只认 `rag_documents.json`；KT facts 仍来自 KT engine。

### demo / smoke fixture / full data 区别

| 模式 | 入口 | 使用场景 | Git 规则 |
| --- | --- | --- | --- |
| demo | 默认 `MATHTUTOR_CONTENT_SOURCE=demo`、`MATHTUTOR_RAG_SOURCE=demo`、`MATHTUTOR_KT_ENGINE=mock` | 本地启动、默认测试、dashboard 演示。 | 提交小型 `data/content`、`data/rag`、`data/mapping/*.fixture.*`。 |
| imported fixture / smoke | `data/imported/assist2017_fixture/*.json` + 显式 `MATHTUTOR_CONTENT_SOURCE=imported` / `MATHTUTOR_RAG_SOURCE=imported` | CI 和本地 smoke 验证真实导入 contract。 | 只提交小型 fixture artifact。 |
| full | `--dataset-mode full --source-rows ... --q-matrix ...` | 研究者在本机用完整 ASSISTments2017 构建 artifact。 | raw train/test、checkpoint 和 full generated artifact 不提交，输出到 Git 外部或 ignored 目录。 |

### coverage report 解读

`coverage_report.json` 的 `summary` 分四组：

- `mapping`：`mapped_question_ids` / `mapped_concept_ids` 表示已对齐；`unmapped_question_ids` / `unmapped_concept_ids` 表示 Q-matrix 中存在但 source rows 或 concept metadata 未覆盖。
- `content`：`complete_question_count`、`partial_question_count` 和 `missing_teaching_content` 用来区分映射成功但题干、标准答案或解析仍不完整的题。
- `rag`：`doc_type_counts` 和 `missing_rag_docs` 说明四类 RAG 文档是否覆盖 canonical question/concept。
- `q_matrix`：`mismatches` 记录 source row 声明的 concept 与 Q-matrix row 不一致，属于 error 级导入问题。

gap category 固定为：`missing_question_mapping`、`missing_concept_mapping`、`q_matrix_mismatch`、`missing_teaching_content`、`missing_rag_doc`。这些 gap 只用于诊断与 TeachingTrace 可见化；RAG 和 Context 不会据此改写 mastery、weak concepts、forgetting risk 或 prediction probability。

## V1.6 DGEKT offline evidence 技术内测

V1.6 接入原 DGEKT explainability 输出的只读 adapter，用来解释 checkpoint prediction，不参与改写 prediction facts。默认 demo/mock 路径仍不读取 checkpoint、raw train/test 或 offline evidence；只有同时显式启用 `MATHTUTOR_KT_ENGINE=dgekt` 和本地 evidence 目录时，才读取离线归因 artifact。

最小 fixture 已提交在 `data/dgekt/offline_evidence_fixture/`，只用于测试 contract 和 dashboard smoke。真实 full explainability outputs 必须放在 Git 外部路径或 ignored 目录。

Offline evidence 目录需要包含：

| 文件 | 用途 |
| --- | --- |
| `diagnosis_cases.json` | sample、target、prediction、checkpoint/scorer provenance 索引。 |
| `attribution_paths.csv` | top attribution paths、path score、graph relation、history question/concept。 |
| `key_history.csv` | 进入 DGEKT 序列的关键历史交互与 influence score。 |
| `path_ablation.csv` | 删除 top path 后的 prediction 变化、impact、comprehensiveness。 |
| `weak_concepts.csv` | 离线 weak concept evidence 与命中 path。 |

V1.6 evidence status：

- `complete` + `offline`：当前 canonical question/concept、student target、checkpoint provenance 和 CSV schema 全部匹配，dashboard 展示 top paths、key history、path ablation 和 scorer provenance。
- `partial`：没有配置 offline evidence，或需要使用在线 proxy；该证据只能说明可审计 fallback，不能伪装成完整 DGEKT 离线归因。
- `unavailable`：artifact 缺失、目标 sample 未命中等可恢复缺口；TeachingTrace 和 dashboard 会显示 gap reason。
- `invalid`：缺列、 malformed row、重复 sample、checkpoint provenance 不一致或 canonical mapping 不一致；系统保留 KT facts，但拒绝把该离线证据标记为 complete。

Offline gap category 包括：`missing_artifact`、`missing_column`、`malformed_row`、`invalid_numeric_value`、`duplicate_sample`、`target_not_found`、`canonical_mapping_mismatch`、`checkpoint_provenance_mismatch`。这些 gap 会进入 `AttributionEvidence.evidence_gaps`、`assembled_context.evidence_gaps` 和 TeachingTrace expert evidence。

核心边界保持不变：KT facts are authoritative；Offline attribution explains prediction, not overwrite prediction facts；RAG 只支持解释，不覆盖预测事实；Context 只组装证据，不决定学习事实。

## V1.7 provider mode contract

V1.7 开始把长期记忆和知识检索统一为 provider 化 contract，但默认运行仍是本地 fallback，不需要 Mem0、VikingDB、OpenViking、真实 DGEKT checkpoint 或完整 ASSISTments2017 数据。

Provider mode 语义固定为：

| mode | 含义 | 默认性 |
| --- | --- | --- |
| `local_fallback` | 使用当前进程内 `InMemoryStudentMemoryStore` 和本地 JSON `LocalKnowledgeRAG`。 | 默认模式。 |
| `fake_provider` | 使用无网络、无密钥的 fake provider fixture，模拟 Mem0 / VikingDB SDK 响应，但只向下游返回稳定领域模型。 | 仅测试 / adapter 开发显式启用。 |
| `live_provider` | 显式加载真实 provider adapter。Mem0 已通过 `StudentMemoryStore` adapter 接入；VikingDB / OpenViking 已通过 `KnowledgeRAG` adapter 接入。 | 非默认；缺少 live provider 配置时不会启用。 |

环境变量：

```bash
MATHTUTOR_MEMORY_PROVIDER_MODE=local_fallback
MATHTUTOR_RAG_PROVIDER_MODE=local_fallback
MATHTUTOR_MEM0_API_KEY=
MATHTUTOR_RUN_MEM0_LIVE_SMOKE=0
MATHTUTOR_VIKINGDB_API_KEY=
MATHTUTOR_OPENVIKING_API_KEY=
```

当前 fake provider fixture 覆盖：

- 记忆写入、记忆检索、recent memory。
- Mem0 adapter 覆盖 preference、repeated_mistake、effective_strategy、reflection 四类记忆，返回 `StudentMemory` 稳定模型，并保留 question / concept / trace / event time provenance、relevance、freshness 和 source 元数据。
- Mem0 写入使用稳定 dedupe key，重复学习事件会更新既有记忆 provenance，不会无界追加重复记录。
- RAG 检索、question / concept 对齐字段、provider 空结果。
- raw provider payload 清洗，防止 `sdk_response`、内部向量距离、embedding vector 等 provider SDK 字段泄漏到 planner、recommender、TeachingTrace API 或 dashboard。

Mem0 live provider 是 opt-in：默认 `local_fallback` 不需要 Mem0 SDK、API key 或网络；只有设置 `MATHTUTOR_MEMORY_PROVIDER_MODE=live_provider` 且提供 `MATHTUTOR_MEM0_API_KEY` 时才会尝试加载 `mem0ai` 的 `MemoryClient`。本地可用 `pip install .[mem0]` 安装可选 SDK；live smoke 还需要显式设置 `MATHTUTOR_RUN_MEM0_LIVE_SMOKE=1`，否则测试会 skip。

VikingDB / OpenViking live RAG 也是 opt-in：只有设置 `MATHTUTOR_RAG_PROVIDER_MODE=live_provider`，并同时提供 `MATHTUTOR_RAG_LIVE_PROVIDER`、`MATHTUTOR_RAG_PROVIDER_ENDPOINT`、`MATHTUTOR_RAG_PROVIDER_COLLECTION` 和对应 API key 时才会创建 live adapter。live smoke 需要 `MATHTUTOR_RUN_VIKING_RAG_SMOKE=1` 且上述配置完整，否则自动 skip；默认测试不会访问外部 provider。

Provider 配置诊断：

- 配置缺失：`live_provider` 缺 API key、endpoint 或 collection 会抛出配置错误；保持默认 `local_fallback` 可继续本地 demo。
- `provider_auth_error`：检查 Mem0 / VikingDB / OpenViking key、权限和 provider 选择；系统不会信任失败 provider 的 evidence。
- `provider_timeout`：检查 endpoint、网络和 `MATHTUTOR_RAG_PROVIDER_TIMEOUT_SECONDS`；主学习流程会继续使用已有 local/fake evidence。
- `provider_empty_result`：provider 未返回可用记忆或 citation；不要伪造 memory/RAG evidence，改查 query、metadata filter 和 collection 内容。
- `provider_schema_mismatch`：provider 响应无法规范化为 `StudentMemory` 或 `RAGSearchResult`；检查字段别名、metadata filter 和 adapter schema。
- `provider_budget_exceeded`：检查 quota/rate limit；系统只使用已取得 evidence，不覆盖 KT facts。

V1.7 所有子任务必须使用独立 git worktree 并发开发：每个 issue 从最新 `origin/master` 创建自己的 `codex/...` 分支和 worktree，不在主工作区直接实现，不共用未提交改动。失败降级、context E2E、dashboard、配置安全和 provider 运维任务都应按这个规则拆开推进。

Provider 化不能改变核心边界：Memory can influence strategy, not mastery；RAG can support explanation, not overwrite prediction facts；Context can assemble evidence, not decide learning facts；KT facts 仍是权威学习事实。

V1.7 仍只允许 small expert trial。内部正式试用不得早于 **V1.8**。

### V1.7 最终收口状态

截至 2026-07-09，#71-#77 已按依赖顺序合并；#78 是最终文档与验收收口项。#70 父 PRD 继续保持 open，作为 V1.7 / V1.8 后续验收入口。

| issue | PR | 状态 | 覆盖能力 |
| --- | --- | --- | --- |
| [#71](https://github.com/255308153/MathTutor-Agent/issues/71) | [#79](https://github.com/255308153/MathTutor-Agent/pull/79) | 已合并 | provider contract 骨架、fake provider、默认 fallback 边界。 |
| [#72](https://github.com/255308153/MathTutor-Agent/issues/72) | [#81](https://github.com/255308153/MathTutor-Agent/pull/81) | 已合并 | Mem0 `StudentMemoryStore` adapter、跨会话记忆 smoke、KT facts 边界。 |
| [#73](https://github.com/255308153/MathTutor-Agent/issues/73) | [#80](https://github.com/255308153/MathTutor-Agent/pull/80) | 已合并 | VikingDB / OpenViking `KnowledgeRAG` adapter、metadata filter 和 deterministic post-filter smoke。 |
| [#74](https://github.com/255308153/MathTutor-Agent/issues/74) | [#82](https://github.com/255308153/MathTutor-Agent/pull/82) | 已合并 | provider auth、timeout、empty result、schema mismatch、budget exceeded 的 evidence gap 降级。 |
| [#75](https://github.com/255308153/MathTutor-Agent/issues/75) | [#83](https://github.com/255308153/MathTutor-Agent/pull/83) | 已合并 | provider-aware LearningContextLayer E2E，context 只组装证据。 |
| [#76](https://github.com/255308153/MathTutor-Agent/issues/76) | [#84](https://github.com/255308153/MathTutor-Agent/pull/84) | 已合并 | dashboard 展示 provider-backed memory / RAG context evidence、selected / omitted assets 和 provider gaps。 |
| [#77](https://github.com/255308153/MathTutor-Agent/issues/77) | [#85](https://github.com/255308153/MathTutor-Agent/pull/85) | 已合并 | opt-in 配置、optional live smoke、安全禁提交护栏。 |
| [#78](https://github.com/255308153/MathTutor-Agent/issues/78) | 本收口 PR | 随本 PR 合并完成 | 中文文档、端到端验收记录、#70 汇总评论。 |

三种 V1.7 验收模式：

| 模式 | 如何运行 | 期望结果 |
| --- | --- | --- |
| default local | 不设置 provider env；运行 `python3 -m pytest backend/tests`、`cd frontend && npm test -- --run`、`cd frontend && npm run build`。 | 使用 `local_fallback` memory / RAG，demo/mock 路径保持可运行，不需要 Mem0、VikingDB、OpenViking、checkpoint 或 full data。 |
| fake provider | 运行 provider contract、Mem0、RAG、context E2E 相关测试，例如 `python3 -m pytest backend/tests/test_provider_contracts.py backend/tests/test_mem0_memory_store.py backend/tests/test_learning_context_e2e.py -q`。 | 无网络、无密钥；fake Mem0 / VikingDB fixture 被规范化为 `StudentMemory`、`RAGSearchResult` 和 context evidence，SDK/debug payload 不下传。 |
| optional live provider smoke | Mem0 需 `MATHTUTOR_RUN_MEM0_LIVE_SMOKE=1` + `MATHTUTOR_MEM0_API_KEY`；VikingDB/OpenViking 需 `MATHTUTOR_RUN_VIKING_RAG_SMOKE=1` + endpoint + collection + 对应 API key。 | 配置完整才运行 live smoke；任一条件缺失时测试 skip，默认 CI / 本地验收不访问外部 provider。 |

本收口 PR 的最终验收命令：

```bash
python3 -m pytest backend/tests
cd frontend && npm test -- --run
cd frontend && npm run build
python3 scripts/check_repository_safety.py
```

这些命令必须在 #78 合并前全部通过；`scripts/check_repository_safety.py` 需要保持 `violation_count=0`。V1.7 只满足 small expert trial only，不满足内部正式试用；内部正式试用仍不得早于 **V1.8**。

2026-07-09 本地验收结果：

| 命令 | 结果 |
| --- | --- |
| `python3 -m pytest backend/tests` | 通过，149 passed，4 skipped。skipped 项为显式 opt-in 的真实 checkpoint / full offline evidence / Mem0 live smoke / VikingDB 或 OpenViking live smoke。 |
| `cd frontend && npm test -- --run` | 通过，1 个 test file / 9 tests passed。 |
| `cd frontend && npm run build` | 通过，Vite production build 成功；`frontend/dist/` 为 ignored build output，不提交。 |
| `python3 scripts/check_repository_safety.py` | 通过，`violation_count=0`，Git tracked 文件未包含 credentials、secrets、provider caches、generated vector indexes、raw datasets、checkpoints、模型文件、`dist` 或 `node_modules`。 |

## V1.6 已知限制与下一阶段优先级

当前仍是技术内测版本：

- `MockKTStateEngine` 仍是默认引擎，用来保证 V1.1 演示不依赖大模型文件。
- `DGEKTStateEngine` 只在显式配置时加载本地 ASSIST2017 checkpoint；checkpoint 和原始数据不提交 Git。
- Demo 内容集现在优先读取 V1.3 canonical mapping fixture；V1.5 imported fixture 只在显式配置或 smoke tests 中启用。
- V1.5 已提供 ASSISTments2017 source rows + Q-matrix 到 imported artifact 的构建链路；完整数据是否覆盖充分取决于本地 full source rows、题解和 RAG 文档质量，coverage report 会显式暴露缺口。
- RAG 文档已支持 imported artifact 和 runtime canonical 对齐；当前提交的 demo / fixture 仍是小样本，不把缺失 citation 伪造成知识资源。
- Attribution evidence 已支持显式配置下的 DGEKT offline evidence adapter；未配置、未命中或证据无效时仍回退为 partial / unavailable / invalid，不会把在线 proxy 伪装成 complete offline evidence。
- 学生长期记忆默认是本地内存实现；显式启用 Mem0 adapter 后可持久化。
- RAG 使用本地 JSON fallback，不是生产向量库。
- 前端是单学习者演示驾驶舱，没有登录、权限和班级管理。
- LearningContextLayer E2E 当前覆盖 demo canonical question / concept 和小型本地 context assets；Mem0 provider smoke 使用 fake client 覆盖跨会话记忆召回，VikingDB / OpenViking adapter 已作为显式 opt-in RAG provider 接入。
- 当前 V1.5 fixture 故意保留缺失 question、缺失 concept、缺失 teaching content 和缺失 RAG doc，用于测试 coverage 诊断；这不是 full data 质量承诺。

### 内部正式试用版本约束

内部正式试用不得早于 **V1.8**。V1.5 已把真实 ASSISTments2017 内容底座、artifact 构建链路、coverage 诊断和 smoke path 建起来；V1.6 接入真实 DGEKT offline attribution / checkpoint evidence，但仍然是技术内测版本，不应邀请普通内部学习者连续使用。

| 版本 | 定位 | 试用边界 |
| --- | --- | --- |
| V1.5 | 真实数据内容底座 | 仅开发 / 研究验证。 |
| V1.6 | 真实 DGEKT offline attribution / checkpoint evidence | 技术内测，不面向普通内部用户。 |
| V1.7 | Mem0 长期记忆 + VikingDB / OpenViking RAG adapter | 小范围专家试用。 |
| V1.8 | 内部正式试用版 | 可邀请真实内部学习者连续使用。 |
| V1.9 | 内部试用优化版 | 扩大内部试用范围。 |
| V2.0 | 产品化 beta | 对外展示或半开放试用。 |

V1.8 的准入门槛：

- 真实 DGEKT evidence、长期记忆、生产级 RAG adapter 和持久化学习状态全部接入并通过验收。
- 答题、推荐、解释、错因、复习计划形成完整闭环。
- 学生记忆可查看、可清理、可禁用。
- RAG / KT / Memory / Context 的证据边界清楚，不静默编造答案、解析或 mastery facts。
- 有基础日志、评估指标和问题反馈入口。
- 至少跑通 3-5 个真实内部用户的连续学习流程。

下一阶段真实集成优先级：

1. Mem0 运营控制：补齐学生记忆查看、禁用、清理和 provider health。
2. Provider 失败降级与可观测性：补齐 Mem0、VikingDB / OpenViking live provider 的健康检查、错误提示和恢复路径。
3. 持久化学习状态与 TeachingTrace：支持连续学习会话审计。
4. Full-data artifact 存储和分发策略：如果 full generated artifact 需要跨机器复用，应进入 Git 外部对象存储或发布流程，而不是直接提交到仓库。

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
- `MATHTUTOR_MEMORY_PROVIDER_MODE=local_fallback`：默认学生长期记忆实现；可显式设为 `fake_provider` 跑离线 provider contract fixture。`live_provider` 会加载 Mem0 adapter，是 opt-in 路径。
- `MATHTUTOR_RAG_PROVIDER_MODE=local_fallback`：默认知识检索实现；可显式设为 `fake_provider` 跑离线 VikingDB/OpenViking contract fixture。`live_provider` 会显式启用 VikingDB / OpenViking RAG adapter。
- `MATHTUTOR_MEM0_API_KEY`：Mem0 live provider 凭据；默认留空，不能提交真实 key。留空且保持默认 mode 时继续使用 local fallback。
- `MATHTUTOR_RUN_MEM0_LIVE_SMOKE=0`：Mem0 live smoke 开关；只有显式设为 `1` 且配置 API key 时才会运行 live smoke。
- `MATHTUTOR_VIKINGDB_API_KEY`：VikingDB live provider 凭据；默认留空，不能提交真实 key。
- `MATHTUTOR_OPENVIKING_API_KEY`：OpenViking live provider 凭据；默认留空，不能提交真实 key。
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
- `MATHTUTOR_DGEKT_DATASET=assist2017`：当前支持的真实数据集。
- `MATHTUTOR_DGEKT_CHECKPOINT_PATH`：本地 ASSIST2017 checkpoint 路径。已验证 checkpoint 示例：`/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/KnowledgeTracing/model/runs/20260707_222733/save2017model.pkl`。
- `MATHTUTOR_DGEKT_CHECKPOINT_ID`：可选 checkpoint provenance ID；用于和 offline evidence artifact 中的 `checkpoint_id` 对齐。
- `MATHTUTOR_DGEKT_DATASET_DIR`：ASSIST2017 数据目录，需包含 `assist2017_pid_train.csv` 和 `assist2017_pid_test.csv`。
- `MATHTUTOR_DGEKT_Q_MATRIX_PATH`：Q-matrix / incidence matrix 文件，例如原始 DGEKT 工程的 `Dataset/H/2017.csv`。
- `MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR`：可选 DGEKT offline evidence artifact 目录；需包含 `attribution_paths.csv`、`key_history.csv`、`path_ablation.csv`、`weak_concepts.csv` 和 `diagnosis_cases.json`。
- `MATHTUTOR_DGEKT_CANONICAL_MAPPING_PATH`：可选 canonical mapping artifact 路径；用于校验 offline evidence 的 canonical question/concept 是否和 runtime 内容一致。
- `MATHTUTOR_RUN_DGEKT_SMOKE=1`：显式运行本地真实 checkpoint smoke test；默认测试不会读取大模型。
- `MATHTUTOR_RUN_DGEKT_OFFLINE_EVIDENCE_SMOKE=1`：显式运行真实 offline explainability outputs smoke；默认测试只使用小型 fixture。

大 checkpoint 和原始数据文件不提交到 Git，只通过本地路径或环境变量引用。默认 mock 模式不会读取上述 DGEKT 文件。

DGEKT checkpoint 读取说明：

- adapter 期望 checkpoint 是包含 `epoch`、`model_state_dict`、`optimizer_state_dict`、`auc`、`acc` 的字典。
- 推理模型只加载 `model_state_dict` 并进入 `eval()`；`optimizer_state_dict` 仅作为 checkpoint 完整性验证，不参与预测。
- PyTorch 2.6+ 默认 `weights_only=True` 会拒绝该历史 checkpoint 中的 numpy 标量 metadata；本项目仅在显式启用 `MATHTUTOR_KT_ENGINE=dgekt` 且用户信任本地文件时使用 `weights_only=False`。
- DGEKT 输入转换读取最近已判题的 `answer_submitted` 事件，使用 payload 中的 `assist2017_question_id` / `dgekt_question_id` 构造原 DGEKT one-hot 序列；concept 来自 `assist2017_concept_id` / `dgekt_concept_id` 或 Q-matrix。映射缺失或与 Q-matrix 不一致时会明确失败，不返回伪结果。
- DGEKT 诊断会把模型预测规范化为 `KTDiagnosis.prediction_probability`、weak concept proxy 和 forgetting risk proxy；推荐器和 TeachingTrace 读取这些 KT facts，但 RAG / Memory 不会覆盖它们。
- DGEKT attribution evidence 会进入 `AttributionEvidence` 和 TeachingTrace expert evidence：`prediction_probability` 是模型预测答对概率，`raw_model_target` 记录 DGEKT 使用的 ASSIST2017 question / concept，`mapped_teaching_content` 记录映射后的 MathTutor 教学内容，`key_history` 是进入 DGEKT 序列的关键历史交互，`top_paths` 记录 offline path 或在线 proxy path，`path_ablation` 记录删除 top path 后的 prediction 变化。`diagnose` 阶段 TeachingTrace 会额外写入 `attribution_chain`，展示 raw model target -> mapped teaching content -> attribution evidence。只有 `evidence_status=complete` 且 `evidence_source=offline` 才能解读为完整离线归因；partial / unavailable / invalid 只用于诊断和降级展示，不能覆盖 KT facts。

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
