from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..schemas.learning import KTLearningProgress, LearningEvent, MathTutorEventResponse


RuntimeIntent = Literal["next_step_advice", "answer_submission", "general_chat"]


class LearningTurnContext(BaseModel):
    """Unified per-turn fact carrier for the MathTutor Agent runtime.

    The runtime context stores references and snapshots for orchestration. It is
    not a source of learning truth; KT progress, memory, RAG, and context stores
    keep their existing ownership boundaries.
    """

    turn_id: str = Field(default_factory=lambda: f"turn-{uuid4().hex[:12]}")
    runtime_name: str = "MathTutorAgentRuntime"
    subject: str = "math"
    session_id: str
    student_id: str
    intent: RuntimeIntent
    learning_event: LearningEvent
    kt_progress: KTLearningProgress
    context_asset_refs: list[str] = Field(default_factory=list)
    assembled_context_ref: str | None = None
    tool_observation_refs: list[str] = Field(default_factory=list)
    trace_refs: list[str] = Field(default_factory=list)
    teaching_trace_id: str | None = None
    authority_boundaries: list[str] = Field(
        default_factory=lambda: [
            "KT facts are authoritative.",
            "LLM plans are advisory.",
            "Offline attribution explains prediction, not overwrite prediction facts.",
            "Memory can influence strategy, not mastery.",
            "RAG can support explanation, not overwrite prediction facts.",
            "Context can assemble evidence, not decide learning facts.",
        ]
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None

    def complete_from_response(self, response: MathTutorEventResponse) -> "LearningTurnContext":
        expert_evidence = response.teaching_trace_summary.expert_evidence
        context_assets = expert_evidence.get("context_assets") or []
        assembled_context = expert_evidence.get("assembled_context") or {}
        context_asset_refs = [
            str(asset.get("asset_id") or asset.get("source_ref"))
            for asset in context_assets
            if isinstance(asset, dict) and (asset.get("asset_id") or asset.get("source_ref"))
        ]
        assembled_context_ref = None
        if isinstance(assembled_context, dict) and assembled_context.get("context_id"):
            assembled_context_ref = str(assembled_context["context_id"])
        tool_observation_refs = [
            f"tool_observation:{event.metadata['tool_id']}"
            for event in response.teaching_trace
            if event.metadata.get("tool_id")
        ]
        trace_refs = [f"trace:{response.trace_id}"]
        if assembled_context_ref:
            trace_refs.append(f"context:{assembled_context_ref}")
        return self.model_copy(
            update={
                "context_asset_refs": list(dict.fromkeys(context_asset_refs)),
                "assembled_context_ref": assembled_context_ref,
                "tool_observation_refs": list(dict.fromkeys(tool_observation_refs)),
                "trace_refs": list(dict.fromkeys(trace_refs)),
                "teaching_trace_id": response.trace_id,
                "completed_at": datetime.now(UTC).isoformat(),
            },
            deep=True,
        )

    def public_summary(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "runtime_name": self.runtime_name,
            "subject": self.subject,
            "student_id": self.student_id,
            "session_id": self.session_id,
            "intent": self.intent,
            "learning_event": _learning_event_summary(self.learning_event),
            "kt_progress_ref": f"progress:{self.student_id}:v{self.kt_progress.version}",
            "kt_progress_version": self.kt_progress.version,
            "current_session_id": self.kt_progress.current_session_id,
            "context_asset_refs": self.context_asset_refs,
            "assembled_context_ref": self.assembled_context_ref,
            "tool_observation_refs": self.tool_observation_refs,
            "trace_refs": self.trace_refs,
            "teaching_trace_id": self.teaching_trace_id,
            "authority_boundaries": self.authority_boundaries,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "state_reference_only": True,
        }


def _learning_event_summary(event: LearningEvent) -> dict[str, Any]:
    safe_payload = {
        str(key): _safe_payload_value(key, value)
        for key, value in event.payload.items()
        if not _is_sensitive_key(str(key))
    }
    return {
        "session_id": event.session_id,
        "student_id": event.student_id,
        "type": event.type,
        "message": _safe_text(event.message[:240]),
        "payload": safe_payload,
    }


def _safe_payload_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {
            str(child_key): _safe_payload_value(str(child_key), child_value)
            for child_key, child_value in value.items()
            if not _is_sensitive_key(str(child_key))
        }
    if isinstance(value, list):
        return [_safe_payload_value(key, item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        token in lowered
        for token in (
            "api_key",
            "apikey",
            "authorization",
            "credential",
            "secret",
            "token",
            "password",
            "raw_provider_payload",
            "sdk_response",
            "provider_debug",
            "embedding",
            "vector",
            "checkpoint",
            "model_path",
        )
    )


def _looks_sensitive(value: str) -> bool:
    lowered = value.lower()
    return any(
        token in lowered
        for token in (
            "bearer ",
            "api_key=",
            "authorization:",
            "/users/",
            "\\users\\",
            "/home/",
            "\\home\\",
            "checkpoint",
            ".pkl",
            ".pt",
            ".pth",
            ".ckpt",
            ".safetensors",
        )
    )


def _safe_text(value: str) -> str:
    if _looks_sensitive(value):
        return "<redacted>"
    return value
