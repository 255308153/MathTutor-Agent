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
from ..storage.content_repository import DemoTeachingContentRepository, content_repository
from ..storage.progress_store import InMemoryProgressStore, progress_store


class MathTutorLearningLoop:
    def __init__(
        self,
        kt_engine: KTStateEngine | None = None,
        store: InMemoryProgressStore | None = None,
        content: DemoTeachingContentRepository | None = None,
    ) -> None:
        self.kt_engine = kt_engine or MockKTStateEngine()
        self.store = store or progress_store
        self.content = content or content_repository

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
        self._grade_answer_if_needed(state)
        state.teaching_trace.append(
            self._trace(
                stage="load_context",
                content="已读取学生学习进度、长期记忆占位和 RAG 上下文占位。",
                metadata={
                    "progress_version_before": state.kt_progress.version,
                    "memory_count": len(state.student_memories),
                    "rag_context_count": len(state.rag_context),
                    "grading_source": state.learning_event.payload.get("grading_source"),
                    "is_correct": state.learning_event.payload.get("is_correct"),
                    "correct_answer_available": "correct_answer" in state.learning_event.payload,
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
            if is_correct is None:
                state.next_action = {
                    "type": "record_ungraded_answer",
                    "label": "记录未判题作答并等待内容集补齐",
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
                return
            state.next_action = {
                "type": "review_answer" if is_correct is False else "reinforce_mastery",
                "label": "讲解错因并安排同类练习" if is_correct is False else "巩固掌握并推荐下一题",
            }
        elif state.intent == "next_step_advice":
            state.next_action = {
                "type": "recommend_next_question",
                "label": "根据薄弱知识点推荐下一步练习",
            }
            question = self.content.first_recommendable_question()
            state.kt_progress.pending_question = question
            state.recommended_questions = [
                self.content.public_question(question)
                | {"reason": "当前先返回 demo 内容集中的第一道可作答题，#5 将改为风险优先排序。"}
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
            question = state.recommended_questions[0]
            state.response = f"我已经查看你的学习状态。下一步先练：{question['stem']} 这题来自「{question['concept_name']}」，做完后我会用标准答案确定性判题。"
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
            return f"收到，你提交的 {question_id} 已由服务端标准答案判定为正确。我会把这次作答计入学习进度，并继续推荐下一步巩固练习。"
        if is_correct is False:
            correct_answer = state.learning_event.payload.get("correct_answer", "标准答案")
            return f"收到，你提交的 {question_id} 已由服务端标准答案判定为不正确。正确答案是 {correct_answer}，我会优先安排错因讲解和同类练习。"
        return f"收到，你提交了 {question_id} 的答案，但我还没有在内容集中找到这道题，暂时只记录事件。"

    def _grade_answer_if_needed(self, state: MathTutorState) -> None:
        if state.learning_event.type != "answer_submitted":
            return

        for key in (
            "is_correct",
            "correct_answer",
            "concept_id",
            "concept_name",
            "difficulty",
            "teaching_type",
            "mistake_patterns",
            "rag_doc_ids",
            "grading_source",
        ):
            state.learning_event.payload.pop(key, None)

        question_id = state.learning_event.payload.get("question_id")
        if not question_id and state.kt_progress.pending_question:
            question_id = state.kt_progress.pending_question.get("question_id")
            state.learning_event.payload["question_id"] = question_id

        if not question_id:
            state.errors.append("answer_submitted missing question_id")
            return

        grade = self.content.grade(
            question_id=str(question_id),
            submitted_answer=state.learning_event.payload.get("answer"),
        )
        if grade is None:
            state.errors.append(f"unknown question_id: {question_id}")
            return

        state.learning_event.payload.update(
            {
                "is_correct": grade.is_correct,
                "correct_answer": grade.question["standard_answer"],
                "concept_id": grade.question["concept_id"],
                "concept_name": grade.question["concept_name"],
                "difficulty": grade.question["difficulty"],
                "teaching_type": grade.question["teaching_type"],
                "mistake_patterns": grade.question["mistake_patterns"],
                "rag_doc_ids": grade.question["rag_doc_ids"],
                "grading_source": "demo_teaching_content",
            }
        )

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
