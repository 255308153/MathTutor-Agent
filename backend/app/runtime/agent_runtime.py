from __future__ import annotations

from typing import Any

from ..graph.learning_loop import MathTutorLearningLoop, learning_loop as default_learning_loop
from ..schemas.learning import LearningEvent, MathTutorEventResponse
from ..schemas.trace import TeachingTraceEvent, TeachingTraceEventType
from .context import LearningTurnContext, RuntimeIntent


class MathTutorAgentRuntime:
    """V1.9 top-level orchestration seam for one mathematics learning turn."""

    def __init__(self, learning_loop: MathTutorLearningLoop | None = None) -> None:
        self.learning_loop = learning_loop or default_learning_loop

    def handle_event(self, event: LearningEvent) -> MathTutorEventResponse:
        turn_context = self._build_turn_context(event)
        start_event = self._runtime_trace(
            event_type=TeachingTraceEventType.STAGE_START,
            stage="runtime_start",
            content="MathTutorAgentRuntime 已接收本轮数学学习事件。",
            metadata={
                "runtime_name": turn_context.runtime_name,
                "turn_id": turn_context.turn_id,
                "subject": turn_context.subject,
                "intent": turn_context.intent,
                "learning_event_type": event.type,
                "kt_progress_version_before": turn_context.kt_progress.version,
                "state_reference_only": True,
                "boundary": "Agent runtime orchestrates teaching flow, not KT facts.",
            },
            evidence_refs=[f"turn:{turn_context.turn_id}"],
        )
        response = self.learning_loop.handle_event(event)
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
        self._attach_runtime_summary(response, completed_context)
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

    def _attach_runtime_summary(
        self,
        response: MathTutorEventResponse,
        context: LearningTurnContext,
    ) -> None:
        response.teaching_trace_summary.stages = [
            event.stage for event in response.teaching_trace
        ]
        expert_evidence = dict(response.teaching_trace_summary.expert_evidence)
        expert_evidence["learning_turn_context"] = context.public_summary()
        expert_evidence["runtime"] = {
            "runtime_name": context.runtime_name,
            "turn_id": context.turn_id,
            "subject": context.subject,
            "intent": context.intent,
            "status": "completed",
            "state_reference_only": True,
            "boundary": "Agent runtime is orchestration; KT remains authoritative.",
        }
        response.teaching_trace_summary.expert_evidence = expert_evidence
