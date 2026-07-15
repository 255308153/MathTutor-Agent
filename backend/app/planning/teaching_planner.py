from __future__ import annotations

from typing import Any

from ..schemas.learning import KTDiagnosis, LearningEvent


class MistakeDiagnoser:
    def diagnose(
        self,
        event: LearningEvent,
        rag_context: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if event.type != "answer_submitted" or event.payload.get("is_correct") is not False:
            return None

        concept_id = event.payload.get("concept_id")
        concept_name = event.payload.get("concept_name")
        mistake_patterns = list(event.payload.get("mistake_patterns", []))
        rag_mistakes = [
            {
                "doc_id": item.get("doc_id"),
                "title": item.get("title"),
                "source": item.get("source"),
                "content": item.get("content"),
            }
            for item in rag_context
            if item.get("doc_type") == "mistake_pattern"
        ]
        if rag_mistakes:
            mistake_patterns.extend(item["title"] for item in rag_mistakes if item.get("title"))

        return {
            "level": "concept_and_pattern",
            "concept": {
                "concept_id": concept_id,
                "concept_name": concept_name,
                "teaching_type": event.payload.get("teaching_type"),
            },
            "question_id": event.payload.get("question_id"),
            "submitted_answer": event.payload.get("answer"),
            "correct_answer": event.payload.get("correct_answer"),
            "mistake_patterns": list(dict.fromkeys(mistake_patterns)),
            "rag_evidence": rag_mistakes,
            "evidence": [
                "deterministic_grading",
                "teaching_content_mistake_patterns",
                *("rag_mistake_pattern" for _ in rag_mistakes[:1]),
            ],
        }


class TeachingPlanner:
    def __init__(self, diagnoser: MistakeDiagnoser | None = None) -> None:
        self.diagnoser = diagnoser or MistakeDiagnoser()

    def plan(
        self,
        *,
        intent: str,
        event: LearningEvent,
        diagnosis: KTDiagnosis | None,
        rag_context: list[dict[str, Any]],
        recommended_questions: list[dict[str, Any]],
        assembled_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mistake_diagnosis = self.diagnoser.diagnose(event, rag_context)
        teaching_type = self._teaching_type(event, recommended_questions, mistake_diagnosis)
        action = self._action_for(teaching_type, intent, event, mistake_diagnosis)
        return {
            "decision": "deterministic_teaching_planner",
            "selected_action": action,
            "teaching_type": teaching_type,
            "mistake_diagnosis": mistake_diagnosis,
            "evidence": self._evidence(
                event,
                diagnosis,
                rag_context,
                recommended_questions,
                assembled_context,
            ),
        }

    def _teaching_type(
        self,
        event: LearningEvent,
        recommended_questions: list[dict[str, Any]],
        mistake_diagnosis: dict[str, Any] | None,
    ) -> str:
        if mistake_diagnosis and mistake_diagnosis["concept"].get("teaching_type"):
            return str(mistake_diagnosis["concept"]["teaching_type"])
        if event.payload.get("teaching_type"):
            return str(event.payload["teaching_type"])
        if recommended_questions:
            return str(recommended_questions[0].get("teaching_type", "concept"))
        return "concept"

    def _action_for(
        self,
        teaching_type: str,
        intent: str,
        event: LearningEvent,
        mistake_diagnosis: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if event.type == "answer_submitted" and event.payload.get("is_correct") is True:
            return {
                "type": "reinforce_mastery",
                "label": "巩固掌握并推荐下一题",
                "student_instruction": "保留刚才有效的解题步骤，再做一道相近难度的巩固题。",
            }
        if mistake_diagnosis is not None:
            base = self._typed_action(teaching_type)
            return base | {
                "type": f"{base['type']}_after_mistake",
                "label": f"{base['label']}，并先处理本题错因",
            }
        if intent == "next_step_advice":
            return self._typed_action(teaching_type)
        return {
            "type": "knowledge_explanation",
            "label": "结合知识库回答问题",
            "student_instruction": "先给出短解释，再用一个检查问题确认理解。",
        }

    def _typed_action(self, teaching_type: str) -> dict[str, Any]:
        actions = {
            "memory": {
                "type": "quick_review",
                "label": "记忆型快速复习",
                "student_instruction": "先快速回忆事实，再用短题即时检查。",
            },
            "concept": {
                "type": "concept_explain_self_check",
                "label": "概念型解释与自我解释检查",
                "student_instruction": "先解释概念含义，再让学生用自己的话复述关键区别。",
            },
            "procedure": {
                "type": "worked_example_steps",
                "label": "程序型 worked example 与步骤练习",
                "student_instruction": "先展示标准步骤，再让学生补全下一步。",
            },
            "design": {
                "type": "challenge_reflection",
                "label": "综合型挑战与反思",
                "student_instruction": "给出稍有挑战的应用题，并要求学生说明建模思路。",
            },
        }
        return actions.get(teaching_type, actions["concept"])

    def _evidence(
        self,
        event: LearningEvent,
        diagnosis: KTDiagnosis | None,
        rag_context: list[dict[str, Any]],
        recommended_questions: list[dict[str, Any]],
        assembled_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        assembled_context = assembled_context or {}
        return {
            "event_type": event.type,
            "question_id": event.payload.get("question_id"),
            "is_correct": event.payload.get("is_correct"),
            "kt_weak_concepts": diagnosis.weak_concepts if diagnosis else [],
            "kt_forgetting_risks": diagnosis.forgetting_risks if diagnosis else [],
            "assembled_context_id": assembled_context.get("context_id"),
            "normalized_context": assembled_context.get("normalized_context", {}),
            "context_included_reasons": _context_included_reasons(assembled_context),
            "context_gap_reasons": [
                gap.get("reason")
                for gap in assembled_context.get("evidence_gaps", [])
                if gap.get("reason")
            ],
            "rag_sources": [
                {
                    "doc_id": item.get("doc_id"),
                    "doc_type": item.get("doc_type"),
                    "source": item.get("source"),
                    "concept_id": item.get("concept_id"),
                    "question_id": item.get("question_id"),
                    "xes3g5m_question_id": item.get("xes3g5m_question_id"),
                    "xes3g5m_concept_id": item.get("xes3g5m_concept_id"),
                    "coverage": item.get("coverage"),
                }
                for item in rag_context
            ],
            "recommended_question_ids": [
                question.get("question_id") for question in recommended_questions
            ],
        }


def _context_included_reasons(assembled_context: dict[str, Any]) -> list[str]:
    normalized = assembled_context.get("normalized_context", {})
    reasons: list[str] = []
    for group_name in ("student_memory", "knowledge_resource"):
        for item in normalized.get(group_name, []):
            if item.get("included_reason"):
                reasons.append(str(item["included_reason"]))
    return list(dict.fromkeys(reasons))


teaching_planner = TeachingPlanner()
