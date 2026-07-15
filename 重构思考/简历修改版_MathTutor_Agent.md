# MathTutor Agent｜简历技术亮点候选库

用途：按“项目介绍 → 技术栈 → 技术亮点 → 验收指标”的简历模板收集候选文案。最终投递只保留 4～5 条。

标记规则：

- **[现有基础]**：已有代码与验收测试，可按“设计并实现”表述。
- **[终局规划]**：尚未完成，只能按“设计 / 建设中 / 规划”表述。

## 项目介绍

面向数学自主学习场景构建知识追踪驱动的对话式教学 Agent。系统将确定性判题、学习状态、检索证据、长期记忆和教学策略解耦为带权限边界的工具能力，重点解决 LLM 在教学中容易脱离学生真实状态、检索串题、历史记忆污染和外部 Provider 不稳定的问题。

## 技术栈

**现有基础：** Python · FastAPI · Pydantic · SQLite · React · TypeScript · Local RAG · Mock KT · pytest · Vitest

**终局规划：** PyTorch · DGEKT / SAFKT · Hybrid GraphRAG · Mem0 · VikingDB / OpenViking · PostgreSQL · Redis · Milvus · Elasticsearch · Neo4j · MCP · SSE

## 核心架构思路

```text
LearningEvent / Chat / Answer
        |
MathTutorAgentRuntime（intent 路由、能力选择、工具挂载）
        |
  +-----+-------------------+------------------+
  |                         |                  |
KT / DGEKT Facts       RAG Evidence       Student Memory
唯一学习事实源           讲解与引用支持       仅影响教学策略
  |                         |                  |
  +----------- LearningContextLayer -----------+
                         |
          Context Governance（排序、裁剪、脱敏、审计）
                         |
      ResponseContextPackage -> Response Generator
                         |
      TeachingTrace / Provider Health / Dashboard
```

架构核心不是“让 LLM 自己决定下一步”，而是将系统分成两条平面：**事实平面**由确定性判题、KT/DGEKT、progress store 生产和写入学习状态；**回复与推荐平面**只读取治理后的 KT、RAG、Memory 证据，按学生问题生成回复，或在明确请求时推荐练习。Runtime、Context Governance、RAG、Memory 和 Provider Health 都没有改写学习事实的权限，TeachingTrace 则负责将每轮状态流、AI 完整回复和证据选择变成可审计记录。

## 技术亮点候选

### • [现有基础] 事实平面—教学平面双轨 Agent 架构

设计并实现“事实生产与教学表达分离”的双轨架构：Progress Store、确定性判题和 KT/DGEKT 组成事实平面，分别负责作答事实、判题结果与 mastery、weak concepts、prediction probability、forgetting risks 等模型状态；RAG、Memory、Response Generator 与推荐器组成只读的回复与推荐平面，按学生主动提出的问题生成回答，或在明确请求时选题。通过 `state_write_policy`、authority boundary、只读 Tool Observation 和契约测试约束跨层访问，解决传统 Agent 将检索文本、历史偏好或模型输出直接写回业务状态导致事实漂移的问题。

### • [现有基础] Runtime Context Governance 与 Evidence Firewall

设计并实现面向教学场景的 Evidence Firewall，将知识追踪事实、当前题目与作答结果、RAG 引用、学生记忆、工具 observation 和 Trace 快照统一建模为 context assets；构建“KT/DGEKT facts > current task > tool snapshot > relevant Memory / RAG”的优先级与 token budget 策略，并记录 selected、clipped、omitted 的原因。通过 selected-only `ResponseContextPackage` 作为未来 LLM / response generator 的唯一上下文入口，隔离 raw provider payload、SDK response、embedding、密钥和私有路径，防止低置信度证据、过期记忆或 provider 数据污染教学反馈。

### • [现有基础] 状态机式 Agent Runtime 与条件工具调度

设计并实现事件驱动的 `MathTutorAgentRuntime`，以 `LearningTurnContext` 作为单轮状态载体，串联 student、session、intent、learning event、KT progress、context refs 和 trace refs；使用 Capability Registry 将 `answer_submission`、`next_step_advice`、`general_chat` 映射到诊断、规划和概念讲解能力，并通过 Tool Registry 将 KT、RAG、Memory 封装为带输入输出约束、前置条件、provider mode、失败语义和 state-write policy 的工具契约。基于 intent、当前题目、证据可用性与 provider readiness 动态输出 mounted / skipped / blocked 决策，避免所有请求使用同一工具集合造成无关诊断和上下文污染。

### • [现有基础] 记忆生命周期控制与个性化 Context Assembly

设计学生偏好、重复错因、有效教学策略和学习反思四类记忆模型，记录来源、evidence、provenance、freshness、启用状态与 tombstone；实现本地 store 与 Mem0 Adapter 双层接入，并通过 enable / disable / delete 控制记忆生命周期。运行时将 disabled memory 转为专家可见的 omitted evidence，将 deleted memory 从检索、assembled context 与 response package 中彻底排除；结合 student / session / question / concept / freshness / confidence 过滤与排序，实现跨会话个性化而不让过期或错误记忆污染当前教学任务。

### • [现有基础] 题目对齐 RAG 与证据缺口治理

设计以 canonical `question_id` / `concept_id` 为核心的教学检索架构，将 concept note、question explanation、mistake pattern 和 learning strategy 组织为带 coverage、provenance 和 XES3G5M mapping 的知识资源；在检索与上下文组装阶段校验题目、知识点、citation 和内容可用性。对空检索、映射缺失、内容缺失、低置信度和上下文超限统一生成 `evidence_gap`，使系统在缺证据时显式降级而非让模型补造引用，降低题目串扰与无依据讲解风险。

### • [现有基础] 可解释推荐与确定性学习闭环

设计服务端确定性判题与风险优先推荐链路，将弱知识点匹配、遗忘风险、预测风险、难度适配、近期重复度、学习偏好和 canonical mapping 完整度拆为 `score_factors`；推荐器输出中文 reason 与候选证据，TeachingTrace 同步记录判题、KT diagnosis、错因证据、RAG citation、memory recall、AI 完整回复和推荐结果。通过将“判题事实—模型状态—推荐决策—学生反馈”绑定到同一 trace，支持定位一条推荐或讲解到底来自哪次作答、哪项风险和哪条资源。

### • [现有基础] Provider Fallback、敏感信息清洗与回归门禁

构建 local fallback、fake provider 与 live provider 的分层运行模型，统一归一化 configuration missing、timeout、auth error、empty result、schema mismatch 和 budget exceeded 等 Provider 状态；外部 DGEKT、Mem0、VikingDB / OpenViking 不可用时自动回退本地实现，同时将降级原因保留在 Provider Health 和 TeachingTrace。针对 credentials、raw payload、SDK response、checkpoint、embedding、vector index 和私有路径实现递归脱敏，并以 default fallback、facts boundary、memory control、RAG citation、runtime / dashboard 等回归测试作为 Agent 发布门禁。

### • [终局规划] Hybrid GraphRAG 教学知识图谱

建设 Milvus Dense Retrieval、Elasticsearch / BM25、Neo4j 教学知识图谱三路召回架构，将真实题目、知识点路线、标准解析、常见错因、解题步骤和教学策略切分为父子 Chunk，并抽取 `QUESTION_OF / REQUIRES / MISCONCEPTION_OF / NEXT_STEP / SUPPORTS` 等关系；通过 RRF 融合、Cross Encoder 重排、图多跳扩散和 question / concept metadata filter 生成带 citation、confidence 与 token budget 的教学 context，提高复杂题目追问下的检索完整性、可解释性与抗串题能力。

### • [终局规划] SAFKT 知识追踪与模型—教学双向 Grounding

以 DGEKT 为底座建设融合题干语义、知识点图关系和题目难度的 SAFKT 模型，复现 DKT / SAKT / AKT 基线并对比 AUC、NLL、Brier Score 与 ECE；将模型输出编译为含 model version、confidence、attribution 和 calibration metadata 的 `TeachingState`，再通过只读工具驱动提示层级、错因诊断和练习规划。建立“题目—知识点—历史交互—模型预测—教学策略”双向 grounding，使异常教学反馈可回溯模型输入与证据，代码 / 数据变更也可反向定位受影响教学资产。

### • [终局规划] 长期对话学习工作区与版本化教学资产

采用 PostgreSQL Event Sourcing 持久化会话事件、学习状态、学生输入、AI 完整回复、证据引用、提示历史和练习修订链，以 Redis 缓存活跃学生工作区；通过滑动窗口、分层摘要、语义记忆检索和 Token Budget Context Pack 管理长对话。为解题步骤、回复记录和练习 Suite 引入 version、JSON Patch、Revision DAG、semantic diff、乐观锁和回滚，使学生能够围绕同一道题持续修改、检查、追问与确认，而不是每轮重新生成导致状态漂移。

### • [终局规划] 动态图 ReAct 教学 Runtime

设计基于 DAG 的教学 Agent Workflow Runtime，将传统串行 Thought–Action–Observation 升级为“可调度、可并行、可恢复”的动态图执行框架；通过任务拆分、节点依赖、拓扑排序、入度控制和 checkpoint 实现对题目检索、知识点检索、Memory recall、KT inference 等无依赖节点的并发执行。引入 Race Strategy 支持多检索源和多模型竞速，并通过最大重试次数与恢复范围控制，使 Agent 能在证据不足时降级回复，而不是主动追问或自行改写学习事实。

### • [终局规划] 状态图驱动的分层提示与教学自我修复

将业务知识点路线、题目约束、标准解题步骤、常见错误、角色权限、掌握度与历史失败编译为教学状态图和覆盖矩阵；基于图遍历与约束组合生成概念提示、方法提示、步骤提示、错误解释、边界题和跨知识点巩固练习。通过中间步骤检查、最小反例、HTTP / Tool Contract 校验、失败归因与最小复现上下文，将执行结果反哺 Agent 重规划、教学资产修订和长期记忆，形成“教学行动—学生反馈—状态更新—策略修复”的闭环。

## 质量指标候选（必须真实测得后使用）

- **Context Governance：** facts 被覆盖次数、敏感字段泄漏次数、无关 evidence 误入率、上下文 Token 降幅、selected / clipped 判定准确率。
- **RAG：** Recall@K、MRR、NDCG、Citation Precision / Recall、题目串题率、检索 P95、context Token 成本。
- **Memory：** 重复记忆合并率、记忆召回命中率、跨会话复用率、失效记忆排除率、负反馈降权率。
- **KT：** AUC、ACC、NLL、Brier Score、ECE、不同知识点与学生子集的稳定性。
- **Agent：** intent 路由准确率、工具选择准确率、策略拦截率、重规划成功率、人工澄清解决率、平均行动轮数。
- **教学：** 数学事实正确率、提前泄露答案率、分层提示命中率、练习规划覆盖率、学习状态可追溯率。
- **性能：** Context Build P95、RAG P95、KT 推理耗时、单轮响应时间、端到端教学回合耗时、Token / Tool 调用成本。

## 当前可写的工程验证口径

- 默认 local fallback：后端 **207 passed / 4 skipped**，前端 **20 passed**；真实 DGEKT、Mem0、VikingDB / OpenViking 均为显式 opt-in。
- 已覆盖 `answer_submission`、`next_step_advice`、`general_chat` 三类学习 intent，以及 KT、RAG、Memory 三类 runtime observation。
- 已验证 RAG、Memory、Context Governance 与 provider readiness 不可改写 KT / DGEKT 学习事实；disabled / deleted memory、raw provider payload、SDK response、embedding 和私有路径不进入 response context package。

## 筛选原则

- 投 **Agent 开发岗位**：优先 Runtime Context Governance、条件 Tool Mount、动态 ReAct Runtime、版本化学习工作区。
- 投 **RAG / 知识工程岗位**：优先题目对齐 RAG、记忆 Context Assembly、Hybrid GraphRAG、模型—教学 Grounding。
- 投 **智能教育 / 算法工程岗位**：优先 SAFKT、可解释推荐、状态图提示与教学闭环。
- 投 **后端 / 平台岗位**：优先 Provider Fallback、Tool Contract、敏感信息清洗、回归门禁与 Event Sourcing。
- 一页简历建议只保留 4～5 条；终局规划未完成前务必使用“设计 / 建设中 / 规划”口径，不能写成已上线成果。
