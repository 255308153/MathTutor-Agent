from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .trace import TeachingTraceEvent, TeachingTraceSummary


class TeachingType(str, Enum):
    MEMORY = "memory"
    CONCEPT = "concept"
    PROCEDURE = "procedure"
    DESIGN = "design"


class LearningEvent(BaseModel):
    session_id: str
    student_id: str
    type: Literal[
        "session_started",
        "chat_message",
        "question_recommended",
        "answer_submitted",
        "question_skipped",
        "hint_requested",
        "review_completed",
    ]
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ConceptState(BaseModel):
    concept_id: str
    concept_name: str
    teaching_type: TeachingType = TeachingType.CONCEPT
    mastery: float = 0.0
    forgetting_risk: float = 0.0
    last_practiced_at: str | None = None
    recent_accuracy: float = 0.0
    evidence_count: int = 0
    status: Literal["new", "learning", "weak", "reviewing", "stable"] = "new"


class KTLearningProgress(BaseModel):
    student_id: str
    subject: str = "math"
    dataset: str = "assist2017"
    current_session_id: str = ""
    concept_states: list[ConceptState] = Field(default_factory=list)
    recent_events: list[LearningEvent] = Field(default_factory=list)
    weak_concepts: list[dict[str, Any]] = Field(default_factory=list)
    forgetting_risks: list[dict[str, Any]] = Field(default_factory=list)
    pending_question: dict[str, Any] | None = None
    recommendation_history: list[dict[str, Any]] = Field(default_factory=list)
    error_records: list[dict[str, Any]] = Field(default_factory=list)
    review_queue: list[dict[str, Any]] = Field(default_factory=list)
    teaching_trace_ids: list[str] = Field(default_factory=list)
    version: int = 0


class KTDiagnosis(BaseModel):
    weak_concepts: list[dict[str, Any]] = Field(default_factory=list)
    forgetting_risks: list[dict[str, Any]] = Field(default_factory=list)
    prediction_probability: float | None = None
    evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttributionEvidence(BaseModel):
    target_question_id: str
    prediction_probability: float | None = None
    top_paths: list[dict[str, Any]] = Field(default_factory=list)
    key_history: list[dict[str, Any]] = Field(default_factory=list)
    weak_concepts: list[dict[str, Any]] = Field(default_factory=list)


class MathTutorState(BaseModel):
    trace_id: str = Field(default_factory=lambda: f"tt-{uuid4().hex[:12]}")
    session_id: str
    student_id: str
    intent: Literal["next_step_advice", "answer_submission", "general_chat"] = "general_chat"
    learning_event: LearningEvent
    kt_progress: KTLearningProgress
    rag_context: list[dict[str, Any]] = Field(default_factory=list)
    student_memories: list[dict[str, Any]] = Field(default_factory=list)
    context_assets: list[dict[str, Any]] = Field(default_factory=list)
    assembled_context: dict[str, Any] | None = None
    kt_diagnosis: KTDiagnosis | None = None
    attribution_evidence: AttributionEvidence | None = None
    teaching_plan: dict[str, Any] | None = None
    next_action: dict[str, Any] | None = None
    recommended_questions: list[dict[str, Any]] = Field(default_factory=list)
    response: str = ""
    teaching_trace: list[TeachingTraceEvent] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "intent": self.intent,
            "progress_version": self.kt_progress.version,
            "concept_states": [
                concept.model_dump() for concept in self.kt_progress.concept_states
            ],
            "weak_concepts": self.kt_diagnosis.weak_concepts if self.kt_diagnosis else [],
            "forgetting_risks": self.kt_diagnosis.forgetting_risks if self.kt_diagnosis else [],
            "mistake_diagnosis": self.teaching_plan.get("mistake_diagnosis") if self.teaching_plan else None,
            "next_action": self.next_action,
            "errors": self.errors,
        }

    def trace_summary(self) -> TeachingTraceSummary:
        return TeachingTraceSummary(
            trace_id=self.trace_id,
            session_id=self.session_id,
            student_id=self.student_id,
            intent=self.intent,
            stages=[event.stage for event in self.teaching_trace],
            student_explanation=self.response,
            expert_evidence={
                "kt_diagnosis": self.kt_diagnosis.model_dump() if self.kt_diagnosis else None,
                "attribution_evidence": (
                    self.attribution_evidence.model_dump() if self.attribution_evidence else None
                ),
                "rag_sources": [
                    {
                        "doc_id": item.get("doc_id"),
                        "title": item.get("title"),
                        "source": item.get("source"),
                    }
                    for item in self.rag_context
                ],
                "student_memories": self.student_memories,
                "context_assets": self.context_assets,
                "assembled_context": self.assembled_context,
                "planner_decision": self.teaching_plan,
                "recommendations": self.recommended_questions,
            },
            invariants=[
                "KT facts are authoritative.",
                "LLM plans are advisory.",
                "Memory can influence strategy, not mastery.",
                "RAG can support explanation, not overwrite prediction facts.",
                "Context can assemble evidence, not decide learning facts.",
            ],
            errors=self.errors,
        )


class MathTutorEventResponse(BaseModel):
    trace_id: str
    response: str
    state_summary: dict[str, Any]
    recommended_questions: list[dict[str, Any]] = Field(default_factory=list)
    teaching_trace: list[TeachingTraceEvent] = Field(default_factory=list)
    teaching_trace_summary: TeachingTraceSummary
