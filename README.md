# MathTutor Agent

面向个人数学学习场景的教学 Agent：以**当前题目**为主界面，以侧边 Agent 为辅导层，用可审计的工具链路完成诊断、推荐与讲解。

```text
一句话定位：
题目是主界面，Agent 是侧边辅导层，下一题按钮是明确的学习推进动作。
```

详细设计见仓库根目录 [`重构思考/`](./重构思考/)：

| 文档 | 内容 |
|------|------|
| [系统总设计.md](./重构思考/系统总设计.md) | 页面模块、状态同步、产品边界 |
| [思考链路.md](./重构思考/思考链路.md) | 意图路由、按需工具调用、DAG / Trace |
| [简历修改版_MathTutor_Agent.md](./重构思考/简历修改版_MathTutor_Agent.md) | 技术亮点与现有/规划边界（求职材料） |

---

## 总目标

V1 不做通用聊天机器人，而是跑通一条**可演示、可测试、可解释**的数学学习闭环：

```text
学生输入 / 学习事件
-> 意图识别（规则优先，LLM 辅助，Policy guard 兜底）
-> 按场景决定是否调用工具
-> 按需检索题库 / RAG / Memory / 历史
-> 按需 KT / DGEKT 诊断
-> 组装证据
-> 教学决策（推荐 / 提示 / 讲解 / 复盘）
-> 生成回复或更新页面状态
-> 记录 TeachingTrace
```

### 要解决的问题

- 生成式 Agent 容易脱离学生真实掌握状态。
- 每次对话全量调用 RAG / KT，造成上下文污染与不可解释。
- 提交答案、推荐下一题、对话答疑职责混在一起。
- 外部 Provider 不稳定时难以本地演示与降级。

### 核心原则

```text
KT facts are authoritative.     # 掌握度 / 风险 / 预测是权威事实
LLM plans are advisory.         # 模型只做策略与表达建议
Memory influences strategy.     # 记忆只影响讲解风格与节奏，不改 mastery
RAG supports explanation.       # RAG 只提供讲解证据，不覆盖预测事实
Context assembles, never writes facts.
证据可并行收集；决策与状态写入必须串行。
不是每句话都调重工具。
```

---

## 产品模块设计

主心智模型是「**当前题目 + 侧边 Agent 辅导**」，不是纯聊天页。三个核心模块共享同一份学习事实状态。

### 1. 当前题目区

展示学生正在做的题：题干、答案输入、提交按钮、当前题状态、可选的简短推荐说明。

**提交答案只做状态保存**，不触发 Agent、不自动推荐下一题：

```text
写答案 -> 提交 -> 保存作答记录 -> 可选确定性判题 -> 更新当前题状态
```

### 2. 左侧 Agent 对话

支持围绕当前题提问、错因解释、为什么推荐、下一步建议、学习复盘等。

按问题按需取证，**不每次全量调用工具**：

| 场景 | 典型工具 |
|------|----------|
| 当前题怎么做 / 卡住 | task_state + 可选 RAG + 可选 Memory |
| 为什么推荐这题 | recommendation_evidence + 可选 KT / Memory |
| 下一步练什么 | KT + Recommender（RAG 可在选题后再查） |
| 泛化概念 | 可选 RAG |
| 闲聊 | 不调重工具 |

Memory 是**内部画像能力**，用户不直接增删改；系统在后台根据学习行为维护。

### 3. 下一题按钮

明确的系统动作，不是普通聊天：

```text
读学习状态 -> 按需 KT / 题库 / 历史 / Memory
-> Recommender 选题 -> 更新 current / pending question
-> 页面跳转下一题 + 一句简短推荐原因
```

用户若再追问「为什么选这道」，Agent 再读取完整推荐证据做详细解释。

### 状态分层

```text
学习事实状态：题目、答案、判题、进度、当前题（全局共享）
对话状态：某次 Agent 会话里问过什么（属 conversation）
内部画像状态：偏好、错因、有效策略（系统维护，用户不可直接操作）
```

边界一句话：

```text
题目区负责做题与保存作答；
下一题按钮负责推进当前题；
Agent 侧边栏负责解释、答疑、复盘与学习建议。
```

---

## 系统模块与架构

架构核心不是「让大模型直接解题」，而是拆成带权限边界的模块：

```text
LearningEvent / Chat / Answer
             |
   Agent Runtime：意图路由、能力选择、工具挂载
             |
    +--------+---------+----------------+
    |                  |                |
KT / DGEKT Facts   RAG Evidence    Student Memory
学习状态唯一来源    题目与概念证据     偏好与有效策略
    |                  |                |
    +--------- LearningContextLayer ----+
                         |
      Context Governance：排序、裁剪、脱敏、审计
                         |
       Planner / Response -> TeachingTrace / Provider Health
```

### 事实平面 vs 教学平面

| 平面 | 职责 | 能否写学习事实 |
|------|------|----------------|
| **事实平面** | 确定性判题、Progress Store、KT / DGEKT | 唯一可写 mastery / weak concepts / prediction 等 |
| **教学平面** | RAG、Memory、Planner、Response | 只读事实，只调整讲解与练习策略 |

Runtime、Context Governance、RAG、Memory、Provider Health **都没有改写学习事实的权限**。

### 模块职责

| 模块 | 职责 | 不做的事 |
|------|------|----------|
| **Agent Runtime** | 意图路由、Capability / Tool Registry、按场景挂载工具 | 不每轮全量调用；不绕过 Policy guard 写状态 |
| **KT / DGEKT** | 掌握度、遗忘 / 预测风险、错因与诊断 | 不被 RAG / Memory / LLM 覆盖 |
| **RAG** | 概念说明、题解、错因模式、教学策略（按 question / concept 对齐） | 不判断「是否已学会」；缺证据时显式 gap，不伪造引用 |
| **Memory** | 偏好、重复错因、有效策略、学习反思 | 不写 mastery；用户不直接 CRUD |
| **Recommender / Planner** | 风险优先选题、教学动作与推荐理由 | 不编造无证据的「个性化」理由 |
| **Context Governance** | 证据优先级、预算裁剪、脱敏、selected-only 回复包 | 不改写原始 KT / RAG / Memory 状态 |
| **TeachingTrace** | 记录意图、工具、证据、决策与边界 | — |

证据优先级（进入回复前）：

```text
KT / DGEKT facts > 当前任务 > 工具快照 > 相关 Memory / RAG
```

默认本地 fallback（Mock KT、本地 RAG / Memory）可演示闭环；真实 Provider（DGEKT checkpoint、Mem0、VikingDB 等）须显式 opt-in，不可用时降级并在 Health / Trace 中标明。

---

## 思考链路（按需调用）

完整意图表、并行/串行约束、LangGraph 子图见 [重构思考/思考链路.md](./重构思考/思考链路.md)。

总体阶段：

```text
Observe -> Route -> Retrieve / Diagnose -> Assemble -> Decide -> Act -> Trace
```

意图与策略摘要：

| 意图 | 是否调 KT | 是否调 RAG | 是否写学习事实 |
|------|-----------|------------|----------------|
| 无关闲聊 | 否 | 否 | 否 |
| 泛化数学问题 | 否 | 可选 | 否 |
| 当前题卡住 | 通常否 | 可选 | 否 |
| 提交答案 | 否 | 否 | 是（仅作答 / 判题 / 进度） |
| 问下一步 / 点下一题 | 是 | 选题后可选 | 推进当前题时写 pending |
| 为何推荐 | 可选 | 通常否 | 否 |
| 学习复盘 | 可选 | 通常否 | 否 |

路由策略：

```text
规则判断明确事件（提交、下一题、卡住、为何推荐…）
LLM 判断模糊语义（只出结构化 intent，不直接写状态）
Policy guard 兜底（无作答事实不写状态、无推荐证据不编造个性化解释…）
```

一句话：

```text
用 DAG 管流程，用规则管安全，用 LLM 管模糊判断，用 TeachingTrace 管可解释性。
```

---

## 仓库结构（简）

```text
backend/          FastAPI + Runtime / KT / RAG / Memory / Planning / Storage
frontend/         React 学习驾驶舱（题目区 + Agent 侧栏）
data/             本地 demo 内容、mapping fixture、import 样例（大文件默认不提交）
docs/             历史 V1.x 架构与验收说明
重构思考/          当前产品与系统重构设计（总设计 + 思考链路）
scripts/          数据构建与仓库安全检查
```

实现细节与历史版本说明见 `docs/`；**产品与模块设计以 `重构思考/` 为准。**
