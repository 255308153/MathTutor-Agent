from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..provider_gaps import PROVIDER_EVIDENCE_GAP_TYPES


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
RAG_RETRIEVAL_TOOL_ID = "rag_retrieval_evidence"
STUDENT_MEMORY_TOOL_ID = "student_memory_evidence"
KT_AUTHORITY_EVIDENCE_BOUNDARY = (
    "KT/DGEKT facts are authoritative for mastery, weak concepts, prediction "
    "probability, forgetting risks, and attribution provenance. RAG, student memory, "
    "LLM output, capability selection, and provider health can support teaching "
    "strategy or explanation, but cannot overwrite these facts."
)
RAG_EVIDENCE_BOUNDARY = (
    "RAG can support mathematical explanation, citations, examples, theorem notes, "
    "and worked-solution context, but cannot overwrite KT/DGEKT prediction facts."
)
STUDENT_MEMORY_EVIDENCE_BOUNDARY = (
    "Student memory can influence teaching strategy, expression style, review reminders, "
    "and personalization, but cannot directly modify mastery, weak concepts, "
    "prediction probability, or forgetting risks."
)


def default_tool_registry() -> MathToolRegistry:
    return MathToolRegistry(
        tools=[
            kt_authoritative_facts_tool(),
            rag_retrieval_evidence_tool(),
            student_memory_evidence_tool(),
        ]
    )


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


def rag_retrieval_evidence_tool() -> RuntimeTool:
    return RuntimeTool(
        tool_id=RAG_RETRIEVAL_TOOL_ID,
        name="RAG 数学知识检索证据",
        purpose=(
            "记录本轮 RAG 检索结果、空结果 evidence gap、provider gap 与上下文纳入情况，"
            "供 TeachingTrace 审计。"
        ),
        input_summary=(
            "load_context 的 rag_query、rag_filters、rag_sources、assembled context、"
            "context asset selection 和标准 provider gap 记录。"
        ),
        output_summary=(
            "RAG result count、citation refs、selected/omitted knowledge assets、"
            "evidence gaps、provider mode 和只读证据边界。"
        ),
        failure_modes=(
            "missing_rag_citation",
            "provider_failure",
            "provider_timeout",
            "provider_auth_error",
            "provider_empty_result",
            "provider_schema_mismatch",
            "provider_budget_exceeded",
            "context_budget",
        ),
        provider_modes=("local_fallback", "fake_provider", "live_provider", "unknown"),
        evidence_boundary=RAG_EVIDENCE_BOUNDARY,
        trace_stage="rag_tool_observation",
        trace_actor="rag",
        visibility="expert",
        handler=_rag_retrieval_evidence_handler,
        state_write_policy=(
            "rag_tool_observation_is_read_only_and_cannot_write_mastery_or_prediction_facts"
        ),
    )


def student_memory_evidence_tool() -> RuntimeTool:
    return RuntimeTool(
        tool_id=STUDENT_MEMORY_TOOL_ID,
        name="学生记忆证据",
        purpose=(
            "记录本轮召回、纳入、排除的学生记忆摘要，以及记忆 provider gap 与控制状态。"
        ),
        input_summary=(
            "load_context 的 memory_query、student_memories、assembled context、"
            "context asset selection、memory update gap 和标准 provider gap 记录。"
        ),
        output_summary=(
            "retrieved memory count、selected/omitted memory refs、disabled exclusion reason、"
            "provider gaps、provider mode 和只读证据边界。"
        ),
        failure_modes=(
            "student_memory",
            "disabled_memory_excluded",
            "provider_failure",
            "provider_timeout",
            "provider_auth_error",
            "provider_empty_result",
            "provider_schema_mismatch",
            "provider_budget_exceeded",
        ),
        provider_modes=("local_fallback", "fake_provider", "live_provider", "unknown"),
        evidence_boundary=STUDENT_MEMORY_EVIDENCE_BOUNDARY,
        trace_stage="memory_tool_observation",
        trace_actor="memory",
        visibility="expert",
        handler=_student_memory_evidence_handler,
        state_write_policy=(
            "memory_tool_observation_is_read_only_and_cannot_write_mastery_or_prediction_facts"
        ),
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


def _rag_retrieval_evidence_handler(invocation: ToolInvocation) -> ToolObservation:
    data = invocation.input_summary
    load_context = _dict_or_empty(data.get("load_context"))
    assembled_context = _dict_or_empty(data.get("assembled_context"))
    context_selection = _selection_from_input(data)
    rag_sources = _list_of_dicts(data.get("rag_sources"))
    selected_assets, omitted_assets = _assets_by_type(context_selection, "knowledge_resource")
    rag_gaps = _rag_evidence_gaps(
        data=data,
        assembled_context=assembled_context,
        omitted_assets=omitted_assets,
    )
    provider, provider_mode = _provider_identity(
        sources=rag_sources,
        selected_assets=selected_assets,
        omitted_assets=omitted_assets,
        gaps=rag_gaps,
        default_provider="local_rag",
    )
    provider_gaps = [gap for gap in rag_gaps if _is_provider_gap(gap)]
    degraded = bool(provider_gaps or omitted_assets or rag_gaps)
    status: ToolObservationStatus = "degraded" if degraded else "completed"
    citation_refs = _rag_citation_refs(rag_sources)
    evidence_refs = _turn_trace_refs(invocation)
    if citation_refs:
        evidence_refs.extend(citation_refs)
    result_summary = sanitize_runtime_value(
        {
            "result_count": len(rag_sources),
            "sources": [_compact_rag_source(source) for source in rag_sources],
            "citation_refs": citation_refs,
            "rag_query": load_context.get("rag_query") or data.get("rag_query"),
            "rag_filters": load_context.get("rag_filters") or data.get("rag_filters") or {},
            "fallback_used": bool(
                load_context.get("rag_fallback_used") or data.get("rag_fallback_used")
            ),
            "selected_count": len(selected_assets),
            "omitted_count": len(omitted_assets),
            "selected_assets": [_compact_context_asset(asset) for asset in selected_assets],
            "omitted_assets": [_compact_context_asset(asset) for asset in omitted_assets],
            "gap_count": len(rag_gaps),
            "evidence_gaps": rag_gaps,
            "provider_gap_count": len(provider_gaps),
            "provider_gaps": provider_gaps,
            "authority": RAG_EVIDENCE_BOUNDARY,
            "state_reference_only": True,
        }
    )
    failure = None
    if degraded:
        failure = sanitize_runtime_value(
            {
                "gap_count": len(rag_gaps),
                "provider_gaps": provider_gaps,
                "omitted_assets": [_compact_context_asset(asset) for asset in omitted_assets],
                "empty_result": len(rag_sources) == 0,
            }
        )

    return ToolObservation(
        tool_id=RAG_RETRIEVAL_TOOL_ID,
        tool_name="RAG 数学知识检索证据",
        provider=provider,
        provider_mode=provider_mode,
        status=status,
        degraded=degraded,
        fallback_used=provider_mode == "local_fallback",
        result_summary=result_summary,
        evidence_boundary=RAG_EVIDENCE_BOUNDARY,
        evidence_refs=list(dict.fromkeys(evidence_refs)),
        failure=failure,
    )


def _student_memory_evidence_handler(invocation: ToolInvocation) -> ToolObservation:
    data = invocation.input_summary
    load_context = _dict_or_empty(data.get("load_context"))
    assembled_context = _dict_or_empty(data.get("assembled_context"))
    context_selection = _selection_from_input(data)
    student_memories = _list_of_dicts(data.get("student_memories"))
    selected_assets, omitted_assets = _assets_by_type(context_selection, "student_memory")
    memory_gaps = _memory_evidence_gaps(
        data=data,
        assembled_context=assembled_context,
        omitted_assets=omitted_assets,
    )
    provider, provider_mode = _provider_identity(
        sources=student_memories,
        selected_assets=selected_assets,
        omitted_assets=omitted_assets,
        gaps=memory_gaps,
        default_provider="local_fallback",
    )
    provider_gaps = [gap for gap in memory_gaps if _is_provider_gap(gap)]
    degraded = bool(provider_gaps or omitted_assets or memory_gaps)
    status: ToolObservationStatus = "degraded" if degraded else "completed"
    evidence_refs = _turn_trace_refs(invocation)
    evidence_refs.extend(
        _memory_ref(memory) for memory in student_memories if _memory_ref(memory)
    )
    evidence_refs.extend(
        str(asset["source_ref"]) for asset in [*selected_assets, *omitted_assets] if asset.get("source_ref")
    )
    result_summary = sanitize_runtime_value(
        {
            "memory_query": load_context.get("memory_query") or data.get("memory_query"),
            "retrieved_count": len(student_memories),
            "selected_count": len(selected_assets),
            "omitted_count": len(omitted_assets),
            "retrieved_memories": [_compact_student_memory(memory) for memory in student_memories],
            "selected_assets": [_compact_context_asset(asset) for asset in selected_assets],
            "omitted_assets": [_compact_context_asset(asset) for asset in omitted_assets],
            "disabled_excluded_count": sum(
                1 for asset in omitted_assets if _looks_disabled_memory_asset(asset)
            ),
            "gap_count": len(memory_gaps),
            "evidence_gaps": memory_gaps,
            "provider_gap_count": len(provider_gaps),
            "provider_gaps": provider_gaps,
            "authority": STUDENT_MEMORY_EVIDENCE_BOUNDARY,
            "state_reference_only": True,
        }
    )
    failure = None
    if degraded:
        failure = sanitize_runtime_value(
            {
                "gap_count": len(memory_gaps),
                "provider_gaps": provider_gaps,
                "omitted_assets": [_compact_context_asset(asset) for asset in omitted_assets],
                "disabled_excluded_count": result_summary["disabled_excluded_count"],
            }
        )

    return ToolObservation(
        tool_id=STUDENT_MEMORY_TOOL_ID,
        tool_name="学生记忆证据",
        provider=provider,
        provider_mode=provider_mode,
        status=status,
        degraded=degraded,
        fallback_used=provider_mode == "local_fallback",
        result_summary=result_summary,
        evidence_boundary=STUDENT_MEMORY_EVIDENCE_BOUNDARY,
        evidence_refs=list(dict.fromkeys(evidence_refs)),
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


def _turn_trace_refs(invocation: ToolInvocation) -> list[str]:
    refs: list[str] = []
    if invocation.trace_id:
        refs.append(f"trace:{invocation.trace_id}")
    if invocation.turn_id:
        refs.append(f"turn:{invocation.turn_id}")
    return refs


def _selection_from_input(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    direct = _dict_or_empty(data.get("context_asset_selection"))
    assembled = _dict_or_empty(data.get("assembled_context"))
    assembled_selection = _dict_or_empty(assembled.get("asset_selection"))
    selected = _list_of_dicts(direct.get("selected")) or _list_of_dicts(
        assembled_selection.get("selected")
    )
    omitted = _list_of_dicts(direct.get("omitted")) or _list_of_dicts(
        assembled_selection.get("omitted")
    )
    return {"selected": selected, "omitted": omitted}


def _assets_by_type(
    selection: dict[str, list[dict[str, Any]]],
    asset_type: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = [
        asset for asset in selection.get("selected", []) if asset.get("asset_type") == asset_type
    ]
    omitted = [
        asset for asset in selection.get("omitted", []) if asset.get("asset_type") == asset_type
    ]
    return selected, omitted


def _rag_evidence_gaps(
    *,
    data: dict[str, Any],
    assembled_context: dict[str, Any],
    omitted_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps = []
    for gap in _all_gap_records(data, assembled_context):
        gap_type = _gap_type(gap)
        if gap_type in PROVIDER_EVIDENCE_GAP_TYPES and _gap_provider(gap) in {
            "vikingdb",
            "openviking",
            "rag",
            "local_rag",
            "fake_vikingdb",
        }:
            gaps.append(gap)
        elif gap_type in {
            "missing_rag_citation",
            "knowledge_resource",
            "context_budget",
        }:
            if gap_type != "context_budget" or _has_asset_type(omitted_assets, "knowledge_resource"):
                gaps.append(gap)
    return _dedupe_gaps(gaps)


def _memory_evidence_gaps(
    *,
    data: dict[str, Any],
    assembled_context: dict[str, Any],
    omitted_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps = []
    for gap in _all_gap_records(data, assembled_context):
        gap_type = _gap_type(gap)
        if gap_type in PROVIDER_EVIDENCE_GAP_TYPES and _gap_provider(gap) in {
            "mem0",
            "memory",
            "local_fallback",
            "fake_mem0_fixture",
        }:
            gaps.append(gap)
        elif gap_type in {"student_memory", "memory_control"}:
            gaps.append(gap)
    for asset in omitted_assets:
        if _looks_disabled_memory_asset(asset):
            gaps.append(
                {
                    "gap_type": "memory_control",
                    "reason": asset.get("excluded_reason"),
                    "impact": "disabled memory is omitted from assembled context",
                    "severity": "info",
                    "recoverable": True,
                    "source_ref": asset.get("source_ref"),
                }
            )
    return _dedupe_gaps(gaps)


def _all_gap_records(
    data: dict[str, Any],
    assembled_context: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    records.extend(_list_of_dicts(data.get("evidence_gaps")))
    records.extend(_list_of_dicts(assembled_context.get("evidence_gaps")))
    records.extend(_list_of_dicts(data.get("error_records")))
    load_context = _dict_or_empty(data.get("load_context"))
    records.extend(_list_of_dicts(load_context.get("evidence_gap_records")))
    memory_update = _dict_or_empty(data.get("memory_update"))
    records.extend(_list_of_dicts(memory_update.get("provider_evidence_gaps")))
    return records


def _dedupe_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for gap in gaps:
        compact = sanitize_runtime_value(gap)
        key = (
            _gap_type(compact),
            compact.get("reason") or compact.get("message"),
            _gap_provider(compact),
            compact.get("operation"),
            compact.get("source_ref"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(compact)
    return deduped


def _gap_type(gap: dict[str, Any]) -> str:
    return str(gap.get("gap_type") or gap.get("category") or gap.get("code") or "")


def _gap_provider(gap: dict[str, Any]) -> str:
    details = _dict_or_empty(gap.get("details"))
    provider = gap.get("provider") or details.get("provider")
    return str(provider or "").lower()


def _is_provider_gap(gap: dict[str, Any]) -> bool:
    return _gap_type(gap) in PROVIDER_EVIDENCE_GAP_TYPES


def _has_asset_type(assets: list[dict[str, Any]], asset_type: str) -> bool:
    return any(asset.get("asset_type") == asset_type for asset in assets)


def _provider_identity(
    *,
    sources: list[dict[str, Any]],
    selected_assets: list[dict[str, Any]],
    omitted_assets: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    default_provider: str,
) -> tuple[str, ToolProviderMode]:
    for gap in gaps:
        provider = _gap_provider(gap)
        if provider:
            return provider, _provider_mode_from_name(provider)
    for asset in [*selected_assets, *omitted_assets]:
        metadata = _dict_or_empty(asset.get("metadata"))
        provider = _dict_or_empty(metadata.get("provider"))
        provider_name = str(
            metadata.get("provider_name")
            or provider.get("provider_name")
            or provider.get("name")
            or asset.get("source_type")
            or default_provider
        )
        provider_mode = str(metadata.get("provider_mode") or provider.get("provider_mode") or "")
        if provider_mode:
            return provider_name, _coerce_provider_mode(provider_mode)
        if provider_name:
            return provider_name, _provider_mode_from_name(provider_name)
    for source in sources:
        source_name = str(source.get("source") or source.get("provider") or "")
        if source_name:
            return default_provider, _provider_mode_from_name(default_provider)
    return default_provider, _provider_mode_from_name(default_provider)


def _provider_mode_from_name(provider: str) -> ToolProviderMode:
    lowered = provider.lower()
    if any(token in lowered for token in ("local", "demo", "mock")):
        return "local_fallback"
    if "fake" in lowered:
        return "fake_provider"
    if any(token in lowered for token in ("mem0", "viking", "openviking", "dgekt")):
        return "live_provider"
    return "unknown"


def _coerce_provider_mode(mode: str) -> ToolProviderMode:
    if mode in {"local_fallback", "fake_provider", "live_provider", "unknown"}:
        return mode  # type: ignore[return-value]
    return _provider_mode_from_name(mode)


def _compact_rag_source(source: dict[str, Any]) -> dict[str, Any]:
    return sanitize_runtime_value(
        {
            "doc_id": source.get("doc_id"),
            "doc_type": source.get("doc_type"),
            "title": source.get("title"),
            "source": source.get("source"),
            "concept_id": source.get("concept_id"),
            "question_id": source.get("question_id"),
            "assist2017_question_id": source.get("assist2017_question_id"),
            "assist2017_concept_id": source.get("assist2017_concept_id"),
            "coverage": source.get("coverage"),
        }
    )


def _compact_student_memory(memory: dict[str, Any]) -> dict[str, Any]:
    return sanitize_runtime_value(
        {
            "memory_id": memory.get("memory_id"),
            "memory_type": memory.get("memory_type"),
            "summary": memory.get("summary") or memory.get("content"),
            "source": memory.get("source"),
            "enabled": memory.get("enabled"),
            "status": memory.get("status"),
            "freshness": memory.get("freshness"),
            "relevance_score": memory.get("relevance_score"),
        }
    )


def _compact_context_asset(asset: dict[str, Any]) -> dict[str, Any]:
    return sanitize_runtime_value(
        {
            "asset_id": asset.get("asset_id"),
            "asset_type": asset.get("asset_type"),
            "source_type": asset.get("source_type"),
            "source_ref": asset.get("source_ref"),
            "summary": asset.get("summary"),
            "included_reason": asset.get("included_reason"),
            "excluded_reason": asset.get("excluded_reason"),
            "confidence": asset.get("confidence"),
            "freshness": asset.get("freshness"),
        }
    )


def _rag_citation_refs(sources: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for source in sources:
        if source.get("source"):
            refs.append(str(source["source"]))
        elif source.get("doc_id"):
            refs.append(f"rag:{source['doc_id']}")
    return list(dict.fromkeys(refs))


def _memory_ref(memory: dict[str, Any]) -> str | None:
    memory_id = memory.get("memory_id")
    return f"memory:{memory_id}" if memory_id else None


def _looks_disabled_memory_asset(asset: dict[str, Any]) -> bool:
    reason = str(asset.get("excluded_reason") or "")
    return "禁用" in reason or "disabled" in reason.lower()


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
