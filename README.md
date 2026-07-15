# MathTutor Agent

面向个人数学学习场景的教学 Agent：以**当前题目**为主界面，以侧边 Agent 为辅导层，用可审计的工具链路完成诊断、推荐与讲解。

```text
一句话定位：
题目是主界面，Agent 是侧边辅导层，下一题按钮是明确的学习推进动作。
```

详细设计见 [`重构思考/`](./重构思考/)：

| 文档 | 内容 |
|------|------|
| [系统总设计.md](./重构思考/系统总设计.md) | 页面模块、状态同步、产品边界 |
| [思考链路.md](./重构思考/思考链路.md) | 意图路由、按需工具调用、DAG / Trace |
| [记忆模块.md](./重构思考/记忆模块.md) | 学生记忆模型、读写边界、与 RAG/KT 分工 |
| [RAG模块.md](./重构思考/RAG模块.md) | RAG 目标态：XES3G5M 语料、检索、编排与验收 |
| [简历修改版_MathTutor_Agent.md](./重构思考/简历修改版_MathTutor_Agent.md) | 各模块技术设计口径与亮点拆解 |

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

- 生成式 Agent 容易脱离学生真实掌握状态，把检索文本或模型输出误写成「已学会」。
- 每次对话全量调用 RAG / KT，造成上下文污染、成本高、不可解释。
- 提交答案、推荐下一题、对话答疑职责混在一起，状态写入不可控。
- 外部 Provider 不稳定时难以本地演示与安全降级。

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

主心智模型是「**当前题目 + 侧边 Agent 辅导**」，不是纯聊天页。三个产品模块共享同一份学习事实状态，但**写入路径严格分离**。

### 1. 当前题目区 —— 怎么设计

**设计目标：** 做题与保存作答是主路径；不要把「提交答案」做成一次 Agent 对话。

**界面职责：** 题干、答案输入、提交按钮、当前题状态、可选的一句简短推荐说明。

**链路设计：**

```text
写答案 -> 点击提交
-> 加载 pending / current question
-> 保存作答事件（可幂等：同题同答不重复写事实）
-> 可选服务端确定性判题（有标准答案才判）
-> 持久化进度快照
-> 更新页面当前题状态
-> 不触发 Agent、不查 RAG / Memory、不自动推荐下一题
```

**设计理由：**

- 提交答案是**状态保存流程**，不是教学决策流程；后续学生问「为什么错 / 下一步练什么」再由新 intent 触发 Agent。
- 判题放在服务端确定性逻辑，不依赖 LLM 记答案，保证演示与回归可复现。
- 与 Agent 对话解耦后，重复提交、无标准答案等边界可以单独做幂等与降级，而不污染对话状态。

### 2. 左侧 Agent 对话 —— 怎么设计

**设计目标：** Agent 是辅导层，只在问题需要时取证；Memory 是内部画像，不向用户开放 CRUD。

**能力范围：** 当前题提示、错因解释、为何推荐、下一步建议、概念讲解、学习复盘；支持多会话切换，但始终可引用**全局学习事实**。

**按场景挂载工具（条件调度，而非每轮全量）：**

| 场景 | 设计策略 | 典型工具 |
|------|----------|----------|
| 当前题卡住 / 要提示 | 读任务状态 + 讲解证据，通常不写 mastery | task_state、可选 RAG / Memory |
| 为什么推荐这题 | 解释「当时为何选它」，一般不重新推荐 | recommendation_evidence、可选 KT / Memory |
| 下一步练什么 | 必须先有诊断，再推荐 | KT、题库、历史、Recommender；选题后再可选 RAG |
| 泛化概念 | 不绑定当前作答事实 | 可选 RAG |
| 闲聊 | 零重工具，必要时拉回学习任务 | 无 |
| 学习复盘 | 汇总进度与轨迹，按需诊断 | progress、events、trace、可选 KT / Memory |

**设计理由：**

- 避免「所有请求同一工具集合」带来的无关诊断和上下文污染。
- 明确事件（提交、下一题、卡住、为何推荐）用规则路由；模糊语义才用 LLM 输出结构化 intent，且 **LLM 不直接写状态**。
- Policy guard 兜底：无作答事实不写学习状态、无推荐证据不编造个性化理由、置信度低则追问而非调重工具。

### 3. 下一题按钮 —— 怎么设计

**设计目标：** 「推进当前题」是显式系统动作，不是聊天里的自然语言猜测。

**链路设计：**

```text
点击下一题
-> 并行：KT 诊断 / Memory / 题库 / 近期历史
-> Recommender 排序选题
-> 保存 current / pending question 与推荐证据
-> 生成题目区一句短推荐原因
-> 页面跳到下一题 + 记 state trace
```

**设计理由：**

- 按钮意图确定，无需 LLM 做 intent 分类，减少误路由。
- 推荐证据与当前题一并落库，Agent 后续解释「为什么推荐」时可复用，不必重新猜。
- 短推荐原因放在题目区，完整解释留给侧边 Agent，避免主界面信息过载。

### 状态分层设计

```text
学习事实状态：题目、答案、判题、进度、当前题 —— 全局共享，严格写入权限
对话状态：某次 Agent 会话里问过什么 —— 属 conversation，可引用事实
内部画像状态：偏好、错因、有效策略 —— 系统维护，用户不可直接操作
```

```text
题目区负责做题与保存作答；
下一题按钮负责推进当前题；
Agent 侧边栏负责解释、答疑、复盘与学习建议。
```

---

## 系统模块设计

架构核心不是「让大模型直接解题」，而是把系统拆成**带权限边界的模块**：KT 生产学习事实，RAG 提供教学证据，Memory 提供个性化策略，Runtime 按需编排，Context Governance 控制哪些信息能进入回复。

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

### 0. 事实平面 vs 教学平面 —— 怎么设计

**设计目标：** 解决传统 Agent 把检索文本、历史偏好或模型输出直接写回业务状态导致的**事实漂移**。

| 平面 | 组成 | 职责 | 写学习事实？ |
|------|------|------|--------------|
| **事实平面** | 确定性判题、Progress Store、KT / DGEKT | 生产并写入 mastery、weak concepts、prediction、forgetting risk 等 | **唯一可写** |
| **教学平面** | RAG、Memory、Planner、Response | 只读事实，调整讲解、提示与练习策略 | **只读** |

**关键机制：**

- `state_write_policy`：工具契约声明本工具是否允许写状态。
- Authority boundary：跨层访问由只读 Tool Observation 与契约测试约束。
- Runtime / Context Governance / RAG / Memory / Provider Health **均无改写学习事实的权限**。

---

### 1. Agent Runtime —— 怎么设计

**设计目标：** 状态机式、事件驱动的单轮编排；按 intent **条件挂载工具**，而不是固定流水线。

**核心对象：**

- `MathTutorAgentRuntime`：编排入口。
- `LearningTurnContext`：单轮状态载体（student、session、intent、learning event、KT progress、context refs、trace refs）。
- **Capability Registry**：把 `answer_submission`、`next_step_advice`、`general_chat` 等映射到诊断 / 规划 / 讲解能力。
- **Tool Registry**：把 KT、RAG、Memory 封装为带输入输出约束、前置条件、provider mode、失败语义、`state_write_policy` 的工具契约。

**调度设计：**

```text
Observe -> Route -> Retrieve / Diagnose -> Assemble -> Decide -> Act -> Trace
```

基于 intent、当前题、证据可用性、provider readiness 输出 **mounted / skipped / blocked**，避免无关诊断。

**与终局方向的关系：** 当前是可审计的 Runtime + 条件工具；后续可演进为 DAG / LangGraph 动态图（并行检索、checkpoint、Human-in-the-loop），见 `重构思考/思考链路.md`。

---

### 2. KT / DGEKT（知识追踪）—— 怎么设计

**设计目标：** 学习事实的**权威层**。只有判题 + Progress Store + KT 引擎可以写入掌握相关状态。

**职责：**

- 将作答历史归纳为掌握度、遗忘风险、预测风险、薄弱知识点、错因与复习线索。
- 输出供推荐与诊断使用的结构化 facts，而不是自由文本结论。

**当前与后续：**

| 层次 | 设计 |
|------|------|
| **当前** | `MockKTStateEngine` 本地可跑；`DGEKTStateEngine` 适配器显式 opt-in（checkpoint / 数据 / KC routes） |
| **后续** | 以 DGEKT 为底座融合题干语义、知识点图、难度特征的 SAFKT；输出带 model version、confidence、attribution、calibration 的 `TeachingState` |

**边界：** RAG、Memory、Context Governance、LLM **只能读** KT facts，不能覆盖 mastery 或 prediction。Offline attribution 只解释预测，不覆盖预测事实。

---

### 3. RAG（教学证据）—— 怎么设计

**设计目标：** **题目对齐**的检索，而不是泛化相似文本硬塞进回答；负责「怎样解释更有依据」，不负责「学生是否已学会」。

完整目标态见 **[重构思考/RAG模块.md](./重构思考/RAG模块.md)**（数据底座 **XES3G5M**）。

**资源组织：**

- 以 XES3G5M 的 `question_id` / KC（`concept_id` / `kc_routes`）对齐，不与旧题库题号混用。
- 文档类型：concept note、question explanation、mistake pattern、learning strategy。
- 携带 coverage、provenance 等元数据。

**检索与缺口治理：**

- 检索与组装阶段校验题目、知识点、citation、内容可用性。
- 空检索、映射缺失、内容缺失、低置信度、上下文超限 → 统一生成 **`evidence_gap`**，显式降级，**禁止伪造 citation**。
- 推荐链路中，RAG 可放在**选题之后**，只查选中题解释，减少串题。

**当前与后续：**

| 层次 | 设计 |
|------|------|
| **当前** | 本地教学 RAG + 可选 VikingDB / OpenViking adapter（demo / 既有 fixture 路径） |
| **目标态** | XES3G5M 语料 + Hybrid（BM25 + dense + metadata filter） |
| **终局** | Hybrid GraphRAG：稠密 + 关键词 + 教学知识图谱，RRF 融合、重排、多跳扩展 |

---

### 4. Memory（学生记忆）—— 怎么设计

**设计目标：** 跨会话个性化**只影响策略，不改写能力**；用户不直接操作记忆。

**记忆模型（四类）：**

```text
学习偏好 · 重复错因 · 有效教学策略 · 学习反思
```

每条记录来源、evidence、provenance、freshness、启用状态与 tombstone。

**生命周期：**

| 状态 | 运行时行为 |
|------|------------|
| enabled | 可进入检索与个性化组装 |
| disabled | 转为专家可见的 omitted evidence，不进学生可见回复 |
| deleted | 从检索、assembled context、response package **彻底排除** |

**召回设计：** 按 student / session / question / concept / freshness / confidence 过滤排序；本地 store + opt-in Mem0 Adapter。

**边界：** Memory 可调提示颗粒度、讲解风格、复习节奏；**禁止**写入 mastery、weak concepts、prediction probability。

---

### 5. Context Governance（Evidence Firewall）—— 怎么设计

**设计目标：** 教学 Agent 的证据防火墙——控制「什么能进最终回复」，而不是再发明一套事实。

**资产建模：** 将 KT facts、当前任务与作答、RAG 引用、Memory、工具 observation、Trace 快照统一为 **context assets**（`LearningContextLayer`）。

**优先级与预算：**

```text
KT / DGEKT facts > 当前任务 > 工具快照 > 相关 Memory / RAG
```

- 执行 token budget、裁剪与脱敏。
- 记录 **selected / clipped / omitted** 及原因，可审计。
- 对回复层只暴露 **selected-only `ResponseContextPackage`**。

**隔离内容：** raw provider payload、SDK response、embedding、密钥、私有路径、低置信度与过期记忆。

**边界：** Governance 只能编排与审计，**不能改写** KT / RAG / Memory 的原始状态。

---

### 6. Recommender / Planner —— 怎么设计

**设计目标：** 可解释的风险优先推荐 + 教学动作规划，并与判题、KT、Trace 绑定在同一闭环。

**推荐打分因子（`score_factors`）：**

```text
弱知识点匹配 · 遗忘风险 · 预测风险 · 难度适配
· 近期重复度 · 学习偏好 · canonical mapping 完整度
```

**输出：** 排序候选 + 中文 reason + 可追溯证据；同步写入 TeachingTrace（判题、KT diagnosis、错因、RAG citation、memory recall、planner decision）。

**Planner 动作类型（概念上）：** 提示、分步讲解、补概念、巩固练习、复盘等；决策依赖治理后的 context package，而不是 raw 全量日志。

**可追溯性：** 一条推荐应能回溯到「哪次作答、哪项风险、哪条资源」。

---

### 7. TeachingTrace —— 怎么设计

**设计目标：** 把每轮从意图到决策变成**可观察、可解释**的记录，而不是黑盒聊天日志。

**建议记录维度（每个工具 / 阶段）：**

```text
为什么调用 · 输入摘要 · 输出摘要 · 是否成功
· 是否降级 / fallback · 是否写状态 · 证据边界
· 结果如何影响下一步
```

**呈现分层：** 学生可读主流程 + 专家证据层（KT / RAG / memory / recommendation / governance）。

---

### 8. Provider Health / Fallback —— 怎么设计

**设计目标：** 默认本地可演示；真实外部依赖显式 opt-in；失败可归一、可脱敏、可回归。

**分层运行模型：**

```text
local fallback  →  fake provider（测试）  →  live provider（显式配置）
```

**状态归一：** configuration missing、timeout、auth error、empty result、schema mismatch、budget exceeded 等统一为安全 gap 摘要。

**脱敏：** credentials、raw payload、SDK response、checkpoint 路径、embedding / vector index、私有路径递归清洗。

**门禁思路：** default fallback、facts boundary、memory control、RAG citation、runtime / dashboard 等回归作为发布约束；「能跑」≠「内部试用 ready」（Readiness Gate 另计）。

---

## 思考链路（编排层摘要）

完整意图表、并行/串行约束、LangGraph 子图见 [重构思考/思考链路.md](./重构思考/思考链路.md)。

| 意图 | KT | RAG | 写学习事实 |
|------|----|-----|------------|
| 无关闲聊 | 否 | 否 | 否 |
| 泛化数学问题 | 否 | 可选 | 否 |
| 当前题卡住 | 通常否 | 可选 | 否 |
| 提交答案 | 否 | 否 | 是（仅作答 / 判题 / 进度） |
| 问下一步 / 点下一题 | 是 | 选题后可选 | 推进当前题时写 pending |
| 为何推荐 | 可选 | 通常否 | 否 |
| 学习复盘 | 可选 | 通常否 | 否 |

```text
规则判断明确事件；LLM 判断模糊语义；Policy guard 防止错误写状态。
用 DAG 管流程，用规则管安全，用 LLM 管模糊判断，用 TeachingTrace 管可解释性。
```

---

## 仓库结构（简）

```text
backend/          FastAPI + Runtime / KT / RAG / Memory / Planning / Storage
frontend/         React 学习驾驶舱（题目区 + Agent 侧栏）
data/             本地 demo 内容、mapping fixture、import 样例
docs/             历史 V1.x 架构与验收说明
重构思考/          产品总设计 + 思考链路 + 技术亮点口径
scripts/          数据构建与仓库安全检查
```

实现细节与历史版本说明见 `docs/`；**产品与模块设计以 `重构思考/` 与本 README 为准。**
