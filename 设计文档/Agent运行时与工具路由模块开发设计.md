# Agent 运行时与工具路由模块开发设计

> 状态：设计完成，待开发。

## 1. 文档说明

本文档设计 MathTutor 中 Agent 侧边栏一次聊天交互的运行过程。

本文重点回答：

```text
学生发送一条聊天消息后，由谁接收和完成这一轮处理。
七类聊天意图如何识别，当前题求助如何进一步选择回复策略。
Runtime 如何调用上下文、回复规划、回复生成、记忆观察和 TeachingTrace。
不同意图允许调用哪些工具，哪些调用必须禁止。
工具失败后如何降级，又不编造证据或修改正式学习状态。
一次聊天如何使用 conversation_id、turn_id 和 trace_id 串联起来。
```

本文不重新设计其他模块已经确定的业务规则。

以下内容分别以对应开发设计文档为权威来源：

```text
上下文选择、Token 预算和证据组装
  -> 上下文模块开发设计.md

正式提交、判题、作答证据和 KT 准入
  -> 判题与作答证据模块开发设计.md
  -> 学习事实与题目状态模块开发设计.md

掌握度、遗忘风险、目标题预测和 TeachingState
  -> 知识追踪模块开发设计.md

RAG 检索、引用和 Evidence Gap
  -> 知识RAG模块开发设计.md

对话记忆、长期画像读取和记忆后台提炼
  -> 记忆系统开发设计.md

练习路径、下一题和换题
  -> 练习路径与题目推荐模块开发设计.md

回复策略和最终自然语言生成
  -> 回复规划与生成模块开发设计.md

执行记录和审计模型
  -> TeachingTrace模块开发设计.md
```

---

## 2. 一句话定义

```text
Agent Runtime 是一次 Agent 聊天 Turn 的统一执行入口，
负责识别聊天意图、选择受控工作流、调用已有深模块、组织回复并记录执行过程。
```

它负责的是：

```text
这一轮 Agent 对话怎样运行。
```

它不负责的是：

```text
答案怎样判定。
掌握度怎样计算。
下一题怎样排序。
RAG 怎样检索。
长期记忆怎样提炼。
最终回复模板和语言风格怎样设计。
```

---

## 3. 已确定的设计决策

### 3.1 Runtime 只处理 Agent 聊天

Runtime 的正式入口只处理：

```text
ChatMessage
```

以下明确页面命令不进入 Agent Runtime：

```text
SubmitAnswerCommand：提交答案。
RevealAnswerCommand：查看答案。
RequestNextQuestionCommand：下一题。
ChangeQuestionCommand：换题。
```

这些命令分别进入判题、学习事实和推荐模块的独立应用流程。

Runtime 可以在后续聊天中读取这些流程已经保存的事实，但不能替代它们执行命令。

### 3.2 不使用 LangGraph

第一版不使用 LangGraph，也不建立通用图编排框架。

Runtime 使用普通 Python 实现固定的聊天工作流：

```text
路由
-> 策略检查
-> 构建上下文
-> 规划回复
-> 生成回复
-> 保存对话与记忆观察
-> 完成 Trace
```

需要并行读取的数据由对应深模块内部处理。例如 RAG、长期记忆和学习事实的并行读取属于上下文模块实现，不由 Runtime 展开成大量底层节点。

### 3.3 固定工作流，LLM 不自由调用工具

Runtime 不把所有工具交给 LLM 自由选择。

规则如下：

```text
规则确定明确意图。
LLM 只辅助分类模糊聊天。
ToolPolicy 根据最终意图确定允许调用的深模块。
TurnPlanBuilder 从固定模板生成本轮执行计划。
LLM 不能增加工具、扩大写入范围或修改执行顺序。
```

### 3.4 Runtime 不写正式学习状态

Agent 聊天允许写入：

```text
学生消息。
AI 完整回复。
当前 conversation 的短期记录。
MemoryObservation。
TeachingTrace。
```

Agent 聊天禁止写入：

```text
AnswerSubmission。
GradingResult。
EvidenceEligibility。
mastery。
KT / TeachingState。
current_question。
recommendation_history。
RecommendationFeedback。
正式长期记忆。
```

即使学生在聊天中说出答案、表示题目太难或声称自己已经掌握，也不能绕过正式页面命令修改这些状态。

### 3.5 Runtime 只调用其他模块的外部接口

Runtime 不直接访问：

```text
数据库表。
向量数据库。
HMS 内部记忆索引和关联结构。
SAFKT checkpoint。
题库内部 Repository。
Memory 内部候选和提炼任务。
```

Runtime 只依赖其他模块公开的深接口。

---

## 4. 模块边界

### 4.1 模块负责

```text
接收并验证 AgentTurnRequest。
生成 turn_id 和 trace_id。
识别七类聊天意图。
为 current_question_help 选择内部回复策略。
检查当前题、判题、推荐证据等前置条件。
根据意图选择固定 RuntimeWorkflow。
生成 ToolDecision 和 TurnPlan。
按计划调用上下文、回复、记忆和 Trace 接口。
汇总 Evidence Gap 和 ToolOutcome。
返回 AgentTurnResult。
```

### 4.2 模块不负责

```text
不接收页面提交答案命令。
不接收查看答案命令。
不执行下一题和换题。
不重新计算作答证据资格。
不消费 formal_answer_recorded。
不更新 mastery 或 TeachingState。
不直接调用推荐器修改当前题。
不直接查询 RAG、HMS 或数据库。
不直接生成正式长期记忆。
不保存或暴露模型内部思考过程。
```

### 4.3 删除测试

如果删除 Agent Runtime，七类聊天意图的路由、上下文调用、回复生成、对话保存、记忆观察和 Trace 串联逻辑会重新散落到多个 API 或调用方中。

因此 Runtime 的价值是集中一次聊天 Turn 的跨模块编排，而不是承载各模块内部业务实现。

---

## 5. 与页面命令流程的关系

MathTutor 有两类入口。

### 5.1 页面命令入口

```text
提交答案
-> 判题与作答证据模块
-> 学习事实模块
-> 符合资格时由 KT 消费正式事件

查看答案
-> 学习事实模块保存 AnswerRevealFact

下一题
-> 练习路径与题目推荐模块
-> 使用 TeachingState 和候选题 KT 分数选题
-> 更新 current_question

换题
-> 保存 RecommendationFeedback
-> 推荐模块重排或重选
-> 更新 current_question
```

### 5.2 Agent 聊天入口

```text
学生发送 ChatMessage
-> Agent Runtime
-> 读取页面命令已经产生的事实
-> 生成解释、提示、建议或复盘
-> 不反向修改正式事实
```

例如：

```text
学生在聊天里说“答案是不是 3/4？”
-> current_question_help / attempt_check
-> 作为草稿讨论
-> 不产生正式提交

学生点击提交后问“我为什么错？”
-> mistake_explanation
-> 读取已经保存的 Submission、GradingResult 和 TeachingState
-> 不重新判题

学生问“下一步练什么？”
-> next_step_advice
-> 只说明学习方向
-> 不调用推荐器，不修改 current_question
```

---

## 6. 核心身份字段

```text
student_id：学生编号。
session_id：一段连续学习过程编号。
conversation_id：一个 Agent 聊天窗口编号。
turn_id：一次学生消息和 AI 回复编号。
trace_id：本轮系统执行与审计编号。
```

关系：

```text
一个 student 可以有多个 session。
一个 session 可以有多个 conversation。
一个 conversation 可以有多个 turn。
一个 turn 对应一个 trace_id。
```

`conversation_id`不能用 `session_id`代替。学生新开聊天窗口时，只创建新的 conversation，不清空 KT、当前题、正式学习事实或长期画像。

---

## 7. 总体结构

```text
AgentTurnRequest
        ↓
AgentRuntime
    ├── IntentRouter
    ├── RuntimePolicy
    ├── TurnPlanBuilder
    ├── RuntimeToolRegistry
    ├── TurnRunner
    └── ResultAssembler
        ↓
深模块接口
    ├── LearningContextLayer
    ├── ResponsePlanner
    ├── ResponseGenerator
    ├── LearningMemorySystem
    ├── ConversationStore
    └── TeachingTraceRecorder
        ↓
AgentTurnResult
```

核心调用链：

```text
validate_request
-> route_intent
-> resolve_policy
-> build_turn_plan
-> build_context
-> plan_response
-> generate_response
-> persist_conversation
-> observe_memory
-> finalize_trace
-> return_result
```

---

## 8. 核心请求与返回模型

### 8.1 AgentTurnRequest

```python
class AgentTurnRequest(BaseModel):
    student_id: str
    session_id: str
    conversation_id: str
    message_id: str
    message: str
    client_context: dict[str, str] = Field(default_factory=dict)
```

约束：

```text
message_id 用于网络重试幂等。
client_context 只允许传页面位置和引用编号，不接受客户端声明 mastery 或判题结果。
当前题、正式提交和推荐依据必须从权威模块读取。
```

### 8.2 AgentTurnResult

```python
class AgentTurnResult(BaseModel):
    turn_id: str
    trace_id: str
    conversation_id: str
    intent: str
    help_strategy: str | None = None
    response: str
    status: Literal["completed", "degraded", "needs_clarification", "failed"]
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    tool_outcomes: list[ToolOutcome] = Field(default_factory=list)
```

返回结果不包含：

```text
模型内部思考过程。
Provider 原始响应。
Embedding。
密钥和认证信息。
未裁剪的学生隐私数据。
```

---

## 9. 聊天意图设计

### 9.1 七个主意图

```text
small_talk：闲聊。
concept_question：泛化数学概念问题。
current_question_help：当前题求助。
mistake_explanation：追问正式提交后的错因。
next_step_advice：询问下一步学习方向。
recommendation_reason：询问当前题为什么被推荐。
review_summary：学习复盘。
```

### 9.2 当前题求助内部策略

`current_question_help`继续细分回复策略：

```text
understand_problem：看不懂题意。
solution_approach：询问整体思路。
stuck_on_step：卡在某一步。
attempt_check：检查聊天草稿、步骤或答案猜测。
request_direct_answer：尚未查看答案时直接索要答案。
explain_revealed_answer：查看答案后的解析追问。
```

这些是回复策略，不是新的顶层 Runtime 意图。

### 9.3 路由顺序

```text
1. 明确规则。
2. LLM 结构化分类。
3. RuntimePolicy 前置条件检查。
4. 保守回退或追问。
```

明确规则示例：

```text
存在当前题，学生说“提示、不会、卡住、这一步”
-> current_question_help

存在最近正式判题，学生说“为什么错、错在哪里”
-> mistake_explanation

学生说“下一步学什么、最近该练什么”
-> next_step_advice

学生说“为什么推荐这道题”
-> recommendation_reason

学生说“总结、复盘、最近进步”
-> review_summary
```

### 9.4 LLM 分类输出

```python
class IntentResult(BaseModel):
    intent: RuntimeIntent
    help_strategy: CurrentQuestionHelpStrategy | None = None
    confidence: float
    source: Literal["rule", "llm", "fallback"]
    reason_code: str
    needs_clarification: bool = False
```

`reason_code`是可审计的稳定编码，不保存模型内部推理文本。

### 9.5 保守回退

无法确定时：

```text
有明确当前题引用
-> 回退 current_question_help，并只给轻量提示或追问。

没有当前题引用
-> 回退 concept_question。
```

回退不得调用推荐器、更新 KT、切题或生成正式判题结果。

---

## 10. Runtime Tool 的含义

Runtime Tool 不是 RAG、KT 或 Memory 的第二套实现。

它是其他深模块外部接口在 Runtime 中的受控调用描述。

例如：

```text
context.build
-> 调用 LearningContextLayer.build(...)

response.plan
-> 调用 ResponsePlanner.plan(...)

response.generate
-> 调用 ResponseGenerator.generate(...)

memory.observe
-> 调用 LearningMemorySystem.observe(...)
```

RAG、LearningMemoryReader、LearningFactReader 和 TeachingStateReader 是上下文模块内部的数据源 Adapter。Runtime 不绕过 `LearningContextLayer` 再次调用这些底层接口。

### 10.1 第一版 Runtime Tool

```text
context.build
response.plan
response.generate
conversation.append_turn
memory.observe
trace.record
```

`context.build`返回的上下文审计中可以包含底层数据源调用结果，例如：

```text
TeachingState 是否读取成功。
RAG 是否命中。
HMS 是否超时、熔断或使用召回缓存。
哪些学习事实被选入。
哪些证据因预算被省略。
```

这些是一次真实上下文构建产生的 Observation，不允许 Runtime 为了展示工具状态重新检索第二次。

### 10.2 RuntimeToolSpec

```python
class RuntimeToolSpec(BaseModel):
    tool_id: str
    purpose: str
    input_schema: str
    output_schema: str
    allowed_intents: set[RuntimeIntent]
    access_mode: Literal["read", "decision", "write"]
    required: bool
    timeout_ms: int
    failure_policy: Literal["stop", "degrade", "retry_async"]
    state_write_scopes: set[str] = Field(default_factory=set)
    trace_visibility: Literal["expert", "debug"] = "expert"
```

工具描述只保存稳定元数据，不保存 Provider 密钥、模型路径或数据库连接信息。

---

## 11. ToolPolicy

### 11.1 决策结果

每个 Runtime Tool 在本轮得到一个明确状态：

```text
required：本轮必须执行，失败时本轮不能正常完成。
optional：有条件执行，失败后可以降级。
skipped：本轮不需要。
blocked：当前意图禁止调用。
```

```python
class ToolDecision(BaseModel):
    tool_id: str
    status: Literal["required", "optional", "skipped", "blocked"]
    reason_code: str
    reason: str
    allowed_write_scopes: set[str] = Field(default_factory=set)
```

### 11.2 写入范围

Runtime 只认识以下写入范围：

```text
conversation_turn
memory_observation
teaching_trace
```

以下范围对所有聊天意图永久 blocked：

```text
learning_fact
grading_result
kt_state
mastery
question_state
recommendation_record
long_term_memory
```

### 11.3 七类意图的工具策略

| 意图 | Context | Response Plan | Response Generate | Conversation | Memory Observation | Trace |
|---|---|---|---|---|---|---|
| `small_talk` | required，最小对话上下文 | required | required | required | optional | required |
| `concept_question` | required | required | required | required | optional | required |
| `current_question_help` | required | required | required | required | optional | required |
| `mistake_explanation` | required | required | required | required | optional | required |
| `next_step_advice` | required | required | required | required | optional | required |
| `recommendation_reason` | required | required | required | required | optional | required |
| `review_summary` | required | required | required | required | optional | required |

差异不在于是否绕过上下文模块，而在于 `ContextPolicy`选择哪些数据源。

### 11.4 永久禁止规则

```text
聊天中出现一个答案，不挂载正式提交工具。
聊天中说“下一题”，不调用 Recommender，不修改 current_question。
聊天中说“换一道”，不执行页面换题命令，引导学生使用换题入口。
聊天中说“太简单”，不修改 mastery。
聊天中要求直接看答案，answer_revealed=false 时不返回标准答案或完整解析。
推荐原因只读取保存的推荐证据，不重新推荐。
错因解释只读取正式判题，不重新判题。
```

---

## 12. TurnPlan

第一版不设计任意 DAG，只使用固定顺序和少量条件步骤。

```python
class TurnStep(BaseModel):
    step_id: str
    tool_id: str
    required: bool
    run_if: str | None = None
    failure_policy: Literal["stop", "degrade", "retry_async"]


class TurnPlan(BaseModel):
    turn_id: str
    intent_result: IntentResult
    tool_decisions: list[ToolDecision]
    steps: list[TurnStep]
    allowed_write_scopes: set[str]
```

标准计划：

```text
context.build
-> response.plan
-> response.generate
-> conversation.append_turn
-> memory.observe（可选）
-> trace.record
```

其中：

```text
response.plan 必须等待 context.build。
response.generate 必须等 response.plan。
conversation.append_turn 必须拿到最终学生消息和 AI 回复。
memory.observe 只能接收已经裁剪的记忆观察，不能直接写长期记忆。
最终 Trace 必须记录实际执行结果，而不是计划中的预期结果。
```

---

## 13. 七类聊天工作流

### 13.1 small_talk

```text
读取当前 conversation 的短对话。
不读取 TeachingState、学习事实、RAG 或长期画像。
生成轻量回复。
保存对话和 Trace。
```

### 13.2 concept_question

```text
按 ContextPolicy 组装概念问题上下文。
按需读取 RAG。
一般不读取 TeachingState 和长期画像。
生成概念解释。
没有可靠资料时明确使用通用解释，不伪造 citation。
```

### 13.3 current_question_help

```text
读取 current_question 和当前题状态。
读取当前 conversation 短现场。
按需读取 TeachingState、题目解析和长期画像。
根据 help_strategy 规划回复。
不更新 KT，不切题，不正式提交答案。
```

显示答案约束：

```text
answer_revealed=false 且 help_strategy=request_direct_answer
-> 不提供标准答案或完整解析。
-> 引导学生使用页面“查看答案”。

answer_revealed=true 且 help_strategy=explain_revealed_answer
-> 可以围绕已经展示的答案解释。
```

### 13.4 mistake_explanation

```text
读取最近相关 AnswerSubmission。
读取 GradingResult、AnswerEvidence 和最新 TeachingState。
按需读取题目解析、错因资料和长期画像。
生成错因解释。
不重新判题，不重新更新 KT。
```

缺少正式判题时：

```text
不能编造个性化错因。
回退为草稿检查或通用检查建议。
```

### 13.5 next_step_advice

```text
读取最新 TeachingState。
读取近期正式作答和当前 conversation。
按需读取长期画像。
生成下一步学习方向建议。
```

禁止：

```text
不读取候选题池。
不调用 PracticePathPlanner。
不调用 Recommender。
不修改 current_question。
不保存 recommendation_history。
```

### 13.6 recommendation_reason

```text
读取 current_question。
读取当时保存的推荐依据和 TeachingState 引用。
按需读取相关近期作答和长期画像。
解释当时为什么选择这道题。
```

缺少推荐依据时：

```text
明确说明当前没有完整推荐记录。
不得重新推荐后再把新结果伪装成当时依据。
```

### 13.7 review_summary

```text
读取最新 TeachingState。
读取指定时间范围内的正式学习事实。
读取当前 conversation 和 Trace 摘要。
按需读取长期画像。
生成学习复盘。
```

复盘只总结已有事实，不因为生成了一次总结而更新 mastery 或长期画像。

---

## 14. TurnRunner

### 14.1 执行原则

```text
计划先确定，工具后执行。
必需步骤失败时停止依赖它的后续步骤。
可选证据失败时带 Evidence Gap 继续。
所有写入都检查 allowed_write_scopes。
实际 ToolOutcome 进入 Trace。
```

### 14.2 ToolOutcome

```python
class ToolOutcome(BaseModel):
    tool_id: str
    status: Literal[
        "healthy",
        "degraded",
        "unavailable",
        "not_configured",
        "empty_result",
        "invalid_input",
        "blocked_by_policy",
        "timeout",
    ]
    result_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    fallback_used: bool = False
    actual_write_scopes: set[str] = Field(default_factory=set)
```

Runtime 对工具结果只保留安全摘要和引用，不复制完整 Provider 原始响应。

### 14.3 幂等

相同 `message_id + conversation_id`的网络重放：

```text
不创建第二个 Turn。
不重复保存 conversation_turn。
不重复创建 MemoryObservation。
返回第一次成功处理的 AgentTurnResult。
```

聊天幂等只保护聊天记录，不替代正式提交的 `submission_id`幂等。

---

## 15. 失败与降级

### 15.1 意图分类失败

```text
规则无法识别且 LLM 分类失败
-> 根据是否存在当前题回退 current_question_help 或 concept_question
-> status=degraded
-> 不调用任何写正式状态的能力
```

### 15.2 当前题缺失

```text
current_question_help 但没有 current_question
-> 不查询其他题目的解析
-> 请学生先进入题目，或把完整题目发到聊天中
```

### 15.3 正式判题缺失

```text
mistake_explanation 但没有 GradingResult
-> 不生成确定性错因结论
-> 回退为草稿检查或通用检查步骤
```

### 15.4 推荐证据缺失

```text
recommendation_reason 但没有保存的推荐依据
-> 明确记录 missing_recommendation_evidence
-> 不重新推荐并伪装为历史原因
```

### 15.5 RAG 或长期记忆不可用

```text
RAG 不可用
-> 可以使用模型基础数学能力做保守解释
-> 不生成虚假 citation

长期记忆不可用
-> 使用默认讲解策略
-> 不影响正式学习事实和 KT
```

### 15.6 回复生成失败

```text
ResponseGenerator 失败
-> 使用与意图匹配的最小安全回复
-> 保留 Context 和 Evidence Gap 引用
-> status=degraded
```

最小安全回复不得包含未经验证的答案、错因或推荐理由。

### 15.7 对话保存失败

```text
生成回复成功但 conversation.append_turn 失败
-> 返回 degraded
-> 记录可重试写入任务
-> 不把未保存对话当成后续短期记忆
```

### 15.8 Trace 失败

Trace 失败不能导致已经生成的学生回复被改写，也不能影响正式学习事实。

Runtime 返回：

```text
status=degraded
trace_status=failed
```

---

## 16. TeachingTrace 契约

Runtime 至少向 TeachingTrace 提交：

```text
turn_id、conversation_id 和 trace_id。
最终聊天意图和内部 help_strategy。
意图来源、置信度和 reason_code。
ToolDecision。
TurnPlan。
每个 ToolOutcome。
上下文引用和 Evidence Gap。
回复规划结果引用。
最终回复引用。
实际写入范围。
整体完成、降级或失败状态。
```

禁止记录：

```text
模型内部思考过程。
完整 Provider 原始响应。
密钥、Token 和认证头。
Embedding 和向量。
私有 checkpoint 路径。
未经裁剪的学生隐私数据。
```

TeachingTrace 负责保存和展示这些记录；Runtime 只负责在正确阶段产生记录内容。

---

## 17. Runtime 外部接口

```python
class AgentRuntime:
    def handle_chat(self, request: AgentTurnRequest) -> AgentTurnResult:
        """完成一次 Agent 聊天 Turn。"""
```

Runtime 对调用方只暴露一个主要入口。

内部依赖：

```python
class IntentRouter:
    def route(self, request: AgentTurnRequest, routing_facts: RoutingFacts) -> IntentResult:
        ...


class RuntimePolicy:
    def resolve(self, intent: IntentResult) -> list[ToolDecision]:
        ...


class TurnPlanBuilder:
    def build(
        self,
        request: AgentTurnRequest,
        intent: IntentResult,
        decisions: list[ToolDecision],
    ) -> TurnPlan:
        ...


class TurnRunner:
    def run(self, request: AgentTurnRequest, plan: TurnPlan) -> AgentTurnResult:
        ...
```

调用方不直接操作 `RuntimeToolRegistry`或逐个执行 TurnStep。

---

## 18. 与其他模块的契约

### 18.1 与上下文模块

Runtime 传入：

```text
student_id
session_id
conversation_id
turn_id
intent
help_strategy
message
```

Runtime 只消费上下文模块返回的：

```text
ResponseContextPackage
evidence_refs
evidence_gaps
context_governance_summary
```

Runtime 不接收原始 RAG、Memory 或数据库记录。

### 18.2 与回复规划模块

回复规划模块只接收：

```text
intent
help_strategy
ResponseContextPackage
```

它不能扩大 Runtime 已经确定的工具权限和写入范围。

### 18.3 与回复生成模块

回复生成模块只根据回复计划和回答上下文生成学生可见文本。

它不能：

```text
重新路由意图。
重新调用底层工具。
修改正式学习事实。
绕过 answer_revealed 状态输出标准答案。
```

### 18.4 与记忆模块

Runtime 使用：

```text
LearningMemorySystem.observe(...)
```

只提交经过裁剪的 `MemoryObservation`。正式长期记忆由记忆模块后台提炼，不在聊天请求内同步生成。

### 18.5 与 TeachingTrace

Runtime 负责产生执行事件，TeachingTrace 模块负责存储、查询、展示和隐私裁剪。

---

## 19. 建议目录

```text
backend/app/agent_runtime/
  runtime.py
  models.py
  intent_router.py
  policy.py
  plan.py
  runner.py
  tool_registry.py
  fallbacks.py
```

模块职责：

```text
runtime.py：唯一对外入口。
models.py：请求、意图、计划和结果模型。
intent_router.py：规则和可选 LLM 分类。
policy.py：工具权限和写入范围。
plan.py：固定 TurnPlan 模板。
runner.py：执行计划并汇总结果。
tool_registry.py：深模块接口注册。
fallbacks.py：最小安全回复和降级策略。
```

实际开发时目录可以跟随项目统一命名调整，但模块边界不能重新合并进判题、KT 或推荐实现。

---

## 20. 分阶段开发计划

### Phase 1：建立聊天入口和身份契约

```text
实现 AgentTurnRequest 和 AgentTurnResult。
建立 conversation_id、turn_id、trace_id。
实现 message_id 幂等。
明确页面命令不进入 Agent Runtime。
```

### Phase 2：七类意图和策略检查

```text
实现规则路由。
实现 current_question_help 内部策略。
实现 RuntimePolicy 和永久禁止规则。
先不接入 LLM 分类。
```

### Phase 3：接入上下文深模块

```text
Runtime 只调用 LearningContextLayer.build。
不同意图使用对应 ContextPolicy。
透传 Evidence Gap 和治理摘要。
禁止 Runtime 直接查 RAG、Memory 和数据库。
```

### Phase 4：接入回复规划与生成

```text
实现固定 TurnPlan。
接入 ResponsePlanner。
接入 ResponseGenerator。
补齐答案展示保护和最小安全回复。
```

### Phase 5：对话、记忆观察和 Trace

```text
原子或可恢复地保存一轮完整对话。
提交 MemoryObservation。
完成 ToolOutcome 和 Trace 记录。
实现失败重试与降级状态。
```

### Phase 6：可选 LLM 意图分类

```text
只处理规则无法确定的聊天。
使用结构化输出。
Policy 继续作为最终权限检查。
评测误路由率和工具误调用率。
```

---

## 21. 测试设计

### 21.1 路由测试

```text
七个主意图能够正确区分。
当前题求助能够选择正确内部策略。
聊天中的答案不会形成正式提交。
“下一步练什么”不会变成下一题命令。
“为什么推荐”不会重新执行推荐。
低置信度能够保守回退。
```

### 21.2 权限测试

```text
所有聊天意图都不能写 mastery。
所有聊天意图都不能写 current_question。
所有聊天意图都不能写正式长期记忆。
attempt_check 不调用正式判题提交接口。
next_step_advice 不调用 Recommender。
recommendation_reason 只读取历史推荐依据。
```

### 21.3 工作流测试

```text
上下文完成后才能规划回复。
回复计划完成后才能生成回复。
保存完整对话后才能把它作为后续短期记忆。
Trace 记录实际 ToolOutcome。
同一 message_id 重放不会产生第二个 Turn。
```

### 21.4 失败测试

```text
RAG 为空时不伪造引用。
HMS 不可用且没有有效缓存时使用默认讲解策略。
缺少当前题时不查询其他题目的解析。
缺少判题结果时不编造错因。
缺少推荐依据时不编造个性化推荐理由。
ResponseGenerator 失败时返回最小安全回复。
对话或 Trace 保存失败时返回明确降级状态。
```

### 21.5 最终状态测试

不仅检查回复文字，还要检查最终状态：

```text
概念提问后 mastery 不变。
当前题求助后 current_question 不变。
聊天答案讨论后没有新增 AnswerSubmission。
下一步建议后没有新增 recommendation_history。
推荐原因解释后没有重新推荐。
复盘后 KT state version 不变。
每轮成功聊天只新增一条完整 conversation turn 和对应 Trace。
```

---

## 22. 验收标准

第一版完成标准：

```text
存在唯一 handle_chat 入口。
页面命令与 Agent 聊天入口完全分离。
七类聊天意图和当前题求助内部策略可测试。
Runtime 只调用其他模块的外部深接口。
ToolPolicy 能阻止正式学习状态写入。
不同意图不会误调用推荐、判题提交或 KT 更新能力。
上下文、回复、对话、记忆观察和 Trace 可以串成完整 Turn。
可选证据失败时可以安全降级。
所有工具调用和证据引用可追溯。
不记录模型内部思考和敏感 Provider 数据。
```

关键指标：

```text
聊天意图准确率。
当前题求助策略准确率。
禁止工具误调用率，目标为 0。
正式学习状态误写率，目标为 0。
虚假引用率，目标为 0。
重复 Turn 写入率，目标为 0。
Trace 完整率。
降级回复成功率。
```

---

## 23. 最终结论

Agent Runtime 不再重复设计判题、KT、推荐、上下文、RAG、记忆和回复模块。

它只负责把这些已经定义好的深模块组织成一次受控的 Agent 聊天 Turn：

```text
识别学生在问什么；
按照确定策略构建需要的上下文；
调用回复规划和生成；
保存完整对话和记忆观察；
记录工具、证据、降级和边界；
始终阻止聊天越权修改正式学习状态。
```

一句话总结：

```text
页面命令各走自己的业务流程，Agent Runtime 只把一轮聊天安全地跑完整。
```
