import { FormEvent, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  BookOpenCheck,
  ChevronDown,
  CircleHelp,
  ClipboardCheck,
  MessageCircle,
  Send,
  ShieldCheck,
  Sparkles,
  Target
} from "lucide-react";
import { sendLearningEvent } from "./api";
import type { MathTutorEventResponse, RecommendedQuestion } from "./types";

const SESSION_ID = `demo-${Date.now()}`;
const DEFAULT_STUDENT_ID = "student-demo";

interface HistoryItem {
  id: string;
  label: string;
  response: MathTutorEventResponse;
}

export default function App() {
  const [studentId, setStudentId] = useState(DEFAULT_STUDENT_ID);
  const [message, setMessage] = useState("我下一步应该练什么？");
  const [answerByQuestion, setAnswerByQuestion] = useState<Record<string, string>>({});
  const [current, setCurrent] = useState<MathTutorEventResponse | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void requestNextStep("我下一步应该练什么？");
  }, []);

  const weakConcepts = current?.state_summary.weak_concepts ?? [];
  const forgettingRisks = current?.state_summary.forgetting_risks ?? [];
  const conceptStates = current?.state_summary.concept_states ?? [];
  const recommendations = current?.recommended_questions ?? [];
  const topQuestion = recommendations[0];

  const todaySuggestion = useMemo(() => {
    if (!current) return "正在读取学习状态...";
    if (topQuestion) return `先练「${topQuestion.concept_name}」：${topQuestion.stem}`;
    return current.response;
  }, [current, topQuestion]);

  async function runEvent(label: string, event: Parameters<typeof sendLearningEvent>[0]) {
    setIsLoading(true);
    setError("");
    try {
      const response = await sendLearningEvent(event);
      setCurrent(response);
      setHistory((items) => [{ id: response.trace_id, label, response }, ...items].slice(0, 6));
      return response;
    } catch (err) {
      setError(err instanceof Error ? err.message : "事件处理失败");
      return null;
    } finally {
      setIsLoading(false);
    }
  }

  function requestNextStep(text = message) {
    return runEvent("下一步建议", {
      session_id: SESSION_ID,
      student_id: studentId || DEFAULT_STUDENT_ID,
      type: "chat_message",
      message: text,
      payload: {}
    });
  }

  function sendChat(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!message.trim()) return;
    void runEvent("概念问答", {
      session_id: SESSION_ID,
      student_id: studentId || DEFAULT_STUDENT_ID,
      type: "chat_message",
      message,
      payload: {}
    });
  }

  function submitAnswer(question: RecommendedQuestion) {
    const answer = answerByQuestion[question.question_id] ?? "";
    if (!answer.trim()) return;
    void runEvent("提交答案", {
      session_id: SESSION_ID,
      student_id: studentId || DEFAULT_STUDENT_ID,
      type: "answer_submitted",
      message: `提交 ${question.question_id} 的答案`,
      payload: { question_id: question.question_id, answer }
    });
  }

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">MathTutor Agent V1</p>
          <h1>学习驾驶舱</h1>
        </div>
        <label className="student-switch">
          <span>当前学生</span>
          <input
            value={studentId}
            onChange={(event) => setStudentId(event.target.value)}
            aria-label="当前学生"
          />
        </label>
      </section>

      <section className="dashboard-grid">
        <article className="panel focus-panel">
          <div className="panel-title">
            <Sparkles size={18} />
            <h2>今日建议</h2>
          </div>
          <p className="suggestion">{todaySuggestion}</p>
          <div className="action-row">
            <button className="primary-button" onClick={() => void requestNextStep()} disabled={isLoading}>
              <Target size={18} />
              获取下一步
            </button>
            <span className="trace-chip">trace: {current?.trace_id ?? "等待生成"}</span>
          </div>
        </article>

        <MetricPanel
          icon={<Activity size={18} />}
          title="薄弱概念"
          value={String(weakConcepts.length)}
          detail={weakConcepts.map((item) => String(item.concept_name ?? item.concept_id)).join("、") || "暂无明显薄弱点"}
        />
        <MetricPanel
          icon={<ShieldCheck size={18} />}
          title="遗忘风险"
          value={String(forgettingRisks.length)}
          detail={forgettingRisks.map((item) => String(item.concept_name ?? item.concept_id)).join("、") || "暂无高风险复习项"}
        />
      </section>

      {error && <div className="error-banner">{error}</div>}

      <section className="main-grid">
        <div className="left-stack">
          <article className="panel">
            <div className="panel-title">
              <BookOpenCheck size={18} />
              <h2>概念状态</h2>
            </div>
            <div className="concept-list">
              {conceptStates.length === 0 ? (
                <p className="muted">还没有作答证据，先完成一题后会出现掌握度。</p>
              ) : (
                conceptStates.map((concept) => (
                  <div className="concept-row" key={concept.concept_id}>
                    <div>
                      <strong>{concept.concept_name}</strong>
                      <span>{concept.status} · {teachingTypeName(concept.teaching_type)}</span>
                    </div>
                    <div className="meter" aria-label={`${concept.concept_name} 掌握度`}>
                      <i style={{ width: `${Math.round(concept.mastery * 100)}%` }} />
                    </div>
                    <b>{Math.round(concept.mastery * 100)}%</b>
                  </div>
                ))
              )}
            </div>
          </article>

          <article className="panel">
            <div className="panel-title">
              <ClipboardCheck size={18} />
              <h2>推荐题</h2>
            </div>
            <div className="question-list">
              {recommendations.map((question) => (
                <div className="question-card" key={question.question_id}>
                  <div className="question-header">
                    <span>{question.concept_name}</span>
                    <b>风险分 {Math.round(question.score * 100)}</b>
                  </div>
                  <p>{question.stem}</p>
                  <small>{question.reason}</small>
                  <div className="factor-grid">
                    {Object.entries(question.score_factors).map(([name, value]) => (
                      <span key={name}>{factorName(name)} {Math.round(value * 100)}</span>
                    ))}
                  </div>
                  <form
                    className="answer-row"
                    onSubmit={(event) => {
                      event.preventDefault();
                      submitAnswer(question);
                    }}
                  >
                    <input
                      value={answerByQuestion[question.question_id] ?? ""}
                      onChange={(event) =>
                        setAnswerByQuestion((answers) => ({
                          ...answers,
                          [question.question_id]: event.target.value
                        }))
                      }
                      placeholder="输入答案"
                      aria-label={`${question.question_id} 答案`}
                    />
                    <button aria-label="提交答案" disabled={isLoading}>
                      <Send size={17} />
                    </button>
                  </form>
                </div>
              ))}
              {recommendations.length === 0 && (
                <p className="muted">当前轮次没有新推荐。可以点击“获取下一步”生成练习题。</p>
              )}
            </div>
          </article>
        </div>

        <div className="right-stack">
          <article className="panel">
            <div className="panel-title">
              <MessageCircle size={18} />
              <h2>Agent 回复</h2>
            </div>
            <p className="agent-response">{current?.response ?? "正在准备第一条建议..."}</p>
            <form className="chat-form" onSubmit={sendChat}>
              <input
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="问一个概念，或输入：我下一步应该练什么？"
              />
              <button aria-label="发送消息" disabled={isLoading}>
                <Send size={17} />
              </button>
            </form>
          </article>

          <TracePanel response={current} />

          <article className="panel">
            <div className="panel-title">
              <CircleHelp size={18} />
              <h2>最近记录</h2>
            </div>
            <div className="history-list">
              {history.map((item) => (
                <button key={item.id} onClick={() => setCurrent(item.response)}>
                  <span>{item.label}</span>
                  <small>{item.response.trace_id}</small>
                </button>
              ))}
              {history.length === 0 && <p className="muted">暂无记录。</p>}
            </div>
          </article>
        </div>
      </section>
    </main>
  );
}

function MetricPanel({
  icon,
  title,
  value,
  detail
}: {
  icon: ReactNode;
  title: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="panel metric-panel">
      <div className="panel-title">
        {icon}
        <h2>{title}</h2>
      </div>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function TracePanel({ response }: { response: MathTutorEventResponse | null }) {
  const evidence = response?.teaching_trace_summary.expert_evidence;
  const ragSources = evidence?.rag_sources ?? [];
  const attribution = evidence?.attribution_evidence;

  return (
    <article className="panel trace-panel">
      <details open>
        <summary>
          <span><ChevronDown size={17} /> TeachingTrace</span>
          <small>{response?.teaching_trace.length ?? 0} stages</small>
        </summary>
        <div className="trace-list">
          {(response?.teaching_trace ?? []).map((event) => (
            <div className="trace-event" key={event.id}>
              <span>{event.stage}</span>
              <b>{event.actor} · {visibilityName(event.visibility)}</b>
              <p>{event.content}</p>
            </div>
          ))}
        </div>
      </details>

      <details>
        <summary>
          <span><ChevronDown size={17} /> RAG 引用</span>
          <small>{ragSources.length} sources</small>
        </summary>
        <div className="citation-list">
          {ragSources.map((source) => (
            <p key={`${source.doc_id}-${source.source}`}>
              <strong>{source.title}</strong>
              <span>{source.source}</span>
            </p>
          ))}
          {ragSources.length === 0 && <p className="muted">本轮没有 RAG 引用。</p>}
        </div>
      </details>

      <details>
        <summary>
          <span><ChevronDown size={17} /> 模型证据</span>
          <small>{attribution?.prediction_probability ?? "mock"}</small>
        </summary>
        <pre>{JSON.stringify({
          kt_diagnosis: evidence?.kt_diagnosis,
          attribution_evidence: attribution,
          planner_decision: evidence?.planner_decision
        }, null, 2)}</pre>
      </details>
    </article>
  );
}

function teachingTypeName(type: string) {
  return {
    memory: "记忆",
    concept: "概念",
    procedure: "程序",
    design: "综合"
  }[type] ?? type;
}

function factorName(name: string) {
  return {
    weak_concept_match: "薄弱匹配",
    difficulty_fit: "难度贴合",
    forgetting_urgency: "遗忘风险",
    novelty: "新鲜度",
    preference_fit: "偏好"
  }[name] ?? name;
}

function visibilityName(visibility: string) {
  return visibility === "student" ? "学生可见" : "专家证据";
}
