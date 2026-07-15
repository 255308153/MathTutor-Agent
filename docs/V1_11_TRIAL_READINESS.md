# V1.11 生产 Readiness 与内部试用 Gate

本文档记录 V1.11（父 PRD #132，子 issue #133–#139）的准入边界、默认安全策略与人工试用结论入口。

## 目标

在 V1.10 Context Governance 之上，交付一个只读的 **Trial Readiness Gate**，让运营者能判断系统是否可以进入**有限内部试用**，同时保持：

- 默认 local fallback 可运行
- 真实 provider / DGEKT checkpoint / 完整 artifact / canary probe 必须显式 opt-in
- KT / DGEKT facts 仍是唯一权威学习事实
- Readiness、Probe、Persistence 恢复、Memory 控制、Context Governance 都**不得写入或覆盖** mastery / weak concepts / prediction / active teaching decisions

## 关键边界

| 信号 | 作用 | 是否可写学习事实 |
| --- | --- | --- |
| Trial Readiness Gate | 汇总 ready / degraded / not_ready | 否 |
| Provider Health | 配置与已记录 gap 诊断 | 否 |
| Canary Probe | 受控运维验证 live 可达性 | 否 |
| SQLite 持久化 | 恢复 progress / trace 摘要 / 记忆控制状态 | 只持久化既有快照，不重算 mastery |
| Memory 控制 | enable / disable / delete | 只改记忆元数据，不改 KT facts |
| Runtime Context Governance | 审计上下文预算与证据选择 | 否 |
| 人工试用反馈 | ready / hold / not_ready | 人工记录，不自动批准 |

## API

- `GET /api/trial-readiness`：只读试用 readiness 报告
- `POST /api/trial-readiness/probes`：显式 opt-in canary probe（默认安全跳过）
- `POST /api/trial-readiness/feedback`：记录人工试用结论
- `GET /api/students/{student_id}/sessions/{session_id}/recovery`：恢复 progress 与 TeachingTrace 摘要
- `GET /api/provider-health`：既有 provider 配置诊断（Gate 会复用）

## 报告字段

整体状态词：

| 状态 | 含义 |
| --- | --- |
| `ready` | 组件与证据面均满足自动条件，**仍需人工确认**后才可邀请试用 |
| `degraded` | 存在可恢复缺口；可继续 demo，但应谨慎邀请 |
| `not_ready` | 存在阻塞项，或仍处于默认 fallback（demo 可运行 ≠ 试用 ready） |

默认 local fallback 下：

- `demo_runnable = true`
- `internal_trial_ready = false`
- `fallback_is_not_trial_ready = true`
- 整体 `status = not_ready`

组件至少覆盖：

1. Provider 配置
2. Artifact Readiness
3. 持久化恢复
4. Runtime Context Governance
5. 默认 Fallback 安全
6. Provider Canary Probe
7. 记忆控制持久化

并附带：

- artifact 细分（DGEKT checkpoint / dataset-Qmatrix / offline evidence / imported content / imported RAG）
- checklist（已满足 / 可恢复降级 / 阻塞试用 / 待人工确认）
- residual_risks
- recent_feedback

## 默认安全

| 能力 | 默认 | 显式 opt-in |
| --- | --- | --- |
| Memory | `local_fallback` + SQLite 持久化 | `MATHTUTOR_MEMORY_PROVIDER_MODE=live_provider` + `MATHTUTOR_MEM0_API_KEY` |
| RAG | `local_fallback` | `MATHTUTOR_RAG_PROVIDER_MODE=live_provider` + endpoint/collection/key |
| KT | `mock` | `MATHTUTOR_KT_ENGINE=dgekt` + checkpoint/dataset/q-matrix |
| Content/RAG artifact | demo | `content_source/rag_source=imported` + 本地 artifact 路径 |
| Canary probe | 关闭 | `MATHTUTOR_ENABLE_PROVIDER_CANARY_PROBE=true`，并可配合 live smoke 开关 |
| 持久化 | SQLite `data/local/mathtutor.sqlite` | `MATHTUTOR_PERSISTENCE_BACKEND=memory` 仅用于隔离测试 |

禁止进入 Git：

- credentials / `.env`
- provider cache / vector index
- raw full dataset / checkpoint / 模型文件
- build output / `node_modules`

仓库检查：`python scripts/check_repository_safety.py`

## 连续学习恢复（#134）

本地 SQLite 保存：

- progress snapshot（含 concept states、recent graded events、recommendation history）
- TeachingTrace 摘要与 recommendation basis
- context governance audit ref（仅引用，不重算）
- 学生记忆与 enable/disable/delete 控制状态
- probe 结果与试用反馈

服务重启后：

1. 同一 `student_id` 可继续从 progress 出发
2. `GET .../recovery` 可返回最近 trace 摘要
3. 重复提交相同已判题事件不会重复更新 mastery

## Canary Probe（#135）

- 默认 API / dashboard 首屏 / 普通学习事件**不访问**真实 provider
- 无凭据时 probe 状态为 `skipped`
- 有 opt-in 时只返回规范化字段：provider、mode、status、recoverable、中文 reason、actionable_hint、时间
- 不返回密钥、绝对路径、原始 payload、学生内容

## 记忆控制（#136）

- disable：可在列表中看到，但不进入 search / active context
- delete：tombstone，列表/详情/检索均不可见
- 控制状态跨重启保持
- 不修改 mastery / weak concepts / prediction

## Artifact Evidence（#137）

Gate 区分：

- demo / mock fallback
- 配置缺失
- artifact 不存在 / 不完整
- 受控 fixture 或完整本地 artifact 可用

输出只含类别与状态，不含 checkpoint/dataset 绝对路径或模型载荷。

## 内部试用 Checklist 与反馈（#138）

专家侧 checklist 覆盖 provider/artifact、persistence、memory control、fallback safety、runtime governance、canary probe、人工结论。

人工结论只允许：

- `ready`：可邀请有限内部用户
- `hold`：暂缓
- `not_ready`：暂停邀请

**系统不会因为一次 health 请求或 probe 自动宣布试用获批。**

学生主界面不展示内部 checklist、probe 历史、运营备注。

## 何时可开始有限内部试用（人工前提）

1. Gate 无 blocking 项，或 blocking 已被明确接受并记录风险
2. 持久化恢复与记忆控制已验证
3. 如使用真实 provider，canary probe 已在隔离条件执行且结果可接受
4. 如使用真实数学证据，DGEKT / content artifact readiness 已复核
5. 运营者写入人工 `ready` 结论，并记录 residual risks

## 子 issue 完成情况

| Issue | 交付 |
| --- | --- |
| #133 | Trial Readiness Gate API + 专家概览；默认 fallback ≠ trial ready |
| #134 | SQLite 连续学习恢复 + recovery API + Gate persistence 组件 |
| #135 | 受控 canary probe（默认 skip）+ Gate probe 组件 |
| #136 | 持久化记忆控制与 context 排除 |
| #137 | DGEKT / content artifact 细分 readiness |
| #138 | checklist + 人工反馈闭环 |
| #139 | 本文档与父 PRD 收口 |

## 剩余风险（进入 V2.0 前）

- 默认环境无法证明真实 Mem0 / Viking / DGEKT 生产依赖
- canary 默认不发起真实网络调用，需运维窗口显式执行
- 内部试用规模、SLO、多租户与生产运维栈不在 V1.11 范围
- 最终试用扩大仍依赖人工决策与 residual risk 记录

## 验收记录

默认 local fallback：

1. `GET /api/trial-readiness` 返回 `status=not_ready`、`demo_runnable=true`、`internal_trial_ready=false`
2. 专家侧可见 readiness 概览与 checklist
3. 完成答题后重启，progress 与 trace 摘要可恢复
4. 记忆 disable/delete 跨重启生效
5. 无凭据时 canary probe 安全跳过
6. 人工反馈可记录 hold/ready/not_ready，且不自动批准
7. `scripts/check_repository_safety.py` 无违例
