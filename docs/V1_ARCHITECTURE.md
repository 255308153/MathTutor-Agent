# MathTutor Agent V1 架构设计

## 1. 项目定位

MathTutor Agent V1 是一个面向个人学习者的数学自学平台。Agent 是智能教学编排层，不是产品本体；产品体验继续围绕数学做题、诊断、错因讲解、推荐练习和复习路径展开。

它不是通用学习系统、通用聊天机器人，也不是单纯题目推荐系统，而是围绕个人数学答题历史持续维护学习状态，并基于可解释知识追踪、RAG、长期学习记忆和 Agent Runtime 编排，完成以下闭环：

```text
学习事件 / 学生提问
-> MathTutorAgentRuntime 接收本轮数学学习 turn
-> 构造 LearningTurnContext
-> 读取个人学习状态与记忆
-> 检索数学知识库
-> 知识追踪诊断
-> 组装 LearningContextLayer 上下文证据
-> 规划下一步教学动作
-> 推荐题目 / 讲解 / 复习 / 错因诊断
-> 生成学生可读反馈
-> 记录 TeachingTrace
-> 反思并更新长期学习记忆
```

V1 的一句话定义：

```text
一个基于可解释知识追踪、RAG、长期学习记忆和可观测 Agent Runtime 的数学自学平台。
```

项目英文名建议：

```text
MathTutor Agent: A Mathematics Self-Learning Platform Based on Explainable Knowledge Tracing, Retrieval-Augmented Generation, and Observable Agent Runtime
```

V1.9 起新增最高层 runtime seam：

```text
MathTutorAgentRuntime
-> LearningTurnContext
-> 数学 Capability Registry
-> Tool Registry（逐步拆分）
-> 现有 MathTutorLearningLoop
-> TeachingTrace runtime/tool observation
```

`LearningTurnContext` 是每轮学习 turn 的统一事实载体，记录学生、会话、intent、学习事件、当前 KT progress 快照、context asset 引用、assembled context 引用和 trace 引用。它只做编排与审计引用，不替代 progress store、KT/DGEKT、RAG、memory store 或 LearningContextLayer 的事实所有权。

`MathCapabilityRegistry` 只注册数学学习能力 manifest，并根据 intent 选择本轮激活能力。首批能力包括答题诊断与错因分析、下一步建议与复习规划、数学概念讲解与提示。Capability 只描述用途、适用 intent、预期工具、选择原因和权威边界；当前执行仍委托 `MathTutorLearningLoop`，不得直接写 KT facts、RAG 结果或学生记忆。

`MathToolRegistry` 是数学学习工具目录，不是裸 provider 列表。V1.9 默认登记 `kt_authoritative_facts`、`rag_retrieval_evidence` 和 `student_memory_evidence` 三类只读 observation：KT 工具登记本轮已经由 KT / DGEKT 产出的 `KTDiagnosis` 与 attribution 摘要；RAG 工具登记数学知识检索结果、空结果和 citation evidence gap；学生记忆工具登记本轮召回、纳入、排除的记忆摘要和控制状态。工具 manifest 必须声明用途、输入输出摘要、失败模式、provider mode、证据边界和 trace 展示方式；observation 只能解释本轮工具证据，不能覆盖 prediction probability、weak concepts、forgetting risks 或 attribution provenance。

RAG observation 只支持数学概念、定理、例题、解法和教材片段的讲解证据，空结果必须以 `missing_rag_citation`、`knowledge_resource` 或标准 provider gap 表达，不能伪造 citation。学生记忆 observation 只影响教学策略、表达方式和复习提醒；被禁用的记忆只能以 omitted evidence 和排除原因进入专家可见 trace，被删除的记忆不得进入本轮 assembled context 或学生可见证据。registry 与 trace 输出会清洗 checkpoint 路径、私有本地路径、密钥和 provider raw payload，默认 mock / local RAG / local memory 仍是 local fallback，DGEKT checkpoint、Mem0、VikingDB / OpenViking 仍必须显式 opt-in。

## 2. 参考项目与吸收点

### DeepTutor

参考仓库：`HKUDS/DeepTutor`

V1.9 对 DeepTutor 的吸收边界：

| 优先级 | 可吸收内容 | MathTutor 约束 |
| --- | --- | --- |
| P0 | 外层 Agent Runtime、统一上下文对象、Capability 注册、Tool Registry、TeachingTrace / stream event 抽象。 | 只服务数学自学 turn；必须保留 KT / DGEKT 权威事实边界。 |
| P1 | 上下文预算、证据优先级、工具 observation collector、RAG 抽象的工程模式。 | 只作为 V1.10 / V1.11 的渐进增强，不提前变成通用平台。 |
| P2 | 更丰富的运行时可视化、调试面板和 capability 扩展方式。 | 只能进入内部试用与教学编排视角，不能改写学生端主体验。 |

已吸收或可继续吸收的具体点：

- `LearningProgress` 的进度对象思想。
- `LearningService` 将评分、掌握度更新、复习队列更新集中处理。
- `mastery_status` / `mastery_grade` 等工具将学习状态读取和评分确定性化。
- `MasteryLoopCapability` 通过 capability 机制把学习能力挂到通用 agent loop。
- `StreamEvent` 和 `trace metadata` 用于前端展示可追踪执行过程。

不吸收清单：

- 不吸收 DeepTutor 的通用学习工作台定位；MathTutor 仍是数学自学平台。
- 不使用 DeepTutor 的规则式 mastery 替代 DGEKT / KT；掌握度、薄弱点、预测正确率和推荐风险仍由 KT / DGEKT facts 决定。
- 不把文件式记忆作为主存储方向；长期记忆继续沿本地 store / Mem0 opt-in provider 演进。
- 不整套迁移 DeepTutor 前端形态；前端继续围绕做题、诊断、错题、推荐和复习路径设计。
- 不让 LLM、RAG、记忆或 provider health 覆盖 KT facts。
- 不以教材章节路径作为唯一推进方式。

### AGI-saber

参考仓库：`255308153/AGI-saber`

吸收点：

- Router / Tool / ReAct / Memory / RAG 的通用 Agent 主链路。
- 多阶段智能体模式和工具编排思想。
- 前端对话体验与工具调用展示。

定位：

- 作为通用 Agent 架构参考，不作为 V1 的直接技术底座。

### ProbeFlow

参考仓库：`255308153/ProbeFlow`

吸收点：

- `ContextBuilder`
- `Planner`
- `ToolRouter`
- `ExecutionController`
- `ObservationCollector`
- `LoopDecider`
- `TaskStateStore`
- `Memory Refinery`

映射到 MathTutor：

```text
ContextBuilder              -> LearningContextBuilder
Planner                     -> TeachingPlanner
ToolRouter                  -> TeachingActionRouter
ExecutionController         -> LearningExecutionController
ObservationCollector        -> LearningObservationCollector
LoopDecider                 -> LearningLoopDecider
TaskStateStore              -> StudentStateStore
Memory Refinery             -> LearningMemoryRefinery
```

### Claude Code 编排思想

吸收点：

- 主 Agent 负责全局编排。
- 子 Agent / capability 负责专门能力。
- hooks / trace 记录生命周期节点。
- 上下文隔离，结果回传主流程。

V1 不做重型分布式多 Agent，只做模块化子能力。

### OATutor

参考仓库：`CAHLR/OATutor`

吸收点：

- 自适应教学系统的题目选择与技能掌握建模。
- BKT / skill model / problem selection 的教育系统设计经验。
- hint / scaffold 对个人教师产品形态有参考价值。

## 3. V1 范围

### 包含

```text
MathTutor Agent V1
├─ LangGraph 主编排
├─ Core Learning Loop
├─ Knowledge Q&A Loop
├─ Mem0 风格学生记忆
├─ VikingDB adapter / Chroma fallback RAG 检索
├─ ASSISTments2017 数学数据子集
├─ TeachingContentMap
├─ MockKTStateEngine + DGEKTStateEngine 接口预留
├─ Risk-prioritized Mastery Path
├─ memory / concept / procedure / design 教学类型
├─ 可解释推荐排序器
├─ 错因诊断
├─ 双图归因专家证据层
├─ TeachingTrace 可视化
└─ React 学习驾驶舱
```

### 不包含

```text
多学科
班级 / 教师端
移动端
真实在线训练 DGEKT / SAFKT
完整 AGI-saber 迁移
复杂分布式多 Agent
后台定时推送
自动生成大规模题库
商业级登录、权限、支付
```

## 4. 总体架构

```text
Frontend: React Learning Dashboard
    |
    v
FastAPI Backend
    |
    v
LangGraph Orchestration
    |
    +--> StudentStateStore
    +--> StudentMemoryStore (Mem0 style)
    +--> KnowledgeRAG (VikingDB adapter / Chroma fallback)
    +--> KTStateEngine (Mock / DGEKT / SAFKT)
    +--> LearningContextLayer (ContextAsset / assembled_context)
    +--> TeachingPlanner
    +--> QuestionRecommender
    +--> ResponseGenerator
    +--> TeachingTrace Recorder
```

核心边界：

```text
KT facts are authoritative.
LLM plans are advisory.
Offline attribution explains prediction, not overwrite prediction facts.
Memory can influence strategy, not mastery.
RAG can support explanation, not overwrite prediction facts.
Context can assemble evidence, not decide learning facts.
```

也就是说：

- KTStateEngine 输出掌握度、遗忘风险、薄弱知识点、预测概率和归因证据。
- LangGraph / Planner 决定教学动作。
- Offline attribution 只解释 DGEKT prediction，不覆盖 prediction facts。
- RAG 提供知识点讲解、题目解析、错因和学习策略证据。
- Mem0 风格记忆提供个人偏好、反思和历史策略效果。
- LearningContextLayer 统一组织 context assets 和 assembled_context，但不决定学习事实。next-step advice 中，planner / recommender / response 只读取 `assembled_context.normalized_context` 的 student_memory、knowledge_resource、task_state 和 evidence gaps，不直接调用 Mem0、VikingDB、OpenViking 或 provider SDK。
- `answer_submitted` 会额外生成 task_state、tool_observation 和 trace_reference 快照，把 pending question、grading、KT diagnosis、RAG retrieval、错因诊断、推荐候选和 memory update 来源串到 TeachingTrace；这些快照只做审计引用，不能取代 progress store、LearningEvent、KTDiagnosis、RAG 或 memory store。
- Context retrieval 可以按类型、来源、student/session、question/concept、freshness 和 confidence 过滤，并按相关性与优先级裁剪到预算内。KT facts 位于 `authoritative_kt_facts`，不参与 context asset 预算裁剪；被裁剪或 provider 失败的资产只进入 `asset_summaries` / evidence gaps。
- dashboard 只在 TeachingTrace expert evidence 中展示 selected / omitted context assets、included / excluded reason、预算和 evidence gaps；推荐卡、答题输入和学生回复不依赖 dashboard context 展示来决定学习事实。
- V1.4 #33 的端到端 smoke 使用本地 fallback 验证 `next-step advice -> assembled_context -> recommendation / response -> answer_submitted -> task_state / tool_observation / trace_reference -> TeachingTrace / dashboard`，并要求同一个 canonical concept / question 在 KT facts、student_memory、knowledge_resource、推荐理由和 TeachingTrace evidence 中可追踪。
- ContextAssetStore 的架构职责是保存 context refs、summaries、selection / assembly records，不能成为 progress、event、KTDiagnosis、RAG 或 memory 的唯一 runtime source of truth。
- Mem0、VikingDB、OpenViking 后续只能作为可选 adapter 接入 memory / RAG / context retrieval；默认本地 runtime 不要求这些 provider 凭据，也不能让 provider evidence 覆盖 KT facts。
- 缺少学生记忆或 RAG 资源时，LearningContextLayer 记录 evidence gap，而不是伪造 asset 或覆盖 KT facts。
- LLM 只负责自然语言表达和轻量交互，不负责核心诊断事实。

### 4.1 V1.5 ASSISTments2017 数据生产线

V1.5 把 ASSISTments2017 从“demo 映射 fixture”推进为可重复构建、可诊断、可 smoke 的 imported artifact 生产线。它不改变 Agent runtime 的核心事实边界，也不默认启用 full data。

```text
本地 ASSISTments2017 source rows + Q-matrix
-> build_assist2017_artifacts CLI
-> canonical_mapping.json
-> content_import.json
-> rag_documents.json
-> coverage_report.json
-> smoke_dataset.json
-> ContentRepository / KnowledgeRAG / API smoke / TeachingTrace
```

三个数据层级必须区分：

| 层级 | 说明 | 默认性 |
| --- | --- | --- |
| demo | `data/content/demo_teaching_content.json`、`data/rag/demo_knowledge.json` 和 mapping fixture，供本地默认运行。 | 默认启用。 |
| imported fixture / smoke | `data/imported/assist2017_fixture/*.json`，用小样本验证 V1.5 artifact contract 和学习路径一致性。 | 仅测试或显式配置启用。 |
| full | 本地完整 ASSISTments2017 source rows / Q-matrix 构建出的 artifact。 | 必须显式传路径，输出到 Git 外部或 ignored 目录。 |

Artifact contract：

- `canonical_mapping.json`：stable canonical question/concept id、ASSISTments2017 id、Q-matrix reference 和 RAG doc ids。
- `content_import.json`：题干、标准答案、解析、难度、错因、teaching type、provenance、`content_availability`。`ImportedTeachingContentRepository` 只从这里读取 imported 教学内容。
- `rag_documents.json`：四类 RAG 文档 `concept_note`、`question_explanation`、`mistake_pattern`、`learning_strategy`，并携带 canonical mapping、ASSISTments2017 metadata、coverage 和 provenance。
- `coverage_report.json`：mapping/content/RAG/Q-matrix 的覆盖率与 gap 诊断。
- `smoke_dataset.json`：固定学习路径，证明同一 canonical question/concept 能跨推荐、答题、KT facts、RAG citation、LearningContextLayer 和 TeachingTrace 追踪。

Coverage gap category：

| category | 含义 | 系统行为 |
| --- | --- | --- |
| `missing_question_mapping` | Q-matrix row 没有 source question。 | 进入 coverage 诊断；不伪造题目。 |
| `missing_concept_mapping` | Q-matrix concept 没有 source concept metadata。 | 进入 coverage 诊断；不伪造知识点语义。 |
| `q_matrix_mismatch` | source row question/concept 与 Q-matrix 不一致。 | error 级问题，默认构建失败。 |
| `missing_teaching_content` | 题干、标准答案或解析缺失。 | runtime 通过 `content_availability` / evidence gap 暴露，不能静默生成标准答案。 |
| `missing_rag_doc` | 期望的 RAG doc 未生成或未导入。 | RAG / Context 记录 gap，不伪造 knowledge_resource。 |

安全与 provider 边界：

- 默认 `MATHTUTOR_CONTENT_SOURCE=demo`、`MATHTUTOR_RAG_SOURCE=demo`、`MATHTUTOR_KT_ENGINE=mock`，不读取 full ASSISTments2017、checkpoint、Mem0、VikingDB 或 OpenViking。
- full data 只能通过 `--dataset-mode full --source-rows ... --q-matrix ...` 或等价显式配置启用。
- raw train/test、checkpoint、`.pkl`、`.pt`、`.pth`、`.ckpt`、`.safetensors`、cache、build output 和 full generated artifact 不进入 Git。
- DGEKT 继续 opt-in；V1.6 只在显式配置 offline evidence artifact 时读取 DGEKT explainability 输出，默认 demo/mock 不加载 checkpoint 或 full outputs。

## 5. 双输入模型

V1 不只有聊天消息，还必须接收学习事件。

### ChatMessage

示例：

```json
{
  "session_id": "s001",
  "student_id": "u001",
  "type": "chat_message",
  "message": "我下一步学什么？",
  "payload": {}
}
```

用于：

- 下一步学习建议
- 知识点问答
- 错题讲解
- 复习计划请求
- 普通聊天

### LearningEvent

示例：

```json
{
  "session_id": "s001",
  "student_id": "u001",
  "type": "answer_submitted",
  "message": "我选 B",
  "payload": {
    "question_id": "q12",
    "answer": "B",
    "is_correct": false,
    "time_spent": 73
  }
}
```

核心事件：

```text
session_started
question_recommended
answer_submitted
question_skipped
hint_requested
review_completed
```

## 6. LangGraph 主流程

V1 主图节点：

```text
START
  ↓
load_student_context
  ↓
classify_intent
  ↓
retrieve_learning_context
  ↓
diagnose_learning_state
  ↓
plan_teaching_action
  ↓
execute_teaching_action
  ↓
generate_student_response
  ↓
reflect_and_update_memory
  ↓
END
```

### 节点职责

`load_student_context`

- 读取学生档案。
- 读取结构化学习状态。
- 读取最近答题记录。
- 读取 pending question。

`classify_intent`

- 判断输入是学习事件还是聊天消息。
- 判断意图：
  - `next_step`
  - `answer_submitted`
  - `explain_mistake`
  - `concept_qa`
  - `review_plan`
  - `recommend_question`
  - `casual_chat`

`retrieve_learning_context`

- 从 RAG 召回知识点讲解、题目解析、错因模式、学习策略。
- 从 StudentMemory 召回个人偏好、重复错因、策略效果。

`diagnose_learning_state`

- 调用 KTStateEngine。
- 更新掌握度、遗忘风险、薄弱知识点。
- 在目标题目存在时生成 attribution evidence。

`plan_teaching_action`

- 基于 KT facts、RAG、Memory 和教学类型选择下一步动作。
- 生成 `next_action`。

`execute_teaching_action`

- 调用推荐器、复习计划器、错因诊断器或 RAG 讲解器。
- 输出推荐题、讲解材料、诊断结果。

`generate_student_response`

- 将结构化结果转成学生可读回答。
- 风格：学习搭子 + 小老师，短、具体、鼓励，不长篇说教。

`reflect_and_update_memory`

- 记录本轮推荐、学生反应、效果证据。
- 提纯值得长期保存的学习记忆。

## 7. 两条路线

### Core Learning Loop

用于：

- 提交答题
- 下一步学习建议
- 推荐题目
- 复习计划
- 错因诊断

流程：

```text
load_student_context
-> retrieve_learning_context
-> diagnose_learning_state
-> plan_teaching_action
-> execute_teaching_action
-> generate_student_response
-> reflect_and_update_memory
```

### Knowledge Q&A Loop

用于：

- “什么是导数？”
- “这类题怎么做？”
- “帮我讲一下函数单调性。”

流程：

```text
load_student_context
-> retrieve_learning_context
-> answer_with_student_level
-> optionally_update_memory
```

规则：

```text
凡是涉及下一步学什么 / 推荐什么 / 状态变化，必须走 Core Learning Loop。
凡是纯概念问答 / 解题讲解，可以走 Knowledge Q&A Loop。
```

## 8. MathTutorState

LangGraph 主状态：

```python
class MathTutorState(TypedDict):
    session_id: str
    student_id: str
    user_message: str
    intent: str

    learning_event: dict | None
    kt_progress: dict
    concept_states: list[dict]
    weak_concepts: list[dict]
    forgetting_risks: list[dict]

    teaching_content: dict
    rag_context: list[dict]
    student_memories: list[dict]

    next_action: dict | None
    recommended_questions: list[dict]
    mistake_diagnosis: dict | None
    attribution_evidence: dict | None

    response: str
    teaching_trace: list[dict]
    memory_updates: list[dict]
    errors: list[dict]
```

字段边界：

```text
kt_progress / concept_states
来自 KTStateEngine，是事实层。

rag_context
来自 KnowledgeRAG，是知识证据。

student_memories
来自 Mem0，是个人经验。

next_action / recommended_questions
来自 Planner 和 Recommender，是决策层。

response
来自 LLM，是表达层。

teaching_trace
贯穿全流程，用于展示和调试。
```

节点写入规则：

```text
diagnose_learning_state 只能写 kt_progress / weak_concepts / forgetting_risks / attribution_evidence
retrieve_learning_context 只能写 rag_context / student_memories
plan_teaching_action 只能写 next_action
execute_teaching_action 只能写 recommended_questions / mistake_diagnosis / teaching_content
generate_student_response 只能写 response
reflect_and_update_memory 只能写 memory_updates
```

## 9. KTLearningProgress

保留 DeepTutor 的“进度对象”思想，但替换成 KT 版本。

```text
KTLearningProgress
├─ student_id
├─ subject = math
├─ dataset = assist2017
├─ current_session_id
├─ concept_states
├─ recent_events
├─ weak_concepts
├─ forgetting_risks
├─ pending_question
├─ recommendation_history
├─ error_records
├─ review_queue
├─ teaching_trace_ids
└─ version
```

### ConceptState

```text
ConceptState
├─ concept_id
├─ concept_name
├─ teaching_type: memory | concept | procedure | design
├─ mastery
├─ forgetting_risk
├─ last_practiced_at
├─ recent_accuracy
├─ evidence_count
└─ status: new | learning | weak | reviewing | stable
```

## 10. Teaching Type

保留 DeepTutor 的教学类型：

```text
memory     记忆型：公式、定义、符号规则
concept    概念型：理解含义、关系、图像意义
procedure  程序型：解题步骤、计算流程
design     设计/综合型：开放策略、综合应用
```

边界：

```text
KT concept_id
来自 ASSISTments / Q-matrix，用于知识追踪计算。

teaching_type
来自人工标注或规则映射，用于决定教学方式。
```

### ConceptTeachingTypeMap

```text
ConceptTeachingTypeMap
├─ concept_id
├─ concept_name
├─ teaching_type
├─ reason
└─ source
```

分类规则：

```text
公式记忆、定义、符号规则
-> memory

函数性质、几何意义、概念关系
-> concept

解方程步骤、求导步骤、代数变形
-> procedure

综合应用、建模、开放解法选择
-> design
```

V1 使用固定映射，不在运行时让 LLM 动态分类。

## 11. Risk-prioritized Mastery Path

V1 采用混合策略：

```text
KT 风险优先 + 类型化掌握门槛
```

核心规则：

```text
KT 决定优先级
Teaching Type 决定教学方式
Mastery Gate 决定能不能升难度 / 跳到后续任务
Memory 影响策略偏好
RAG 提供讲解和证据
LLM 只负责表达与交互
```

门槛示例：

```text
memory:
最近 3 次相关小测 >= 2 次正确，且遗忘风险 < 0.5

concept:
学生能用自己的话解释，并通过 1 道概念判断题

procedure:
同类型步骤题最近正确率 >= 0.8

design:
完成 1 道综合题，并能说出解题策略
```

Planner 行为：

```text
1. KTStateEngine 给出 mastery、forgetting_risk、weak_concepts
2. Planner 选择优先知识点
3. 根据 teaching_type 选择教学动作
4. 没过门槛前，不进入更高难度任务
5. 如果存在高遗忘风险，则插入 review
```

## 12. KTStateEngine 接口

必须从一开始设计可替换接口。

```python
class KTStateEngine(Protocol):
    def update_from_event(
        self,
        progress: KTLearningProgress,
        event: LearningEvent,
    ) -> KTLearningProgress:
        ...

    def diagnose(
        self,
        progress: KTLearningProgress,
        target_question_id: str | None = None,
    ) -> KTDiagnosis:
        ...

    def explain_prediction(
        self,
        progress: KTLearningProgress,
        target_question_id: str,
    ) -> AttributionEvidence:
        ...
```

实现：

```text
MockKTStateEngine
用于 V1 demo 和前端联调。

DGEKTStateEngine
读取真实模型、Q-matrix、序列数据、解释信号。

V1.6 起，DGEKTStateEngine 在显式启用 DGEKT 时通过同一个 `explain_prediction` seam 输出 attribution evidence：

- `raw_model_target`：DGEKT 使用的 ASSIST2017 question / concept target。
- `mapped_teaching_content`：映射回 MathTutor question / concept / teaching_type 的教学内容引用。
- `key_history`：最近进入 one-hot 序列的已判题历史。
- `top_paths`：优先来自 offline `attribution_paths.csv`；未配置或未命中时只可退回 recent history + Q-matrix 的 partial proxy path。
- `path_ablation`：offline `path_ablation.csv` 中删除关键 path 后的 prediction 变化。
- `evidence_status` / `evidence_source`：区分 `complete/offline`、`partial`、`unavailable` 和 `invalid`。
- `evidence_gaps`：记录 missing artifact、缺列、malformed row、numeric 解析失败、target 未命中、checkpoint provenance mismatch 或 canonical mapping mismatch。

只有 `evidence_status=complete` 且 `evidence_source=offline` 的结果可解释为完整离线归因。online proxy 必须保留 partial reason；Offline attribution 只解释 prediction，不覆盖 KT diagnosis facts。

未来可扩展：
SAFKTStateEngine
BKTStateEngine
```

Planner 永远依赖 `KTStateEngine` 接口，不直接依赖 DGEKT 文件路径或 PyTorch 模型细节。

### V1.6 offline evidence adapter

V1.6 新增 `DGEKTOfflineEvidenceAdapter`，它读取原 DGEKT explainability 输出形状：

```text
diagnosis_cases.json
attribution_paths.csv
key_history.csv
path_ablation.csv
weak_concepts.csv
```

adapter 只在 `MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR` 被显式配置时启用。它用 `diagnosis_cases.json` 定位 sample、student、target question/concept 和 checkpoint provenance，再把 CSV 归一为 `AttributionEvidence`：

```text
recommendation / answer event
-> KTDiagnosis prediction facts
-> DGEKTStateEngine.explain_prediction
-> DGEKTOfflineEvidenceAdapter lookup
-> AttributionEvidence
-> assembled_context.evidence_gaps
-> TeachingTrace expert evidence
-> dashboard 模型证据面板
```

证据边界：

- KT facts are authoritative：`prediction_probability`、mastery、weak concepts、forgetting risk 仍来自 KT engine。
- Offline attribution explains prediction, not overwrite prediction facts。
- RAG 只支持解释与 citation；不能覆盖 prediction facts。
- Context 只组装 evidence 与 gap；不能决定 learning facts。

invalid / unavailable 结果必须可见：缺 artifact、缺列、重复 sample、checkpoint provenance 不一致、canonical mapping 不一致、target 未命中时，系统只能展示 gap 和 fallback 状态，不能把 online proxy 伪装成 complete offline evidence。

## 13. 推荐排序器

推荐题目不能完全交给 LLM。

V1 使用可解释排序器：

```text
score(q) =
  0.40 * weak_concept_match
+ 0.25 * difficulty_fit
+ 0.20 * forgetting_urgency
+ 0.10 * novelty
+ 0.05 * student_preference_fit
```

输出保留分数拆解：

```json
{
  "question_id": "q12",
  "score": 0.83,
  "reason_factors": {
    "weak_concept_match": 0.9,
    "difficulty_fit": 0.8,
    "forgetting_urgency": 0.75,
    "novelty": 1.0,
    "student_preference_fit": 0.7
  }
}
```

LLM 只将分数拆解改写成自然语言推荐理由。

## 14. 错因诊断

V1 做到：

```text
知识点级 + 错因模式级
```

不声称能精确判断心理原因。

错因来源：

```text
1. KT 状态：哪个知识点弱
2. 当前题目解析：这题常见错误是什么
3. RAG 错因库：该知识点常见误区
```

结构：

```text
MistakeDiagnosis
├─ target_concept
├─ likely_pattern
├─ evidence
├─ remediation
└─ confidence
```

示例：

```json
{
  "target_concept": "导数与单调性",
  "likely_pattern": "导数符号和增减性对应关系混淆",
  "evidence": ["最近5道相关题错3道", "本题涉及 f'(x)<0 区间判断"],
  "remediation": "先复习符号规则，再做2道区间判断基础题",
  "confidence": 0.72
}
```

## 15. 双图归因专家证据层

保留本项目的可解释知识追踪特色：

```text
Dual-Graph Path Attribution
Attribution Path
Weak-Concept Hit
Path Ablation Impact
```

展示分两层：

```text
学生层：
你之前在“导数符号判断”上的错误，会影响现在做“函数单调性”的题。

专家层 / 调试层：
Attribution path:
q17 -> 导数符号 -> 函数单调性 -> q42
score = 0.84
```

前端可折叠区：

```text
为什么系统这样判断？
├─ 学生可读解释
└─ 查看模型证据
   ├─ top attribution paths
   ├─ key history questions
   ├─ weak concepts
   └─ prediction probability
```

## 16. 记忆系统

采用：

```text
Mem0 风格记忆提纯 + Student Memory Store
```

V1 可以真实接 Mem0，也必须保留接口 fallback。

```python
class StudentMemoryStore:
    def add_memory(student_id, memory_type, content, metadata): ...
    def search_memory(student_id, query, filters, top_k): ...
    def refine_from_session(student_id, session_trace): ...
```

实现：

```text
Mem0StudentMemoryStore
InMemoryStudentMemoryStore
```

记忆类型：

```text
student_preference
strategy_effect
repeated_mistake
learning_pattern
reflection_summary
```

边界：

```text
RAG / VikingDB
存稳定知识：知识点讲解、题目解析、常见错因、学习策略文档、教材片段。

Mem0 / Student Memory
存个人记忆：学生常卡题型、偏好、推荐效果、重复错因。

KTState / Database
存结构化状态：recent_interactions、mastery、forgetting_risk、weak_concepts。
```

## 17. RAG 知识库

RAG 不能只是“查资料回答概念”，必须进入规划节点。

知识库分四类：

```text
1. Concept Notes
   知识点讲解：定义、公式、常见题型、易错点

2. Question Explanations
   题目解析：题干、答案、解法步骤、关联知识点

3. Mistake Patterns
   错因模式：常见错误、误区、前置知识缺口

4. Learning Strategies
   学习策略：什么情况该复习、该降难度、该做变式题
```

最小 metadata：

```text
chunk_id
doc_type: concept_note | question_explanation | mistake_pattern | learning_strategy
concept_id
question_id
assist2017_question_id
assist2017_concept_id
canonical_mapping
provenance
coverage
difficulty
source
updated_at
```

`canonical_mapping` 保存 MathTutor question/concept 到 ASSIST2017 question/concept 和 Q-matrix 的对齐摘要；`coverage` 标记 `question`、`concept`、`global`、`unmapped_question` 或 `unmapped_concept`，用于可见化 RAG 缺口。

### V1.3 Evidence Gap Model

V1.3 的缺口可见化采用统一 `error_records` / `evidence_gaps`，覆盖：

```text
missing_mapping
missing_content
missing_rag_citation
unsupported_dgekt_target
scorer_failure
```

这些记录写入 `state_summary.error_records`、`teaching_trace[*].metadata.error_records`、`teaching_trace_summary.expert_evidence.evidence_gaps` 和 `teaching_trace_summary.expert_evidence.error_records`。

边界：

- `missing_content` 可以阻止确定性判题，但不能写入伪 KT facts。
- `missing_rag_citation` 只能说明没有知识资源证据，不能生成假的 citation。
- `scorer_failure` 只影响 attribution evidence；`KTDiagnosis.prediction_probability`、`weak_concepts`、`forgetting_risks` 仍以 KT engine 输出为准。
- dashboard 可以展示这些缺口和重试入口，但不能把它们作为 mastery / risk 的来源。

### V1.3 End-To-End Acceptance Chain

#25 不新增新的事实来源，而是验证真实语义对齐链路已经闭合：

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

验收 smoke 至少要证明同一 canonical concept 同时出现在：

- `KTDiagnosis.weak_concepts` / `forgetting_risks`。
- 推荐题的 `concept_id`、`reason`、`canonical_mapping` 和 `selected_canonical_targets`。
- RAG citation 的 `concept_id` / `question_id` / ASSIST2017 metadata。
- `mistake_diagnosis.concept`。
- `AttributionEvidence.key_history`、`top_paths.weak_concept_evidence` 和 `diagnose.attribution_chain`。
- `assembled_context.normalized_context.knowledge_resource` 与 evidence gaps。

这里的 context、RAG 和 TeachingTrace 只负责组装和展示证据；DGEKT / KT engine 输出的 prediction facts 仍是权威事实。

不同意图召回：

```text
问概念：
concept_note + mistake_pattern

问错题：
question_explanation + mistake_pattern + concept_note

问下一步学什么：
learning_strategy + concept_note + similar question explanations

问推荐理由：
concept_note + mistake_pattern + recommendation history
```

RAG 强化标准：

```text
分类型索引
canonical metadata 过滤
引用溯源到 question / concept / ASSIST2017 id
进入规划节点
```

## 18. TeachingContentMap

ASSISTments2017 作为交互序列和知识追踪数据底座，但需要额外构建教学内容映射。

```text
TeachingContentMap
├─ question_id
├─ display_stem
├─ answer
├─ explanation
├─ concept_ids
├─ concept_names
├─ difficulty
├─ mistake_patterns
├─ teaching_type
├─ canonical_mapping
│  ├─ assist2017_question_id
│  ├─ assist2017_concept_id
│  ├─ q_matrix_reference
│  └─ source
├─ provenance
├─ content_availability
└─ rag_doc_ids
```

V1 策略：

```text
KT 数据：ASSISTments2017 全量或子集
教学展示数据：精选 20-50 题人工补全
RAG 知识库：围绕这些题和知识点建设
```

V1.3 #21 主链路约束：

```text
recommend_next_question
→ ContentRepository.public_question()
→ 推荐 payload 携带 stem / answer / explanation / concept / difficulty / teaching_type
→ plan trace 记录 selected_canonical_targets
→ answer_submitted 时后端重新读取 standard_answer 确定性判题
```

`answer` 是推荐 payload 的教学内容快照；`standard_answer` 是服务端内容集字段，不能由客户端覆盖。若题干、标准答案或解析缺失，`content_availability` 必须返回缺口和中文 fallback，KTDiagnosis / mastery / weak_concepts / forgetting_risk / prediction_probability 仍只来自 KT engine。

## 19. 存储模型

V1 分三块：

```text
1. SQLite / PostgreSQL
   存结构化学习状态和事件

2. Mem0 + Vector Store
   存学生长期记忆

3. Knowledge Base Files + Vector Index
   存数学 RAG 文档和题目解析
```

结构化 DB 表：

```text
students
questions
concepts
concept_teaching_types
learning_events
kt_learning_progress
concept_states
recommendations
teaching_traces
error_records
pending_questions
```

开发期建议：

```text
SQLite + Chroma
```

接口保留：

```text
PostgreSQL + VikingDB
```

## 20. TeachingTrace

V1 必须展示可追踪教学决策轨迹。

结构：

```text
TeachingTrace
├─ intent
├─ retrieved_context
├─ kt_diagnosis
├─ attribution_chain
├─ planner_decision
├─ selected_action
├─ recommended_questions
├─ generated_response
└─ memory_updates
```

前端展示：

```text
教学决策轨迹
1. 意图识别：学生请求下一步学习建议
2. 学习状态：导数单调性 mastery=0.42，遗忘风险=0.71
3. 召回资料：导数单调性常见错因、2 条题目解析
4. 教学决策：先基础复习，再中等题
5. 推荐结果：q12、q15、q19
6. 记忆更新：记录本次推荐策略
```

可以参考 DeepTutor 的 `StreamEvent` 协议：

```text
stage_start
observation
tool_call
tool_result
sources
result
error
done
```

## 21. 前端学习驾驶舱

不要做纯 ChatGPT 式窗口。

推荐布局：

```text
顶部：当前学生 + 今日建议
左侧：知识点掌握度 / 薄弱点 / 遗忘风险
中间：推荐题目与答题区
右侧：Agent 解释 / 推荐理由 / 最近记录
底部或侧边：简短对话输入
可折叠：TeachingTrace / 模型证据 / RAG 引用
```

V1 必须体现三个视觉信号：

```text
1. 知识点状态会变
2. 推荐题目会变
3. Agent 的解释和状态有关
```

## 22. 回答风格

风格：

```text
学习搭子 + 小老师
短、具体、鼓励
不卖萌
不长篇说教
不暴露底层模型术语给学生
```

模板：

```text
1. 先说下一步建议
2. 再说为什么
3. 给 2-3 个可选动作
4. 最后一句轻微鼓励
```

示例：

```text
你现在最该补的是“导数判断单调性”。

原因很直接：最近 5 道相关题你错了 3 道，而且这类题已经 4 天没练。先做两道基础题，把“导数为正/负对应增减”的规则找回来，再做一道综合题。
```

## 23. 评估指标

### 第一层：知识追踪模型指标

```text
AUC
ACC
RMSE / F1
```

### 第二层：解释有效性指标

```text
Path Ablation Impact
Weak-Concept Hit
Stability
Fidelity
```

### 第三层：推荐 / 教学决策指标

```text
推荐题是否覆盖薄弱知识点
推荐题难度是否匹配当前 mastery
推荐后下一次同知识点表现是否改善
推荐多样性
重复推荐率
```

### 第四层：Agent 系统指标

```text
TeachingTrace 完整率
RAG 引用命中率
记忆写入有效率
同一学生多轮建议一致性
用户可理解性评分
```

最小论文实验：

```text
1. KT 预测性能保留
2. Weak-Concept Hit
3. 推荐命中薄弱点比例
4. 案例分析：TeachingTrace + RAG 引用 + 归因路径
```

## 24. 建议接口

```text
POST /api/events
提交 ChatMessage 或 LearningEvent。

GET /api/students/{student_id}/state
读取 KTLearningProgress。

POST /api/students/{student_id}/next-step
生成下一步学习建议。

GET /api/questions
读取题库。

POST /api/rag/ingest
导入数学 RAG 文档。

GET /api/traces/{trace_id}
查看 TeachingTrace。
```

## 25. 开发里程碑

### Milestone 1：骨架

```text
FastAPI 项目结构
LangGraph 主图
MathTutorState
SQLite 存储
TeachingTrace 基础记录
```

### Milestone 2：数据与内容

```text
ASSISTments2017 子集整理
TeachingContentMap
ConceptTeachingTypeMap
20-50 道演示题
3-6 个核心数学知识点
```

### Milestone 3：RAG

```text
Concept Notes
Question Explanations
Mistake Patterns
Learning Strategies
Chroma fallback
VikingDB adapter 接口
RAG 引用溯源
```

### Milestone 4：KTStateEngine

```text
MockKTStateEngine
KTDiagnosis
AttributionEvidence schema
DGEKTStateEngine + opt-in offline attribution evidence adapter
```

### Milestone 5：教学规划

```text
Risk-prioritized Mastery Path
QuestionRecommender
MistakeDiagnosis
ReviewQueue
PendingQuestion
```

### Milestone 6：记忆系统

```text
StudentMemoryStore 接口
Mem0StudentMemoryStore
LearningMemoryRefinery
strategy_effect / repeated_mistake 写入
```

### Milestone 7：前端

```text
React 学习驾驶舱
答题区
知识点状态面板
推荐理由
TeachingTrace 面板
模型证据折叠区
RAG 引用展示
```

### Milestone 8：真实模型接入

```text
DGEKTStateEngine
return_explanation=True
Dual-Graph Path Attribution artifact adapter
Weak concept / forgetting risk 映射
```

### 内部正式试用约束

内部正式试用不得早于 **V1.8**。V1.5 是真实 ASSISTments2017 内容底座和 artifact 生产线，V1.6 / V1.7 仍属于技术验证与专家试用阶段；只有 V1.8 同时满足模型证据、长期记忆、生产级检索、持久化状态、可解释 trace 和反馈闭环后，才允许邀请真实内部学习者连续使用。

```text
V1.5: 真实数据内容底座，开发 / 研究验证。
V1.6: 真实 DGEKT offline attribution / checkpoint evidence，技术内测。
V1.7: Mem0 长期记忆 + VikingDB / OpenViking RAG adapter，小范围专家试用。
V1.8: 内部正式试用版。
V1.9: 内部试用优化版。
V2.0: 产品化 beta。
```

V1.8 必须满足：

- 用户会话、学习状态和关键 TeachingTrace 可持久化。
- 真实 DGEKT evidence、Mem0 记忆和生产级 RAG adapter 均通过验收。
- 答题、推荐、解释、错因、复习计划形成闭环。
- 学生记忆可查看、可清理、可禁用。
- KT / RAG / Memory / Context 的证据边界可审计。
- 异常、缺失内容和 provider 失败有明确降级或错误提示。
- 至少 3-5 个真实内部用户完成连续学习流程。

## 26. 核心设计原则

```text
1. 学科先锁数学，不做泛学科。
2. 数据集先锁 ASSISTments2017 / 本地 DGEKT 数据。
3. Agent 主线是个人下一步学习决策。
4. RAG、Memory、KT 都必须进入规划，不做装饰。
5. LLM 不负责核心评分、掌握度或推荐排序。
6. DeepTutor 的 Mastery Path 思想要保留，但改造成 KT Learning Path。
7. TeachingTrace 必须可展示、可审计、可用于论文案例分析。
8. 先 Mock 打通闭环，再接真实 DGEKT / SAFKT。
```
