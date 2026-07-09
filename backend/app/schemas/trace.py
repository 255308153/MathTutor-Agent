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
