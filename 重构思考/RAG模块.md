# RAG 模块：预期实现设计

> 本文描述 MathTutor Agent 的 **RAG 目标态实现**，数据底座以 **XES3G5M** 为准。  
> 不是当前实验报告；实现状态以代码与配置为准，文档负责对齐「应该怎么做」。

相关文档：

| 文档 | 关系 |
|------|------|
| [系统总设计.md](./系统总设计.md) | 产品与模块总览 |
| [思考链路.md](./思考链路.md) | 按意图 Route，再按需 Retrieve |
| [记忆模块.md](./记忆模块.md) | RAG vs Memory 边界 |
| [上下文总设计.md](./上下文总设计.md) | 检索结果如何进资产、预算与 Package |
| `docs/V1_ARCHITECTURE.md` | V1 已实现架构（含 demo / ASSIST 路径） |
| `docs/简历草稿_MathTutor目标态实验验收.md` | XES3G5M 评测与验收口径 |

---

## 1. 一句话目标

围绕 **真实题目** 做可引用的教学证据检索：

```text
从 XES3G5M 加工教学文档
→ 按意图混合召回 + 题 / KC 元数据过滤
→ 服务讲解与规划，带 citation
→ 空结果记 evidence gap，禁止伪造引用
→ 绝不改写 KT / 判分事实
```

RAG 负责「怎样解释更有依据」，不负责「学生是否已学会」。

---

## 2. 权威边界

三类存储严格切开：

| 存储 | 内容 | 权限 |
|------|------|------|
| **RAG** | 稳定知识：题解、概念、错因模式、学习策略 | 只读讲解证据，可进 citation |
| **Memory** | 个人经验：偏好、重复错因、策略效果、反思 | 只影响教学策略，不改 mastery |
| **KT / Progress / 判分** | 会不会、对不对：mastery、weak concepts、prediction、is_correct | **唯一权威事实** |

硬规则：

```text
KT facts are authoritative.
RAG supports explanation, not overwrite prediction facts.
LLM plans are advisory.
空检索 / 映射缺失 / schema 错误 → evidence_gap，禁止伪造 citation。
```

---

## 3. 数据底座：XES3G5M（不是 ASSIST2017）

### 3.1 为什么换数据集

ASSIST2017 公开竞赛包保留序列、题号、知识点、对错，但 **没有题干 / 选项 / 图片正文**。  
无法支撑「围绕真实题讲解」的 Agent 与 RAG。

目标底座改为 **XES3G5M** 真实中文小学数学数据：

| 规模（目标态口径） | 内容 |
|--------------------|------|
| 7,652 题 | 真实题干、解析、答案 |
| 6,142 填空 / 1,510 单选 | 可确定性判分 |
| 865 叶子知识点 | `kc_routes` 知识点路线 |
| 约 555 万条 question-level 交互 | KT / 学生序列 |
| 题图与 embedding 资产 | 展示与 dense 检索 |

### 3.2 本地资产路径

```text
XES3G5M/metadata/questions.json      # content / type / answer / options / analysis / kc_routes
XES3G5M/metadata/kc_routes_map.json
XES3G5M/metadata/embeddings/         # qid2content_emb, qid2analysis_emb, cid2content_emb
XES3G5M/metadata/images/
XES3G5M/question_level/              # 学生作答序列（与题 id 同源）
```

### 3.3 标识空间

```text
判分 · SAFKT/KT · RAG · TeachingTrace
必须共用同一套 question_id / concept(KC) id。
禁止与 ASSIST2017 题号混用。
```

---

## 4. 语料层：四类教学文档

从题目与知识点加工，而不是通用网页乱切：

| doc_type | 主要来源 | 用途 |
|----------|----------|------|
| `question_explanation` | `content` + `analysis` + 题型/答案 | 题意、步骤、标准解法 |
| `concept_note` | `kc_routes` / KC 聚合说明 | 定义、公式、常见题型、易错点 |
| `mistake_pattern` | 错因库 / 规则或标注 | 常见错误、误区、前置缺口 |
| `learning_strategy` | 策略文档 | 何时复习、降难度、做变式 |

每份文档必须标明来源等级：

```text
authoritative：题库直接提供的题干、答案、解析等原始内容
curated：人工整理并审核过的概念、错因或策略内容
derived：规则或模型根据已有证据生成的辅助内容
```

`derived` 内容可以辅助教学，但不能伪装成题库原文引用。

### 4.1 最小字段

```text
doc_id
doc_type: concept_note | question_explanation | mistake_pattern | learning_strategy
title
content
source
question_id?                 # 题级文档必填
concept_id / kc_route?       # 知识点对齐
provenance                   # 来自哪道题 / 哪份资产 / 哪次导入
coverage                     # question | concept | global | unmapped_*
keywords?                    # 可选，辅助关键词召回
```

### 4.2 导入与覆盖率

预期导入链路：

```text
XES3G5M questions + KC +（可选）人工整理的错因/策略
→ rag_documents（分类型 chunk）
→ coverage_report（缺解析、缺 KC、缺 doc → gap）
→ KnowledgeRAG 加载 / 建索引
```

缺文档记 `missing_rag_doc` 一类缺口，**不静默跳过、不伪造内容**。

---

## 5. 检索层：契约与算法

### 5.1 稳定契约

```text
KnowledgeRAG.search(query, filters, limit) → list[RAGSearchResult]
```

- **filters**：`doc_type` / `doc_types`、`question_id`、`concept_id` / KC（抗串题核心）
- **结果**：标准字段 + `score` + `provenance` + `coverage`
- **失败**：归一为 provider gap / evidence gap，不进假 citation

实现可切换，契约不变：

| mode | 用途 |
|------|------|
| `local_fallback` | 默认：本地索引 / 本地文档，零外部依赖 |
| `fake_provider` | 契约与回归测试 |
| `live_provider` | VikingDB / OpenViking 等，显式 opt-in；失败可回退 local |

### 5.2 目标检索管线

```text
1. Metadata 硬过滤（当前题 / 薄弱 KC / doc_type）
2. Hybrid 召回
   - BM25 / 关键词（题号、公式、中文术语）
   - Dense（可用 XES3G5M 官方 emb 或向量库）
3. 融合（如 RRF）+ 可选 Cross-Encoder 重排
4. Top-K（常 3～5）→ rag_context
```

### 5.3 终局扩展：Hybrid GraphRAG

在 Hybrid 之上增加教学知识图谱多跳：

```text
Dense（如 Milvus）
+ BM25 / ES
+ 图关系（QUESTION_OF / REQUIRES / MISCONCEPTION_OF / NEXT_STEP / SUPPORTS）
→ RRF 融合 + 重排 + question/KC filter
→ 带 citation、confidence、token budget 的教学 context
```

仍统一走 `KnowledgeRAG.search`，不让编排层依赖某一家 SDK。

---

## 6. 编排层：何时调用

原则：**先 Route 意图，再按需 Retrieve**。不是每轮固定调 RAG / KT。

| 场景 | 是否 RAG | 典型 doc_type / filter |
|------|----------|-------------------------|
| 无关闲聊 | 否 | — |
| 泛化概念问答 | 可选 / 优先 RAG | concept_note + mistake_pattern |
| 当前题卡住 / 要提示 | 是 | 当前 `question_id` + explanation / mistake / concept |
| 交答案后讲解 | 是 | 本题 explanation + mistake + strategy |
| 下一步学什么 | 可选 | 薄弱 KC 的 strategy + concept_note |
| 推荐理由 | 可选 | concept_note + mistake_pattern |
| 推荐选题之后 | 是（选题后） | **只查选中题**，减少串题 |

推荐链路预期顺序：

```text
诊断 → 推荐选题 → rag(selected_question_id) → 组装解释
```

题级无命中时：

- 可降级到 KC / concept 级检索；
- 必须在 TeachingTrace 标记 `rag_fallback_used`；
- 真实 imported 库应比 demo 更严格，避免乱绑证据。

---

## 7. 消费层：结果如何进入教学闭环

```text
rag_search(query, filters)
  → state.rag_context
  → LearningContext.knowledge_resource
  → Context Governance（预算裁剪；KT facts 不可裁）
  → 回复流程（根据学生问题生成讲解 / 提示 / 错因说明）
  → 回复 citation（doc_id / source / question_id / KC）
  → TeachingTrace + rag_retrieval_evidence observation
```

Runtime 侧：

- 工具 observation `rag_retrieval_evidence` 只读：结果数、sources 摘要、empty_result、provider gap；
- 不得写入 mastery / prediction；
- 脱敏：不落 raw payload、embedding 全文、密钥、私有路径。

空结果：

```text
missing_rag_citation
provider_empty_result / provider_schema_mismatch / timeout / ...
→ 显式 gap，降级讲解策略，禁止假引用
```

---

## 8. 实现分层与落地顺序

```text
┌──────────────────────────────────────────────┐
│ 编排   Intent → 是否调 RAG / query + filters │
├──────────────────────────────────────────────┤
│ 契约   KnowledgeRAG.search → RAGSearchResult │
├──────────────────────────────────────────────┤
│ 适配   Local | Fake | Viking（可回退）        │
├──────────────────────────────────────────────┤
│ 索引   BM25 + Dense（+ 图，终局）             │
├──────────────────────────────────────────────┤
│ 语料   XES3G5M 加工四类 doc + coverage         │
└──────────────────────────────────────────────┘
```

建议顺序：

1. **导入**：`questions.json` → 统一题目模型 + 四类 `rag_documents` + coverage  
2. **Local 检索**：关键词 / BM25 + `question_id` / KC filter（先抗串题）  
3. **挂编排**：按意图调用、gap、Trace、Context Governance  
4. **Dense**：接入官方 emb 或向量库，Hybrid 融合  
5. **Live adapter** + 离线评测集  
6. **（终局）** Graph 多跳 + 重排  

---

## 9. 验收口径（目标态）

同一真实 `question_id` / KC 应能贯通：

```text
判分 → KT weak_concepts → 推荐题 → RAG citation → 错因诊断 → TeachingTrace
```

检索评测建议（见目标态验收文档）：

| 指标方向 | 说明 |
|----------|------|
| Recall@K / MRR / NDCG | 检索完整性 |
| Citation Precision / Recall | 引用是否对题、对点 |
| 串题率 | 错绑其他题目的比例（目标尽量极低） |
| P95 延迟 / token 成本 | 工程可用性 |
| gap 正确性 | 无结果时必须暴露 gap，不得静默编造 |

对照组至少覆盖：BM25、Dense、Hybrid、Hybrid + metadata filter（+ rerank）。

---

## 10. 与现状对照（避免口径混淆）

| 维度 | 当前常见实现 | 本文预期（目标态） |
|------|--------------|--------------------|
| 数据 | demo JSON / ASSIST2017 artifact | **XES3G5M** 真实题 + 解析 + KC |
| id | assist2017 / demo id | XES3G5M `question_id` / KC，不混用 ASSIST2017 |
| 检索 | 本地词重叠 + 可选 Viking 归一化 | BM25 + dense + filter（+ 重排 / 图） |
| 调用 | load_context 内按事件构造 query | 按意图 Route；推荐后只查选中题 |
| 边界 | 已有：不覆盖 KT、空结果 gap | **保持不变**，扩展到真实题 citation |

**契约形态**（`search`、四类 doc、provider 三档、gap、进 Trace）可延续；  
**语料与 id 空间、Hybrid 检索** 必须迁到 XES3G5M。

---

## 11. 总览流程图

```text
XES3G5M 真实题
  → 切成「题解 / 概念 / 错因 / 策略」并打 question + KC 标签
  → 按意图 Hybrid 检索 + 元数据过滤
  → 进入回答资料包，带 citation
  → 缺证据记 gap；永远不覆盖 KT / 判分事实
```

---

## 12. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-07-11 | 初稿：汇总 RAG 预期实现；数据底座明确为 XES3G5M；与 demo/ASSIST 路径区分 |
