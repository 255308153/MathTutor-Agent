# MathTutor Agent 开发文档

本文档是后续 agent 和开发者的本地开发入口。默认语言为中文；用户可见文案也应优先中文。

## 1. 环境准备

要求：

- Python 3.11+
- pip
- 可选：Node.js 20+，用于后续 React 学习驾驶舱

初始化：

```bash
cd /Users/lqc/Downloads/MathTutor-Agent
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

如果只想快速验证当前代码能否导入，也可以先运行：

```bash
python -m compileall backend/app
```

## 2. 启动后端

本地启动：

```bash
uvicorn backend.app.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

预期输出：

```json
{"status":"ok"}
```

如果使用 `cd backend && uvicorn app.main:app --reload` 也可以启动；仓库根目录启动时优先使用 `backend.app.main:app`。

## 3. 测试命令

常用检查：

```bash
python -m compileall backend/app
pytest
ruff check .
```

开发节奏：

- 小改动先运行相关单测。
- 改动核心主循环、schema、KT、RAG、memory 或 API 后运行 `pytest`。
- 每个 issue 收口前至少运行 Python 编译检查和相关测试。
- 新功能必须补可验证测试，除非 issue 明确只改文档。

## 4. 统一事件 API

V1 后端通过统一事件入口接收聊天消息和学习事件：

```bash
curl -X POST http://127.0.0.1:8000/api/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "s001",
    "student_id": "u001",
    "type": "chat_message",
    "message": "我下一步应该学什么？",
    "payload": {}
  }'
```

答题提交示例：

```bash
curl -X POST http://127.0.0.1:8000/api/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "s001",
    "student_id": "u001",
    "type": "answer_submitted",
    "message": "我选 B",
    "payload": {
      "question_id": "q_frac_001",
      "answer": "B",
      "time_spent": 73
    }
  }'
```

响应包含：

```json
{
  "response": "学生可读中文回复",
  "state_summary": {
    "session_id": "s001",
    "student_id": "u001",
    "intent": "next_step_advice",
    "progress_version": 1,
    "weak_concepts": [],
    "forgetting_risks": [],
    "next_action": {
      "type": "recommend_next_question",
      "label": "根据薄弱知识点推荐下一步练习"
    },
    "errors": []
  },
  "recommended_questions": [],
  "teaching_trace": [
    {"type": "observation", "stage": "load_context"},
    {"type": "observation", "stage": "diagnose"},
    {"type": "observation", "stage": "plan"},
    {"type": "observation", "stage": "generate_response"}
  ]
}
```

当前推荐来自本地 demo 内容集，答题提交由服务端根据标准答案确定性判题；#5 会进一步接入风险优先排序理由。

## 5. 风险优先推荐

下一步学习建议由确定性推荐器完成，入口在：

```text
backend/app/planning/recommender.py
```

推荐结果包含：

- `question_id`：题目 ID。
- `stem_summary` / `stem`：题干摘要和完整题干。
- `concept`：知识点 ID、中文名和教学类型。
- `difficulty`：题目难度。
- `score`：最终排序分。
- `score_factors`：五类可解释分数因子。
- `reason`：中文推荐理由。

当前五类分数因子：

| 因子 | 作用 | 边界 |
| --- | --- | --- |
| `weak_concept_match` | 优先匹配 KT 诊断出的薄弱知识点。 | 来自 KT diagnosis，推荐器只读取，不改写。 |
| `difficulty_fit` | 选择与当前 mastery 接近、略有挑战的题。 | 使用题目 `difficulty` 和 KT mastery 计算。 |
| `forgetting_urgency` | 遗忘风险越高越优先复习。 | 来自 KT forgetting risk。 |
| `novelty` | 降权最近做过或刚推荐过的题，减少重复。 | 读取 recent_events 和 recommendation_history。 |
| `preference_fit` | 允许学生偏好影响题型或教学类型。 | 只影响排序，不覆盖 mastery / risk。 |

核心边界：

```text
KT 决定学习优先级。
推荐器决定从内容集中选哪道题。
LLM 只负责把推荐理由说得更自然，不能决定最终排序。
```

TeachingTrace 的 `plan` 阶段会记录：

- `candidate_count`：候选题数量。
- `recommendation_candidates`：排序后的前几名候选、分数和分数因子。
- `selected_question_ids`：最终返回的 1-3 道题。

## 6. Demo 教学内容集

本地 demo 内容集位于：

```text
data/content/demo_teaching_content.json
```

数据结构：

```json
{
  "concept_teaching_type_map": {
    "c_fraction_addition": "procedure"
  },
  "questions": [
    {
      "question_id": "q_frac_001",
      "stem": "计算：1/2 + 1/4 = ?",
      "standard_answer": "3/4",
      "explanation": "先通分到四分之一，1/2 = 2/4，所以 2/4 + 1/4 = 3/4。",
      "concept_id": "c_fraction_addition",
      "concept_name": "异分母分数加法",
      "difficulty": 0.35,
      "mistake_patterns": ["没有通分", "分母直接相加"],
      "rag_doc_ids": ["rag_fraction_addition_basic"]
    }
  ]
}
```

字段约定：

- `question_id`：题目稳定 ID，后续推荐、判题、RAG、UI 都使用它串联。
- `stem`：学生可见题干。
- `standard_answer`：服务端标准答案，不在推荐题 payload 中返回。
- `explanation`：题解，推荐时不提前返回，后续讲解 / RAG 使用。
- `concept_id` / `concept_name`：知识点标识和中文名。
- `difficulty`：0-1 难度分，后续推荐排序使用。
- `mistake_patterns`：常见错因，后续错因诊断使用。
- `rag_doc_ids`：关联 RAG 文档 ID。
- `concept_teaching_type_map`：稳定标注知识点教学类型，取值为 `memory`、`concept`、`procedure`、`design`。

确定性判题规则：

- `answer_submitted` 进入主循环后，服务端会根据 `question_id` 读取内容集标准答案。
- 客户端传入的 `is_correct`、`correct_answer`、`concept_id` 等判题字段会被清理，避免覆盖服务端事实。
- 判题结果写回 learning event payload，再交给 `MockKTStateEngine` 更新 progress。
- 正确路径会提高 mastery、降低 forgetting risk，并走 `reinforce_mastery`。
- 错误路径会降低 mastery、提高 forgetting risk，写入 `error_records` / `review_queue`，并走 `review_answer`。

替换为 ASSISTments2017 / DGEKT 数据时：

1. 保持 `question_id`、标准答案、知识点、难度、解析、错因、RAG 文档 ID 的字段语义不变。
2. 将 ASSISTments skill / problem 映射到 `concept_id` 与 `question_id`。
3. 将 DGEKT 需要的历史序列特征放在 adapter 内部，不泄漏到 API payload。
4. 保持核心边界：KT facts authoritative，内容集和 RAG 不能覆盖 KT prediction facts。
5. 先让 adapter 产出同样的 public question / grade result，再替换推荐器和 KT engine。

## 7. 环境变量

从示例文件创建本地配置：

```bash
cp .env.example .env
```

变量说明：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MATHTUTOR_ENV` | `development` | 当前运行环境。 |
| `MATHTUTOR_DB_URL` | `sqlite:///./data/local/mathtutor.sqlite` | 本地状态库。 |
| `MATHTUTOR_VECTOR_BACKEND` | `chroma` | 本地 RAG fallback；后续预留 VikingDB。 |
| `MATHTUTOR_LLM_PROVIDER` | `mock` | V1 优先用 mock / 规则化响应跑通闭环。 |
| `MATHTUTOR_LLM_MODEL` | 空 | 真实 LLM 模型名，mock 模式可留空。 |
| `MATHTUTOR_OPENAI_API_KEY` | 空 | 真实 LLM key，mock 模式可留空。 |

## 8. 数据目录约定

```text
data/
  content/      小型数学教学内容集：题目、知识点、答案、题解、错因、策略。
  rag/          本地 RAG 文档和可检索片段。
  local/        sqlite、cache、临时索引等本地运行产物，不提交。
```

当前策略：

- 先用本地 JSON / sqlite / 内存实现跑通 V1 闭环。
- `MockKTStateEngine` 是默认 KT 实现。
- DGEKT / SAFKT 只通过稳定接口预留 adapter。
- 本地 memory 是默认实现，Mem0 adapter 后续接入。
- 本地 RAG fallback 是默认实现，VikingDB adapter 后续接入。

## 9. V1 不做什么

V1 明确不做：

- 多学科。
- 班级 / 教师端。
- 移动端。
- 商业登录、权限和支付。
- 完整 AGI-saber 迁移。
- 真实在线训练 DGEKT / SAFKT。
- 后台定时推送。
- 自动生成大规模题库。
- 复杂分布式多 Agent。

## 10. 核心实现边界

以下规则优先级高于任何自然语言生成结果：

```text
KT facts are authoritative.
LLM plans are advisory.
Memory can influence strategy, not mastery.
RAG can support explanation, not overwrite prediction facts.
```

具体含义：

- KTStateEngine 输出的 mastery、risk、prediction、weak concepts 和 evidence 是学习诊断事实。
- LLM 可以润色表达、生成提示和总结，但不能改写 KT 事实。
- Memory 可以影响节奏、偏好和教学策略，不直接覆盖 mastery。
- RAG 只提供解释证据，不覆盖 KT prediction facts。

## 11. GitHub Issue 工作流

实现顺序以 GitHub issue 为准，优先选择当前未完成且依赖已满足的最小 issue。

建议流程：

1. 查看 issue 描述和验收点。
2. 找到相关代码和文档。
3. 用最小可运行切片实现功能。
4. 补测试和中文文档。
5. 运行相关检查。
6. 提交 commit。
7. 如可行，push 并在 issue 留完成说明。

完成说明应包含：

- 已完成的验收点。
- 运行过的测试命令。
- 演示方式。
- 如有遗留风险，明确列出。

## 12. 常见排错

### `ModuleNotFoundError: No module named 'backend'`

确认命令在仓库根目录运行，或已安装 editable 包：

```bash
pip install -e ".[dev]"
```

### `ModuleNotFoundError: No module named 'app'`

如果在仓库根目录启动，请使用：

```bash
uvicorn backend.app.main:app --reload
```

如果在 `backend/` 目录启动，请使用：

```bash
uvicorn app.main:app --reload
```

### 端口被占用

换端口启动：

```bash
uvicorn backend.app.main:app --reload --port 8001
```

### 本地数据污染

本地运行产物应放在 `data/local/`。该目录默认不提交，需要重置演示数据时可以删除本地 sqlite 或 cache。

### RAG / LLM 依赖不可用

V1 必须能在本地 fallback 下运行。没有真实向量库、真实 LLM key 或外部服务时，应使用 mock / 本地实现继续完成闭环。
