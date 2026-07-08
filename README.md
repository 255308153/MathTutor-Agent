# MathTutor Agent

MathTutor Agent 是一个面向个人学习者的数学学习 Agent。V1 目标不是做通用聊天机器人，而是先跑通一个可演示、可测试、可解释的数学学习闭环：

```text
学习事件 / 学生提问
-> 读取学生状态与长期记忆
-> 检索数学知识与题目解释
-> 知识追踪诊断
-> 规划下一步教学动作
-> 推荐题目 / 讲解 / 复习 / 错因诊断
-> 生成学生可读反馈
-> 记录 TeachingTrace
-> 更新长期学习记忆
```

V1 的一句话定位：

```text
一个基于可解释知识追踪、RAG 和长期学习记忆的数学个人教师 Agent。
```

## V1 范围

V1 优先服务一个学生、一个数学学习场景、一条可审计学习闭环。

包含：

- FastAPI 后端入口。
- MathTutor 事件处理主循环。
- `MockKTStateEngine` 本地知识追踪实现。
- 小型本地数学教学内容集和确定性判题。
- 风险优先的题目推荐与推荐理由。
- 本地 RAG fallback，并预留 VikingDB adapter。
- 本地学生长期记忆，并预留 Mem0 adapter。
- 错因诊断和四类教学动作。
- TeachingTrace，可追踪每次 agent 决策依据。
- React 学习驾驶舱首版。

暂不包含：

- 多学科。
- 班级 / 教师端。
- 移动端。
- 商业级登录、权限和支付。
- 完整 AGI-saber 迁移。
- 真实在线训练 DGEKT / SAFKT。
- 大规模自动题库生成。
- 复杂分布式多 Agent。

## 核心边界

实现时必须保持以下规则：

```text
KT facts are authoritative.
LLM plans are advisory.
Memory can influence strategy, not mastery.
RAG can support explanation, not overwrite prediction facts.
```

也就是说：

- KT 输出的掌握度、遗忘风险、预测概率和薄弱知识点是权威事实。
- LLM 只给教学表达和策略建议，不覆盖 KT 事实。
- Memory 可以影响讲解风格、复习策略和偏好，不直接改写 mastery。
- RAG 支持解释、证据和题解，不覆盖 prediction facts。

## 目录结构

```text
backend/
  app/
    api/        FastAPI routers
    core/       配置、事件、trace 基础能力
    graph/      MathTutor 主循环编排
    kt/         KTStateEngine 接口与 Mock / DGEKT 预留实现
    memory/     学生长期记忆接口与本地实现
    planning/   教学动作规划与推荐
    rag/        知识检索接口、本地 fallback、VikingDB 预留
    schemas/    Pydantic 领域模型
    storage/    本地数据仓储
  tests/        后端测试

data/
  content/      小型数学题库、知识点、题解、错因与策略材料
  local/        本地运行产生的 sqlite / cache，默认不提交
  rag/          本地 RAG 文档

docs/           中文架构、开发和演示文档
frontend/       React 学习驾驶舱
```

## 本地启动

建议使用 Python 3.11+。

```bash
cd /Users/lqc/Downloads/MathTutor-Agent
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

启动后端：

```bash
uvicorn backend.app.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

预期返回：

```json
{"status":"ok"}
```

启动 React 学习驾驶舱：

```bash
cd frontend
npm install
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173
```

前端开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。如果后端使用其他地址，可设置：

```bash
VITE_MATHTUTOR_API_BASE=http://127.0.0.1:8000 npm run dev
```

## 一分钟演示路径

1. 启动后端：`uvicorn backend.app.main:app --reload`。
2. 启动前端：`cd frontend && npm run dev`。
3. 打开 `http://127.0.0.1:5173`，页面会自动请求“我下一步应该练什么？”。
4. 看“今日建议”“推荐题”“薄弱概念”“遗忘风险”，确认 Agent 给出下一步练习。
5. 在第一道推荐题输入一个错误答案并提交，查看错因诊断、概念状态变化和新的推荐题。
6. 再对下一道推荐题输入正确答案，查看巩固反馈和后续推荐。
7. 展开 `TeachingTrace`、`RAG 引用`、`模型证据`，检查 KT facts、RAG 来源、planner decision 和 attribution evidence。

V1.1 演示验收点：

- 答题提交由服务端本地内容集确定性判题，不依赖 LLM 记答案。
- 答对 / 答错后都会返回新的推荐题，便于连续演示。
- TeachingTrace 使用学生可读主流程 + 专家证据层，研究者可以看到 KT / RAG / memory / recommendation evidence。
- 推荐题、题解、错因和 citation 使用本地 demo 数据，便于后续替换为真实 ASSISTments2017 / DGEKT 产物。

## V1.1 已知限制与下一阶段优先级

当前仍是本地可演示版本：

- `MockKTStateEngine` 只模拟知识追踪事实，不代表真实 DGEKT 预测。
- 学生长期记忆默认是本地内存实现，服务重启后不会持久化。
- RAG 使用本地 JSON fallback，不是生产向量库。
- Demo 内容集是小型人工整理题库，不是完整 ASSISTments2017 导入结果。
- 前端是单学习者演示驾驶舱，没有登录、权限和班级管理。

下一阶段真实集成优先级：

1. `DGEKTStateEngine`：接入真实 mastery、prediction probability、weak-concept hit 和 attribution evidence。
2. `Mem0` adapter：把本地 memory store 替换成可持久化的学生长期记忆。
3. `VikingDB` adapter：把本地 RAG JSON fallback 替换成可扩展向量检索。
4. `ASSISTments2017` 数据导入：建立题目、知识点、历史作答和 RAG 文档的稳定映射。

## 测试与检查

```bash
python -m compileall backend/app
pytest
ruff check .
cd frontend && npm test && npm run build
```

当前基线要求：

- 健康检查测试通过。
- Python 编译检查通过。
- React smoke test 和生产构建通过。
- 新增功能应优先补最小可验证测试。

## 环境变量

复制 `.env.example` 为 `.env` 后按需调整：

```bash
cp .env.example .env
```

默认约定：

- `MATHTUTOR_ENV=development`：本地开发环境。
- `MATHTUTOR_DB_URL=sqlite:///./data/local/mathtutor.sqlite`：本地 sqlite。
- `MATHTUTOR_VECTOR_BACKEND=chroma`：本地向量检索 fallback。
- `MATHTUTOR_LLM_PROVIDER=mock`：V1 先用 mock / 规则化响应跑通闭环。
- `MATHTUTOR_LLM_MODEL`：真实 LLM 模型名，mock 模式可留空。
- `MATHTUTOR_OPENAI_API_KEY`：真实 LLM key，本地 mock 模式可留空。
- `MATHTUTOR_KT_ENGINE=mock`：默认 KT 引擎；保持 V1.1 演示不依赖真实 checkpoint。
- `MATHTUTOR_KT_ENGINE=dgekt`：显式启用真实 DGEKT 配置校验。
- `MATHTUTOR_DGEKT_DATASET=assist2017`：V1.2 当前支持的真实数据集。
- `MATHTUTOR_DGEKT_CHECKPOINT_PATH`：本地 ASSIST2017 checkpoint 路径。已验证 checkpoint 示例：`/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本/KnowledgeTracing/model/runs/20260707_222733/save2017model.pkl`。
- `MATHTUTOR_DGEKT_DATASET_DIR`：ASSIST2017 数据目录，需包含 `assist2017_pid_train.csv` 和 `assist2017_pid_test.csv`。
- `MATHTUTOR_DGEKT_Q_MATRIX_PATH`：Q-matrix / incidence matrix 文件，例如原始 DGEKT 工程的 `Dataset/H/2017.csv`。

大 checkpoint 和原始数据文件不提交到 Git，只通过本地路径或环境变量引用。默认 mock 模式不会读取上述 DGEKT 文件。

## Agent 工作方式

后续实现优先从 GitHub issue 开始：

1. 选择当前未完成且依赖已满足的最小 issue。
2. 阅读 issue 描述、验收点和相关文档。
3. 做到可运行、可测试、可演示，而不是只提交代码骨架。
4. 更新 README、开发文档或用户可见中文文案。
5. 运行相关测试。
6. 提交 git commit。
7. 如可行，推送到 GitHub，并在对应 issue 留完成说明。

每个 PR / commit 都应说明覆盖了哪些验收点，未覆盖的点必须明确留在 issue 中。

更多架构细节见 [docs/V1_ARCHITECTURE.md](docs/V1_ARCHITECTURE.md)，开发细节见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。
