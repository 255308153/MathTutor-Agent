from __future__ import annotations

from enum import Enum
from typing import Any
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
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
