# 知识 RAG 模块开发设计

> 本文描述知识 RAG（Retrieval-Augmented Generation，检索增强生成）模块的正式开发方案。
> 本模块面向 PDF 数学教材、XES3G5M 题目解析、概念资料、错因资料和学习策略资料。
> 目标是先实现关键技术链路，不以 demo（演示版）为目标。

## 1. 模块目标

RAG 的职责是：

```text
接收学生问题和当前学习上下文
→ 理解并改写学生的模糊表达
→ 从教材和题库中检索相关证据
→ 合并关键词、向量和知识图谱结果
→ 重排序、去重、裁剪
→ 返回带题号、书名、章节和页码的教学资料
```

RAG 不负责：

```text
判断学生是否掌握知识点
修改 KT（Knowledge Tracing，知识追踪）事实
决定下一道题
修改学生长期记忆
```

## 2. 总体架构

```text
PDF / 题库 / 概念资料
        ↓
资料导入与切片
        ↓
统一文档和知识片段
        ↓
PostgreSQL 权威元数据
OpenSearch 关键词索引
Milvus 向量索引
Neo4j 全局教学知识图谱
        ↓
学生原始问题
        ↓
分层路由判断
        ↓
按需查询改写和指代消解
        ↓
OpenSearch + Milvus 并行召回
        ↓
RRF（倒数排名融合）+ Neo4j 按需扩展
        ↓
Reranker（重排序模型）
        ↓
证据是否充足判断
        ↓
必要时启动 KnowTrace 多轮知识探索
        ↓
本轮临时证据图 + 重复过滤 + 上下文裁剪
        ↓
回答生成与引用校验
        ↓
知识回溯 + TeachingTrace（教学追踪）
```

## 3. 存储分工

知识 RAG 从一开始采用确定的正式架构，不设计 SQLite、Chroma 或 PostgreSQL 图关系查询作为过渡主链路。

| 存储 | 负责内容 |
|------|----------|
| PostgreSQL | 文档元数据、导入任务、版本、引用、证据缺口、关系审核记录、Prompt 版本和索引发布状态 |
| OpenSearch | 中文关键词检索、BM25 排序、字段权重、短语搜索、元数据过滤 |
| Milvus | 稠密向量、向量近邻搜索和向量元数据过滤 |
| Neo4j | 全局教学知识图谱、邻居查询、前置关系和多跳路径查询 |
| Redis | 导入任务运行状态、查询缓存和本轮临时证据图 |
| 持久化挂载目录 | 原始 PDF 和解析中间文件 |

PostgreSQL 是 Source of Truth（权威数据源）。OpenSearch、Milvus 和 Neo4j 是可重建的查询索引，不允许业务代码绕开 PostgreSQL 随意同时写多个系统。

同步采用 Outbox Pattern（本地消息表模式）：

```text
资料和审核结果写入 PostgreSQL
→ 同一事务写入 outbox_event
→ 索引 Worker 消费事件
→ 更新 OpenSearch、Milvus、Neo4j
→ 回写各索引的同步状态和版本
```

每个可检索片段记录：

```text
opensearch_status
milvus_status
neo4j_status
index_version
```

必要索引未完成时，该资料版本不得发布。

## 4. 资料类型

### 4.1 题目解析

来源为 XES3G5M 题库，内容包括题干、选项、答案、官方解析、题型和知识点。

```text
doc_type = question_explanation
source_level = authoritative
```

### 4.2 概念讲义

来源为 PDF 数学教材和人工整理资料，内容包括概念定义、公式、步骤、例题和易错点。

```text
doc_type = concept_note
source_level = authoritative | curated
```

### 4.3 错因模式

内容包括常见错误、错误原因、混淆概念和前置知识缺口。

```text
doc_type = mistake_pattern
source_level = curated | derived
```

### 4.4 学习策略

内容包括复习时机、降难度策略、变式练习和下一步学习建议。

```text
doc_type = learning_strategy
source_level = curated | derived
```

`derived`（推导内容）可以辅助回答，但不能伪装成教材原文。

## 5. 统一资料结构

每个资料片段至少包含以下字段：

```text
doc_id
doc_type
title
content

book_id?
page_start?
page_end?
chapter?
section_path?

question_id?
concept_ids[]

source_level
source_ref
content_hash
schema_version
```

题目和知识点统一使用 MathTutor 的标准 `question_id` 和 `concept_id`。XES3G5M 原始编号保留在 `source_ref` 中，不在模块外部暴露两套互相竞争的编号。

## 6. PDF 导入流程

```text
检查 PDF 文件
→ 计算文件指纹
→ 提取文字、目录和页码
→ 识别章节和小节
→ 处理可提取的公式和表格文本
→ 按章节和段落切成知识片段
→ 绑定已有知识点
→ 使用统一 Embedding Model 生成稠密向量
→ 写入 PostgreSQL 和 outbox_event
→ 同步 OpenSearch 和 Milvus
→ 提取、审核并同步 Neo4j 关系
→ 生成覆盖率报告
```

当前资料范围只接受具有可提取文字层的 PDF，不处理扫描版 PDF，不执行 OCR，不提取教材插图，也不保存页面截图。缺少文字层时导入失败并记录：

```text
gap_type = pdf_text_layer_missing
```

每本书记录：

```text
book_id
file_name
file_hash
edition
page_count
import_version
```

相同 `book_id` 和 `file_hash` 的文件不重复导入。新版本保留旧版本，保证历史引用可以继续定位。

## 7. PDF 切片规则

切片优先级：

```text
章节
→ 小节
→ 段落
→ 过长时按长度切分
```

普通片段建议为 300～800 个中文字符，并保留少量相邻片段重叠。

以下内容不能拆开：

```text
公式和公式解释
例题和解答
题目和解题步骤
表格标题和表格内容
结论和紧接着的说明
```

每个片段保存：

```text
chunk_id
parent_chunk_id
prev_chunk_id
next_chunk_id
page_start
page_end
section_path
```

## 8. 知识点绑定

知识点只能来自系统已有知识点表：

```text
concept_id
concept_name
concept_path
```

绑定优先级：

```text
人工配置映射
→ PDF 章节与知识点目录匹配
→ AI 辅助推荐
→ 人工审核确认
```

AI 只能推荐知识点，不能直接创造新的正式知识点编号。

一个片段可以绑定多个知识点：

```json
{
  "concept_ids": [
    "c_fraction_addition",
    "c_common_denominator"
  ]
}
```

无法确认时保留空数组并记录 `mapping_status = unmapped`，不得强行绑定到相似知识点。

## 9. OpenSearch 关键词检索

OpenSearch 负责：

```text
中文分词
BM25（关键词相关性排序）
标题和正文搜索
章节搜索
知识点名称搜索
公式文本搜索
短语匹配
元数据过滤
```

字段权重建议：

```text
question_id：最高
concept_id 和知识点名称：高
标题和章节：高
公式：高
正文：普通
```

OpenSearch 是正式关键词检索实现。测试环境使用相同类型的容器服务，避免使用另一套全文检索行为代替生产行为。

## 10. Milvus 向量检索

Dense Retrieval（稠密向量检索）的过程是：

```text
PDF 片段
→ Embedding Model（向量模型）
→ 生成向量
→ 写入 Milvus

学生问题
→ 使用同一个向量模型生成问题向量
→ Milvus 查找相似片段
```

Milvus 负责：

```text
稠密向量搜索
近似最近邻索引
向量过滤
```

Milvus 不负责生成向量、生成回答或判断教学正确性。

建议统一记录：

```text
model_name
model_version
embedding_dimension
index_version
```

更换向量模型后必须重建对应版本的向量索引。XES3G5M 自带向量只有在确认原始编码模型后才能复用，否则重新编码。

## 11. 混合检索

Hybrid Search（混合检索）同时执行：

```text
OpenSearch 关键词召回
Milvus 稠密向量召回
```

建议两边各取 20～50 条候选结果，再使用 RRF 合并排名：

```text
两边都出现的结果优先
关键词排名高的结果加分
向量排名高的结果加分
```

上层 RAG 不依赖 OpenSearch 或 Milvus 的 SDK，而依赖统一的召回器接口：

```text
LexicalRetriever：关键词召回器
VectorRetriever：向量召回器
```

## 12. 查询改写

查询改写是在线链路的必要步骤，用于处理学生表达不清、代词和省略。

```text
学生原始发言
→ 读取当前题和最近对话
→ 判断指代对象
→ 生成完整问题
→ 生成关键词查询
→ 生成语义查询
→ 判断是否需要追问
```

输入包括：

```text
学生原始发言
当前题目和 question_id
当前 concept_ids
当前作答状态
最近 3～5 轮对话
上一轮 AI 讲解主题
```

输出必须结构化：

```text
intent
resolved_query
lexical_query
semantic_query
question_id
concept_ids
doc_types
graph_seeds
confidence
clarification_required
clarification_question
```

含义明确时直接改写。存在多个可能含义时先追问，不执行大范围检索。

建议规则：

```text
confidence >= 0.80：直接检索
0.55 <= confidence < 0.80：生成多个查询并谨慎回答
confidence < 0.55：向学生追问
```

涉及提交答案、切换题目、修改推荐或写入学习事实时，不能只依赖模型置信度，必须由明确的系统事件触发。

## 13. 分层路由设计

完整能力不代表每次请求都调用全部系统。路由按照以下顺序判断：

```text
系统事件
→ 明确规则
→ 模糊情况交给 LLM 路由器
→ Policy Guard（策略守卫）检查
→ 首轮检索
→ 根据证据是否充足决定是否升级 KnowTrace
```

系统按钮事件由代码直接判断：

```text
提交答案 → answer_submission
点击下一题 → next_question_action
点击换题 → recommendation_feedback
显示答案 → reveal_answer
发送聊天消息 → conversation_message
```

提交答案、下一题、换题和显示答案不能由 LLM 改写成 RAG 请求。

聊天路由只保留以下执行类型：

```text
no_retrieval：闲聊和简单确认
fast_question_rag：绑定当前题的明确问题
fast_concept_rag：明确概念问题
rewrite_then_rag：带代词、省略或依赖最近对话
graph_rag：需要前置知识、错因或概念关系
knowtrace_rag：首轮证据不足，需要多轮知识探索
clarification：存在多个合理解释，必须追问
state_action：明确的系统状态动作
```

LLM 路由器输出：

```text
intent
clarity
scope
reasoning_depth
needs_rewrite
needs_knowledge_relation
state_write
confidence
reason_code
```

Policy Guard 必须执行以下检查：

```text
系统事件优先于 LLM 分类
没有当前题时禁止 fast_question_rag
低置信度且存在多个解释时转 clarification
聊天语义判断不得直接写学习事实
question_id 和 concept_id 必须来自当前状态或标准映射
```

不要在学生刚发言时就强行判断是否启动 KnowTrace。普通请求先执行一次混合检索，证据仍不足时再升级。

工具调用策略：

| 场景 | 查询改写 | OpenSearch | Milvus | Neo4j | KnowTrace |
|------|----------|------------|---------|-------|-----------|
| 闲聊 | 否 | 否 | 否 | 否 | 否 |
| 当前题明确提问 | 否 | 是 | 是 | 按需 | 否 |
| 明确概念问题 | 否 | 是 | 是 | 按需 | 否 |
| 模糊表达 | 是 | 是 | 是 | 按需 | 否 |
| 前置知识或概念关系 | 按需 | 是 | 是 | 是 | 证据不足时启动 |
| 多步错因分析 | 是 | 是 | 是 | 是 | 是 |
| 系统状态动作 | 否 | 否 | 否 | 按动作规则 | 否 |

OpenSearch、Milvus 和按需执行的 Neo4j 查询必须并行发起，不得串行等待。

## 14. 知识图谱

系统同时使用两张用途不同的图：

```text
全局教学知识图谱：长期保存，存储在 Neo4j
本轮临时证据图：围绕当前学生问题生成，运行时保存在 Redis，结束后写入 PostgreSQL 和 TeachingTrace
```

全局图谱节点类型：

```text
Question：题目
Concept：知识点
Chunk：教材片段
MistakePattern：错因
LearningStrategy：学习策略
Formula：公式
```

关系类型采用固定白名单：

```text
PARENT_OF：上级知识点
QUESTION_OF：题目属于知识点
REQUIRES：题目需要知识点
EXPLAINS：资料解释知识点
PREREQUISITE_OF：前置知识
MISCONCEPTION_OF：常见错误
SUPPORTS：资料支持讲解
USES_FORMULA：使用公式
NEXT_STEP：下一步学习方向
CONTRASTS_WITH：概念对比
```

不允许 LLM 在运行时自由创造关系名称。

确定关系直接从知识点目录、XES3G5M 映射和已审核资料生成。由 LLM 从 PDF 提取的关系只能先进入 PostgreSQL 候选审核记录，审核通过后才通过 outbox_event 发布到 Neo4j。

每条关系必须记录：

```text
edge_id
from_node_id
relation_type
to_node_id
source_chunk_ids
source_level
confidence
created_by
review_status
graph_version
```

没有来源的关系不能作为正式教学证据。重复关系合并来源，冲突关系标记 `graph_conflict` 并停止自动使用。

本轮临时证据图中的关系分为：

```text
global：来自已发布的 Neo4j 全局图谱
retrieved：来自本轮检索片段并带引用
derived：模型根据本轮证据推导，只能辅助规划
```

本轮临时图不得直接写入全局 Neo4j 图谱。反复出现且来源可靠的新关系进入候选审核队列。

## 15. KnowTrace 多轮知识探索

KnowTrace-RAG 追踪的是“回答当前问题还缺什么知识”，不是学生掌握度 KT。

```text
Student KT：追踪学生会不会
KnowTrace-RAG：追踪当前回答已经有什么证据、还缺什么证据
```

新增运行状态：

```text
KnowledgeTraceState
```

至少记录：

```text
trace_id
student_message
resolved_query
intent
question_id
concept_ids
current_round
max_rounds
knowledge_triples[]
exploration_targets[]
retrieved_chunk_ids[]
supporting_triple_ids[]
status
stop_reason
evidence_gaps[]
```

每一轮包含两个步骤：

```text
Knowledge Exploration（知识探索）
→ 判断当前证据是否足够，并生成下一步实体、关系和检索查询

Knowledge Completion（知识补全）
→ 从重排序后的资料中提取带来源的知识三元组
```

知识探索输出：

```text
evidence_sufficient
missing_knowledge[]
exploration_targets[]
```

每个探索目标包含：

```text
entity
relation
lexical_query
semantic_query
doc_types[]
filters
```

知识补全输出的每条三元组必须包含：

```text
subject
predicate
object
source_chunk_id
citation
confidence
```

三元组进入临时证据图前必须校验关系白名单、来源片段、页码、知识点标识、重复关系和证据支持情况。

运行限制：

```text
普通深度问题最多 2 轮
复杂问题硬上限 3 轮
每轮最多 2 个探索目标
每个目标融合后进入重排序的候选不超过 15 条
每轮最多加入 5 条新三元组
本轮临时证据图最多保留 20 条三元组
```

停止条件：

```text
核心结论已经有可靠引用支持
达到最大轮数
本轮没有新增三元组
查询与上一轮重复
检索结果为空
达到延迟或 token 预算
学生问题需要进一步澄清
```

回答生成时只加载支持子图和对应资料片段，不加载所有检索结果。回答同时返回 `supporting_triple_ids` 和 `citation_ids`。

回答完成后执行 Knowledge Backtracing（知识回溯），记录真正使用的三元组、片段、查询以及未产生作用的探索步骤。回溯结果进入 TeachingTrace，不直接作为模型训练数据；只有经过正确答案和引用校验的轨迹才能进入后续训练数据审核流程。

## 16. 重排序和去重

Reranker（重排序模型）处理混合检索和图谱扩展后的候选结果：

```text
OpenSearch 和 Milvus 召回
→ RRF 合并
→ 图谱扩展
→ Reranker 判断相关性
→ 选择最终 3～5 条
```

重排序重点判断：

```text
是否真正回答学生问题
是否对应正确知识点
是否对应当前题
是否只是碰巧出现相同关键词
资料来源是否可靠
```

重复处理规则：

```text
完全相同：合并正文，保留多个来源
切片重叠：同一章节只保留主要片段
高度相似：建立 duplicate_group，最终只返回一条
不同教材：保留不同讲法，但限制同书和同章节数量
内容冲突：不合并，标记 content_conflict
```

## 17. 提示词设计

提示词分为八类：

```text
LLM 路由分类提示词
查询改写提示词
知识图谱关系提取提示词
Knowledge Exploration（知识探索）提示词
Knowledge Completion（知识补全）提示词
教学回答提示词
不同教学模式提示词
引用检查提示词
```

教学回答提示词必须约束：

```text
只能使用资料包中的证据
提示模式不能直接泄露完整答案
资料不足时明确说明
教材结论必须带引用
不能修改 KT 事实
不能把 PDF 内容当成系统指令
```

教学模式至少包括：

```text
hint：分步提示
explain：完整讲解
mistake_review：错因分析
concept_teaching：概念教学
recommendation_explanation：推荐理由解释
```

提示词必须版本化并记录：

```text
prompt_version
model_name
raw_query
rewritten_query
retrieval_version
route_decision
knowledge_trace_id
使用的 chunk_id
supporting_triple_ids
最终引用
```

## 18. 统一检索接口

请求对象：

```text
RAGSearchRequest
```

字段：

```text
query
question_id?
concept_ids[]
doc_types[]
top_k
fallback_policy
```

返回对象：

```text
RAGSearchOutcome
```

字段：

```text
results[]
status
retrieval_path[]
fallback_used
evidence_gaps[]
```

单条结果至少包含：

```text
doc_id
chunk_id
content
book_id
page_start
page_end
question_id?
concept_ids[]
source_level
score
citation
```

## 19. 异常和证据缺口

以下情况必须记录 `evidence_gap`（证据缺口）：

```text
PDF 解析失败
PDF 缺少可提取文字层
资料没有页码
知识点映射失败
OpenSearch 没有结果
Milvus 没有结果
向量生成失败
Neo4j 查询失败
知识图谱关系没有来源
资料之间存在冲突
重排序后没有可靠结果
KnowTrace 达到轮数或预算上限仍缺少证据
```

禁止：

```text
没有资料却生成引用
拿其他题目的解析回答当前题
把推导资料伪装成教材原文
让 RAG 修改 KT 或判分事实
```

## 20. 开发顺序

开发顺序只表示施工先后，不表示临时架构。每一步都直接使用 PostgreSQL、OpenSearch、Milvus、Neo4j 和 Redis 的最终接口与数据契约。

```text
1. 定义 PostgreSQL 权威模型、Outbox Event 和索引版本协议
2. 建立 PDF 持久化目录、文字层检查、页码和章节解析
3. 完成文档片段切分、知识点绑定、去重和引用定位
4. 完成 OpenSearch 中文关键词索引和字段权重
5. 完成 Milvus 稠密向量索引和模型版本管理
6. 完成 OpenSearch、Milvus、Neo4j 的索引 Worker 和重试状态
7. 建立 Neo4j 全局知识图谱、关系白名单和审核发布流程
8. 完成系统事件、规则、LLM 和 Policy Guard 分层路由
9. 完成查询改写、指代消解和 clarification 追问
10. 完成 OpenSearch + Milvus 并行召回、RRF 融合和 Reranker
11. 完成证据充足判断和 KnowTrace 多轮知识探索
12. 完成本轮临时证据图、三元组校验和 Redis 运行状态
13. 完成支持子图回答、引用校验和知识回溯
14. 完成提示词、检索器、图谱和模型版本管理
15. 完成 TeachingTrace、评测集、性能预算和 Provider 健康检查
```

## 21. 验收标准

```text
学生说“这里为什么这样”，系统能结合当前题完成改写
学生说“还是不懂”，系统能结合上一轮讲解继续检索
按钮事件不会被 LLM 错误路由成 RAG 请求
明确问题走快速路径，不会无条件启动全部工具
OpenSearch 能命中术语、公式和章节
Milvus 能命中语义相近内容
两路结果能正确融合
重排序能过滤不相关片段
重复教材内容不会全部进入上下文
Neo4j 能找到前置知识、错因和概念关系
KnowTrace 能根据证据缺口生成下一轮检索目标
KnowTrace 能在证据充分、无新证据或达到预算时正确停止
每条临时知识三元组都能定位到来源片段和页码
回答带书名、章节、页码或题目编号
资料不足时不会编造引用
RAG 不会修改 KT 和学习事实
每次检索都能追踪原问题、路由、改写、探索轮次、支持子图和最终证据
```

## 22. 关键原则

```text
查询改写负责把学生的话说清楚
分层路由负责选择最短且足够的执行路径
OpenSearch 负责精确找词
Milvus 负责理解语义
Neo4j 全局图谱负责提供经过审核的教学关系
KnowTrace 临时证据图负责追踪当前回答还缺什么知识
Reranker 负责最后筛选
提示词负责把证据变成合适的教学回答
引用负责让回答可以追溯
知识回溯负责识别真正支持回答的资料和步骤
```
