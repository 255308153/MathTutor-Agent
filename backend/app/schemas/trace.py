from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class TeachingTraceEventType(str, Enum):
    STAGE_START = "stage_start"
    STAGE_END = "stage_end"
    OBSERVATION = "observation"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SOURCES = "sources"
    RESULT = "result"
    ERROR = "error"


class TeachingTraceEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"trace-{uuid4().hex[:10]}")
    type: TeachingTraceEventType
    stage: str
    actor: Literal[
        "system",
        "runtime",
        "kt",
        "rag",
        "memory",
        "context",
        "planner",
        "response",
    ] = "system"
    visibility: Literal["student", "expert", "debug"] = "expert"
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class TeachingTraceSummary(BaseModel):
    trace_id: str
    session_id: str
    student_id: str
    intent: str
    stages: list[str] = Field(default_factory=list)
    student_explanation: str = ""
    expert_evidence: dict[str, Any] = Field(default_factory=dict)
    invariants: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RuntimeTraceStageView(BaseModel):
    event_id: str
    event_type: str
    stage: str
    actor: str
    visibility: Literal["student", "expert", "debug"]
    student_visible: bool = False
    content: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    capability_id: str | None = None
    tool_id: str | None = None
    provider: str | None = None
    provider_mode: str | None = None
    status: str | None = None
    degraded: bool = False
    fallback_used: bool = False
    provider_gap_count: int = 0
    gap_count: int = 0
    evidence_boundary: str | None = None
    state_write_policy: str | None = None


class RuntimeToolCallView(BaseModel):
    tool_id: str
    name: str
    stage: str
    actor: str
    visibility: Literal["student", "expert", "debug"] = "expert"
    purpose: str = ""
    input_summary: str = ""
    output_summary: str = ""
    failure_modes: list[str] = Field(default_factory=list)
    provider_modes: list[str] = Field(default_factory=list)
    state_write_policy: str = ""
    observed: bool = False
    provider: str | None = None
    provider_mode: str | None = None
    status: str | None = None
    degraded: bool = False
    fallback_used: bool = False
    provider_gap_count: int = 0
    evidence_refs: list[str] = Field(default_factory=list)


class RuntimeToolObservationView(BaseModel):
    tool_id: str
    name: str
    stage: str
    actor: str
    visibility: Literal["student", "expert", "debug"] = "expert"
    provider: str
    provider_mode: str
    status: str
    degraded: bool = False
    fallback_used: bool = False
    metrics: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_boundary: str
    provider_gap_count: int = 0
    provider_gaps: list[dict[str, Any]] = Field(default_factory=list)
    gap_count: int = 0
    state_write_policy: str


class RuntimeTraceOverview(BaseModel):
    runtime_name: str
    turn_id: str | None = None
    intent: str
    active_capability_id: str
    active_capability_name: str
    active_capability_fallback: bool = False
    active_capability_reason: str = ""
    stage_events: list[RuntimeTraceStageView] = Field(default_factory=list)
    tool_calls: list[RuntimeToolCallView] = Field(default_factory=list)
    tool_observations: list[RuntimeToolObservationView] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    visibility_counts: dict[str, int] = Field(default_factory=dict)
    provider_gap_count: int = 0
    provider_gaps: list[dict[str, Any]] = Field(default_factory=list)
    state_reference_only: bool = True
    boundary: str = (
        "Runtime observability is read-only and cannot overwrite KT facts, "
        "memory, RAG, TeachingTrace, or learning progress state."
    )
