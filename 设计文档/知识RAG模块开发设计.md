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
OpenSearch 关键词索引
Milvus 向量索引
PostgreSQL 知识图谱和元数据
        ↓
学生原始问题
        ↓
查询改写和指代消解
        ↓
OpenSearch 关键词召回 + Milvus 向量召回
        ↓
RRF（倒数排名融合）
        ↓
知识图谱扩展
        ↓
Reranker（重排序模型）
        ↓
重复过滤和上下文裁剪
        ↓
回答生成与引用校验
        ↓
TeachingTrace（教学追踪）
```

## 3. 存储分工

本项目当前默认使用 SQLite，主要用于本地运行和已有 V1 能力。目标 RAG 实现不要求所有数据都放在 SQLite 中。

| 存储 | 负责内容 |
|------|----------|
| PostgreSQL | 文档元数据、导入任务、版本、引用、证据缺口、知识图谱关系 |
| OpenSearch | 中文关键词检索、BM25 排序、字段权重、短语搜索、元数据过滤 |
| Milvus | 稠密向量、稀疏向量、向量近邻搜索和向量过滤 |
| 本地文件或对象存储 | 原始 PDF、页面图片、解析中间文件 |
| SQLite | 本地降级、测试和无外部依赖运行 |

知识图谱第一阶段可以使用 PostgreSQL 的节点表和关系表。只有当多跳查询和关系规模明显增加时，再考虑专用图数据库。

## 4. 资料类型

### 4.1 题目解析

来源为 XES3G5M 题库，内容包括题干、选项、答案、官方解析、题型、知识点和题图。

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
→ 对扫描页执行 OCR（图片文字识别）
→ 识别章节和小节
→ 处理公式、表格和图片
→ 按章节和段落切成知识片段
→ 绑定已有知识点
→ 生成稠密和稀疏表示
→ 写入 OpenSearch
→ 写入 Milvus
→ 建立知识图谱关系
→ 生成覆盖率报告
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

SQLite FTS5 只作为本地降级和测试实现，不作为正式生产关键词检索方案。

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
稀疏向量搜索
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
Milvus 稠密 / 稀疏向量召回
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

## 13. 知识图谱

节点类型：

```text
Question：题目
Concept：知识点
Chunk：教材片段
MistakePattern：错因
Strategy：学习策略
Formula：公式
```

关系类型：

```text
QUESTION_OF：题目属于知识点
REQUIRES：题目需要知识点
EXPLAINS：资料解释知识点
PREREQUISITE_OF：前置知识
MISCONCEPTION_OF：常见错误
SUPPORTS：资料支持讲解
NEXT_STEP：下一步学习方向
```

图谱用于：

```text
补充前置知识
寻找相关错因
寻找相关公式
寻找相关例题
扩展关键词和向量召回结果
```

推导关系必须记录：

```text
source_chunk_ids
confidence
created_by
review_status
```

没有来源的关系不能作为正式教学证据。

## 14. 重排序和去重

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

## 15. 提示词设计

提示词分为五类：

```text
查询改写提示词
知识图谱关系提取提示词
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
使用的 chunk_id
最终引用
```

## 16. 统一检索接口

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

## 17. 异常和证据缺口

以下情况必须记录 `evidence_gap`（证据缺口）：

```text
PDF 解析失败
OCR 质量过低
资料没有页码
知识点映射失败
OpenSearch 没有结果
Milvus 没有结果
向量生成失败
知识图谱关系没有来源
资料之间存在冲突
重排序后没有可靠结果
```

禁止：

```text
没有资料却生成引用
拿其他题目的解析回答当前题
把推导资料伪装成教材原文
让 RAG 修改 KT 或判分事实
```

## 18. 开发顺序

第一阶段实现关键生产链路：

```text
1. PDF 解析、页码和章节保留
2. 文档片段切分和知识点绑定
3. OpenSearch 中文关键词检索
4. Milvus 稠密 / 稀疏向量检索
5. 查询改写和指代消解
6. RRF 混合检索
7. Reranker 重排序
8. 引用定位和校验
9. 重复内容处理
10. 提示词版本管理
11. TeachingTrace 记录
```

第二阶段完善：

```text
1. 知识图谱关系完善
2. 图谱多跳检索
3. 错因和学习策略联动
4. 多查询改写
5. 检索评测和提示词评测
6. Provider（外部服务）降级和健康检查
```

## 19. 验收标准

```text
学生说“这里为什么这样”，系统能结合当前题完成改写
学生说“还是不懂”，系统能结合上一轮讲解继续检索
OpenSearch 能命中术语、公式和章节
Milvus 能命中语义相近内容
两路结果能正确融合
重排序能过滤不相关片段
重复教材内容不会全部进入上下文
知识图谱能找到前置知识和错因
回答带书名、章节、页码或题目编号
资料不足时不会编造引用
RAG 不会修改 KT 和学习事实
每次检索都能追踪原问题、改写结果和最终证据
```

## 20. 关键原则

```text
查询改写负责把学生的话说清楚
OpenSearch 负责精确找词
Milvus 负责理解语义
知识图谱负责补充关系
Reranker 负责最后筛选
提示词负责把证据变成合适的教学回答
引用负责让回答可以追溯
```
