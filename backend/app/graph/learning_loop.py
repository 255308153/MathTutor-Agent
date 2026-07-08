from __future__ import annotations

from typing import Any, Literal

from ..context.learning_context import LearningContextLayer, context_layer as default_context_layer
from ..kt.engine import KTStateEngine
from ..kt.factory import create_kt_engine
from ..memory.store import StudentMemory, StudentMemoryStore, memory_store
from ..planning.recommender import RiskPrioritizedRecommender, recommender
from ..planning.teaching_planner import TeachingPlanner, teaching_planner
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
        memories: StudentMemoryStore | None = None,
        planner: TeachingPlanner | None = None,
        context_layer: LearningContextLayer | None = None,
    ) -> None:
        self.kt_engine = kt_engine or create_kt_engine()
        self.store = store or progress_store
        self.content = content or content_repository
        self.recommender = question_recommender or recommender
        self.rag = rag or knowledge_rag
        self.memories = memories or memory_store
        self.planner = planner or teaching_planner
        self.context_layer = context_layer or default_context_layer

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
        self._assemble_context(state)
        self._plan(state)
        self._generate_response(state)
        self._update_memory(state)

        self.store.save(state.kt_progress)
        return MathTutorEventResponse(
            trace_id=state.trace_id,
            response=state.response,
            state_summary=state.summary(),
            recommended_questions=state.recommended_questions,
            teaching_trace=state.teaching_trace,
            teaching_trace_summary=state.trace_summary(),
        )

    def _load_context(self, state: MathTutorState) -> None:
        self._grade_answer_if_needed(state)
        memory_query = self._memory_query(state)
        state.student_memories = [
            memory.model_dump()
            for memory in self.memories.search(
                student_id=state.student_id,
                query=memory_query,
                limit=5,
            )
        ]
        rag_query, rag_filters = self._build_rag_request(state)
        rag_results = self.rag.search(query=rag_query, filters=rag_filters, limit=3)
        rag_fallback_used = False
        if not rag_results and rag_filters.get("question_id"):
            fallback_filters = dict(rag_filters)
            fallback_filters.pop("question_id", None)
            rag_results = self.rag.search(query=rag_query, filters=fallback_filters, limit=3)
            rag_fallback_used = True
        state.rag_context = [result.model_dump() for result in rag_results]
        state.teaching_trace.append(
            self._trace(
                stage="load_context",
                content="已读取学生学习进度、长期记忆和 RAG 上下文。",
                metadata={
                    "progress_version_before": state.kt_progress.version,
                    "memory_count": len(state.student_memories),
                    "memory_query": memory_query,
                    "memory_summaries": [
                        {
                            "memory_type": item["memory_type"],
                            "content": item["content"],
                            "evidence": item["evidence"],
                        }
                        for item in state.student_memories
                    ],
                    "rag_context_count": len(state.rag_context),
                    "rag_query": rag_query,
                    "rag_filters": rag_filters,
                    "rag_fallback_used": rag_fallback_used,
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
        if target_question_id:
            state.attribution_evidence = self.kt_engine.explain_prediction(
                state.kt_progress,
                target_question_id=target_question_id,
            )
        state.kt_progress.weak_concepts = state.kt_diagnosis.weak_concepts
        state.kt_progress.forgetting_risks = state.kt_diagnosis.forgetting_risks
        state.teaching_trace.append(
            self._trace(
                stage="diagnose",
                content=f"{self._kt_engine_name()} 已产出权威学习诊断事实。",
                metadata={
                    "kt_engine": self._kt_engine_name(),
                    "kt_engine_diagnostics": self._kt_engine_diagnostics(),
                    "target_question_id": target_question_id,
                    "weak_concept_count": len(state.kt_diagnosis.weak_concepts),
                    "forgetting_risk_count": len(state.kt_diagnosis.forgetting_risks),
                    "prediction_probability": state.kt_diagnosis.prediction_probability,
                    "prediction_facts": {
                        "prediction_probability": state.kt_diagnosis.prediction_probability,
                        "weak_concepts": state.kt_diagnosis.weak_concepts,
                        "forgetting_risks": state.kt_diagnosis.forgetting_risks,
                    },
                    "evidence": state.kt_diagnosis.evidence,
                    "attribution_evidence": (
                        state.attribution_evidence.model_dump()
                        if state.attribution_evidence
                        else None
                    ),
                },
            )
        )

    def _kt_engine_name(self) -> str:
        return str(getattr(self.kt_engine, "engine_name", self.kt_engine.__class__.__name__))

    def _kt_engine_diagnostics(self) -> dict[str, Any]:
        diagnostics = getattr(self.kt_engine, "diagnostics", None)
        if isinstance(diagnostics, dict):
            return diagnostics
        return {"engine_name": self._kt_engine_name()}

    def _assemble_context(self, state: MathTutorState) -> None:
        kt_facts = self._authoritative_kt_facts(state)
        assets = self.context_layer.collect_assets(
            student_id=state.student_id,
            session_id=state.session_id,
            intent=state.intent,
            learning_event=state.learning_event,
            kt_progress=state.kt_progress,
            student_memories=state.student_memories,
            rag_context=state.rag_context,
            kt_facts=kt_facts,
            trace_id=state.trace_id,
        )
        concept_id = self._context_concept_id(state)
        question_id = self._target_question_id(state.learning_event)
        retrieved = self.context_layer.retrieve_assets(
            student_id=state.student_id,
            session_id=state.session_id,
            concept_id=concept_id,
            question_id=question_id,
            top_k=8,
        )
        if not retrieved:
            retrieved = assets[:8]
        assembled = self.context_layer.assemble_context(
            intent=state.intent,
            assets=retrieved,
            kt_facts=kt_facts,
            token_budget=1200,
        )
        context_record = self.context_layer.record_context_trace(
            session_id=state.session_id,
            student_id=state.student_id,
            assembled_context=assembled,
        )
        state.context_assets = [asset.model_dump() for asset in retrieved]
        state.assembled_context = assembled.model_dump()
        state.teaching_trace.append(
            self._trace(
                stage="context_assemble",
                content="LearningContextLayer 已组装本轮上下文证据，KT facts 保持权威。",
                metadata={
                    "context_asset_count": len(state.context_assets),
                    "assembled_context": state.assembled_context,
                    "context_record": context_record,
                    "authoritative_kt_facts": kt_facts,
                    "boundary": "Context can assemble evidence, not decide learning facts.",
                },
            )
        )

    def _authoritative_kt_facts(self, state: MathTutorState) -> dict[str, Any]:
        diagnosis = state.kt_diagnosis
        return {
            "weak_concepts": diagnosis.weak_concepts if diagnosis else [],
            "forgetting_risks": diagnosis.forgetting_risks if diagnosis else [],
            "prediction_probability": diagnosis.prediction_probability if diagnosis else None,
            "mastery_by_concept": {
                concept.concept_id: concept.mastery for concept in state.kt_progress.concept_states
            },
        }

    def _context_concept_id(self, state: MathTutorState) -> str | None:
        if state.learning_event.payload.get("concept_id"):
            return str(state.learning_event.payload["concept_id"])
        if state.kt_diagnosis and state.kt_diagnosis.weak_concepts:
            concept_id = state.kt_diagnosis.weak_concepts[0].get("concept_id")
            return str(concept_id) if concept_id else None
        return None

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
            ranked_questions = self.recommender.recommend(
                progress=state.kt_progress,
                diagnosis=state.kt_diagnosis,
                preferences=self._planning_preferences(state),
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
        elif state.intent == "next_step_advice":
            state.next_action = {
                "type": "recommend_next_question",
                "label": "根据薄弱知识点推荐下一步练习",
            }
            ranked_questions = self.recommender.recommend(
                progress=state.kt_progress,
                diagnosis=state.kt_diagnosis,
                preferences=self._planning_preferences(state),
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
            state.next_action = None

        state.teaching_plan = self.planner.plan(
            intent=state.intent,
            event=state.learning_event,
            diagnosis=state.kt_diagnosis,
            rag_context=state.rag_context,
            recommended_questions=state.recommended_questions,
            assembled_context=state.assembled_context,
        )
        state.next_action = state.teaching_plan["selected_action"]

        state.teaching_trace.append(
            self._trace(
                stage="plan",
                content="TeachingPlanner 已生成教学动作和证据化决策。",
                metadata={
                    "intent": state.intent,
                    "planner_decision": state.teaching_plan["decision"],
                    "next_action": state.next_action,
                    "selected_action": state.teaching_plan["selected_action"],
                    "teaching_type": state.teaching_plan["teaching_type"],
                    "mistake_diagnosis": state.teaching_plan["mistake_diagnosis"],
                    "planner_evidence": state.teaching_plan["evidence"],
                    "recommended_question_count": len(state.recommended_questions),
                    "candidate_count": len(self.content.list_questions()),
                    "assembled_context_id": (
                        state.assembled_context or {}
                    ).get("context_id"),
                    "context_asset_count": len(state.context_assets),
                    "context_rationale": self._context_rationale(state),
                    "evidence_gaps": (state.assembled_context or {}).get("evidence_gaps", []),
                    "recommendation_candidates": [
                        {
                            "question_id": question["question_id"],
                            "score": question["score"],
                            "score_factors": question["score_factors"],
                            "canonical_mapping": question.get("canonical_mapping"),
                            "content_availability": question.get("content_availability"),
                        }
                        for question in ranked_questions[:5]
                    ],
                    "selected_question_ids": [
                        question["question_id"] for question in state.recommended_questions
                    ],
                    "selected_canonical_targets": [
                        self._recommendation_target(question)
                        for question in state.recommended_questions
                    ],
                },
            )
        )

    def _generate_response(self, state: MathTutorState) -> None:
        if state.intent == "answer_submission":
            state.response = self._answer_submission_response(state)
        elif state.intent == "next_step_advice":
            question = state.recommended_questions[0]
            action_label = state.next_action["label"] if state.next_action else "下一步练习"
            instruction = state.next_action.get("student_instruction", "") if state.next_action else ""
            stem = question.get("stem") or question.get("content_availability", {}).get(
                "fallback_message",
                "这道题题干暂缺，请先补齐教学内容。",
            )
            state.response = f"我已经查看你的学习状态。{self._context_preface(state)}下一步先练：{stem} 这题来自「{question['concept_name']}」。教学动作：{action_label}。{instruction} 推荐理由：{question['reason']}。{self._citation_sentence(state)}做完后我会用标准答案确定性判题。"
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
            instruction = state.next_action.get("student_instruction", "") if state.next_action else ""
            return f"收到，你提交的 {question_id} 已由服务端标准答案判定为正确。我会把这次作答计入学习进度，并继续推荐下一步巩固练习。{instruction}{self._next_question_sentence(state)}{self._citation_sentence(state)}"
        if is_correct is False:
            correct_answer = state.learning_event.payload.get("correct_answer", "标准答案")
            diagnosis_text = self._mistake_diagnosis_sentence(state)
            action_label = state.next_action["label"] if state.next_action else "错因讲解"
            instruction = state.next_action.get("student_instruction", "") if state.next_action else ""
            return f"收到，你提交的 {question_id} 已由服务端标准答案判定为不正确。正确答案是 {correct_answer}。错因诊断：{diagnosis_text}。教学动作：{action_label}。{instruction}{self._next_question_sentence(state)}{self._citation_sentence(state)}"
        return f"收到，你提交了 {question_id} 的答案，但我还没有在内容集中找到这道题，暂时只记录事件。"

    def _mistake_diagnosis_sentence(self, state: MathTutorState) -> str:
        diagnosis = state.teaching_plan.get("mistake_diagnosis") if state.teaching_plan else None
        if not diagnosis:
            return "本题还没有足够证据生成错因诊断"
        concept = diagnosis["concept"].get("concept_name") or "当前知识点"
        patterns = diagnosis.get("mistake_patterns", [])
        pattern_text = "；".join(patterns[:2]) if patterns else "需要回到题目步骤核对"
        return f"问题集中在「{concept}」，可观察证据是 {pattern_text}"

    def _update_memory(self, state: MathTutorState) -> None:
        updates: list[StudentMemory] = []
        preferred_teaching_type = state.learning_event.payload.get("preferred_teaching_type")
        preferred_concept_id = state.learning_event.payload.get("preferred_concept_id")
        if preferred_teaching_type or preferred_concept_id:
            updates.append(
                StudentMemory(
                    student_id=state.student_id,
                    memory_type="preference",
                    content="学生在推荐中表达了学习偏好。",
                    evidence={
                        "preferred_teaching_type": preferred_teaching_type,
                        "preferred_concept_id": preferred_concept_id,
                    },
                )
            )

        if state.learning_event.type == "answer_submitted":
            is_correct = state.learning_event.payload.get("is_correct")
            if is_correct is False:
                updates.append(
                    StudentMemory(
                        student_id=state.student_id,
                        memory_type="repeated_mistake",
                        content=f"学生在「{state.learning_event.payload.get('concept_name')}」上出现错题。",
                        evidence={
                            "question_id": state.learning_event.payload.get("question_id"),
                            "concept_id": state.learning_event.payload.get("concept_id"),
                            "mistake_patterns": state.learning_event.payload.get("mistake_patterns", []),
                        },
                    )
                )
            elif is_correct is True:
                updates.append(
                    StudentMemory(
                        student_id=state.student_id,
                        memory_type="effective_strategy",
                        content="学生完成了一次正确作答，可继续用同类巩固题推进。",
                        evidence={
                            "question_id": state.learning_event.payload.get("question_id"),
                            "concept_id": state.learning_event.payload.get("concept_id"),
                        },
                    )
                )

        written = [self.memories.write(memory).model_dump() for memory in updates]
        state.teaching_trace.append(
            self._trace(
                stage="memory_update",
                content="已生成并写入本轮长期记忆更新。",
                metadata={
                    "memory_update_count": len(written),
                    "memory_updates": [
                        {
                            "memory_type": item["memory_type"],
                            "content": item["content"],
                            "evidence": item["evidence"],
                        }
                        for item in written
                    ],
                    "boundary": "Memory influences strategy, not mastery.",
                },
            )
        )

    def _knowledge_response(self, state: MathTutorState) -> str:
        if not state.rag_context:
            return "我已收到你的问题。当前 V1 主循环已经记录上下文，后续会结合本地数学知识库给出更完整讲解。"
        top = state.rag_context[0]
        return f"我查到一条相关知识：{top['content']} {self._citation_sentence(state)}"

    def _memory_query(self, state: MathTutorState) -> str:
        parts = [
            state.learning_event.message,
            str(state.learning_event.payload.get("concept_name", "")),
            str(state.learning_event.payload.get("concept_id", "")),
            "偏好 错因 策略 反思",
        ]
        return " ".join(part for part in parts if part)

    def _planning_preferences(self, state: MathTutorState) -> dict[str, Any]:
        preferences = dict(state.learning_event.payload)
        normalized = self._normalized_context(state)
        strategy_hints = normalized.get("strategy_hints", {})
        for key in ("preferred_teaching_type", "preferred_concept_id"):
            if key not in preferences and strategy_hints.get(key):
                preferences[key] = strategy_hints[key]
        preferences["context_included_reasons"] = self._context_included_reasons(state)
        preferences["context_gap_reasons"] = self._context_gap_reasons(state)
        preferences["knowledge_doc_types"] = normalized.get("knowledge_hints", {}).get("doc_types", [])
        return preferences

    def _memory_preface(self, state: MathTutorState) -> str:
        return self._context_preface(state)

    def _context_preface(self, state: MathTutorState) -> str:
        reasons = self._context_included_reasons(state)
        if any(reason in reasons for reason in ("参考学生偏好", "参考有效策略", "参考重复错因")):
            return "我会参考你之前的学习偏好，"
        if "参考相关知识资源" in reasons:
            return "我会参考相关知识资源，"
        return ""

    def _citation_sentence(self, state: MathTutorState) -> str:
        sources = self._knowledge_sources(state)
        if not sources:
            return ""
        return f"参考：{'；'.join(sources[:2])}。"

    def _next_question_sentence(self, state: MathTutorState) -> str:
        if not state.recommended_questions:
            return ""
        question = state.recommended_questions[0]
        return f"下一题建议：{question['stem']} 推荐理由：{question['reason']}。"

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

        question = self.content.get_question(str(question_id))
        if question is None:
            state.errors.append(f"unknown question_id: {question_id}")
            return

        availability = question.get("content_availability") or self.content.content_availability(question)
        if "standard_answer" in availability.get("missing_fields", []):
            state.learning_event.payload["grading_source"] = "missing_teaching_content"
            state.errors.append(
                availability.get("fallback_message")
                or f"{question_id} 缺少标准答案，无法进行服务端确定性判题。"
            )
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
        explicit_assist_question_id = state.learning_event.payload.get(
            "assist2017_question_id"
        ) or state.learning_event.payload.get("dgekt_question_id")
        grade_assist_question_id = grade.question.get("assist2017_question_id") or grade.question.get(
            "dgekt_question_id"
        )
        mapping_matches_payload = (
            explicit_assist_question_id is None
            or str(explicit_assist_question_id) == str(grade_assist_question_id)
        )
        for key in ("assist2017_question_id", "dgekt_question_id"):
            if key in grade.question and key not in state.learning_event.payload:
                state.learning_event.payload[key] = grade.question[key]
        if mapping_matches_payload:
            for key in ("assist2017_concept_id", "dgekt_concept_id"):
                if key in grade.question and key not in state.learning_event.payload:
                    state.learning_event.payload[key] = grade.question[key]

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

    def _normalized_context(self, state: MathTutorState) -> dict[str, Any]:
        assembled = state.assembled_context or {}
        normalized = assembled.get("normalized_context")
        return normalized if isinstance(normalized, dict) else {}

    def _context_included_reasons(self, state: MathTutorState) -> list[str]:
        normalized = self._normalized_context(state)
        reasons: list[str] = []
        for group_name in ("student_memory", "knowledge_resource"):
            for item in normalized.get(group_name, []):
                if item.get("included_reason"):
                    reasons.append(str(item["included_reason"]))
        return list(dict.fromkeys(reasons))

    def _context_gap_reasons(self, state: MathTutorState) -> list[str]:
        assembled = state.assembled_context or {}
        return [
            str(gap["reason"])
            for gap in assembled.get("evidence_gaps", [])
            if gap.get("reason")
        ]

    def _context_rationale(self, state: MathTutorState) -> dict[str, Any]:
        return {
            "included_reasons": self._context_included_reasons(state),
            "gap_reasons": self._context_gap_reasons(state),
        }

    def _knowledge_sources(self, state: MathTutorState) -> list[str]:
        normalized = self._normalized_context(state)
        sources: list[str] = []
        for item in normalized.get("knowledge_resource", []):
            metadata = item.get("metadata", {})
            source = metadata.get("source") if isinstance(metadata, dict) else None
            if source:
                summary = item.get("summary") or "知识资源"
                sources.append(f"{summary}（{source}）")
        return sources

    def _recommendation_target(self, question: dict[str, Any]) -> dict[str, Any]:
        canonical = question.get("canonical_mapping") or {}
        return {
            "question_id": question.get("question_id"),
            "concept_id": question.get("concept_id"),
            "concept_name": question.get("concept_name"),
            "teaching_type": question.get("teaching_type"),
            "assist2017_question_id": question.get("assist2017_question_id")
            or canonical.get("assist2017_question_id"),
            "assist2017_concept_id": question.get("assist2017_concept_id")
            or canonical.get("assist2017_concept_id"),
            "q_matrix_reference": question.get("q_matrix_reference")
            or canonical.get("q_matrix_reference"),
            "mapping_source": (
                question.get("provenance", {}).get("mapping_source")
                or canonical.get("source")
            ),
            "content_availability": question.get("content_availability"),
        }

    def _trace(
        self,
        stage: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> TeachingTraceEvent:
        actor_by_stage = {
            "load_context": "system",
            "diagnose": "kt",
            "context_assemble": "context",
            "plan": "planner",
            "generate_response": "response",
            "memory_update": "memory",
        }
        visibility_by_stage = {
            "generate_response": "student",
            "memory_update": "expert",
        }
        evidence_refs = self._evidence_refs(metadata or {})
        return TeachingTraceEvent(
            type=TeachingTraceEventType.OBSERVATION,
            stage=stage,
            actor=actor_by_stage.get(stage, "system"),
            visibility=visibility_by_stage.get(stage, "expert"),
            content=content,
            metadata=metadata or {},
            evidence_refs=evidence_refs,
        )

    def _evidence_refs(self, metadata: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        for source in metadata.get("rag_sources", []):
            if source.get("source"):
                refs.append(str(source["source"]))
        attribution = metadata.get("attribution_evidence") or {}
        if attribution.get("target_question_id"):
            refs.append(f"kt-attribution:{attribution['target_question_id']}")
        planner_evidence = metadata.get("planner_evidence") or {}
        for source in planner_evidence.get("rag_sources", []):
            if source.get("source"):
                refs.append(str(source["source"]))
        for question_id in metadata.get("selected_question_ids", []):
            refs.append(f"question:{question_id}")
        assembled_context = metadata.get("assembled_context") or {}
        for ref in assembled_context.get("evidence_refs", []):
            refs.append(str(ref))
        return list(dict.fromkeys(refs))


learning_loop = MathTutorLearningLoop()
