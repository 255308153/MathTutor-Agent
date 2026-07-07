from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


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


class AttributionEvidence(BaseModel):
    target_question_id: str
    prediction_probability: float | None = None
    top_paths: list[dict[str, Any]] = Field(default_factory=list)
    key_history: list[dict[str, Any]] = Field(default_factory=list)
    weak_concepts: list[dict[str, Any]] = Field(default_factory=list)
