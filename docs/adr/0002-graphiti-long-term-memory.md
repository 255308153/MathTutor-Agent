---
status: superseded
superseded_by: 0004-hms-long-term-memory.md
---

# 使用 Graphiti 和 Neo4j 作为生产默认长期关系记忆

> 本决策已被 `0004-hms-long-term-memory.md` 替代。第一阶段不再安装或运行 Graphiti / Neo4j。

Graphiti 属于记忆模块的长期关系存储与检索实现，不是判题、KT、学习事实或上下文模块本身。第一阶段即接入 Graphiti，生产默认使用 Neo4j 和云端 DeepSeek V4 Pro；Embedding 模型暂未决定，在接入前通过配置补齐。

审核后的正式记忆先写入本地事实账本，再投影到 Graphiti。上下文模块只能通过 `LongTermContextStore` 读取长期记忆；Graphiti 超时或失败时熔断并降级到本地已审核投影，写入失败进入待同步队列，恢复后按 `memory_id` 幂等补写。
