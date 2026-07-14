# V1.9 Runtime E2E 回归与默认安全护栏验收记录

本文档对应 #116「V1.9: Runtime E2E 回归与默认安全护栏」，用于记录 V1.9 最终收口范围、默认安全护栏和后续版本边界。

## 收口范围

V1.9 是数学 Agent Runtime 与可观测学习编排的架构补强版，不等于真实内容、真实 provider、生产级 readiness 全部完成版。本版本验证一条完整数学学习 turn 可以贯通：

- `MathTutorAgentRuntime` 入口。
- `LearningTurnContext` 本轮上下文引用。
- 数学 Capability 选择。
- `MathToolRegistry` 中的 KT/DGEKT 权威事实、RAG 检索证据、学生记忆证据三类只读 observation。
- KT/DGEKT facts、RAG/记忆 observation、TeachingTrace 和前端 Runtime 概览。
- 空 RAG / evidence gap 等降级路径不会伪造 citation 或可信证据。

## 默认安全护栏

默认后端与前端测试只使用本地 demo/mock/fallback：

- KT 默认仍为 mock，本地 demo 不读取真实 DGEKT checkpoint。
- RAG 默认仍为 demo/local fallback，空 RAG smoke 不访问 VikingDB 或 OpenViking。
- 学生记忆默认仍为本地 in-memory store，Mem0 live provider 必须显式 opt-in。
- 完整 XES3G5M 数据、真实 DGEKT checkpoint、generated vector index、provider cache、raw dataset、模型文件和生成构建产物不得进入 tracked 文件。

Runtime 与 Provider Health 语义保持一致：provider mode 只允许 `local_fallback`、`fake_provider`、`live_provider`；readiness/status 只允许 `healthy`、`degraded`、`unavailable`、`not_configured`。这些状态只用于诊断和运营可见性，不能写 memory、progress、context、RAG、TeachingTrace 或 KT state。

## 权威事实边界

V1.9 收口继续保持以下边界：

- KT/DGEKT facts 是掌握度、薄弱点、预测正确率和推荐风险的权威来源。
- Offline attribution 解释 prediction，不覆盖 prediction facts。
- RAG 只能支持数学解释、引用、例题、定理和解法片段，不能覆盖 KT/DGEKT prediction facts。
- 学生记忆只能影响教学策略、表达方式和复习提醒，不能直接修改 mastery、weak concepts、prediction probability 或 forgetting risks。
- Context 只能组装 evidence，不能决定 learning facts。
- LLM 只能负责教学表达、提示策略、追问、总结和解释组织，不能覆盖 KT facts。

## 验收测试

#116 新增 / 强化的验收测试包括：

- 后端 `backend/tests/test_runtime_e2e_safety.py`：通过 `/api/events` 跑一条完整 `answer_submitted` 学习 turn，覆盖 runtime 入口、capability、Tool Registry、KT facts、空 RAG 降级、记忆 observation、TeachingTrace、`trace_overview`、provider mode/status 归一和敏感信息清洗。
- 前端 `frontend/src/App.test.tsx`：确认 Runtime 概览展示激活 capability、工具观察数量、provider gap 数量、工具状态、fallback、observation 摘要、evidence refs 和证据边界，不渲染 provider raw payload。

最终收口仍需运行：

```bash
python3 -m pytest backend/tests
cd frontend && npm test -- --run
cd frontend && npm run build
python3 scripts/check_repository_safety.py
git diff --check
```

## 后续版本边界

V1.10 仍负责上下文治理增强，包括 context budget、证据优先级、历史摘要、条件工具挂载和更完整的上下文生命周期管理。

V1.11 仍负责生产可用性增强，包括 provider health 运营化、真实 provider 连续验证、ready/not-ready 运维诊断、真实内容和真实 provider 的内部试用 gate。

V1.9 的完成标准是架构闭环、默认安全、可观测、可测试；不是把 Mem0、VikingDB/OpenViking、真实 DGEKT checkpoint 或完整 XES3G5M 变成默认依赖。
