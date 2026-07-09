import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { MathTutorEventResponse } from "./types";

const baseResponse: MathTutorEventResponse = {
  trace_id: "tt-test",
  response: "下一步先练：1/2 + 1/4。做完后我会用标准答案确定性判题。",
  state_summary: {
    session_id: "demo",
    student_id: "student-demo",
    intent: "next_step_advice",
    progress_version: 1,
    concept_states: [
      {
        concept_id: "c_fraction_addition",
        concept_name: "异分母分数加法",
        teaching_type: "procedure",
        mastery: 0.42,
        forgetting_risk: 0.71,
        recent_accuracy: 0.33,
        evidence_count: 3,
        status: "weak"
      }
    ],
    weak_concepts: [{ concept_id: "c_fraction_addition", concept_name: "异分母分数加法" }],
    forgetting_risks: [{ concept_id: "c_fraction_addition", concept_name: "异分母分数加法" }],
    mistake_diagnosis: null,
    next_action: { type: "recommend_next_question" },
    errors: [],
    error_records: []
  },
  recommended_questions: [
    {
      question_id: "q_frac_001",
      assist2017_question_id: 1,
      stem: "计算：1/2 + 1/4 = ?",
      concept_id: "c_fraction_addition",
      concept_name: "异分母分数加法",
      difficulty: 0.35,
      teaching_type: "procedure",
      score: 0.82,
      reason: "匹配当前薄弱知识点；遗忘风险较高；难度与当前掌握度接近",
      score_factors: {
        weak_concept_match: 1,
        difficulty_fit: 0.8,
        forgetting_urgency: 0.7,
        novelty: 1,
        preference_fit: 0.5
      }
    }
  ],
  teaching_trace: [
    {
      id: "trace-1",
      stage: "load_context",
      actor: "system",
      visibility: "expert",
      content: "已读取学生学习进度。",
      metadata: {},
      evidence_refs: []
    },
    {
      id: "trace-2",
      stage: "generate_response",
      actor: "response",
      visibility: "student",
      content: "已生成学生可读中文回复。",
      metadata: {},
      evidence_refs: []
    }
  ],
  teaching_trace_summary: {
    trace_id: "tt-test",
    intent: "next_step_advice",
    stages: ["load_context", "generate_response"],
    student_explanation: "下一步先练：1/2 + 1/4。",
    expert_evidence: {
      kt_diagnosis: {
        weak_concepts: [{ concept_id: "c_fraction_addition" }],
        forgetting_risks: [{ concept_id: "c_fraction_addition" }],
        prediction_probability: 0.58,
        evidence: ["mock"]
      },
      attribution_evidence: {
        target_question_id: "q_frac_001",
        prediction_probability: 0.58,
        top_paths: [
          {
            path_id: "dgekt-partial-1-2-1",
            partial_evidence: true,
            history_assist2017_question_id: 1,
            target_assist2017_question_id: 2,
            path_weight: 0.85
          }
        ],
        key_history: [{ assist2017_question_id: 1, is_correct: false }],
        weak_concepts: []
      },
      rag_sources: [
        {
          doc_id: "rag_fraction_addition",
          doc_type: "concept_note",
          title: "异分母分数加法",
          source: "demo-rag/fraction_addition.md",
          concept_id: "c_fraction_addition",
          question_id: "q_frac_001",
          assist2017_question_id: 3,
          assist2017_concept_id: 2
        }
      ],
      planner_decision: { decision: "recommend" },
      recommendations: [],
      context_assets: [],
      assembled_context: {
        context_id: "assembled-test",
        budget_used: 45,
        budget_limit: 1200,
        compression_summary: {
          strategy: "priority_budget_summary",
          selected_asset_count: 4,
          excluded_asset_count: 1,
          candidate_asset_count: 5,
          budget_used: 45,
          budget_limit: 1200
        },
        asset_summaries: [
          {
            asset_id: "memory-preference",
            asset_type: "student_memory",
            source_type: "local_fallback",
            source_ref: "memory/student-demo",
            summary: "学生偏好步骤化讲解。",
            included_reason: "参考学生偏好",
            selection_status: "included",
            freshness: "recent",
            confidence: 0.86
          },
          {
            asset_id: "rag-concept-note",
            asset_type: "knowledge_resource",
            source_type: "local_rag",
            source_ref: "demo-rag/fraction_addition.md",
            summary: "异分母分数加法知识资源",
            included_reason: "参考相关知识资源",
            selection_status: "included",
            freshness: "fresh",
            confidence: 0.9
          },
          {
            asset_id: "tool-kt-snapshot",
            asset_type: "tool_observation",
            source_type: "kt_engine",
            source_ref: "tt-test",
            summary: "KT diagnosis snapshot",
            included_reason: "记录 KT 工具观察快照；不能覆盖当前 KT facts",
            selection_status: "included",
            freshness: "fresh",
            confidence: 1
          },
          {
            asset_id: "task-state-current",
            asset_type: "task_state",
            source_type: "learning_event",
            source_ref: "event/tt-test",
            summary: "当前推荐题 q_frac_001 待作答",
            included_reason: "记录当前任务状态；不能替代 progress runtime state",
            selection_status: "included",
            freshness: "fresh",
            confidence: 1
          },
          {
            asset_id: "trace-reference-old",
            asset_type: "trace_reference",
            source_type: "teaching_trace",
            source_ref: "trace-old",
            summary: "上一轮 trace reference",
            excluded_reason: "超出上下文预算，已裁剪低优先级资产",
            selection_status: "excluded",
            freshness: "stale",
            confidence: 0.5
          }
        ],
        evidence_gaps: [
          {
            gap_type: "context_budget",
            reason: "部分上下文资产因预算限制被裁剪"
          }
        ]
      },
      evidence_gaps: [
        {
          gap_type: "context_budget",
          reason: "部分上下文资产因预算限制被裁剪"
        }
      ],
      error_records: []
    },
    invariants: ["KT facts are authoritative."],
    errors: []
  }
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("学习驾驶舱", () => {
  it("可以加载建议、提交推荐题答案，并展示 trace 与证据", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(baseResponse))
      .mockResolvedValueOnce(jsonResponse({
        ...baseResponse,
        trace_id: "tt-answer",
        response: "收到，你提交的 q_frac_001 已由服务端标准答案判定为正确。"
      }));

    render(<App />);

    expect(await screen.findByText("学习驾驶舱")).toBeInTheDocument();
    expect(await screen.findByText("计算：1/2 + 1/4 = ?")).toBeInTheDocument();
    expect(screen.getByText("TeachingTrace")).toBeInTheDocument();
    expect(screen.getByText("读取上下文")).toBeInTheDocument();
    expect(screen.getByText("RAG 引用")).toBeInTheDocument();
    expect(screen.getByText("题 q_frac_001 · 知识点 c_fraction_addition · ASSIST2017 Q3 · C2")).toBeInTheDocument();
    expect(screen.getByText("模型证据")).toBeInTheDocument();
    expect(screen.getByText("KT 预测")).toBeInTheDocument();
    expect(screen.getByText("DGEKT attribution")).toBeInTheDocument();
    expect(screen.getByText("partial evidence")).toBeInTheDocument();
    expect(screen.getByText("1 -> 2")).toBeInTheDocument();
    expect(screen.getByText("0.850")).toBeInTheDocument();
    expect(screen.getByText("上下文证据")).toBeInTheDocument();
    expect(screen.getByText("45/1200")).toBeInTheDocument();
    expect(screen.getByText("priority_budget_summary")).toBeInTheDocument();
    expect(screen.getByText("Memory evidence")).toBeInTheDocument();
    expect(screen.getByText("RAG citation")).toBeInTheDocument();
    expect(screen.getByText("Tool snapshot")).toBeInTheDocument();
    expect(screen.getByText("Task state")).toBeInTheDocument();
    expect(screen.getByText("学生偏好步骤化讲解。")).toBeInTheDocument();
    expect(screen.getByText("参考相关知识资源")).toBeInTheDocument();
    expect(screen.getByText("Trace reference 已排除")).toBeInTheDocument();
    expect(screen.getByText("部分上下文资产因预算限制被裁剪")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("q_frac_001 答案"), "3/4");
    await userEvent.click(screen.getByLabelText("提交答案"));

    await waitFor(() => {
      expect(screen.getByText(/服务端标准答案判定为正确/)).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][1]?.body).toContain("\"answer\":\"3/4\"");
    expect(fetchMock.mock.calls[1][1]?.body).toContain("\"assist2017_question_id\":1");
  });

  it("没有上下文资产时保持推荐主流程可用并展示 fallback", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({
      ...baseResponse,
      teaching_trace_summary: {
        ...baseResponse.teaching_trace_summary,
        expert_evidence: {
          ...baseResponse.teaching_trace_summary.expert_evidence,
          context_assets: [],
          assembled_context: null,
          evidence_gaps: []
        }
      }
    }));

    render(<App />);

    expect(await screen.findByText("计算：1/2 + 1/4 = ?")).toBeInTheDocument();
    expect(screen.getByText("上下文证据")).toBeInTheDocument();
    expect(screen.getByText("本轮没有上下文资产；主学习流程仍按 KT facts 和默认内容运行。")).toBeInTheDocument();
    expect(screen.getAllByText("暂无").length).toBeGreaterThan(0);
  });

  it("展示答题提交追加的 task/tool/trace 上下文证据", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({
      ...baseResponse,
      trace_id: "tt-answer-context",
      teaching_trace_summary: {
        ...baseResponse.teaching_trace_summary,
        expert_evidence: {
          ...baseResponse.teaching_trace_summary.expert_evidence,
          context_asset_selection: {
            selected: [
              {
                asset_id: "answer-task-state",
                asset_type: "task_state",
                source_type: "learning_loop_event",
                source_ref: "event:tt-answer-context:answer_submitted",
                summary: "answer_submitted question=q_frac_001; is_correct=false",
                included_reason: "记录答题 task_state 快照；权威 runtime state 仍在 progress/event/trace",
                freshness: "fresh",
                confidence: 1
              },
              {
                asset_id: "answer-mistake-tool",
                asset_type: "tool_observation",
                source_type: "mistake_diagnoser",
                source_ref: "mistake:tt-answer-context:diagnosis",
                summary: "mistake diagnosis snapshot for q_frac_001",
                included_reason: "记录错因诊断工具观察快照",
                freshness: "fresh",
                confidence: 0.85
              },
              {
                asset_id: "answer-trace-ref",
                asset_type: "trace_reference",
                source_type: "teaching_trace",
                source_ref: "trace:tt-answer-context:answer_submission",
                summary: "answer_submitted trace references retrieval, decision, and memory-update source",
                included_reason: "记录 trace 引用，串联检索路径、决策证据和 memory update 来源",
                freshness: "fresh",
                confidence: 1
              }
            ],
            omitted: []
          }
        }
      }
    }));

    render(<App />);

    expect(await screen.findByText("上下文证据")).toBeInTheDocument();
    expect(screen.getByText("answer_submitted question=q_frac_001; is_correct=false")).toBeInTheDocument();
    expect(screen.getByText("记录错因诊断工具观察快照")).toBeInTheDocument();
    expect(screen.getByText("answer_submitted trace references retrieval, decision, and memory-update source")).toBeInTheDocument();
  });

  it("后端不可达时展示中文错误和重试入口", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("网络不可用"));

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("网络不可用");
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("后端返回可恢复 evidence gap 时在顶部展示处理提示", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({
      ...baseResponse,
      state_summary: {
        ...baseResponse.state_summary,
        errors: ["q_missing_answer 缺少标准答案，请补齐教学内容后再用于完整练习。"],
        error_records: [
          {
            code: "missing_standard_answer",
            category: "missing_content",
            stage: "load_context",
            message: "q_missing_answer 缺少标准答案，请补齐教学内容后再用于完整练习。",
            actionable_hint: "补齐题目的 standard_answer 后再用于完整练习。",
            severity: "warning",
            recoverable: true
          }
        ]
      },
      teaching_trace_summary: {
        ...baseResponse.teaching_trace_summary,
        expert_evidence: {
          ...baseResponse.teaching_trace_summary.expert_evidence,
          evidence_gaps: [
            {
              gap_type: "missing_content",
              reason: "q_missing_answer 缺少标准答案，请补齐教学内容后再用于完整练习。"
            }
          ],
          error_records: [
            {
              category: "missing_content",
              message: "q_missing_answer 缺少标准答案，请补齐教学内容后再用于完整练习。"
            }
          ]
        }
      }
    }));

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("q_missing_answer 缺少标准答案");
    expect(screen.getByRole("alert")).toHaveTextContent("补齐题目的 standard_answer");
    expect(screen.getAllByText("Evidence gaps").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2 项").length).toBeGreaterThan(0);
    expect(screen.getAllByText("教学内容缺口").length).toBeGreaterThan(0);
    expect(screen.getAllByText("q_missing_answer 缺少标准答案，请补齐教学内容后再用于完整练习。").length).toBeGreaterThan(0);
  });

  it("后端返回 DGEKT detail 时展示可理解错误", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "DGEKT 映射失败：缺少 ASSIST2017 题目映射" }), {
        status: 400,
        headers: { "Content-Type": "application/json" }
      })
    );

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "事件处理失败：400 DGEKT 映射失败：缺少 ASSIST2017 题目映射"
    );
  });
});

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}
