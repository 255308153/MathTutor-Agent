import { FormEvent, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  BookOpenCheck,
  Brain,
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
import { fetchStudentMemories, sendLearningEvent } from "./api";
import type {
  AttributionEvidence,
  ContextAssetEvidence,
  EvidenceGap,
  MathTutorEventResponse,
  RecommendedQuestion,
  StudentMemory
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
  const [memories, setMemories] = useState<StudentMemory[]>([]);
  const [selectedMemoryId, setSelectedMemoryId] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isMemoryLoading, setIsMemoryLoading] = useState(false);
  const [error, setError] = useState("");
  const [memoryError, setMemoryError] = useState("");
  const activeStudentId = studentId || DEFAULT_STUDENT_ID;

  useEffect(() => {
    void requestNextStep("我下一步应该练什么？");
  }, []);

  useEffect(() => {
    void loadStudentMemories(activeStudentId);
  }, [activeStudentId]);

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
      void loadStudentMemories(event.student_id);
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
      student_id: activeStudentId,
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
      student_id: activeStudentId,
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
      student_id: activeStudentId,
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

  async function loadStudentMemories(targetStudentId = activeStudentId) {
    setIsMemoryLoading(true);
    setMemoryError("");
    try {
      const response = await fetchStudentMemories(targetStudentId);
      setMemories(response.memories);
      setSelectedMemoryId((currentId) => {
        if (response.memories.some((memory) => memory.memory_id === currentId)) return currentId;
        return response.memories[0]?.memory_id ?? "";
      });
    } catch (err) {
      setMemories([]);
      setSelectedMemoryId("");
      setMemoryError(err instanceof Error ? err.message : "学生记忆读取失败");
    } finally {
      setIsMemoryLoading(false);
    }
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

          <MemoryPanel
            memories={memories}
            selectedMemoryId={selectedMemoryId}
            isLoading={isMemoryLoading}
            error={memoryError}
            onSelect={setSelectedMemoryId}
            onRefresh={() => void loadStudentMemories()}
          />

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

function MemoryPanel({
  memories,
  selectedMemoryId,
  isLoading,
  error,
  onSelect,
  onRefresh
}: {
  memories: StudentMemory[];
  selectedMemoryId: string;
  isLoading: boolean;
  error: string;
  onSelect: (memoryId: string) => void;
  onRefresh: () => void;
}) {
  const selectedMemory =
    memories.find((memory) => memory.memory_id === selectedMemoryId) ?? memories[0] ?? null;
  const evidenceFacts = selectedMemory ? memoryEvidenceFacts(selectedMemory) : [];
  const provenanceFacts = selectedMemory ? memoryProvenanceFacts(selectedMemory) : [];

  return (
    <article className="panel memory-panel">
      <div className="panel-title panel-title-with-action">
        <span>
          <Brain size={18} />
          <h2>长期记忆</h2>
        </span>
        <button
          type="button"
          className="icon-button"
          onClick={onRefresh}
          disabled={isLoading}
          aria-label="刷新长期记忆"
          title="刷新长期记忆"
        >
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="memory-summary-row">
        <span>{memories.length} 条</span>
        <span>{selectedMemory ? memoryProviderName(selectedMemory.source) : "等待读取"}</span>
      </div>

      {isLoading && <p className="loading-line">正在读取长期记忆...</p>}
      {error && (
        <div className="memory-error" role="status">
          <span>{error}</span>
          <button type="button" onClick={onRefresh}>
            <RefreshCw size={15} />
            重试
          </button>
        </div>
      )}
      {!isLoading && !error && memories.length === 0 && (
        <p className="muted">暂无长期记忆；完成练习或产生偏好后会出现在这里。</p>
      )}

      {memories.length > 0 && (
        <div className="memory-layout">
          <div className="memory-list" aria-label="长期记忆列表">
            {memories.map((memory) => (
              <button
                type="button"
                key={memory.memory_id}
                className={memory.memory_id === selectedMemory?.memory_id ? "memory-active" : ""}
                onClick={() => onSelect(memory.memory_id)}
              >
                <span>{memoryTypeName(memory.memory_type)}</span>
                <strong>{memory.summary || memory.content}</strong>
                <small>
                  {freshnessName(memory.freshness)} · {memoryStatusName(memory.status)}
                </small>
              </button>
            ))}
          </div>

          {selectedMemory && (
            <div className="memory-detail">
              <div className="memory-detail-heading">
                <span className={`memory-type memory-type-${selectedMemory.memory_type}`}>
                  {memoryTypeName(selectedMemory.memory_type)}
                </span>
                <span className={`memory-status memory-status-${selectedMemory.status}`}>
                  {memoryStatusName(selectedMemory.status)}
                </span>
              </div>
              <h3>{selectedMemory.summary || selectedMemory.content}</h3>
              <p>{selectedMemory.content}</p>
              <div className="memory-facts">
                <p>
                  <strong>来源</strong>
                  <span>{memoryProviderName(selectedMemory.source)}</span>
                </p>
                <p>
                  <strong>Freshness</strong>
                  <span>{freshnessName(selectedMemory.freshness)}</span>
                </p>
                <p>
                  <strong>更新时间</strong>
                  <span>{formatDateTime(selectedMemory.updated_at)}</span>
                </p>
              </div>

              <MemoryFactGroup title="证据" facts={evidenceFacts} emptyLabel="暂无证据字段" />
              <MemoryFactGroup
                title="来源链"
                facts={provenanceFacts}
                emptyLabel="暂无来源链字段"
              />
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function MemoryFactGroup({
  title,
  facts,
  emptyLabel
}: {
  title: string;
  facts: Array<{ label: string; value: string }>;
  emptyLabel: string;
}) {
  return (
    <div className="memory-fact-group">
      <strong>{title}</strong>
      {facts.length > 0 ? (
        facts.map((fact) => (
          <p key={`${title}-${fact.label}`}>
            <span>{fact.label}</span>
            <b>{fact.value}</b>
          </p>
        ))
      ) : (
        <small>{emptyLabel}</small>
      )}
    </div>
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
  const pathAblation = attribution?.path_ablation?.[0];
  const attributionGaps = evidenceGapItems(attribution?.evidence_gaps);
  const evidenceGaps = uniqueEvidenceGaps([
    ...evidenceGapItems(assembledContext?.evidence_gaps),
    ...evidenceGapItems(evidence?.evidence_gaps),
    ...attributionGaps
  ]);
  const errorRecords = evidenceGapItems(evidence?.error_records);
  const firstEvidenceGap = attributionGaps[0] ?? evidenceGaps[0] ?? errorRecords[0];
  const evidenceStatus = attributionEvidenceStatusLabel(attribution);
  const scorerSummary = attributionScorerSummary(attribution);
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
        {omittedContextAssets.length > 0 && (
          <div className="context-asset-list context-asset-list-omitted">
            {omittedContextAssets.map((asset) => (
              <ContextAssetRow key={`omitted-${contextAssetKey(asset)}`} asset={asset} />
            ))}
          </div>
        )}
        {evidenceGaps.length + errorRecords.length > 0 && (
          <div className="gap-list">
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
            <strong>Evidence source</strong>
            <span>{attribution?.evidence_source ?? "暂无"}</span>
          </p>
          <p>
            <strong>Scorer provenance</strong>
            <span>{scorerSummary}</span>
          </p>
          <p>
            <strong>Evidence gaps</strong>
            <span>{evidenceGaps.length + errorRecords.length} 项</span>
          </p>
          <p>
            <strong>Gap reason</strong>
            <span>{firstEvidenceGap?.reason ?? firstEvidenceGap?.message ?? "暂无"}</span>
          </p>
          <p>
            <strong>Canonical target</strong>
            <span>{canonicalTargetLabel(attribution)}</span>
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
            <strong>Top path id</strong>
            <span>{String(topPath?.path_id ?? "暂无")}</span>
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
          <p>
            <strong>Path ablation</strong>
            <span>{pathAblationSummary(pathAblation)}</span>
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
  const excluded = isExcludedAsset(asset);
  return (
    <div className={`context-asset ${excluded ? "context-asset-omitted" : ""}`}>
      <div className="context-asset-badges">
        <span className={`asset-badge asset-${asset.asset_type ?? "unknown"}`}>
          {assetTypeName(asset.asset_type)}
        </span>
        <span className={`asset-status ${excluded ? "asset-omitted" : "asset-selected"}`}>
          {excluded ? `${assetTypeName(asset.asset_type)} 已排除` : "Selected asset"}
        </span>
        <span className={`asset-provider ${providerBadgeClass(asset)}`}>
          {providerEvidenceLabel(asset)}
        </span>
      </div>
      <div>
        <strong>{asset.summary ?? "上下文资产"}</strong>
        <p>{asset.included_reason ?? asset.excluded_reason ?? "已纳入本轮上下文证据"}</p>
        <small>
          {contextAssetSourceLabel(asset)} · {freshnessName(asset.freshness)} · confidence{" "}
          {formatNumber(asset.confidence)}
        </small>
      </div>
    </div>
  );
}

function memoryEvidenceFacts(memory: StudentMemory) {
  return publicFacts(memory.evidence, [
    ["preferred_concept_id", "偏好知识点"],
    ["concept_id", "知识点"],
    ["question_id", "题目"],
    ["preferred_teaching_type", "偏好讲法"],
    ["source_event", "来源事件"],
    ["trace_id", "Trace"],
    ["event_time", "事件时间"]
  ]);
}

function memoryProvenanceFacts(memory: StudentMemory) {
  const facts = publicFacts(memory.provenance, [
    ["trace_id", "Trace"],
    ["session_id", "Session"],
    ["source_event", "来源事件"],
    ["event_type", "事件类型"],
    ["occurred_at", "发生时间"]
  ]);
  const provider = memory.provenance.provider;
  if (isRecord(provider)) {
    const providerName = primitiveText(provider.name);
    if (providerName) facts.unshift({ label: "Provider", value: providerName });
  }
  return facts;
}

function publicFacts(
  record: Record<string, unknown>,
  fields: Array<[key: string, label: string]>
) {
  return fields.flatMap(([key, label]) => {
    const value = primitiveText(record[key]);
    return value ? [{ label, value }] : [];
  });
}

function primitiveText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const parts = value.map(primitiveText).filter(Boolean);
    return parts.join("、");
  }
  return "";
}

function memoryTypeName(type: StudentMemory["memory_type"]) {
  return {
    preference: "偏好",
    repeated_mistake: "重复错因",
    effective_strategy: "有效策略",
    reflection: "反思"
  }[type];
}

function memoryStatusName(status: StudentMemory["status"]) {
  return status === "disabled" ? "已禁用" : "已启用";
}

function memoryProviderName(source: string) {
  return {
    local_fallback: "local fallback",
    fake_provider: "fake provider",
    mem0: "Mem0",
    mem0_unavailable: "Mem0 unavailable"
  }[source] ?? source;
}

function formatDateTime(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Date(timestamp).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
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

function uniqueEvidenceGaps(gaps: EvidenceGap[]) {
  const seen = new Set<string>();
  return gaps.filter((gap) => {
    const key = [
      gap.gap_type ?? gap.category,
      gap.reason ?? gap.message,
      gap.code,
      gap.sample_id
    ].join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function attributionEvidenceStatusLabel(
  attribution: AttributionEvidence | null | undefined
) {
  if (!attribution) return "暂无";
  const status = String(
    attribution.evidence_status
      ?? (attribution.top_paths?.[0]?.partial_evidence ? "partial" : "complete")
  );
  const source = attribution.evidence_source;
  if (status === "complete" && source === "offline") return "offline complete evidence";
  if (status === "complete") return "complete evidence";
  if (status === "partial") return source === "online_proxy" ? "partial online proxy" : "partial evidence";
  if (status === "unavailable") return "unavailable evidence";
  if (status === "invalid") return "invalid evidence";
  return source ? `${source} · ${status}` : status;
}

function attributionScorerSummary(
  attribution: AttributionEvidence | null | undefined
) {
  const scorer = attribution?.scorer;
  if (!scorer) return "暂无";
  const parts = [
    scorer.name,
    scorer.version,
    scorer.run_id,
    scorer.matching_method
  ].filter(Boolean);
  return parts.length > 0 ? parts.map(String).join(" · ") : "未记录";
}

function canonicalTargetLabel(
  attribution: AttributionEvidence | null | undefined
) {
  if (!attribution) return "暂无";
  const question =
    attribution.mapped_teaching_content?.question_id
    ?? attribution.canonical_mapping?.question_id
    ?? attribution.target_question_id;
  const concept =
    attribution.mapped_teaching_content?.concept_id
    ?? attribution.canonical_mapping?.concept_id
    ?? attribution.target_concept_id;
  return [question, concept].filter(Boolean).map(String).join(" · ") || "暂无";
}

function pathAblationSummary(value: Record<string, unknown> | undefined) {
  if (!value) return "暂无";
  const strategy = value.strategy ? `${String(value.strategy)} ` : "";
  const impact = formatNumber(value.impact);
  const comprehensiveness = formatNumber(value.comprehensiveness);
  return `${strategy}impact ${impact} · comp ${comprehensiveness}`;
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

  const assembledSelected = evidence?.assembled_context?.asset_selection?.selected ?? [];
  const assembledOmitted = evidence?.assembled_context?.asset_selection?.omitted ?? [];
  for (const asset of assembledSelected) {
    addAsset(asset, "included");
  }
  for (const asset of assembledOmitted) {
    addAsset(asset, "excluded");
  }
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
  if (asset.asset_id) return asset.asset_id;
  return (
    [asset.asset_type, asset.source_type, asset.source_ref, asset.summary]
      .filter(Boolean)
      .join("|") || "context-asset"
  );
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

function providerEvidenceLabel(asset: ContextAssetEvidence) {
  const providerMode = metadataString(asset, "provider_mode");
  if (providerMode === "fake_provider") return "fake provider";
  if (providerMode === "live_provider") return "live provider";
  if (providerMode === "local_fallback") return "local fallback";
  if (isProviderBackedAsset(asset)) return "provider-backed";
  if (isLocalFallbackAsset(asset)) return "local fallback";
  return "local evidence";
}

function providerBadgeClass(asset: ContextAssetEvidence) {
  const label = providerEvidenceLabel(asset);
  if (label === "fake provider") return "asset-provider-fake";
  if (label === "live provider") return "asset-provider-live";
  if (label === "local fallback") return "asset-provider-local";
  if (label === "provider-backed") return "asset-provider-backed";
  return "asset-provider-local";
}

function contextAssetSourceLabel(asset: ContextAssetEvidence) {
  if (isProviderBackedAsset(asset)) return providerEvidenceLabel(asset);
  if (isLocalFallbackAsset(asset)) return "local fallback";
  return sourceTypeName(asset.source_type);
}

function isProviderBackedAsset(asset: ContextAssetEvidence) {
  const providerBacked = asset.metadata?.provider_backed;
  const providerMode = metadataString(asset, "provider_mode");
  return (
    providerBacked === true ||
    asset.source_type === "provider_memory" ||
    asset.source_type === "provider_rag" ||
    providerMode === "fake_provider" ||
    providerMode === "live_provider"
  );
}

function isLocalFallbackAsset(asset: ContextAssetEvidence) {
  const providerMode = metadataString(asset, "provider_mode");
  return (
    providerMode === "local_fallback" ||
    asset.source_type === "local_fallback" ||
    asset.source_type === "local_rag" ||
    asset.source_type === "student_memory_store"
  );
}

function metadataString(asset: ContextAssetEvidence, key: string) {
  const value = asset.metadata?.[key];
  return typeof value === "string" ? value : "";
}

function sourceTypeName(value: string | undefined) {
  return {
    kt_engine: "KT evidence",
    learning_event: "learning event",
    learning_loop_event: "learning event",
    mistake_diagnoser: "mistake diagnosis",
    teaching_trace: "TeachingTrace",
    rag: "RAG evidence"
  }[value ?? ""] ?? "local context";
}

function gapLabel(gap: EvidenceGap) {
  return {
    student_memory: "缺少 memory evidence",
    knowledge_resource: "缺少 RAG citation",
    stale_task_state: "task_state 已过期",
    low_confidence_observation: "低置信度 tool observation",
    provider_failure: "provider failure",
    provider_timeout: "provider timeout",
    provider_auth_error: "provider auth error",
    provider_empty_result: "provider empty result",
    provider_schema_mismatch: "provider schema mismatch",
    provider_budget_exceeded: "provider budget exceeded",
    context_budget: "上下文预算裁剪",
    missing_content: "教学内容缺口",
    missing_mapping: "映射缺口",
    missing_rag_citation: "RAG citation 缺口",
    missing_artifact: "DGEKT offline artifact 缺失",
    missing_column: "DGEKT evidence 缺列",
    malformed_row: "DGEKT evidence 行异常",
    invalid_numeric_value: "DGEKT evidence 数值异常",
    duplicate_sample: "DGEKT evidence sample 重复",
    target_not_found: "DGEKT evidence 未匹配 target",
    canonical_mapping_mismatch: "DGEKT canonical mapping 不一致",
    checkpoint_provenance_mismatch: "DGEKT checkpoint provenance 不一致"
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
