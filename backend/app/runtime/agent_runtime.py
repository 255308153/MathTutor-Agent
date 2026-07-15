from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from ..graph.learning_loop import MathTutorLearningLoop, learning_loop as default_learning_loop
from ..schemas.learning import LearningEvent, MathTutorEventResponse
from ..schemas.trace import (
    RuntimeToolCallView,
    RuntimeToolObservationView,
    RuntimeTraceOverview,
    RuntimeTraceStageView,
    TeachingTraceEvent,
    TeachingTraceEventType,
)
from .capabilities import (
    CapabilitySelection,
    MathCapabilityRegistry,
    default_capability_registry,
)
from .context import LearningTurnContext, RuntimeIntent
from .governance import ContextGovernanceOverview, ResponseContextPackage
from .tools import (
    KT_AUTHORITY_TOOL_ID,
    RAG_RETRIEVAL_TOOL_ID,
    STUDENT_MEMORY_TOOL_ID,
    MathToolRegistry,
    ToolInvocation,
    ToolObservation,
    default_tool_registry,
    sanitize_runtime_value,
)


class MathTutorAgentRuntime:
    """V1.9 top-level orchestration seam for one mathematics learning turn."""

    def __init__(
        self,
        learning_loop: MathTutorLearningLoop | None = None,
        capability_registry: MathCapabilityRegistry | None = None,
        tool_registry: MathToolRegistry | None = None,
    ) -> None:
        self.learning_loop = learning_loop or default_learning_loop
        self.capability_registry = capability_registry or default_capability_registry
        self.tool_registry = tool_registry or default_tool_registry()

    def handle_event(self, event: LearningEvent) -> MathTutorEventResponse:
        turn_context = self._build_turn_context(event)
        capability_selection = self.capability_registry.select(turn_context)
        capability_summary = capability_selection.public_summary()
        start_event = self._runtime_trace(
            event_type=TeachingTraceEventType.STAGE_START,
            stage="runtime_start",
            content=self._runtime_start_content(capability_selection),
            metadata={
                "runtime_name": turn_context.runtime_name,
                "turn_id": turn_context.turn_id,
                "subject": turn_context.subject,
                "intent": turn_context.intent,
                "capability_selection": capability_summary,
                "learning_event_type": event.type,
                "kt_progress_version_before": turn_context.kt_progress.version,
                "state_reference_only": True,
                "boundary": (
                    "Agent runtime orchestrates teaching flow; capability selection "
                    "cannot overwrite KT facts."
                ),
            },
            evidence_refs=[
                f"turn:{turn_context.turn_id}",
                f"capability:{capability_summary['capability_id']}",
            ],
        )
        response = self.learning_loop.handle_event(event)
        tool_mounts = self._tool_mount_decisions(response=response, context=turn_context)
        tool_observations = self._collect_tool_observations(
            response=response,
            context=turn_context,
            tool_mounts=tool_mounts,
        )
        response.teaching_trace.extend(
            self._tool_observation_trace(observation)
            for observation in tool_observations
        )
        governance = self._context_governance_overview(
            response=response,
            context=turn_context,
            tool_observations=tool_observations,
            tool_mounts=tool_mounts,
        )
        response_context = self._response_context_package(
            response=response,
            context=turn_context,
            governance=governance,
        )
        governance.response_context_ref = response_context.context_package_id
        response.teaching_trace_summary.expert_evidence["context_governance"] = governance.model_dump(
            mode="json"
        )
        response.teaching_trace_summary.expert_evidence["response_context_package"] = (
            response_context.model_dump(mode="json")
        )
        completed_progress = self.learning_loop.store.get_or_create(
            event.student_id
        ).model_copy(deep=True)
        completed_context = turn_context.model_copy(
            update={"kt_progress": completed_progress},
            deep=True,
        ).complete_from_response(response)
        end_event = self._runtime_trace(
            event_type=TeachingTraceEventType.STAGE_END,
            stage="runtime_end",
            content="MathTutorAgentRuntime 已完成本轮学习编排并保持现有学习响应兼容。",
            metadata={
                "runtime_name": completed_context.runtime_name,
                "turn_id": completed_context.turn_id,
                "subject": completed_context.subject,
                "intent": completed_context.intent,
                "capability_selection": capability_summary,
                "kt_progress_version_after": completed_context.kt_progress.version,
                "context_asset_ref_count": len(completed_context.context_asset_refs),
                "assembled_context_ref": completed_context.assembled_context_ref,
                "trace_refs": completed_context.trace_refs,
                "state_reference_only": True,
                "boundary": "Runtime trace is observational and cannot overwrite KT facts.",
                "learning_turn_context": completed_context.public_summary(),
            },
            evidence_refs=completed_context.trace_refs,
        )
        response.teaching_trace = [start_event, *response.teaching_trace, end_event]
        self._sanitize_trace_events(response)
        self._attach_runtime_summary(
            response,
            completed_context,
            capability_selection,
            tool_observations,
            tool_mounts,
        )
        return response

    def _build_turn_context(self, event: LearningEvent) -> LearningTurnContext:
        progress = self.learning_loop.store.get_or_create(event.student_id).model_copy(deep=True)
        return LearningTurnContext(
            session_id=event.session_id,
            student_id=event.student_id,
            intent=self._classify_intent(event),
            learning_event=event.model_copy(deep=True),
            kt_progress=progress,
        )

    def _classify_intent(self, event: LearningEvent) -> RuntimeIntent:
        classifier = getattr(self.learning_loop, "_classify_intent", None)
        if callable(classifier):
            return classifier(event)
        if event.type == "answer_submitted":
            return "answer_submission"
        if event.type == "chat_message" and any(
            keyword in event.message for keyword in ("下一步", "推荐", "练什么", "学什么")
        ):
            return "next_step_advice"
        return "general_chat"

    def _runtime_trace(
        self,
        *,
        event_type: TeachingTraceEventType,
        stage: str,
        content: str,
        metadata: dict[str, Any],
        evidence_refs: list[str],
    ) -> TeachingTraceEvent:
        return TeachingTraceEvent(
            type=event_type,
            stage=stage,
            actor="runtime",
            visibility="expert",
            content=content,
            metadata=metadata,
            evidence_refs=list(dict.fromkeys(evidence_refs)),
        )

    def _runtime_start_content(self, selection: CapabilitySelection) -> str:
        if selection.fallback:
            return (
                "MathTutorAgentRuntime 已接收本轮数学学习事件；"
                "未匹配专用数学能力，使用现有学习流 fallback。"
            )
        capability_name = selection.capability.name if selection.capability else "未知能力"
        return (
            "MathTutorAgentRuntime 已接收本轮数学学习事件；"
            f"已选择数学能力：{capability_name}。"
        )

    def _attach_runtime_summary(
        self,
        response: MathTutorEventResponse,
        context: LearningTurnContext,
        capability_selection: CapabilitySelection,
        tool_observations: list[ToolObservation],
        tool_mounts: list[dict[str, str]],
    ) -> None:
        response.teaching_trace_summary.stages = [
            event.stage for event in response.teaching_trace
        ]
        expert_evidence = dict(response.teaching_trace_summary.expert_evidence)
        capability_summary = capability_selection.public_summary()
        expert_evidence["learning_turn_context"] = context.public_summary()
        expert_evidence["active_capability"] = capability_summary
        expert_evidence["capability_manifest"] = self.capability_registry.manifest()
        expert_evidence["tool_registry_manifest"] = self.tool_registry.manifest()
        expert_evidence["tool_observations"] = [
            observation.public_summary() for observation in tool_observations
        ]
        expert_evidence["runtime"] = {
            "runtime_name": context.runtime_name,
            "turn_id": context.turn_id,
            "subject": context.subject,
            "intent": context.intent,
            "active_capability_id": capability_summary["capability_id"],
            "tool_observation_count": len(tool_observations),
            "tool_observation_refs": [
                f"tool_observation:{observation.tool_id}" for observation in tool_observations
            ],
            "status": "completed",
            "state_reference_only": True,
            "boundary": (
                "Agent runtime is orchestration; capability selection delegates execution "
                "and KT remains authoritative."
            ),
        }
        expert_evidence["trace_overview"] = self._runtime_trace_overview(
            response=response,
            context=context,
            capability_selection=capability_selection,
            tool_observations=tool_observations,
            tool_mounts=tool_mounts,
        ).model_dump(mode="json", exclude_none=True)
        response.teaching_trace_summary.expert_evidence = sanitize_runtime_value(
            expert_evidence
        )

    def _context_governance_overview(
        self,
        *,
        response: MathTutorEventResponse,
        context: LearningTurnContext,
        tool_observations: list[ToolObservation],
        tool_mounts: list[dict[str, str]],
    ) -> ContextGovernanceOverview:
        assembled = _dict_or_empty(
            response.teaching_trace_summary.expert_evidence.get("assembled_context")
        )
        selection = _dict_or_empty(assembled.get("asset_selection"))
        selected = _list_of_dicts(selection.get("selected"))
        omitted = _list_of_dicts(selection.get("omitted"))
        return ContextGovernanceOverview(
            intent=context.intent,
            budget_summary={
                "budget_used": assembled.get("budget_used"),
                "budget_limit": assembled.get("budget_limit"),
                "policy": "LearningContextLayer priority_budget_summary",
            },
            evidence_priority_rules=[
                "KT/DGEKT authoritative facts are non-clippable.",
                "Current task, question, answer, learning event, and capability target come first.",
                "RAG and student memory are ranked by intent, freshness, confidence, relevance, and authority boundary.",
            ],
            evidence_selection_summary={
                "selected_count": len(selected),
                "omitted_count": len(omitted),
                "clipped_count": sum(
                    "预算" in str(item.get("excluded_reason") or "") for item in omitted
                ),
                "policy": "LearningContextLayer priority_budget_summary",
            },
            evidence_decisions=[
                *[
                    {
                        "asset_id": item.get("asset_id"),
                        "asset_type": item.get("asset_type"),
                        "status": "selected",
                        "reason": item.get("included_reason"),
                    }
                    for item in selected
                ],
                *[
                    {
                        "asset_id": item.get("asset_id"),
                        "asset_type": item.get("asset_type"),
                        "status": (
                            "clipped"
                            if "预算" in str(item.get("excluded_reason") or "")
                            else "omitted"
                        ),
                        "reason": item.get("excluded_reason"),
                    }
                    for item in omitted
                ],
            ],
            non_clippable_evidence=["authoritative_kt_facts"],
            tool_mount_summary={
                "mounted": [
                    item["tool_id"] for item in tool_mounts if item["status"] == "mounted"
                ],
                "skipped": [
                    {"tool_id": item["tool_id"], "reason": item["reason"]}
                    for item in tool_mounts
                    if item["status"] == "skipped"
                ],
                "blocked": [
                    {"tool_id": item["tool_id"], "reason": item["reason"]}
                    for item in tool_mounts
                    if item["status"] == "blocked"
                ],
                "fallback_used": [
                    observation.tool_id
                    for observation in tool_observations
                    if observation.fallback_used
                ],
            },
            response_context_ref=None,
        )

    def _response_context_package(
        self,
        *,
        response: MathTutorEventResponse,
        context: LearningTurnContext,
        governance: ContextGovernanceOverview,
    ) -> ResponseContextPackage:
        assembled = _dict_or_empty(
            response.teaching_trace_summary.expert_evidence.get("assembled_context")
        )
        selected = _list_of_dicts(_dict_or_empty(assembled.get("asset_selection")).get("selected"))
        assets_by_type = {
            asset_type: [
                self._response_context_asset(item)
                for item in selected
                if item.get("asset_type") == asset_type
                and not _disabled_or_deleted_memory(item)
            ]
            for asset_type in ("task_state", "knowledge_resource", "student_memory")
        }
        evidence_refs = _dedupe_strings(
            ref
            for item in selected
            for ref in _list_or_empty(item.get("evidence_refs"))
        )
        return ResponseContextPackage(
            governance_id=governance.governance_id,
            intent=context.intent,
            authority_boundary={
                "kt_dgekt_facts": "authoritative learning facts; never overwritten by this package.",
                "task_state": "current task context only.",
                "rag_evidence": "explanation and citation support only.",
                "student_memory": "strategy and expression support only; never mastery.",
                "debug_evidence": "expert-only and excluded from the response context package.",
            },
            authoritative_kt_facts=_dict_or_empty(assembled.get("authoritative_kt_facts")),
            task_state=assets_by_type["task_state"],
            rag_evidence=assets_by_type["knowledge_resource"],
            student_memory=assets_by_type["student_memory"],
            evidence_refs=evidence_refs,
        )

    def _response_context_asset(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "asset_id": item.get("asset_id"),
            "source_ref": item.get("source_ref"),
            "summary": item.get("summary"),
            "evidence_refs": _list_or_empty(item.get("evidence_refs")),
        }

    def _runtime_trace_overview(
        self,
        *,
        response: MathTutorEventResponse,
        context: LearningTurnContext,
        capability_selection: CapabilitySelection,
        tool_observations: list[ToolObservation],
        tool_mounts: list[dict[str, str]],
    ) -> RuntimeTraceOverview:
        capability_summary = capability_selection.public_summary()
        tool_manifest = self.tool_registry.manifest()
        observation_by_tool = {
            observation.tool_id: observation.public_summary()
            for observation in tool_observations
        }
        tool_calls = [
            self._runtime_tool_call_view(
                manifest,
                observation_by_tool.get(manifest["tool_id"]),
                next(
                    (item for item in tool_mounts if item["tool_id"] == manifest["tool_id"]),
                    {"status": "skipped", "reason": "本轮未挂载该工具。"},
                ),
            )
            for manifest in tool_manifest
        ]
        observation_views = [
            self._runtime_tool_observation_view(observation)
            for observation in tool_observations
        ]
        provider_gaps = _dedupe_records(
            gap
            for observation in observation_views
            for gap in observation.provider_gaps
        )
        stage_events = [
            self._runtime_stage_view(event, capability_summary)
            for event in response.teaching_trace
        ]
        visibility_counts: dict[str, int] = {"student": 0, "expert": 0, "debug": 0}
        for event in stage_events:
            visibility_counts[event.visibility] = (
                visibility_counts.get(event.visibility, 0) + 1
            )
        evidence_refs = _dedupe_strings(
            ref for event in stage_events for ref in event.evidence_refs
        )
        return RuntimeTraceOverview(
            runtime_name=context.runtime_name,
            turn_id=context.turn_id,
            intent=context.intent,
            active_capability_id=str(capability_summary["capability_id"]),
            active_capability_name=str(
                capability_summary.get("capability_name")
                or capability_summary.get("name")
                or "现有学习流 fallback"
            ),
            active_capability_fallback=bool(capability_summary["fallback"]),
            active_capability_reason=str(capability_summary["reason"]),
            stage_events=stage_events,
            tool_calls=tool_calls,
            tool_observations=observation_views,
            evidence_refs=evidence_refs,
            visibility_counts=visibility_counts,
            provider_gap_count=sum(
                observation.provider_gap_count for observation in observation_views
            ),
            provider_gaps=provider_gaps,
        )

    def _runtime_tool_call_view(
        self,
        manifest: dict[str, Any],
        observation: dict[str, Any] | None,
        mount: dict[str, str],
    ) -> RuntimeToolCallView:
        provider_gap_count = _int_metric(
            _dict_or_empty(observation).get("result_summary"),
            "provider_gap_count",
        )
        return RuntimeToolCallView(
            tool_id=str(manifest["tool_id"]),
            name=str(manifest["name"]),
            stage=str(manifest["trace_stage"]),
            actor=str(manifest["trace_actor"]),
            visibility=manifest.get("visibility", "expert"),
            purpose=str(manifest.get("purpose") or ""),
            input_summary=str(manifest.get("input_summary") or ""),
            output_summary=str(manifest.get("output_summary") or ""),
            failure_modes=[str(item) for item in manifest.get("failure_modes", [])],
            provider_modes=[str(item) for item in manifest.get("provider_modes", [])],
            state_write_policy=str(manifest.get("state_write_policy") or ""),
            observed=observation is not None,
            mount_status=mount["status"],
            mount_reason=mount["reason"],
            provider=observation.get("provider") if observation else None,
            provider_mode=observation.get("provider_mode") if observation else None,
            status=observation.get("status") if observation else None,
            degraded=bool(observation.get("degraded")) if observation else False,
            fallback_used=bool(observation.get("fallback_used")) if observation else False,
            provider_gap_count=provider_gap_count,
            evidence_refs=[
                str(ref)
                for ref in _list_or_empty(
                    observation.get("evidence_refs") if observation else []
                )
            ],
        )

    def _runtime_tool_observation_view(
        self,
        observation: ToolObservation,
    ) -> RuntimeToolObservationView:
        summary = observation.public_summary()
        result_summary = _dict_or_empty(summary.get("result_summary"))
        tool = self.tool_registry.find(observation.tool_id)
        provider_gaps = _list_of_dicts(result_summary.get("provider_gaps"))
        return RuntimeToolObservationView(
            tool_id=observation.tool_id,
            name=observation.tool_name,
            stage=tool.trace_stage if tool else "tool_observation",
            actor=tool.trace_actor if tool else "system",
            visibility=observation.visibility,
            provider=observation.provider,
            provider_mode=observation.provider_mode,
            status=observation.status,
            degraded=observation.degraded,
            fallback_used=observation.fallback_used,
            metrics=_observation_metrics(result_summary),
            evidence_refs=list(dict.fromkeys(observation.evidence_refs)),
            evidence_boundary=observation.evidence_boundary,
            provider_gap_count=_int_metric(result_summary, "provider_gap_count"),
            provider_gaps=provider_gaps,
            gap_count=_int_metric(result_summary, "gap_count"),
            state_write_policy=observation.state_write_policy,
        )

    def _runtime_stage_view(
        self,
        event: TeachingTraceEvent,
        capability_summary: dict[str, Any],
    ) -> RuntimeTraceStageView:
        metadata = _dict_or_empty(event.metadata)
        tool_observation = _dict_or_empty(metadata.get("tool_observation"))
        result_summary = _dict_or_empty(
            metadata.get("result_summary") or tool_observation.get("result_summary")
        )
        capability = _dict_or_empty(metadata.get("capability_selection"))
        capability_id = capability.get("capability_id")
        tool_id = metadata.get("tool_id") or tool_observation.get("tool_id")
        return RuntimeTraceStageView(
            event_id=event.id,
            event_type=event.type.value,
            stage=event.stage,
            actor=event.actor,
            visibility=event.visibility,
            student_visible=event.visibility == "student",
            content=event.content,
            evidence_refs=list(dict.fromkeys(event.evidence_refs)),
            capability_id=str(capability_id or capability_summary["capability_id"])
            if event.stage.startswith("runtime_") or capability_id
            else None,
            tool_id=str(tool_id) if tool_id else None,
            provider=_optional_string(
                metadata.get("provider") or tool_observation.get("provider")
            ),
            provider_mode=_optional_string(
                metadata.get("provider_mode") or tool_observation.get("provider_mode")
            ),
            status=_optional_string(
                metadata.get("status") or tool_observation.get("status")
            ),
            degraded=bool(metadata.get("degraded") or tool_observation.get("degraded")),
            fallback_used=bool(
                metadata.get("fallback_used") or tool_observation.get("fallback_used")
            ),
            provider_gap_count=_int_metric(result_summary, "provider_gap_count"),
            gap_count=_int_metric(result_summary, "gap_count"),
            evidence_boundary=_optional_string(metadata.get("evidence_boundary")),
            state_write_policy=_optional_string(metadata.get("state_write_policy")),
        )

    def _collect_tool_observations(
        self,
        *,
        response: MathTutorEventResponse,
        context: LearningTurnContext,
        tool_mounts: list[dict[str, str]],
    ) -> list[ToolObservation]:
        expert_evidence = response.teaching_trace_summary.expert_evidence
        load_context_event = self._trace_event(response, "load_context")
        diagnose_event = self._trace_event(response, "diagnose")
        plan_event = self._trace_event(response, "plan")
        memory_update_event = self._trace_event(response, "memory_update")
        diagnostics = {}
        engine_name = self._kt_engine_name()
        error_records = expert_evidence.get("error_records") or []
        if diagnose_event is not None:
            diagnostics = diagnose_event.metadata.get("kt_engine_diagnostics") or {}
            engine_name = str(diagnose_event.metadata.get("kt_engine") or engine_name)
            error_records = diagnose_event.metadata.get("error_records") or error_records
        invocation = ToolInvocation(
            tool_id=KT_AUTHORITY_TOOL_ID,
            turn_id=context.turn_id,
            trace_id=response.trace_id,
            input_summary={
                "kt_engine": engine_name,
                "kt_engine_diagnostics": diagnostics,
                "kt_diagnosis": expert_evidence.get("kt_diagnosis"),
                "attribution_evidence": expert_evidence.get("attribution_evidence"),
                "error_records": error_records,
                "learning_event_type": context.learning_event.type,
            },
            context_summary={
                "learning_turn_context": context.public_summary(),
            },
        )
        mount_status = {item["tool_id"]: item["status"] for item in tool_mounts}
        observations = (
            self._call_tool_if_available(KT_AUTHORITY_TOOL_ID, invocation)
            if mount_status.get(KT_AUTHORITY_TOOL_ID) == "mounted"
            else []
        )
        assembled_context = expert_evidence.get("assembled_context") or {}
        context_asset_selection = (
            expert_evidence.get("context_asset_selection")
            or (
                assembled_context.get("asset_selection")
                if isinstance(assembled_context, dict)
                else None
            )
            or (plan_event.metadata.get("context_asset_selection") if plan_event else None)
            or {}
        )
        load_context_metadata = load_context_event.metadata if load_context_event else {}
        memory_update_metadata = memory_update_event.metadata if memory_update_event else {}
        rag_invocation = ToolInvocation(
            tool_id=RAG_RETRIEVAL_TOOL_ID,
            turn_id=context.turn_id,
            trace_id=response.trace_id,
            input_summary={
                "rag_sources": expert_evidence.get("rag_sources")
                or load_context_metadata.get("rag_sources")
                or [],
                "rag_query": load_context_metadata.get("rag_query"),
                "rag_filters": load_context_metadata.get("rag_filters"),
                "rag_fallback_used": load_context_metadata.get("rag_fallback_used"),
                "load_context": {
                    "rag_query": load_context_metadata.get("rag_query"),
                    "rag_filters": load_context_metadata.get("rag_filters"),
                    "rag_context_count": load_context_metadata.get("rag_context_count"),
                    "rag_fallback_used": load_context_metadata.get("rag_fallback_used"),
                    "evidence_gap_records": load_context_metadata.get(
                        "evidence_gap_records", []
                    ),
                },
                "assembled_context": assembled_context,
                "context_asset_selection": context_asset_selection,
                "evidence_gaps": expert_evidence.get("evidence_gaps") or [],
                "error_records": expert_evidence.get("error_records") or [],
                "learning_event_type": context.learning_event.type,
            },
            context_summary={"learning_turn_context": context.public_summary()},
        )
        if mount_status.get(RAG_RETRIEVAL_TOOL_ID) == "mounted":
            observations.extend(self._call_tool_if_available(RAG_RETRIEVAL_TOOL_ID, rag_invocation))
        memory_invocation = ToolInvocation(
            tool_id=STUDENT_MEMORY_TOOL_ID,
            turn_id=context.turn_id,
            trace_id=response.trace_id,
            input_summary={
                "student_memories": expert_evidence.get("student_memories") or [],
                "memory_query": load_context_metadata.get("memory_query"),
                "load_context": {
                    "memory_query": load_context_metadata.get("memory_query"),
                    "memory_count": load_context_metadata.get("memory_count"),
                    "evidence_gap_records": load_context_metadata.get(
                        "evidence_gap_records", []
                    ),
                },
                "memory_update": {
                    "memory_update_count": memory_update_metadata.get("memory_update_count"),
                    "provider_evidence_gaps": memory_update_metadata.get(
                        "provider_evidence_gaps", []
                    ),
                },
                "assembled_context": assembled_context,
                "context_asset_selection": context_asset_selection,
                "evidence_gaps": expert_evidence.get("evidence_gaps") or [],
                "error_records": expert_evidence.get("error_records") or [],
                "learning_event_type": context.learning_event.type,
            },
            context_summary={"learning_turn_context": context.public_summary()},
        )
        if mount_status.get(STUDENT_MEMORY_TOOL_ID) == "mounted":
            observations.extend(
                self._call_tool_if_available(STUDENT_MEMORY_TOOL_ID, memory_invocation)
            )
        return observations

    def _tool_mount_decisions(
        self,
        *,
        response: MathTutorEventResponse,
        context: LearningTurnContext,
    ) -> list[dict[str, str]]:
        evidence = response.teaching_trace_summary.expert_evidence
        has_rag = bool(evidence.get("rag_sources"))
        has_memory = bool(evidence.get("student_memories"))
        intent_policy = {
            "answer_submission": {
                KT_AUTHORITY_TOOL_ID: ("mounted", "答题提交必须保留 KT/DGEKT observation。"),
                RAG_RETRIEVAL_TOOL_ID: ("mounted", "当前题目可使用数学讲解 citation。"),
                STUDENT_MEMORY_TOOL_ID: ("skipped", "答题诊断优先当前题目与 KT facts。"),
            },
            "next_step_advice": {
                KT_AUTHORITY_TOOL_ID: ("mounted", "下一步建议需要 KT facts。"),
                RAG_RETRIEVAL_TOOL_ID: ("mounted", "下一步建议可使用 RAG 讲解证据。"),
                STUDENT_MEMORY_TOOL_ID: ("mounted", "下一步建议可使用学生记忆策略。"),
            },
            "general_chat": {
                KT_AUTHORITY_TOOL_ID: ("skipped", "概念讲解不挂载答题诊断工具。"),
                RAG_RETRIEVAL_TOOL_ID: (
                    ("mounted", "本轮概念讲解有可用 RAG evidence。")
                    if has_rag
                    else ("skipped", "本轮没有可用 RAG evidence。")
                ),
                STUDENT_MEMORY_TOOL_ID: (
                    ("mounted", "本轮概念讲解可使用学生记忆。")
                    if has_memory
                    else ("skipped", "本轮没有可用学生记忆。")
                ),
            },
        }[context.intent]
        decisions: list[dict[str, str]] = []
        for tool_id in (KT_AUTHORITY_TOOL_ID, RAG_RETRIEVAL_TOOL_ID, STUDENT_MEMORY_TOOL_ID):
            status, reason = intent_policy[tool_id]
            if self.tool_registry.find(tool_id) is None:
                status, reason = "blocked", "工具不可用，已保持 local fallback 学习路径。"
            decisions.append({"tool_id": tool_id, "status": status, "reason": reason})
        return decisions

    def _trace_event(
        self,
        response: MathTutorEventResponse,
        stage: str,
    ) -> TeachingTraceEvent | None:
        return next((event for event in response.teaching_trace if event.stage == stage), None)

    def _call_tool_if_available(
        self,
        tool_id: str,
        invocation: ToolInvocation,
    ) -> list[ToolObservation]:
        if self.tool_registry.find(tool_id) is None:
            return []
        return [self.tool_registry.call(tool_id, invocation)]

    def _tool_observation_trace(
        self,
        observation: ToolObservation,
    ) -> TeachingTraceEvent:
        summary = observation.public_summary()
        tool = self.tool_registry.find(observation.tool_id)
        stage = tool.trace_stage if tool else "tool_observation"
        actor = tool.trace_actor if tool else "system"
        tool_call = tool.manifest_entry() if tool else {}
        return TeachingTraceEvent(
            type=TeachingTraceEventType.OBSERVATION,
            stage=stage,
            actor=actor,
            visibility=observation.visibility,
            content=self._tool_observation_content(observation),
            metadata={
                "tool_call": tool_call,
                "tool_observation": summary,
                "tool_name": observation.tool_name,
                "tool_id": observation.tool_id,
                "provider": observation.provider,
                "provider_mode": observation.provider_mode,
                "status": observation.status,
                "degraded": observation.degraded,
                "fallback_used": observation.fallback_used,
                "result_summary": summary["result_summary"],
                "evidence_boundary": observation.evidence_boundary,
                "state_write_policy": observation.state_write_policy,
            },
            evidence_refs=observation.evidence_refs,
        )

    def _tool_observation_content(self, observation: ToolObservation) -> str:
        if observation.tool_id == KT_AUTHORITY_TOOL_ID:
            return (
                "Tool Registry 已记录 KT/DGEKT 权威学习事实 observation；"
                "RAG、学生记忆与 LLM 不能覆盖 prediction facts。"
            )
        if observation.tool_id == RAG_RETRIEVAL_TOOL_ID:
            return (
                "Tool Registry 已记录 RAG 数学知识检索 observation；"
                "RAG 只支持讲解和 citation，不能覆盖 KT facts。"
            )
        if observation.tool_id == STUDENT_MEMORY_TOOL_ID:
            return (
                "Tool Registry 已记录学生记忆 observation；"
                "记忆只影响教学策略和表达方式，不能改写 mastery。"
            )
        return "Tool Registry 已记录只读工具 observation。"

    def _sanitize_trace_events(self, response: MathTutorEventResponse) -> None:
        response.teaching_trace = [
            event.model_copy(
                update={
                    "content": sanitize_runtime_value(event.content),
                    "metadata": sanitize_runtime_value(event.metadata),
                    "evidence_refs": sanitize_runtime_value(event.evidence_refs),
                },
                deep=True,
            )
            for event in response.teaching_trace
        ]

    def _kt_engine_name(self) -> str:
        return str(
            getattr(
                self.learning_loop.kt_engine,
                "engine_name",
                self.learning_loop.kt_engine.__class__.__name__,
            )
        )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _int_metric(summary: Any, key: str) -> int:
    value = _dict_or_empty(summary).get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _disabled_or_deleted_memory(item: dict[str, Any]) -> bool:
    metadata = _dict_or_empty(item.get("metadata"))
    control = _dict_or_empty(metadata.get("memory_control"))
    status = str(control.get("status") or metadata.get("status") or "")
    return item.get("asset_type") == "student_memory" and status in {"disabled", "deleted"}


def _observation_metrics(
    result_summary: dict[str, Any],
) -> dict[str, str | int | float | bool | None]:
    allowed = {
        "prediction_probability",
        "weak_concept_count",
        "forgetting_risk_count",
        "result_count",
        "retrieved_count",
        "selected_count",
        "omitted_count",
        "disabled_excluded_count",
        "gap_count",
        "provider_gap_count",
        "fallback_used",
        "state_reference_only",
    }
    metrics: dict[str, str | int | float | bool | None] = {}
    for key in allowed:
        value = result_summary.get(key)
        if isinstance(value, (str, int, float, bool)):
            metrics[key] = value
    citation_refs = _list_or_empty(result_summary.get("citation_refs"))
    if citation_refs:
        metrics["citation_count"] = len(citation_refs)
    return metrics


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        ref = str(value)
        if ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def _dedupe_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        sanitized = sanitize_runtime_value(record)
        key = json.dumps(sanitized, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(sanitized)
    return deduped
