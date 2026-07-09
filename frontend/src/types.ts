export type LearningEventType =
  | "session_started"
  | "chat_message"
  | "question_recommended"
  | "answer_submitted"
  | "question_skipped"
  | "hint_requested"
  | "review_completed";

export interface LearningEventRequest {
  session_id: string;
  student_id: string;
  type: LearningEventType;
  message: string;
  payload: Record<string, unknown>;
}

export interface ConceptState {
  concept_id: string;
  concept_name: string;
  teaching_type: string;
  mastery: number;
  forgetting_risk: number;
  recent_accuracy: number;
  evidence_count: number;
  status: string;
}

export type StudentMemoryType =
  | "preference"
  | "repeated_mistake"
  | "effective_strategy"
  | "reflection";

export type StudentMemoryFreshness = "fresh" | "recent" | "stale";
export type StudentMemoryStatus = "enabled" | "disabled" | "deleted";

export interface StudentMemory {
  memory_id: string;
  memory_type: StudentMemoryType;
  content: string;
  summary: string;
  source: string;
  evidence: Record<string, unknown>;
  provenance: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  freshness: StudentMemoryFreshness;
  enabled: boolean;
  status: StudentMemoryStatus;
}

export interface StudentMemoryListResponse {
  student_id: string;
  count: number;
  memories: StudentMemory[];
}

export interface StudentMemoryDetailResponse {
  student_id: string;
  memory: StudentMemory;
}

export type ProviderHealthStatus =
  | "healthy"
  | "degraded"
  | "unavailable"
  | "not_configured";

export type ProviderHealthSeverity = "info" | "warning" | "error";

export interface ProviderHealthComponent {
  component: string;
  display_name: string;
  mode: string;
  provider: string;
  configured: boolean;
  status: ProviderHealthStatus;
  severity: ProviderHealthSeverity;
  recoverable: boolean;
  actionable_hint: string;
  evidence_gaps: EvidenceGap[];
  last_checked_at: string;
}

export interface ProviderHealthResponse {
  status: ProviderHealthStatus;
  summary: string;
  generated_at: string;
  components: ProviderHealthComponent[];
}

export interface RecommendedQuestion {
  question_id: string;
  assist2017_question_id?: number | string;
  dgekt_question_id?: number | string;
  assist2017_concept_id?: number | string;
  dgekt_concept_id?: number | string;
  stem: string;
  answer?: string | null;
  explanation?: string | null;
  concept_id: string;
  concept_name: string;
  difficulty: number;
  teaching_type: string;
  content_availability?: {
    status: "available" | "partial";
    has_stem: boolean;
    has_answer: boolean;
    has_explanation: boolean;
    missing_fields: string[];
    missing_labels: string[];
    fallback_message?: string | null;
  };
  provenance?: Record<string, unknown>;
  canonical_mapping?: Record<string, unknown>;
  score: number;
  reason: string;
  score_factors: Record<string, number>;
}

export interface TeachingTraceEvent {
  id: string;
  stage: string;
  actor: string;
  visibility: "student" | "expert" | "debug";
  content: string;
  metadata: Record<string, unknown>;
  evidence_refs: string[];
}

export interface ContextAssetEvidence {
  asset_id?: string;
  asset_type?: string;
  source_type?: string;
  source_ref?: string;
  summary?: string;
  included_reason?: string | null;
  excluded_reason?: string | null;
  selection_status?: "included" | "excluded" | string;
  confidence?: number;
  freshness?: string;
  budget_cost?: number;
  metadata?: Record<string, unknown>;
}

export interface EvidenceGap {
  gap_type?: string;
  category?: string;
  reason?: string;
  impact?: string;
  severity?: string;
  recoverable?: boolean;
  stage?: string;
  code?: string;
  message?: string;
  actionable_hint?: string;
  source_ref?: string | null;
  sample_id?: string | null;
  details?: Record<string, unknown>;
  evidence_status?: string | null;
  evidence_source?: string | null;
}

export interface AssembledContextEvidence {
  context_id?: string;
  authoritative_kt_facts?: Record<string, unknown>;
  normalized_context?: Record<string, unknown>;
  asset_summaries?: ContextAssetEvidence[];
  asset_selection?: {
    selected?: ContextAssetEvidence[];
    omitted?: ContextAssetEvidence[];
  };
  evidence_gaps?: EvidenceGap[];
  evidence_refs?: string[];
  budget_used?: number;
  budget_limit?: number;
  compression_summary?: {
    strategy?: string;
    selected_asset_count?: number;
    excluded_asset_count?: number;
    candidate_asset_count?: number;
    budget_used?: number;
    budget_limit?: number;
    excluded_reasons?: string[];
  };
}

export interface TeachingTraceSummary {
  trace_id: string;
  intent: string;
  stages: string[];
  student_explanation: string;
  expert_evidence: {
    kt_diagnosis?: {
      weak_concepts: Array<Record<string, unknown>>;
      forgetting_risks: Array<Record<string, unknown>>;
      prediction_probability?: number | null;
      evidence: string[];
    } | null;
    attribution_evidence?: AttributionEvidence | null;
    rag_sources?: Array<{
      doc_id?: string;
      doc_type?: string;
      title?: string;
      source?: string;
      concept_id?: string | null;
      question_id?: string | null;
      assist2017_question_id?: number | string | null;
      assist2017_concept_id?: number | string | null;
      canonical_mapping?: Record<string, unknown> | null;
      provenance?: Record<string, unknown> | null;
      coverage?: Record<string, unknown> | null;
    }>;
    student_memories?: Array<Record<string, unknown>>;
    context_assets?: ContextAssetEvidence[];
    context_asset_selection?: {
      selected?: ContextAssetEvidence[];
      omitted?: ContextAssetEvidence[];
    };
    assembled_context?: AssembledContextEvidence | null;
    evidence_gaps?: EvidenceGap[];
    error_records?: EvidenceGap[];
    planner_decision?: Record<string, unknown> | null;
    recommendations?: RecommendedQuestion[];
    tool_registry_manifest?: Array<Record<string, unknown>>;
    tool_observations?: Array<Record<string, unknown>>;
    runtime?: Record<string, unknown>;
  };
  invariants: string[];
  errors: string[];
}

export interface AttributionEvidence {
  target_question_id: string;
  target_concept_id?: string | null;
  target_assist2017_question_id?: number | string | null;
  target_assist2017_concept_id?: number | string | null;
  prediction_probability?: number | null;
  evidence_status?: string | null;
  evidence_source?: string | null;
  partial_evidence?: boolean;
  partial_evidence_reason?: string | null;
  raw_model_target?: Record<string, unknown>;
  mapped_teaching_content?: Record<string, unknown>;
  canonical_mapping?: Record<string, unknown>;
  scorer?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
  top_paths: Array<Record<string, unknown>>;
  key_history: Array<Record<string, unknown>>;
  weak_concepts: Array<Record<string, unknown>>;
  path_ablation?: Array<Record<string, unknown>>;
  evidence_gaps?: EvidenceGap[];
}

export interface MathTutorEventResponse {
  trace_id: string;
  response: string;
  state_summary: {
    session_id: string;
    student_id: string;
    intent: string;
    progress_version: number;
    concept_states: ConceptState[];
    weak_concepts: Array<Record<string, unknown>>;
    forgetting_risks: Array<Record<string, unknown>>;
    mistake_diagnosis?: Record<string, unknown> | null;
    next_action?: Record<string, unknown> | null;
    errors: string[];
    error_records: Array<Record<string, unknown>>;
  };
  recommended_questions: RecommendedQuestion[];
  teaching_trace: TeachingTraceEvent[];
  teaching_trace_summary: TeachingTraceSummary;
}
