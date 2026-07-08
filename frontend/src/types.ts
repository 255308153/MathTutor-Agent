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

export interface RecommendedQuestion {
  question_id: string;
  assist2017_question_id?: number | string;
  dgekt_question_id?: number | string;
  assist2017_concept_id?: number | string;
  dgekt_concept_id?: number | string;
  stem: string;
  concept_id: string;
  concept_name: string;
  difficulty: number;
  teaching_type: string;
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
    attribution_evidence?: {
      target_question_id: string;
      prediction_probability?: number | null;
      top_paths: Array<Record<string, unknown>>;
      key_history: Array<Record<string, unknown>>;
      weak_concepts: Array<Record<string, unknown>>;
    } | null;
    rag_sources?: Array<{ doc_id?: string; title?: string; source?: string }>;
    student_memories?: Array<Record<string, unknown>>;
    planner_decision?: Record<string, unknown> | null;
    recommendations?: RecommendedQuestion[];
  };
  invariants: string[];
  errors: string[];
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
  };
  recommended_questions: RecommendedQuestion[];
  teaching_trace: TeachingTraceEvent[];
  teaching_trace_summary: TeachingTraceSummary;
}
