from __future__ import annotations

from typing import Any

from ..graph.learning_loop import MathTutorLearningLoop, learning_loop as default_learning_loop
from ..schemas.learning import LearningEvent, MathTutorEventResponse
from ..schemas.trace import TeachingTraceEvent, TeachingTraceEventType
from .capabilities import (
    CapabilitySelection,
    MathCapabilityRegistry,
    default_capability_registry,
)
from .context import LearningTurnContext, RuntimeIntent
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
        tool_observations = self._collect_tool_observations(
            response=response,
            context=turn_context,
        )
        response.teaching_trace.extend(
            self._tool_observation_trace(observation)
            for observation in tool_observations
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
        response.teaching_trace_summary.expert_evidence = sanitize_runtime_value(
            expert_evidence
        )

    def _collect_tool_observations(
        self,
        *,
        response: MathTutorEventResponse,
        context: LearningTurnContext,
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
        observations = self._call_tool_if_available(KT_AUTHORITY_TOOL_ID, invocation)
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
        observations.extend(
            self._call_tool_if_available(RAG_RETRIEVAL_TOOL_ID, rag_invocation)
        )
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
        observations.extend(
            self._call_tool_if_available(STUDENT_MEMORY_TOOL_ID, memory_invocation)
        )
        return observations

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
        return TeachingTraceEvent(
            type=TeachingTraceEventType.OBSERVATION,
            stage=stage,
            actor=actor,
            visibility=observation.visibility,
            content=self._tool_observation_content(observation),
            metadata={
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
