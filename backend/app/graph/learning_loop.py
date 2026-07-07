from __future__ import annotations

from typing import Any, Literal

from ..kt.engine import KTStateEngine
from ..kt.mock_engine import MockKTStateEngine
from ..schemas.learning import (
    LearningEvent,
    MathTutorEventResponse,
    MathTutorState,
)
from ..schemas.trace import TeachingTraceEvent, TeachingTraceEventType
from ..storage.progress_store import InMemoryProgressStore, progress_store


class MathTutorLearningLoop:
    def __init__(
        self,
        kt_engine: KTStateEngine | None = None,
        store: InMemoryProgressStore | None = None,
    ) -> None:
        self.kt_engine = kt_engine or MockKTStateEngine()
        self.store = store or progress_store

    def handle_event(self, event: LearningEvent) -> MathTutorEventResponse:
        progress = self.store.get_or_create(event.student_id)
        state = MathTutorState(
            session_id=event.session_id,
            student_id=event.student_id,
            intent=self._classify_intent(event),
            learning_event=event,
            kt_progress=progress,
        )

        self._load_context(state)
        self._diagnose(state)
        self._plan(state)
        self._generate_response(state)

        self.store.save(state.kt_progress)
        return MathTutorEventResponse(
            response=state.response,
            state_summary=state.summary(),
            recommended_questions=state.recommended_questions,
            teaching_trace=state.teaching_trace,
        )

    def _load_context(self, state: MathTutorState) -> None:
        state.teaching_trace.append(
            self._trace(
                stage="load_context",
                content="已读取学生学习进度、长期记忆占位和 RAG 上下文占位。",
                metadata={
                    "progress_version_before": state.kt_progress.version,
                    "memory_count": len(state.student_memories),
                    "rag_context_count": len(state.rag_context),
                },
            )
        )
        state.kt_progress = self.kt_engine.update_from_event(
            state.kt_progress,
            state.learning_event,
        )

    def _diagnose(self, state: MathTutorState) -> None:
        target_question_id = self._target_question_id(state.learning_event)
        state.kt_diagnosis = self.kt_engine.diagnose(
            state.kt_progress,
            target_question_id=target_question_id,
        )
        state.kt_progress.weak_concepts = state.kt_diagnosis.weak_concepts
        state.kt_progress.forgetting_risks = state.kt_diagnosis.forgetting_risks
        state.teaching_trace.append(
            self._trace(
                stage="diagnose",
                content="MockKT 已产出权威学习诊断事实。",
                metadata={
                    "target_question_id": target_question_id,
                    "weak_concept_count": len(state.kt_diagnosis.weak_concepts),
                    "forgetting_risk_count": len(state.kt_diagnosis.forgetting_risks),
                    "prediction_probability": state.kt_diagnosis.prediction_probability,
                    "evidence": state.kt_diagnosis.evidence,
                },
            )
        )

    def _plan(self, state: MathTutorState) -> None:
        if state.intent == "answer_submission":
            is_correct = state.learning_event.payload.get("is_correct")
            state.next_action = {
                "type": "review_answer" if is_correct is False else "reinforce_mastery",
                "label": "讲解错因并安排同类练习" if is_correct is False else "巩固掌握并推荐下一题",
            }
        elif state.intent == "next_step_advice":
            state.next_action = {
                "type": "recommend_next_question",
                "label": "根据薄弱知识点推荐下一步练习",
            }
            state.recommended_questions = [
                {
                    "question_id": "placeholder-q-risk-1",
                    "title": "待接入题库的风险优先推荐占位题",
                    "reason": "当前切片先打通主循环，#4/#5 将接入真实题库和排序理由。",
                }
            ]
        else:
            state.next_action = {
                "type": "answer_question",
                "label": "回答学生问题并保留学习上下文",
            }

        state.teaching_trace.append(
            self._trace(
                stage="plan",
                content="已生成最小教学动作计划。",
                metadata={
                    "intent": state.intent,
                    "next_action": state.next_action,
                    "recommended_question_count": len(state.recommended_questions),
                },
            )
        )

    def _generate_response(self, state: MathTutorState) -> None:
        if state.intent == "answer_submission":
            state.response = self._answer_submission_response(state)
        elif state.intent == "next_step_advice":
            state.response = "我已经查看你的学习状态。下一步建议先练一题风险较高的知识点题目，推荐列表里先给出占位题，后续会接入真实题库。"
        else:
            state.response = "我已收到你的问题。当前 V1 主循环已经记录上下文，后续会结合本地数学知识库给出更完整讲解。"

        state.teaching_trace.append(
            self._trace(
                stage="generate_response",
                content="已生成学生可读中文回复。",
                metadata={"response_length": len(state.response)},
            )
        )

    def _answer_submission_response(self, state: MathTutorState) -> str:
        question_id = state.learning_event.payload.get("question_id", "这道题")
        is_correct = state.learning_event.payload.get("is_correct")
        if is_correct is True:
            return f"收到，你提交的 {question_id} 判定为正确。我会把这次作答计入学习进度，并继续推荐下一步巩固练习。"
        if is_correct is False:
            return f"收到，你提交的 {question_id} 目前判定为不正确。我会优先安排错因讲解和同类练习，先帮你把薄弱点补稳。"
        return f"收到，你提交了 {question_id} 的答案。我已记录这次作答，后续会接入确定性判题来更新诊断。"

    def _classify_intent(self, event: LearningEvent) -> Literal[
        "next_step_advice",
        "answer_submission",
        "general_chat",
    ]:
        if event.type == "answer_submitted":
            return "answer_submission"
        if event.type == "chat_message" and any(
            keyword in event.message for keyword in ("下一步", "推荐", "练什么", "学什么")
        ):
            return "next_step_advice"
        return "general_chat"

    def _target_question_id(self, event: LearningEvent) -> str | None:
        question_id = event.payload.get("question_id")
        return str(question_id) if question_id else None

    def _trace(
        self,
        stage: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> TeachingTraceEvent:
        return TeachingTraceEvent(
            type=TeachingTraceEventType.OBSERVATION,
            stage=stage,
            content=content,
            metadata=metadata or {},
        )


learning_loop = MathTutorLearningLoop()
