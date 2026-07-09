import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type {
  MathTutorEventResponse,
  ProviderHealthResponse,
  StudentMemoryListResponse
} from "./types";

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
      id: "trace-runtime-start",
      stage: "runtime_start",
      actor: "runtime",
      visibility: "expert",
      content: "MathTutorAgentRuntime 已接收本轮数学学习事件。",
      metadata: {},
      evidence_refs: []
    },
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
      stage: "kt_tool_observation",
      actor: "kt",
      visibility: "expert",
      content: "Tool Registry 已记录 KT/DGEKT 权威学习事实 observation。",
      metadata: {
        tool_id: "kt_authoritative_facts",
        provider_mode: "local_fallback",
        fallback_used: true
      },
      evidence_refs: ["trace:tt-test", "kt_diagnosis:tt-test"]
    },
    {
      id: "trace-rag-tool",
      stage: "rag_tool_observation",
      actor: "rag",
      visibility: "expert",
      content: "Tool Registry 已记录 RAG 数学知识检索 observation。",
      metadata: {
        tool_id: "rag_retrieval_evidence",
        provider_mode: "local_fallback",
        fallback_used: true
      },
      evidence_refs: ["trace:tt-test", "demo-rag/fraction_addition.md"]
    },
    {
      id: "trace-memory-tool",
      stage: "memory_tool_observation",
      actor: "memory",
      visibility: "expert",
      content: "Tool Registry 已记录学生记忆 observation。",
      metadata: {
        tool_id: "student_memory_evidence",
        provider_mode: "local_fallback",
        fallback_used: true
      },
      evidence_refs: ["trace:tt-test", "memory:mem-preference-1"]
    },
    {
      id: "trace-3",
      stage: "generate_response",
      actor: "response",
      visibility: "student",
      content: "已生成学生可读中文回复。",
      metadata: {},
      evidence_refs: []
    },
    {
      id: "trace-runtime-end",
      stage: "runtime_end",
      actor: "runtime",
      visibility: "expert",
      content: "MathTutorAgentRuntime 已完成本轮学习编排。",
      metadata: {},
      evidence_refs: ["trace:tt-test"]
    }
  ],
  teaching_trace_summary: {
    trace_id: "tt-test",
    intent: "next_step_advice",
    stages: [
      "runtime_start",
      "load_context",
      "kt_tool_observation",
      "rag_tool_observation",
      "memory_tool_observation",
      "generate_response",
      "runtime_end"
    ],
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
      tool_registry_manifest: [
        {
          tool_id: "kt_authoritative_facts",
          name: "KT/DGEKT 权威学习事实"
        },
        {
          tool_id: "rag_retrieval_evidence",
          name: "RAG 数学知识检索证据"
        },
        {
          tool_id: "student_memory_evidence",
          name: "学生记忆证据"
        }
      ],
      tool_observations: [
        {
          tool_id: "kt_authoritative_facts",
          provider_mode: "local_fallback",
          fallback_used: true
        },
        {
          tool_id: "rag_retrieval_evidence",
          provider_mode: "local_fallback",
          fallback_used: true,
          result_summary: {
            result_count: 1,
            citation_refs: ["demo-rag/fraction_addition.md"]
          }
        },
        {
          tool_id: "student_memory_evidence",
          provider_mode: "local_fallback",
          fallback_used: true,
          result_summary: {
            retrieved_count: 1,
            selected_count: 1,
            omitted_count: 0
          }
        }
      ],
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

const baseMemoryResponse: StudentMemoryListResponse = {
  student_id: "student-demo",
  count: 2,
  memories: [
    {
      memory_id: "mem-preference-1",
      memory_type: "preference",
      content: "学生偏好先看分数通分的步骤化讲解。",
      summary: "偏好步骤化分数讲解",
      source: "local_fallback",
      evidence: {
        preferred_concept_id: "c_fraction_addition",
        raw_provider_payload: "should_not_render",
        embedding_vector: [0.1, 0.2, 0.3]
      },
      provenance: {
        trace_id: "tt-memory-1",
        source_event: "event:tt-memory-1:answer_submitted",
        provider_debug: "should_not_render"
      },
      created_at: "2026-07-09T08:00:00+00:00",
      updated_at: "2026-07-09T08:20:00+00:00",
      freshness: "fresh",
      enabled: true,
      status: "enabled"
    },
    {
      memory_id: "mem-mistake-1",
      memory_type: "repeated_mistake",
      content: "学生在分数通分时经常忘记找公分母。",
      summary: "通分时忘记公分母",
      source: "fake_provider",
      evidence: {
        concept_id: "c_fraction_addition",
        question_id: "q_frac_001"
      },
      provenance: {
        provider: { name: "fake_mem0_fixture", record_id: "hidden-provider-id" },
        trace_id: "tt-memory-2"
      },
      created_at: "2026-07-08T08:00:00+00:00",
      updated_at: "2026-07-09T07:20:00+00:00",
      freshness: "recent",
      enabled: true,
      status: "enabled"
    }
  ]
};

const baseProviderHealthResponse: ProviderHealthResponse = {
  status: "healthy",
  summary: "默认本地 fallback / mock / demo provider 状态可运行。",
  generated_at: "2026-07-09T08:30:00+00:00",
  components: [
    {
      component: "memory",
      display_name: "Memory / 长期记忆",
      mode: "local_fallback",
      provider: "local_fallback",
      configured: true,
      status: "healthy",
      severity: "info",
      recoverable: true,
      actionable_hint: "默认本地长期记忆 fallback 可运行；Mem0 live provider 未启用。",
      evidence_gaps: [],
      last_checked_at: "2026-07-09T08:30:00+00:00"
    },
    {
      component: "rag",
      display_name: "RAG / 知识检索",
      mode: "local_fallback",
      provider: "local_fallback",
      configured: true,
      status: "healthy",
      severity: "info",
      recoverable: true,
      actionable_hint: "默认本地 RAG fallback 可运行；VikingDB / OpenViking live provider 未启用。",
      evidence_gaps: [],
      last_checked_at: "2026-07-09T08:30:00+00:00"
    },
    {
      component: "kt",
      display_name: "KT / DGEKT",
      mode: "mock",
      provider: "mock",
      configured: true,
      status: "healthy",
      severity: "info",
      recoverable: true,
      actionable_hint: "默认 mock KT 可运行；真实 DGEKT checkpoint 未启用，KT facts 仍是权威学习事实。",
      evidence_gaps: [],
      last_checked_at: "2026-07-09T08:30:00+00:00"
    },
    {
      component: "content_rag_artifact",
      display_name: "Content/RAG artifact",
      mode: "content:demo/rag:demo",
      provider: "demo_artifacts",
      configured: true,
      status: "healthy",
      severity: "info",
      recoverable: true,
      actionable_hint: "默认 demo content 与 demo RAG artifact 可运行；当前未要求 full ASSISTments2017 或 generated vector index。",
      evidence_gaps: [],
      last_checked_at: "2026-07-09T08:30:00+00:00"
    },
    {
      component: "learning_context",
      display_name: "LearningContextLayer",
      mode: "local_fallback",
      provider: "in_memory_context_layer",
      configured: true,
      status: "healthy",
      severity: "info",
      recoverable: true,
      actionable_hint: "LearningContextLayer 使用本地上下文组装证据；它只汇总 evidence，不决定 mastery 或 KT facts。",
      evidence_gaps: [],
      last_checked_at: "2026-07-09T08:30:00+00:00"
    }
  ]
};

const degradedProviderHealthResponse: ProviderHealthResponse = {
  ...baseProviderHealthResponse,
  status: "not_configured",
  summary: "Memory/RAG live provider 存在配置缺口；默认学习流程仍可继续。",
  components: baseProviderHealthResponse.components.map((component) => {
    if (component.component === "memory") {
      return {
        ...component,
        mode: "live_provider",
        provider: "mem0",
        configured: false,
        status: "degraded",
        severity: "warning",
        actionable_hint: "Mem0 live provider 可诊断但当前降级；请检查 MATHTUTOR_MEM0_API_KEY。",
        evidence_gaps: [
          {
            gap_type: "provider_configuration_missing",
            reason: "mem0 readiness 缺少必要配置。",
            severity: "warning",
            recoverable: true,
            actionable_hint: "请补齐 Mem0 API key 或切回默认 local_fallback。"
          }
        ]
      };
    }
    if (component.component === "rag") {
      return {
        ...component,
        mode: "live_provider",
        provider: "openviking",
        configured: false,
        status: "unavailable",
        severity: "error",
        actionable_hint: "OpenViking live RAG 不可用；检查 endpoint、collection 和 API key。",
        evidence_gaps: [
          {
            gap_type: "provider_auth_error",
            reason: "openviking readiness 无法完成认证。",
            severity: "error",
            recoverable: true,
            actionable_hint: "请确认 OpenViking API key 仍有效。"
          }
        ]
      };
    }
    return component;
  })
};

const ktArtifactProviderHealthResponse: ProviderHealthResponse = {
  ...baseProviderHealthResponse,
  status: "degraded",
  summary: "DGEKT 与 imported artifact readiness 存在降级；默认学习流程仍可继续。",
  components: baseProviderHealthResponse.components.map((component) => {
    if (component.component === "kt") {
      return {
        ...component,
        mode: "dgekt",
        provider: "dgekt",
        configured: true,
        status: "degraded",
        severity: "warning",
        actionable_hint: "DGEKT 核心配置可诊断，但 offline evidence 未配置；当前只能视为 partial readiness。"
      };
    }
    if (component.component === "content_rag_artifact") {
      return {
        ...component,
        mode: "content:imported/rag:imported",
        provider: "imported_artifacts",
        configured: false,
        status: "unavailable",
        severity: "error",
        actionable_hint: "Content/RAG artifact readiness 存在缺口；补齐导入路径或切回 demo。"
      };
    }
    if (component.component === "learning_context") {
      return {
        ...component,
        mode: "context_evidence_assembly",
        provider: "in_memory_context_layer",
        configured: true,
        status: "healthy",
        severity: "info",
        actionable_hint: "LearningContextLayer 会组装当前 Memory/RAG/Content/KT 证据；只保留 evidence gap，不改写学习事实。"
      };
    }
    return component;
  })
};

const providerGapSanitizedHealthResponse: ProviderHealthResponse = {
  ...baseProviderHealthResponse,
  status: "unavailable",
  summary: "Provider gap 已归一为安全诊断；默认学习流程仍可继续。",
  components: baseProviderHealthResponse.components.map((component) => {
    if (component.component === "rag") {
      return {
        ...component,
        mode: "live_provider",
        provider: "openviking",
        configured: true,
        status: "unavailable",
        severity: "warning",
        actionable_hint: "provider 请求超时；请检查 endpoint、网络和 timeout 配置。",
        evidence_gaps: [
          {
            gap_type: "provider_timeout",
            reason: "provider 请求超时。",
            severity: "warning",
            recoverable: true,
            actionable_hint: "检查 endpoint、网络和 timeout 配置；必要时切回 local_fallback。",
            details: {
              raw_provider_payload: "raw_provider_payload_should_not_render",
              sdk_response: "sdk_response_should_not_render",
              embedding_vector: [0.1, 0.2, 0.3],
              provider_debug: "provider_debug_should_not_render",
              authorization: "Bearer token_should_not_render",
              safe_summary: "safe_summary_should_not_render"
            }
          }
        ]
      };
    }
    return component;
  })
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("学习驾驶舱", () => {
  it("展示系统 Provider 状态面板和默认本地 fallback 可运行状态", async () => {
    mockMathTutorApi();

    render(<App />);

    expect(await screen.findByText("系统状态 / Provider 状态")).toBeInTheDocument();
    expect(screen.getByText("默认本地 fallback / mock / demo provider 状态可运行。")).toBeInTheDocument();
    expect(screen.getByText("Memory / 长期记忆")).toBeInTheDocument();
    expect(screen.getByText("RAG / 知识检索")).toBeInTheDocument();
    expect(screen.getByText("KT / DGEKT")).toBeInTheDocument();
    expect(screen.getByText("Content/RAG artifact")).toBeInTheDocument();
    expect(screen.getByText("LearningContextLayer")).toBeInTheDocument();
    expect(screen.getAllByText("正常").length).toBeGreaterThanOrEqual(6);
    expect(screen.getAllByText("local_fallback").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText("demo_artifacts")).toBeInTheDocument();
    expect(screen.getByText(/本地长期记忆 fallback 可运行/)).toBeInTheDocument();
    expect(screen.getByText(/本地 RAG fallback 可运行/)).toBeInTheDocument();
    expect(screen.queryByText(/raw_provider_payload/)).not.toBeInTheDocument();
    expect(screen.queryByText(/embedding_vector/)).not.toBeInTheDocument();
    expect(screen.queryByText(/provider_debug/)).not.toBeInTheDocument();
  });

  it("展示 Memory/RAG readiness 的降级、不可用、未配置和严重程度，不阻断推荐题", async () => {
    mockMathTutorApi({
      providerHealthResponse: degradedProviderHealthResponse
    });

    render(<App />);

    expect(await screen.findByText("计算：1/2 + 1/4 = ?")).toBeInTheDocument();
    expect(screen.getByText("Memory/RAG live provider 存在配置缺口；默认学习流程仍可继续。")).toBeInTheDocument();
    expect(screen.getAllByText("未配置").length).toBeGreaterThan(0);
    expect(screen.getByText("Memory / 长期记忆")).toBeInTheDocument();
    expect(screen.getByText("RAG / 知识检索")).toBeInTheDocument();
    expect(screen.getByText("mem0")).toBeInTheDocument();
    expect(screen.getByText("openviking")).toBeInTheDocument();
    expect(screen.getAllByText("live_provider").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("降级")).toBeInTheDocument();
    expect(screen.getByText("不可用")).toBeInTheDocument();
    expect(screen.getByText("警告")).toBeInTheDocument();
    expect(screen.getByText("错误")).toBeInTheDocument();
    expect(screen.getByText(/MATHTUTOR_MEM0_API_KEY/)).toBeInTheDocument();
    expect(screen.getByText(/OpenViking live RAG 不可用/)).toBeInTheDocument();
  });

  it("Provider Health 降级时仍可用 fallback 提交推荐题答案", async () => {
    const fetchMock = mockMathTutorApi({
      providerHealthResponse: degradedProviderHealthResponse,
      eventResponses: [
        baseResponse,
        {
          ...baseResponse,
          trace_id: "tt-health-degraded-answer",
          response: "收到，你提交的 q_frac_001 已由服务端标准答案判定为正确。"
        }
      ]
    });

    render(<App />);

    expect(await screen.findByText("计算：1/2 + 1/4 = ?")).toBeInTheDocument();
    expect(screen.getByText("Memory/RAG live provider 存在配置缺口；默认学习流程仍可继续。")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("q_frac_001 答案"), "3/4");
    await userEvent.click(screen.getByLabelText("提交答案"));

    await waitFor(() => {
      expect(screen.getByText(/服务端标准答案判定为正确/)).toBeInTheDocument();
    });
    const eventCalls = eventFetchCalls(fetchMock);
    expect(eventCalls).toHaveLength(2);
    expect(eventCalls[1][1]?.body).toContain("\"type\":\"answer_submitted\"");
    expect(eventCalls[1][1]?.body).toContain("\"answer\":\"3/4\"");
    expect(eventCalls[1][1]?.body).toContain("\"assist2017_question_id\":1");
  });

  it("展示 KT/DGEKT、Content/RAG artifact 与 LearningContextLayer readiness", async () => {
    mockMathTutorApi({
      providerHealthResponse: ktArtifactProviderHealthResponse
    });

    render(<App />);

    expect(await screen.findByText("计算：1/2 + 1/4 = ?")).toBeInTheDocument();
    expect(screen.getByText("DGEKT 与 imported artifact readiness 存在降级；默认学习流程仍可继续。")).toBeInTheDocument();
    expect(screen.getByText("KT / DGEKT")).toBeInTheDocument();
    expect(screen.getAllByText("dgekt").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/offline evidence 未配置/)).toBeInTheDocument();
    expect(screen.getByText("Content/RAG artifact")).toBeInTheDocument();
    expect(screen.getByText("content:imported/rag:imported")).toBeInTheDocument();
    expect(screen.getByText("imported_artifacts")).toBeInTheDocument();
    expect(screen.getByText(/补齐导入路径或切回 demo/)).toBeInTheDocument();
    expect(screen.getByText("LearningContextLayer")).toBeInTheDocument();
    expect(screen.getByText("context_evidence_assembly")).toBeInTheDocument();
    expect(screen.getByText(/不改写学习事实/)).toBeInTheDocument();
  });

  it("展示 provider gap 中文摘要，但不渲染 raw payload、SDK response、embedding 或 debug details", async () => {
    mockMathTutorApi({
      providerHealthResponse: providerGapSanitizedHealthResponse
    });

    render(<App />);

    expect(await screen.findByText("Provider gap 已归一为安全诊断；默认学习流程仍可继续。")).toBeInTheDocument();
    expect(screen.getByText("provider 请求超时")).toBeInTheDocument();
    expect(screen.getByText("provider 请求超时。")).toBeInTheDocument();
    expect(screen.getAllByText(/检查 endpoint、网络和 timeout 配置/).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/raw_provider_payload_should_not_render/)).not.toBeInTheDocument();
    expect(screen.queryByText(/sdk_response_should_not_render/)).not.toBeInTheDocument();
    expect(screen.queryByText(/provider_debug_should_not_render/)).not.toBeInTheDocument();
    expect(screen.queryByText(/token_should_not_render/)).not.toBeInTheDocument();
    expect(screen.queryByText(/safe_summary_should_not_render/)).not.toBeInTheDocument();
  });

  it("可以加载建议、提交推荐题答案，并展示 trace 与证据", async () => {
    const fetchMock = mockMathTutorApi({
      eventResponses: [
        baseResponse,
        {
        ...baseResponse,
        trace_id: "tt-answer",
        response: "收到，你提交的 q_frac_001 已由服务端标准答案判定为正确。"
        }
      ]
    });

    render(<App />);

    expect(await screen.findByText("学习驾驶舱")).toBeInTheDocument();
    expect(await screen.findByText("计算：1/2 + 1/4 = ?")).toBeInTheDocument();
    expect(screen.getByText("TeachingTrace")).toBeInTheDocument();
    expect(screen.getByText("Runtime 开始")).toBeInTheDocument();
    expect(screen.getByText("读取上下文")).toBeInTheDocument();
    expect(screen.getByText("KT 工具观察")).toBeInTheDocument();
    expect(screen.getByText("RAG 工具观察")).toBeInTheDocument();
    expect(screen.getByText("记忆工具观察")).toBeInTheDocument();
    expect(screen.getByText("Runtime 结束")).toBeInTheDocument();
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
    expect(screen.getAllByText("部分上下文资产因预算限制被裁剪").length).toBeGreaterThan(0);
    expect(screen.getByText("长期记忆")).toBeInTheDocument();
    expect((await screen.findAllByText("偏好步骤化分数讲解")).length).toBeGreaterThan(0);
    expect(screen.getByText("偏好知识点")).toBeInTheDocument();
    expect(screen.getByText("来源链")).toBeInTheDocument();
    expect(screen.queryByText(/should_not_render/)).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("q_frac_001 答案"), "3/4");
    await userEvent.click(screen.getByLabelText("提交答案"));

    await waitFor(() => {
      expect(screen.getByText(/服务端标准答案判定为正确/)).toBeInTheDocument();
    });
    const eventCalls = eventFetchCalls(fetchMock);
    expect(eventCalls).toHaveLength(2);
    expect(eventCalls[1][1]?.body).toContain("\"answer\":\"3/4\"");
    expect(eventCalls[1][1]?.body).toContain("\"assist2017_question_id\":1");
  });

  it("没有上下文资产时保持推荐主流程可用并展示 fallback", async () => {
    mockMathTutorApi({
      eventResponses: [{
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
      }]
    });

    render(<App />);

    expect(await screen.findByText("计算：1/2 + 1/4 = ?")).toBeInTheDocument();
    expect(screen.getByText("上下文证据")).toBeInTheDocument();
    expect(screen.getByText("本轮没有上下文资产；主学习流程仍按 KT facts 和默认内容运行。")).toBeInTheDocument();
    expect(screen.getAllByText("暂无").length).toBeGreaterThan(0);
  });

  it("长期记忆读取中展示加载状态", async () => {
    mockMathTutorApi({ memoryPending: true });

    render(<App />);

    expect(await screen.findByText("正在读取长期记忆...")).toBeInTheDocument();
  });

  it("长期记忆为空时展示空状态", async () => {
    mockMathTutorApi({
      memoryResponse: {
        student_id: "student-demo",
        count: 0,
        memories: []
      }
    });

    render(<App />);

    expect(await screen.findByText("暂无长期记忆；完成练习或产生偏好后会出现在这里。")).toBeInTheDocument();
  });

  it("长期记忆读取失败时展示面板级错误，不影响推荐主流程", async () => {
    mockMathTutorApi({
      memoryError: new Response(JSON.stringify({ detail: "memory provider unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" }
      })
    });

    render(<App />);

    expect(await screen.findByText("计算：1/2 + 1/4 = ?")).toBeInTheDocument();
    expect(await screen.findByText(/学生记忆读取失败：503 memory provider unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新长期记忆" })).toBeInTheDocument();
  });

  it("可以在长期记忆面板禁用并重新启用单条记忆", async () => {
    const fetchMock = mockMathTutorApi();

    render(<App />);

    expect((await screen.findAllByText("偏好步骤化分数讲解")).length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("button", { name: "禁用记忆" }));

    expect(await screen.findByRole("button", { name: "重新启用记忆" })).toBeInTheDocument();
    expect(screen.getAllByText("已禁用").length).toBeGreaterThan(0);
    expect(screen.getByText("控制操作")).toBeInTheDocument();
    expect(screen.getByText("disable")).toBeInTheDocument();
    expect(screen.getByText("学生在记忆控制面板中禁用该记忆。")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "重新启用记忆" }));

    expect(await screen.findByRole("button", { name: "禁用记忆" })).toBeInTheDocument();
    expect(screen.getAllByText("已启用").length).toBeGreaterThan(0);

    const memoryControlCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).includes("/api/students/student-demo/memories/mem-preference-1/")
    );
    expect(memoryControlCalls.map(([input]) => String(input))).toEqual([
      "/api/students/student-demo/memories/mem-preference-1/disable",
      "/api/students/student-demo/memories/mem-preference-1/enable"
    ]);
    expect(memoryControlCalls[0][1]?.body).toContain("学生在记忆控制面板中禁用该记忆。");
    expect(memoryControlCalls[1][1]?.body).toContain("学生在记忆控制面板中重新启用该记忆。");
  });

  it("删除长期记忆前需要确认，成功后从列表移除并展示成功状态", async () => {
    const fetchMock = mockMathTutorApi();

    render(<App />);

    expect((await screen.findAllByText("偏好步骤化分数讲解")).length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("button", { name: "删除记忆" }));

    expect(screen.getByRole("button", { name: "确认删除" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect(await screen.findByText("已删除该条长期记忆。")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("偏好步骤化分数讲解")).not.toBeInTheDocument();
    });

    const deleteCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input) === "/api/students/student-demo/memories/mem-preference-1" &&
        init?.method === "DELETE"
    );
    expect(deleteCall?.[1]?.body).toContain("学生在记忆控制面板中删除该记忆。");
  });

  it("删除长期记忆失败时保留列表并展示失败状态", async () => {
    mockMathTutorApi({
      memoryDeleteError: new Response(
        JSON.stringify({
          detail: {
            code: "provider_timeout",
            message: "mem0 memory_delete failed: provider timed out",
            actionable_hint: "请稍后重试；默认学习流程会继续使用可用的本地证据。",
            recoverable: true
          }
        }),
        {
          status: 503,
          headers: { "Content-Type": "application/json" }
        }
      )
    });

    render(<App />);

    expect((await screen.findAllByText("偏好步骤化分数讲解")).length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("button", { name: "删除记忆" }));
    await userEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect(
      await screen.findByText(/学生记忆删除失败：503 mem0 memory_delete failed/)
    ).toBeInTheDocument();
    expect(screen.getByText(/默认学习流程会继续使用可用的本地证据/)).toBeInTheDocument();
    expect(screen.getAllByText("偏好步骤化分数讲解").length).toBeGreaterThan(0);
  });

  it("展示 provider-backed selected/omitted context evidence 并隐藏 SDK 噪声", async () => {
    mockMathTutorApi({
      eventResponses: [{
      ...baseResponse,
      teaching_trace_summary: {
        ...baseResponse.teaching_trace_summary,
        expert_evidence: {
          ...baseResponse.teaching_trace_summary.expert_evidence,
          context_assets: [],
          assembled_context: {
            ...baseResponse.teaching_trace_summary.expert_evidence.assembled_context,
            asset_summaries: [],
            asset_selection: {
              selected: [
                {
                  asset_id: "provider-memory-selected",
                  asset_type: "student_memory",
                  source_type: "provider_memory",
                  source_ref: "collection://hidden-provider-memory/private-record",
                  summary: "学生更容易接受分步骤提示。",
                  included_reason: "参考 provider-backed 学生偏好",
                  selection_status: "included",
                  freshness: "fresh",
                  confidence: 0.94,
                  metadata: {
                    provider_backed: true,
                    provider_mode: "fake_provider",
                    provider_name: "fake_mem0_fixture",
                    provider_record_id: "mem-hidden-record",
                    sdk_response: "sdk_response_should_not_render",
                    embedding_vector: "embedding_vector_should_not_render",
                    provider_debug: "provider_debug_should_not_render"
                  }
                },
                {
                  asset_id: "provider-rag-selected",
                  asset_type: "knowledge_resource",
                  source_type: "provider_rag",
                  source_ref: "collection://hidden-rag/private-doc",
                  summary: "Provider RAG 题解：先通分再相加。",
                  included_reason: "参考 provider-backed 知识资源",
                  selection_status: "included",
                  freshness: "fresh",
                  confidence: 0.91,
                  metadata: {
                    provider_backed: true,
                    provider_mode: "fake_provider",
                    provider_name: "fake_vikingdb",
                    provider_debug: "rag_debug_should_not_render"
                  }
                }
              ],
              omitted: [
                {
                  asset_id: "provider-rag-omitted",
                  asset_type: "knowledge_resource",
                  source_type: "provider_rag",
                  source_ref: "collection://hidden-rag/omitted-private-doc",
                  summary: "Provider RAG 长文档",
                  excluded_reason: "超出上下文预算，已裁剪低优先级 provider 证据",
                  selection_status: "excluded",
                  freshness: "stale",
                  confidence: 0.72,
                  metadata: {
                    provider_backed: true,
                    provider_mode: "fake_provider",
                    provider_name: "fake_vikingdb",
                    provider_debug: "omitted_debug_should_not_render"
                  }
                }
              ]
            },
            evidence_gaps: [
              {
                gap_type: "provider_timeout",
                reason: "fake_vikingdb search timed out; local flow continues."
              }
            ]
          },
          evidence_gaps: [
            {
              gap_type: "provider_timeout",
              reason: "fake_vikingdb search timed out; local flow continues."
            }
          ],
          error_records: []
        }
      }
      }]
    });

    render(<App />);

    expect(await screen.findByText("上下文证据")).toBeInTheDocument();
    expect(screen.getByText("学生更容易接受分步骤提示。")).toBeInTheDocument();
    expect(screen.getByText("Provider RAG 题解：先通分再相加。")).toBeInTheDocument();
    expect(screen.getByText("Provider RAG 长文档")).toBeInTheDocument();
    expect(screen.getAllByText("Selected asset").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("RAG citation 已排除")).toBeInTheDocument();
    expect(screen.getAllByText("fake provider").length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("provider 请求超时").length).toBeGreaterThan(0);
    expect(screen.getAllByText("fake_vikingdb search timed out; local flow continues.").length).toBeGreaterThan(0);
    expect(screen.queryByText(/hidden-provider-memory/)).not.toBeInTheDocument();
    expect(screen.queryByText(/hidden-rag/)).not.toBeInTheDocument();
    expect(screen.queryByText(/sdk_response_should_not_render/)).not.toBeInTheDocument();
    expect(screen.queryByText(/embedding_vector_should_not_render/)).not.toBeInTheDocument();
    expect(screen.queryByText(/provider_debug_should_not_render/)).not.toBeInTheDocument();
    expect(screen.queryByText(/rag_debug_should_not_render/)).not.toBeInTheDocument();
    expect(screen.queryByText(/omitted_debug_should_not_render/)).not.toBeInTheDocument();
  });

  it("展示答题提交追加的 task/tool/trace 上下文证据", async () => {
    mockMathTutorApi({
      eventResponses: [{
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
      }]
    });

    render(<App />);

    expect(await screen.findByText("上下文证据")).toBeInTheDocument();
    expect(screen.getByText("answer_submitted question=q_frac_001; is_correct=false")).toBeInTheDocument();
    expect(screen.getByText("记录错因诊断工具观察快照")).toBeInTheDocument();
    expect(screen.getByText("answer_submitted trace references retrieval, decision, and memory-update source")).toBeInTheDocument();
  });

  it("展示 complete/offline DGEKT evidence 的 scorer、路径和消融摘要", async () => {
    mockMathTutorApi({
      eventResponses: [{
      ...baseResponse,
      teaching_trace_summary: {
        ...baseResponse.teaching_trace_summary,
        expert_evidence: {
          ...baseResponse.teaching_trace_summary.expert_evidence,
          attribution_evidence: {
            target_question_id: "q_frac_001",
            target_concept_id: "c_fraction_addition",
            target_assist2017_question_id: 3,
            target_assist2017_concept_id: 2,
            prediction_probability: 0.2,
            evidence_status: "complete",
            evidence_source: "offline",
            partial_evidence: false,
            raw_model_target: {
              sample_id: "fixture-s1-t2-q3",
              canonical_question_id: "q_frac_001"
            },
            mapped_teaching_content: {
              question_id: "q_frac_001",
              concept_id: "c_fraction_addition"
            },
            canonical_mapping: {
              question_id: "q_frac_001",
              concept_id: "c_fraction_addition"
            },
            scorer: {
              name: "dgekt_offline_path_scorer",
              version: "fixture-v1",
              run_id: "dgekt-fixture-run-20260709",
              matching_method: "student_target_exact"
            },
            top_paths: [
              {
                path_id: "path-fixture-history-q3",
                history_assist2017_question_id: 3,
                target_assist2017_question_id: 3,
                path_strength: 0.842,
                partial_evidence: false
              }
            ],
            key_history: [{ assist2017_question_id: 3, is_correct: false }],
            weak_concepts: [],
            path_ablation: [
              {
                strategy: "top_k_paths",
                impact: 0.16,
                comprehensiveness: 0.8
              }
            ],
            evidence_gaps: []
          }
        }
      }
      }]
    });

    render(<App />);

    expect(await screen.findByText("offline complete evidence")).toBeInTheDocument();
    expect(screen.getByText("dgekt_offline_path_scorer · fixture-v1 · dgekt-fixture-run-20260709 · student_target_exact")).toBeInTheDocument();
    expect(screen.getByText("q_frac_001 · c_fraction_addition")).toBeInTheDocument();
    expect(screen.getByText("path-fixture-history-q3")).toBeInTheDocument();
    expect(screen.getByText("0.842")).toBeInTheDocument();
    expect(screen.getByText("top_k_paths impact 0.160 · comp 0.800")).toBeInTheDocument();
  });

  it("展示 unavailable offline evidence gap，不把 partial proxy 当完整证据", async () => {
    const gapReason = "DGEKT offline evidence directory not found: /tmp/missing-offline-evidence.";
    mockMathTutorApi({
      eventResponses: [{
      ...baseResponse,
      teaching_trace_summary: {
        ...baseResponse.teaching_trace_summary,
        expert_evidence: {
          ...baseResponse.teaching_trace_summary.expert_evidence,
          attribution_evidence: {
            target_question_id: "q_frac_001",
            prediction_probability: 0.2,
            evidence_status: "unavailable",
            evidence_source: "offline",
            partial_evidence: true,
            partial_evidence_reason: gapReason,
            scorer: {
              name: "dgekt_offline_path_scorer",
              evidence_status: "unavailable"
            },
            top_paths: [
              {
                path_id: "dgekt-partial-3-3-1",
                partial_evidence: true,
                offline_evidence_status: "unavailable",
                history_assist2017_question_id: 3,
                target_assist2017_question_id: 3,
                path_weight: 0.85
              }
            ],
            key_history: [{ assist2017_question_id: 3, is_correct: false }],
            weak_concepts: [],
            path_ablation: [],
            evidence_gaps: [
              {
                gap_type: "missing_artifact",
                category: "missing_artifact",
                reason: gapReason,
                evidence_status: "unavailable",
                evidence_source: "offline"
              }
            ]
          },
          assembled_context: {
            ...baseResponse.teaching_trace_summary.expert_evidence.assembled_context,
            evidence_gaps: [
              {
                gap_type: "missing_artifact",
                reason: gapReason,
                evidence_status: "unavailable",
                evidence_source: "offline"
              }
            ]
          }
        }
      }
      }]
    });

    render(<App />);

    expect(await screen.findByText("unavailable evidence")).toBeInTheDocument();
    expect(screen.queryByText("offline complete evidence")).not.toBeInTheDocument();
    expect(screen.getAllByText("DGEKT offline artifact 缺失").length).toBeGreaterThan(0);
    expect(screen.getAllByText(gapReason).length).toBeGreaterThan(0);
  });

  it("后端不可达时展示中文错误和重试入口", async () => {
    mockMathTutorApi({ eventError: new Error("网络不可用") });

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("网络不可用");
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("后端返回可恢复 evidence gap 时在顶部展示处理提示", async () => {
    mockMathTutorApi({
      eventResponses: [{
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
      }]
    });

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("q_missing_answer 缺少标准答案");
    expect(screen.getByRole("alert")).toHaveTextContent("补齐题目的 standard_answer");
    expect(screen.getAllByText("Evidence gaps").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/项$/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("教学内容缺口").length).toBeGreaterThan(0);
    expect(screen.getAllByText("q_missing_answer 缺少标准答案，请补齐教学内容后再用于完整练习。").length).toBeGreaterThan(0);
  });

  it("后端返回 DGEKT detail 时展示可理解错误", async () => {
    mockMathTutorApi({
      eventError: new Response(
        JSON.stringify({ detail: "DGEKT 映射失败：缺少 ASSIST2017 题目映射" }),
        {
        status: 400,
        headers: { "Content-Type": "application/json" }
        }
      )
    });

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "事件处理失败：400 DGEKT 映射失败：缺少 ASSIST2017 题目映射"
    );
  });
});

function mockMathTutorApi({
  eventResponses = [baseResponse],
  memoryResponse = baseMemoryResponse,
  providerHealthResponse = baseProviderHealthResponse,
  eventError,
  memoryError,
  providerHealthError,
  memoryDeleteError,
  memoryPending = false
}: {
  eventResponses?: MathTutorEventResponse[];
  memoryResponse?: StudentMemoryListResponse;
  providerHealthResponse?: ProviderHealthResponse;
  eventError?: Error | Response;
  memoryError?: Error | Response;
  providerHealthError?: Error | Response;
  memoryDeleteError?: Error | Response;
  memoryPending?: boolean;
} = {}) {
  const eventQueue = [...eventResponses];
  let currentMemoryResponse = memoryResponse;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/api/provider-health")) {
      if (providerHealthError instanceof Error) throw providerHealthError;
      if (providerHealthError instanceof Response) return providerHealthError.clone();
      return jsonResponse(providerHealthResponse);
    }
    if (url.includes("/api/students/") && url.includes("/memories")) {
      if (memoryPending) return new Promise<Response>(() => {});
      if (memoryError instanceof Error) throw memoryError;
      if (memoryError instanceof Response) return memoryError.clone();
      const controlAction = memoryControlAction(url, init);
      if (controlAction) {
        if (controlAction === "delete" && memoryDeleteError instanceof Error) {
          throw memoryDeleteError;
        }
        if (controlAction === "delete" && memoryDeleteError instanceof Response) {
          return memoryDeleteError.clone();
        }
        const memoryId = decodeURIComponent(url.split("/memories/")[1].split("/")[0]);
        const updated = updateMemoryControlFixture(
          currentMemoryResponse,
          memoryId,
          controlAction
        );
        currentMemoryResponse =
          controlAction === "delete"
            ? {
                ...currentMemoryResponse,
                memories: currentMemoryResponse.memories.filter(
                  (memory) => memory.memory_id !== memoryId
                )
              }
            : {
                ...currentMemoryResponse,
                memories: currentMemoryResponse.memories.map((memory) =>
                  memory.memory_id === memoryId ? updated : memory
                )
              };
        return jsonResponse({
          student_id: currentMemoryResponse.student_id,
          memory: updated
        });
      }
      return jsonResponse(currentMemoryResponse);
    }
    if (url.includes("/api/events")) {
      if (eventError instanceof Error) throw eventError;
      if (eventError instanceof Response) return eventError.clone();
      return jsonResponse(
        eventQueue.shift() ?? eventResponses[eventResponses.length - 1] ?? baseResponse
      );
    }
    throw new Error(`Unexpected fetch: ${url} ${JSON.stringify(init ?? {})}`);
  });
}

function memoryControlAction(
  url: string,
  init?: RequestInit
): "enable" | "disable" | "delete" | null {
  if (init?.method === "DELETE") return "delete";
  if (url.endsWith("/disable")) return "disable";
  if (url.endsWith("/enable")) return "enable";
  return null;
}

function updateMemoryControlFixture(
  memoryResponse: StudentMemoryListResponse,
  memoryId: string,
  action: "enable" | "disable" | "delete"
) {
  const memory = memoryResponse.memories.find((item) => item.memory_id === memoryId);
  if (!memory) throw new Error(`Missing memory fixture: ${memoryId}`);
  const enabled = action === "enable";
  const status: StudentMemoryListResponse["memories"][number]["status"] =
    action === "delete" ? "deleted" : enabled ? "enabled" : "disabled";
  return {
    ...memory,
    enabled: action === "delete" ? false : enabled,
    status,
    provenance: {
      ...memory.provenance,
      control: {
        operation: action,
        status,
        actor: "student",
        reason:
          action === "delete"
            ? "学生在记忆控制面板中删除该记忆。"
            : enabled
              ? "学生在记忆控制面板中重新启用该记忆。"
              : "学生在记忆控制面板中禁用该记忆。",
        occurred_at: "2026-07-09T09:00:00+00:00"
      }
    }
  };
}

function eventFetchCalls(fetchMock: ReturnType<typeof mockMathTutorApi>) {
  return fetchMock.mock.calls.filter(([input]) => String(input).includes("/api/events"));
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}
