from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


TrialReadinessStatus = Literal["ready", "degraded", "not_ready"]
TrialComponentStatus = Literal["ready", "degraded", "not_ready", "skipped"]
TrialDecision = Literal["ready", "hold", "not_ready"]
ChecklistItemStatus = Literal["met", "degraded", "blocking", "pending_human"]


class TrialReadinessComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str
    display_name: str
    status: TrialComponentStatus
    reason: str
    actionable_hint: str
    details: dict[str, Any] = Field(default_factory=dict)


class TrialProbeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    mode: str
    status: TrialComponentStatus
    recoverable: bool
    reason: str
    actionable_hint: str
    probed_at: str | None = None
    skipped: bool = False


class TrialChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    title: str
    status: ChecklistItemStatus
    summary: str
    actionable_hint: str


class TrialFeedbackRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_id: str
    student_flow: str
    issue_category: str
    impact: str
    handling_status: str
    residual_risk: str
    decision: TrialDecision
    operator_note: str = ""
    recorded_at: str
    actor: str = "operator"


class TrialFeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_flow: str
    issue_category: str
    impact: str
    handling_status: str = "open"
    residual_risk: str
    decision: TrialDecision
    operator_note: str = ""
    actor: str = "operator"


class TrialReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TrialReadinessStatus
    summary: str
    generated_at: str
    demo_runnable: bool
    internal_trial_ready: bool
    fallback_is_not_trial_ready: bool = True
    components: list[TrialReadinessComponent] = Field(default_factory=list)
    probe_summaries: list[TrialProbeSummary] = Field(default_factory=list)
    artifact_summaries: list[TrialReadinessComponent] = Field(default_factory=list)
    checklist: list[TrialChecklistItem] = Field(default_factory=list)
    recent_feedback: list[TrialFeedbackRecord] = Field(default_factory=list)
    residual_risks: list[str] = Field(default_factory=list)
    human_decision_required: bool = True
    boundary: str = (
        "Trial Readiness Gate 只读汇总 readiness / 审计信号；"
        "不得写入或覆盖 KT/DGEKT 学习事实、progress、memory、RAG citation、"
        "active context 或 TeachingTrace 学习决策。"
    )


class SessionRecoveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str
    session_id: str
    progress_version: int
    concept_states: list[dict[str, Any]] = Field(default_factory=list)
    weak_concepts: list[dict[str, Any]] = Field(default_factory=list)
    recommendation_basis: list[dict[str, Any]] = Field(default_factory=list)
    recent_trace_summaries: list[dict[str, Any]] = Field(default_factory=list)
    recovered: bool
    message: str


class CanaryProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[str] = Field(default_factory=lambda: ["memory", "rag"])
    canary_token: str = "mathtutor-canary"
