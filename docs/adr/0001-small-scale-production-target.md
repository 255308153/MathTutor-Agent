---
status: accepted
---

# 采用个人和小规模用户的真实可运行架构

MathTutor 第一阶段面向个人或少量用户，以单机或单台云服务器可真实运行、可恢复和可审计为目标，不提前建设多节点集群。学习事实第一阶段使用 SQLite Adapter，保留 `LearningFactStore` seam 以便未来迁移 PostgreSQL；后台任务使用持久任务表和单 Worker，暂不引入 Redis、Kafka 或 Celery。

该选择保留正式事务、幂等、outbox、Provider 降级和数据隔离，但不为尚不存在的并发量增加分布式复杂度。
