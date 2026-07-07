from __future__ import annotations

from typing import Any, Literal

from ..kt.engine import KTStateEngine
from ..kt.mock_engine import MockKTStateEngine
from ..planning.recommender import RiskPrioritizedRecommender, recommender
from ..rag.knowledge_rag import KnowledgeRAG, knowledge_rag
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
        question_recommender: RiskPrioritizedRecommender | None = None,
        rag: KnowledgeRAG | None = None,
    ) -> None:
        self.kt_engine = kt_engine or MockKTStateEngine()
        self.store = store or progress_store
        self.content = content or content_repository
        self.recommender = question_recommender or recommender
        self.rag = rag or knowledge_rag

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
        rag_query, rag_filters = self._build_rag_request(state)
        state.rag_context = [
            result.model_dump()
            for result in self.rag.search(query=rag_query, filters=rag_filters, limit=3)
        ]
        state.teaching_trace.append(
            self._trace(
                stage="load_context",
                content="已读取学生学习进度、长期记忆占位和 RAG 上下文占位。",
                metadata={
                    "progress_version_before": state.kt_progress.version,
                    "memory_count": len(state.student_memories),
                    "rag_context_count": len(state.rag_context),
                    "rag_query": rag_query,
                    "rag_filters": rag_filters,
                    "rag_sources": [
                        {"title": item["title"], "source": item["source"]}
                        for item in state.rag_context
                    ],
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
        ranked_questions: list[dict[str, Any]] = []
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
            ranked_questions = self.recommender.recommend(
                progress=state.kt_progress,
                diagnosis=state.kt_diagnosis,
                preferences=state.learning_event.payload,
                limit=len(self.content.list_questions()),
            )
            state.recommended_questions = ranked_questions[:3]
            first_question = self.content.get_question(state.recommended_questions[0]["question_id"])
            state.kt_progress.pending_question = first_question
            state.kt_progress.recommendation_history.extend(
                {
                    "question_id": question["question_id"],
                    "score": question["score"],
                    "reason": question["reason"],
                }
                for question in state.recommended_questions
            )
            state.kt_progress.recommendation_history = state.kt_progress.recommendation_history[-30:]
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
                    "candidate_count": len(self.content.list_questions()),
                    "recommendation_candidates": [
                        {
                            "question_id": question["question_id"],
                            "score": question["score"],
                            "score_factors": question["score_factors"],
                        }
                        for question in ranked_questions[:5]
                    ],
                    "selected_question_ids": [
                        question["question_id"] for question in state.recommended_questions
                    ],
                },
            )
        )

    def _generate_response(self, state: MathTutorState) -> None:
        if state.intent == "answer_submission":
            state.response = self._answer_submission_response(state)
        elif state.intent == "next_step_advice":
            question = state.recommended_questions[0]
            state.response = f"我已经查看你的学习状态。下一步先练：{question['stem']} 这题来自「{question['concept_name']}」。推荐理由：{question['reason']}。{self._citation_sentence(state)}做完后我会用标准答案确定性判题。"
        else:
            state.response = self._knowledge_response(state)

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
            return f"收到，你提交的 {question_id} 已由服务端标准答案判定为正确。我会把这次作答计入学习进度，并继续推荐下一步巩固练习。{self._citation_sentence(state)}"
        if is_correct is False:
            correct_answer = state.learning_event.payload.get("correct_answer", "标准答案")
            return f"收到，你提交的 {question_id} 已由服务端标准答案判定为不正确。正确答案是 {correct_answer}，我会优先安排错因讲解和同类练习。{self._citation_sentence(state)}"
        return f"收到，你提交了 {question_id} 的答案，但我还没有在内容集中找到这道题，暂时只记录事件。"

    def _knowledge_response(self, state: MathTutorState) -> str:
        if not state.rag_context:
            return "我已收到你的问题。当前 V1 主循环已经记录上下文，后续会结合本地数学知识库给出更完整讲解。"
        top = state.rag_context[0]
        return f"我查到一条相关知识：{top['content']} {self._citation_sentence(state)}"

    def _citation_sentence(self, state: MathTutorState) -> str:
        if not state.rag_context:
            return ""
        sources = "；".join(
            f"{item['title']}（{item['source']}）" for item in state.rag_context[:2]
        )
        return f"参考：{sources}。"

    def _build_rag_request(self, state: MathTutorState) -> tuple[str, dict[str, Any]]:
        if state.learning_event.type == "answer_submitted":
            query = " ".join(
                str(part)
                for part in (
                    state.learning_event.payload.get("concept_name", ""),
                    state.learning_event.payload.get("question_id", ""),
                    "错因 题解 学习策略",
                )
                if part
            )
            filters: dict[str, Any] = {
                "doc_types": ["question_explanation", "mistake_pattern", "learning_strategy"]
            }
            if state.learning_event.payload.get("question_id"):
                filters["question_id"] = state.learning_event.payload["question_id"]
            if state.learning_event.payload.get("concept_id"):
                filters["concept_id"] = state.learning_event.payload["concept_id"]
            return query, filters

        if state.intent == "next_step_advice":
            weak_concept_id = (
                state.kt_diagnosis.weak_concepts[0]["concept_id"]
                if state.kt_diagnosis and state.kt_diagnosis.weak_concepts
                else None
            )
            filters = {"doc_types": ["concept_note", "learning_strategy"]}
            if weak_concept_id:
                filters["concept_id"] = weak_concept_id
            return state.learning_event.message or "下一步 推荐 学习策略", filters

        return state.learning_event.message, {}

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
