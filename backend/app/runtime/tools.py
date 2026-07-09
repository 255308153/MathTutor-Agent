from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re
from typing import Any, Literal

from pydantic import BaseModel, Field


ToolProviderMode = Literal[
    "local_fallback",
    "fake_provider",
    "live_provider",
    "unknown",
]
ToolObservationStatus = Literal["completed", "degraded", "failed", "unavailable"]
ToolVisibility = Literal["student", "expert", "debug"]


class ToolInvocation(BaseModel):
    """Sanitized call envelope for one runtime-managed mathematics tool."""

    tool_id: str
    turn_id: str | None = None
    trace_id: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    context_summary: dict[str, Any] = Field(default_factory=dict)

    def public_summary(self) -> dict[str, Any]:
        return sanitize_runtime_value(self.model_dump(exclude_none=True))


class ToolObservation(BaseModel):
    """Expert-facing tool result snapshot for TeachingTrace."""

    tool_id: str
    tool_name: str
    provider: str
    provider_mode: ToolProviderMode
    status: ToolObservationStatus
    degraded: bool = False
    fallback_used: bool = False
    result_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_boundary: str
    evidence_refs: list[str] = Field(default_factory=list)
    failure: dict[str, Any] | None = None
    visibility: ToolVisibility = "expert"
    state_write_policy: str = (
        "tool_observation_is_read_only_and_cannot_write_mastery_or_prediction_facts"
    )

    def public_summary(self) -> dict[str, Any]:
        return sanitize_runtime_value(self.model_dump(exclude_none=True))


ToolHandler = Callable[[ToolInvocation], ToolObservation]


@dataclass(frozen=True)
class RuntimeTool:
    tool_id: str
    name: str
    purpose: str
    input_summary: str
    output_summary: str
    failure_modes: tuple[str, ...]
    provider_modes: tuple[ToolProviderMode, ...]
    evidence_boundary: str
    trace_stage: str
    trace_actor: str
    visibility: ToolVisibility
    handler: ToolHandler
    state_write_policy: str = (
        "runtime_tool_is_invoked_for_observation_and_cannot_overwrite_kt_facts"
    )

    def manifest_entry(self) -> dict[str, Any]:
        return sanitize_runtime_value(
            {
                "tool_id": self.tool_id,
                "name": self.name,
                "purpose": self.purpose,
                "input_summary": self.input_summary,
                "output_summary": self.output_summary,
                "failure_modes": list(self.failure_modes),
                "provider_modes": list(self.provider_modes),
                "evidence_boundary": self.evidence_boundary,
                "trace_stage": self.trace_stage,
                "trace_actor": self.trace_actor,
                "visibility": self.visibility,
                "state_write_policy": self.state_write_policy,
            }
        )

    def call(self, invocation: ToolInvocation) -> ToolObservation:
        return self.handler(invocation)


class MathToolRegistry:
    """Minimal registry for runtime-controlled mathematics learning tools."""

    def __init__(self, tools: Sequence[RuntimeTool] | None = None) -> None:
        self._tools: dict[str, RuntimeTool] = {}
        for tool in tools or ():
            self.register(tool)

    def register(self, tool: RuntimeTool) -> None:
        if tool.tool_id in self._tools:
            raise ValueError(f"Tool already registered: {tool.tool_id}")
        self._tools[tool.tool_id] = tool

    def list_tools(self) -> list[RuntimeTool]:
        return list(self._tools.values())

    def manifest(self) -> list[dict[str, Any]]:
        return [tool.manifest_entry() for tool in self.list_tools()]

    def find(self, tool_id: str) -> RuntimeTool | None:
        return self._tools.get(tool_id)

    def call(self, tool_id: str, invocation: ToolInvocation) -> ToolObservation:
        tool = self.find(tool_id)
        if tool is None:
            raise KeyError(f"Unknown runtime tool: {tool_id}")
        if invocation.tool_id != tool_id:
            invocation = invocation.model_copy(update={"tool_id": tool_id}, deep=True)
        return tool.call(invocation)


KT_AUTHORITY_TOOL_ID = "kt_authoritative_facts"
KT_AUTHORITY_EVIDENCE_BOUNDARY = (
    "KT/DGEKT facts are authoritative for mastery, weak concepts, prediction "
    "probability, forgetting risks, and attribution provenance. RAG, student memory, "
    "LLM output, capability selection, and provider health can support teaching "
    "strategy or explanation, but cannot overwrite these facts."
)


def default_tool_registry() -> MathToolRegistry:
    return MathToolRegistry(tools=[kt_authoritative_facts_tool()])


def kt_authoritative_facts_tool() -> RuntimeTool:
    return RuntimeTool(
        tool_id=KT_AUTHORITY_TOOL_ID,
        name="KT/DGEKT 权威学习事实",
        purpose=(
            "读取本轮学习 turn 已产出的 KT/DGEKT 诊断事实，并以只读 tool observation "
            "形式进入 TeachingTrace。"
        ),
        input_summary=(
            "LearningTurnContext 引用、KT 引擎名称、安全诊断摘要、KTDiagnosis 和 "
            "AttributionEvidence 摘要。"
        ),
        output_summary=(
            "prediction_probability、weak_concepts、forgetting_risks、attribution 状态、"
            "provider mode、降级状态和证据边界。"
        ),
        failure_modes=(
            "kt_diagnosis_missing",
            "dgekt_mapping_gap",
            "dgekt_scorer_failure",
            "attribution_partial_or_unavailable",
        ),
        provider_modes=("local_fallback", "fake_provider", "live_provider"),
        evidence_boundary=KT_AUTHORITY_EVIDENCE_BOUNDARY,
        trace_stage="kt_tool_observation",
        trace_actor="kt",
        visibility="expert",
        handler=_kt_authoritative_facts_handler,
    )


def _kt_authoritative_facts_handler(invocation: ToolInvocation) -> ToolObservation:
    data = invocation.input_summary
    diagnosis = _dict_or_empty(data.get("kt_diagnosis"))
    attribution = _dict_or_empty(data.get("attribution_evidence"))
    diagnostics = _dict_or_empty(data.get("kt_engine_diagnostics"))
    diagnosis_metadata = _dict_or_empty(diagnosis.get("metadata"))
    engine_name = str(
        data.get("kt_engine")
        or diagnostics.get("engine_name")
        or diagnosis_metadata.get("engine_name")
        or "unknown"
    )
    provider_mode = _provider_mode_for_kt_engine(engine_name)
    diagnose_gaps = [
        gap
        for gap in _list_of_dicts(data.get("error_records"))
        if gap.get("stage") == "diagnose" and gap.get("severity") != "info"
    ]
    attribution_gaps = _list_of_dicts(attribution.get("evidence_gaps"))
    attribution_status = attribution.get("evidence_status")
    partial_attribution = bool(attribution.get("partial_evidence"))
    missing_diagnosis = not diagnosis
    degraded = bool(
        missing_diagnosis
        or diagnose_gaps
        or attribution_gaps
        or partial_attribution
        or attribution_status in {"partial", "unavailable", "failed"}
    )
    status: ToolObservationStatus
    if missing_diagnosis:
        status = "unavailable"
    elif diagnose_gaps:
        status = "degraded"
    else:
        status = "degraded" if degraded else "completed"

    weak_concepts = _list_of_dicts(diagnosis.get("weak_concepts"))
    forgetting_risks = _list_of_dicts(diagnosis.get("forgetting_risks"))
    prediction_probability = diagnosis.get("prediction_probability")
    evidence_refs = _evidence_refs(
        trace_id=invocation.trace_id,
        turn_id=invocation.turn_id,
        target_question_id=attribution.get("target_question_id"),
    )
    result_summary = sanitize_runtime_value(
        {
            "prediction_probability": prediction_probability,
            "weak_concepts": weak_concepts,
            "forgetting_risks": forgetting_risks,
            "weak_concept_count": len(weak_concepts),
            "forgetting_risk_count": len(forgetting_risks),
            "prediction_facts": {
                "prediction_probability": prediction_probability,
                "weak_concepts": weak_concepts,
                "forgetting_risks": forgetting_risks,
            },
            "attribution": {
                "target_question_id": attribution.get("target_question_id"),
                "prediction_probability": attribution.get("prediction_probability"),
                "evidence_status": attribution_status,
                "evidence_source": attribution.get("evidence_source"),
                "partial_evidence": partial_attribution,
                "top_path_count": len(_list_of_dicts(attribution.get("top_paths"))),
                "key_history_count": len(_list_of_dicts(attribution.get("key_history"))),
                "provenance": attribution.get("provenance"),
                "evidence_gaps": attribution_gaps,
            },
            "kt_engine": engine_name,
            "kt_engine_diagnostics": diagnostics,
            "authority": KT_AUTHORITY_EVIDENCE_BOUNDARY,
        }
    )
    failure = None
    if degraded:
        failure = sanitize_runtime_value(
            {
                "diagnose_gaps": diagnose_gaps,
                "attribution_gaps": attribution_gaps,
                "attribution_status": attribution_status,
                "partial_attribution": partial_attribution,
                "missing_diagnosis": missing_diagnosis,
            }
        )

    return ToolObservation(
        tool_id=KT_AUTHORITY_TOOL_ID,
        tool_name="KT/DGEKT 权威学习事实",
        provider=engine_name,
        provider_mode=provider_mode,
        status=status,
        degraded=degraded,
        fallback_used=provider_mode == "local_fallback",
        result_summary=result_summary,
        evidence_boundary=KT_AUTHORITY_EVIDENCE_BOUNDARY,
        evidence_refs=evidence_refs,
        failure=failure,
    )


def sanitize_runtime_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return sanitize_runtime_value(value.model_dump())
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                continue
            sanitized[key_text] = sanitize_runtime_value(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_runtime_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_runtime_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _provider_mode_for_kt_engine(engine_name: str) -> ToolProviderMode:
    lowered = engine_name.lower()
    if "mock" in lowered:
        return "local_fallback"
    if "fake" in lowered:
        return "fake_provider"
    if "dgekt" in lowered:
        return "live_provider"
    return "unknown"


def _evidence_refs(
    *,
    trace_id: str | None,
    turn_id: str | None,
    target_question_id: Any,
) -> list[str]:
    refs = []
    if trace_id:
        refs.append(f"trace:{trace_id}")
        refs.append(f"kt_diagnosis:{trace_id}")
    if turn_id:
        refs.append(f"turn:{turn_id}")
    if target_question_id:
        refs.append(f"attribution:{target_question_id}")
    return list(dict.fromkeys(refs))


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "secret",
        "token",
        "password",
        "raw_provider_payload",
        "sdk_response",
        "provider_debug",
        "embedding",
        "embedding_vector",
        "vector",
        "cache_path",
        "checkpoint_path",
        "model_path",
        "dataset_dir",
        "q_matrix_path",
        "local_path",
    }:
        return True
    return lowered.endswith("_api_key") or lowered.endswith("_secret")


def _sanitize_text(value: str) -> str:
    sanitized = value
    patterns = [
        (r"(?i)(authorization\s*:\s*bearer\s+)\S+", r"\1<redacted>"),
        (r"(?i)(bearer\s+)\S+", r"\1<redacted>"),
        (r"(?i)(api[_-]?key\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(x-api-key\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(credential[s]?\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(secret\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(token\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(/Users/|/home/|/var/|/tmp/|/private/|/Volumes/)[^\s\"']+", "<local_path_redacted>"),
        (r"(?i)[A-Z]:\\[^\s\"']+", "<local_path_redacted>"),
    ]
    for pattern, replacement in patterns:
        sanitized = re.sub(pattern, replacement, sanitized)
    if _looks_like_model_artifact(sanitized):
        return "<model_artifact_redacted>"
    return sanitized


def _looks_like_model_artifact(value: str) -> bool:
    lowered = value.lower()
    return any(
        token in lowered
        for token in (".pkl", ".pt", ".pth", ".ckpt", ".safetensors")
    )
