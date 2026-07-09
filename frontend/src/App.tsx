import { FormEvent, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  BookOpenCheck,
  ChevronDown,
  CircleHelp,
  ClipboardCheck,
  RefreshCw,
  MessageCircle,
  Send,
  ShieldCheck,
  Sparkles,
  Target
} from "lucide-react";
import { sendLearningEvent } from "./api";
import type {
  ContextAssetEvidence,
  EvidenceGap,
  MathTutorEventResponse,
  RecommendedQuestion
} from "./types";

const SESSION_ID = `demo-${Date.now()}`;
const DEFAULT_STUDENT_ID = "student-demo";

interface HistoryItem {
  id: string;
  label: string;
  response: MathTutorEventResponse;
}

type RagSource = NonNullable<
  MathTutorEventResponse["teaching_trace_summary"]["expert_evidence"]["rag_sources"]
>[number];

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
  const responseIssue = visibleResponseIssue(current);

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
      payload: {
        question_id: question.question_id,
        answer,
        assist2017_question_id: question.assist2017_question_id,
        dgekt_question_id: question.dgekt_question_id,
        assist2017_concept_id: question.assist2017_concept_id,
        dgekt_concept_id: question.dgekt_concept_id
      }
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

      {(error || responseIssue) && (
        <div className="error-banner" role="alert">
          <span>{error || responseIssue}</span>
          <button onClick={() => void requestNextStep()} disabled={isLoading}>
            <RefreshCw size={16} />
            重试
          </button>
        </div>
      )}

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
                    <button
                      aria-label="提交答案"
                      disabled={isLoading || !(answerByQuestion[question.question_id] ?? "").trim()}
                    >
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
              <button aria-label="发送消息" disabled={isLoading || !message.trim()}>
                <Send size={17} />
              </button>
            </form>
            {isLoading && <p className="loading-line">正在处理学习事件...</p>}
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
  const ktDiagnosis = evidence?.kt_diagnosis;
  const plannerDecision = evidence?.planner_decision;
  const recommendations = evidence?.recommendations ?? [];
  const assembledContext = evidence?.assembled_context ?? null;
  const contextAssets = contextAssetItems(evidence);
  const selectedContextAssets = contextAssets.filter((asset) => !isExcludedAsset(asset));
  const omittedContextAssets = contextAssets.filter(isExcludedAsset);
  const topPath = attribution?.top_paths?.[0];
  const keyHistory = attribution?.key_history?.[0];
  const evidenceGaps = evidenceGapItems(evidence?.evidence_gaps ?? assembledContext?.evidence_gaps);
  const errorRecords = evidenceGapItems(evidence?.error_records);
  const evidenceStatus = topPath?.partial_evidence ? "partial evidence" : "完整证据";
  const contextBudget = formatContextBudget(assembledContext);

  return (
    <article className="panel trace-panel">
      <details open>
        <summary>
          <span><ChevronDown size={17} /> TeachingTrace</span>
          <small>{response?.teaching_trace.length ?? 0} 个阶段</small>
        </summary>
        <div className="trace-list">
          {(response?.teaching_trace ?? []).map((event) => (
            <div className="trace-event" key={event.id}>
              <span>{stageName(event.stage)}</span>
              <b>{event.actor} · {visibilityName(event.visibility)}</b>
              <p>{event.content}</p>
              {event.evidence_refs.length > 0 && (
                <small>证据引用：{event.evidence_refs.join("、")}</small>
              )}
            </div>
          ))}
          {!response && <p className="muted">等待第一轮事件生成 TeachingTrace。</p>}
        </div>
      </details>

      <details>
        <summary>
          <span><ChevronDown size={17} /> RAG 引用</span>
          <small>{ragSources.length} 条引用</small>
        </summary>
        <div className="citation-list">
          {ragSources.map((source) => (
            <p key={`${source.doc_id}-${source.source}`}>
              <strong>{source.title}</strong>
              <span>{source.source}</span>
              <small>{ragSourceTarget(source)}</small>
            </p>
          ))}
          {ragSources.length === 0 && <p className="muted">本轮没有 RAG 引用。</p>}
        </div>
      </details>

      <details>
        <summary>
          <span><ChevronDown size={17} /> 上下文证据</span>
          <small>{selectedContextAssets.length} 纳入 · {omittedContextAssets.length} 排除</small>
        </summary>
        <div className="context-summary">
          <p>
            <strong>预算</strong>
            <span>{contextBudget}</span>
          </p>
          <p>
            <strong>Evidence gaps</strong>
            <span>{evidenceGaps.length + errorRecords.length} 项</span>
          </p>
          <p>
            <strong>压缩策略</strong>
            <span>{assembledContext?.compression_summary?.strategy ?? "暂无"}</span>
          </p>
        </div>
        <div className="context-asset-list">
          {selectedContextAssets.map((asset) => (
            <ContextAssetRow key={contextAssetKey(asset)} asset={asset} />
          ))}
          {selectedContextAssets.length === 0 && (
            <p className="muted">本轮没有上下文资产；主学习流程仍按 KT facts 和默认内容运行。</p>
          )}
        </div>
        {(omittedContextAssets.length > 0 || evidenceGaps.length + errorRecords.length > 0) && (
          <div className="gap-list">
            {omittedContextAssets.map((asset) => (
              <p key={`omitted-${contextAssetKey(asset)}`}>
                <strong>{assetTypeName(asset.asset_type)} 已排除</strong>
                <span>{asset.excluded_reason ?? "未纳入本轮上下文"}</span>
              </p>
            ))}
            {[...evidenceGaps, ...errorRecords].map((gap, index) => (
              <p key={`gap-${index}-${gap.gap_type ?? gap.code ?? "context"}`}>
                <strong>{gapLabel(gap)}</strong>
                <span>{gap.reason ?? gap.message ?? gap.impact ?? "上下文证据缺口"}</span>
              </p>
            ))}
          </div>
        )}
      </details>

      <details>
        <summary>
          <span><ChevronDown size={17} /> 模型证据</span>
          <small>{formatProbability(attribution?.prediction_probability)}</small>
        </summary>
        <div className="evidence-grid">
          <p>
            <strong>KT 预测</strong>
            <span>{formatProbability(ktDiagnosis?.prediction_probability)}</span>
          </p>
          <p>
            <strong>推荐候选</strong>
            <span>{recommendations.length} 道</span>
          </p>
          <p>
            <strong>教学动作</strong>
            <span>{actionLabel(plannerDecision)}</span>
          </p>
          <p>
            <strong>DGEKT attribution</strong>
            <span>{attribution ? evidenceStatus : "暂无"}</span>
          </p>
          <p>
            <strong>Evidence gaps</strong>
            <span>{evidenceGaps.length + errorRecords.length} 项</span>
          </p>
          <p>
            <strong>Top path</strong>
            <span>
              {topPath
                ? `${topPath.history_assist2017_question_id ?? topPath.history_question_id ?? "?"} -> ${topPath.target_assist2017_question_id ?? topPath.target_question_id ?? "?"}`
                : "暂无"}
            </span>
          </p>
          <p>
            <strong>Path strength</strong>
            <span>{formatNumber(topPath?.path_strength ?? topPath?.path_weight ?? topPath?.weight)}</span>
          </p>
          <p>
            <strong>Key history</strong>
            <span>
              {keyHistory
                ? `${keyHistory.assist2017_question_id ?? keyHistory.question_id ?? "?"} · ${keyHistory.is_correct ? "正确" : "错误"}`
                : "暂无"}
            </span>
          </p>
        </div>
        <pre>{JSON.stringify({
          kt_diagnosis: ktDiagnosis,
          attribution_evidence: attribution,
          planner_decision: plannerDecision,
          recommendations
        }, null, 2)}</pre>
      </details>
    </article>
  );
}

function ContextAssetRow({ asset }: { asset: ContextAssetEvidence }) {
  const source = [asset.source_type, asset.source_ref].filter(Boolean).join(" · ");
  return (
    <div className="context-asset">
      <span className={`asset-badge asset-${asset.asset_type ?? "unknown"}`}>
        {assetTypeName(asset.asset_type)}
      </span>
      <div>
        <strong>{asset.summary ?? "上下文资产"}</strong>
        <p>{asset.included_reason ?? asset.excluded_reason ?? "已纳入本轮上下文证据"}</p>
        <small>
          {source || "本地上下文"} · {freshnessName(asset.freshness)} · confidence{" "}
          {formatNumber(asset.confidence)}
        </small>
      </div>
    </div>
  );
}

function visibleResponseIssue(response: MathTutorEventResponse | null) {
  const records = response?.state_summary.error_records ?? [];
  const warning = records.find((record) => record.severity !== "info");
  if (warning?.message) {
    const hint = warning.actionable_hint ? `；${String(warning.actionable_hint)}` : "";
    return `${String(warning.message)}${hint}`;
  }
  return response?.state_summary.errors?.[0] ?? "";
}

function evidenceGapItems(value: unknown): EvidenceGap[] {
  return Array.isArray(value) ? value.filter(isRecord) as EvidenceGap[] : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function contextAssetItems(
  evidence: MathTutorEventResponse["teaching_trace_summary"]["expert_evidence"] | undefined
): ContextAssetEvidence[] {
  const items: ContextAssetEvidence[] = [];
  const seen = new Set<string>();
  const addAsset = (asset: ContextAssetEvidence, selectionStatus?: "included" | "excluded") => {
    const normalized = {
      ...asset,
      selection_status: asset.selection_status ?? selectionStatus
    };
    const key = contextAssetKey(normalized);
    if (seen.has(key)) return;
    seen.add(key);
    items.push(normalized);
  };

  for (const asset of evidence?.assembled_context?.asset_summaries ?? []) {
    addAsset(asset);
  }
  const selected = evidence?.context_asset_selection?.selected ?? [];
  const omitted = evidence?.context_asset_selection?.omitted ?? [];
  for (const asset of selected) {
    addAsset(asset, "included");
  }
  for (const asset of omitted) {
    addAsset(asset, "excluded");
  }
  for (const asset of evidence?.context_assets ?? []) {
    addAsset(asset);
  }
  return items;
}

function isExcludedAsset(asset: ContextAssetEvidence) {
  return asset.selection_status === "excluded" || Boolean(asset.excluded_reason);
}

function contextAssetKey(asset: ContextAssetEvidence) {
  return asset.asset_id ?? `${asset.asset_type}-${asset.source_ref}-${asset.summary}`;
}

function assetTypeName(type: string | undefined) {
  return {
    student_memory: "Memory evidence",
    knowledge_resource: "RAG citation",
    task_state: "Task state",
    tool_observation: "Tool snapshot",
    trace_reference: "Trace reference"
  }[type ?? ""] ?? "Context asset";
}

function freshnessName(value: string | undefined) {
  return {
    fresh: "fresh",
    recent: "recent",
    stale: "stale"
  }[value ?? ""] ?? "unknown freshness";
}

function gapLabel(gap: EvidenceGap) {
  return {
    student_memory: "缺少 memory evidence",
    knowledge_resource: "缺少 RAG citation",
    stale_task_state: "task_state 已过期",
    low_confidence_observation: "低置信度 tool observation",
    provider_failure: "provider failure",
    context_budget: "上下文预算裁剪",
    missing_content: "教学内容缺口",
    missing_mapping: "映射缺口",
    missing_rag_citation: "RAG citation 缺口"
  }[gap.gap_type ?? gap.category ?? ""] ?? "Evidence gap";
}

function formatContextBudget(
  assembledContext: MathTutorEventResponse["teaching_trace_summary"]["expert_evidence"]["assembled_context"]
) {
  if (!assembledContext) return "暂无";
  if (
    typeof assembledContext.budget_used === "number" &&
    typeof assembledContext.budget_limit === "number"
  ) {
    return `${assembledContext.budget_used}/${assembledContext.budget_limit}`;
  }
  return "未记录";
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
    canonical_alignment: "映射",
    novelty: "新鲜度",
    preference_fit: "偏好"
  }[name] ?? name;
}

function ragSourceTarget(source: RagSource) {
  const parts = [
    source.question_id ? `题 ${source.question_id}` : "",
    source.concept_id ? `知识点 ${source.concept_id}` : "",
    source.assist2017_question_id ? `ASSIST2017 Q${source.assist2017_question_id}` : "",
    source.assist2017_concept_id ? `C${source.assist2017_concept_id}` : ""
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "全局学习策略";
}

function stageName(stage: string) {
  return {
    load_context: "读取上下文",
    diagnose: "KT 诊断",
    plan: "教学规划",
    generate_response: "生成回复",
    memory_update: "记忆更新"
  }[stage] ?? stage;
}

function visibilityName(visibility: string) {
  return visibility === "student" ? "学生可见" : "专家证据";
}

function formatProbability(value: number | null | undefined) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "暂无";
}

function formatNumber(value: unknown) {
  return typeof value === "number" ? value.toFixed(3) : "暂无";
}

function actionLabel(plannerDecision: Record<string, unknown> | null | undefined) {
  const selectedAction = plannerDecision?.selected_action;
  if (
    selectedAction &&
    typeof selectedAction === "object" &&
    "label" in selectedAction &&
    typeof selectedAction.label === "string"
  ) {
    return selectedAction.label;
  }
  return "等待规划";
}
