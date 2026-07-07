import { render, screen, waitFor } from "@testing-library/react";
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
    errors: []
  },
  recommended_questions: [
    {
      question_id: "q_frac_001",
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
        top_paths: [{ path_id: "mock-path-1" }],
        key_history: [],
        weak_concepts: []
      },
      rag_sources: [
        {
          doc_id: "rag_fraction_addition",
          title: "异分母分数加法",
          source: "demo-rag/fraction_addition.md"
        }
      ],
      planner_decision: { decision: "recommend" },
      recommendations: []
    },
    invariants: ["KT facts are authoritative."],
    errors: []
  }
};

afterEach(() => {
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
    expect(screen.getByText("RAG 引用")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("q_frac_001 答案"), "3/4");
    await userEvent.click(screen.getByLabelText("提交答案"));

    await waitFor(() => {
      expect(screen.getByText(/服务端标准答案判定为正确/)).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][1]?.body).toContain("\"answer\":\"3/4\"");
  });
});

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}
