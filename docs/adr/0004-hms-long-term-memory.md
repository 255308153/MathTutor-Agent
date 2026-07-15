---
status: accepted
supersedes: 0002-graphiti-long-term-memory.md
---

# 第一阶段使用 HMS 作为唯一长期记忆底座

MathTutor 第一阶段只部署 HMS，不部署 Graphiti 或 Neo4j。MathTutor 自己开发记忆业务模块，负责候选提取、证据门控、业务查重、冲突判断和清理决策；HMS 作为外接长期记忆服务，负责正式记忆的存储、索引、召回、替换和物理删除。

部署结构：

```text
MathTutor 记忆业务模块
        ↓ HTTP Adapter
HMS API + HMS Worker
        ↓
PostgreSQL 16 + pgvector
```

第一阶段配置：

```text
retain_extraction_mode=chunks
enable_observations=false
Embedding=BAAI/bge-m3
Embedding dimension=1024
```

选择 HMS 单底座是为了避免两套关系数据、同步任务、删除传播和故障处理。只有 HMS 无法满足已经出现的复杂多跳关系需求，并且评测证明 Graphiti 能带来明确收益时，才重新提交新的 ADR 决定是否增加 Graphiti。
