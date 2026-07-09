from __future__ import annotations

from typing import Any

from ..schemas.learning import KTDiagnosis, KTLearningProgress
from ..storage.content_repository import ContentRepository, content_repository


class RiskPrioritizedRecommender:
    def __init__(self, content: ContentRepository | None = None) -> None:
        self.content = content or content_repository

    def recommend(
        self,
        progress: KTLearningProgress,
        diagnosis: KTDiagnosis,
        preferences: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        preferences = preferences or {}
        scored = [
            self._score_question(
                question=question,
                progress=progress,
                diagnosis=diagnosis,
                preferences=preferences,
            )
            for question in self.content.list_questions()
        ]
        scored.sort(key=lambda item: (-item["score"], item["difficulty"], item["question_id"]))
        return [self._with_reason(item) for item in scored[:limit]]

    def _score_question(
        self,
        question: dict[str, Any],
        progress: KTLearningProgress,
        diagnosis: KTDiagnosis,
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        factors = {
            "weak_concept_match": self._weak_concept_match(question, diagnosis),
            "difficulty_fit": self._difficulty_fit(question, progress),
            "forgetting_urgency": self._forgetting_urgency(question, progress, diagnosis),
            "prediction_risk": self._prediction_risk(question, diagnosis),
            "novelty": self._novelty(question, progress),
            "preference_fit": self._preference_fit(question, preferences),
            "canonical_alignment": self._canonical_alignment(question),
            "content_completeness": self._content_completeness(question),
            "context_support": self._context_support(question, preferences),
        }
        score = round(
            factors["weak_concept_match"] * 0.35
            + factors["difficulty_fit"] * 0.15
            + factors["forgetting_urgency"] * 0.2
            + factors["prediction_risk"] * 0.1
            + factors["novelty"] * 0.15
            + factors["preference_fit"] * 0.1
            + factors["canonical_alignment"] * 0.04
            + factors["content_completeness"] * 0.06,
            4,
        )
        public = self.content.public_question(question)
        canonical_mapping = self._canonical_mapping(question)
        return public | {
            "stem_summary": str(question.get("stem") or "题干暂缺")[:60],
            "concept": {
                "concept_id": question["concept_id"],
                "concept_name": question["concept_name"],
                "teaching_type": question["teaching_type"],
            },
            "canonical_mapping": canonical_mapping,
            "score": score,
            "score_factors": factors,
            "context_rationale": {
                "included_reasons": list(preferences.get("context_included_reasons", [])),
                "gap_reasons": list(preferences.get("context_gap_reasons", [])),
                "knowledge_doc_types": list(preferences.get("knowledge_doc_types", [])),
            },
        }

    def _weak_concept_match(self, question: dict[str, Any], diagnosis: KTDiagnosis) -> float:
        weak_concept_ids = {item["concept_id"] for item in diagnosis.weak_concepts}
        if question["concept_id"] in weak_concept_ids:
            return 1.0
        return 0.45 if weak_concept_ids else 0.65

    def _difficulty_fit(self, question: dict[str, Any], progress: KTLearningProgress) -> float:
        if question.get("teaching_type") == "memory":
            target_difficulty = 0.25
            distance = abs(float(question["difficulty"]) - target_difficulty)
            return round(max(0.0, 1.0 - distance / 0.4), 4)
        mastery = self._concept_mastery(question["concept_id"], progress)
        target_difficulty = min(0.85, max(0.25, mastery + 0.18))
        distance = abs(float(question["difficulty"]) - target_difficulty)
        return round(max(0.0, 1.0 - distance / 0.6), 4)

    def _forgetting_urgency(
        self,
        question: dict[str, Any],
        progress: KTLearningProgress,
        diagnosis: KTDiagnosis,
    ) -> float:
        for risk in diagnosis.forgetting_risks:
            if risk["concept_id"] == question["concept_id"]:
                return round(float(risk.get("forgetting_risk", 0.0)), 4)
        for state in progress.concept_states:
            if state.concept_id == question["concept_id"]:
                return round(state.forgetting_risk, 4)
        return 0.2

    def _prediction_risk(self, question: dict[str, Any], diagnosis: KTDiagnosis) -> float:
        probability = diagnosis.prediction_probability
        if probability is None:
            return 0.0
        weak_concept_ids = {item.get("concept_id") for item in diagnosis.weak_concepts}
        if weak_concept_ids and question["concept_id"] not in weak_concept_ids:
            return 0.0
        return round(max(0.0, 1.0 - float(probability)), 4)

    def _novelty(self, question: dict[str, Any], progress: KTLearningProgress) -> float:
        question_id = question["question_id"]
        recent_question_ids = {
            str(event.payload.get("question_id"))
            for event in progress.recent_events[-10:]
            if event.payload.get("question_id")
        }
        recent_question_ids.update(
            str(item.get("question_id"))
            for item in progress.recommendation_history[-10:]
            if item.get("question_id")
        )
        return 0.05 if question_id in recent_question_ids else 1.0

    def _preference_fit(self, question: dict[str, Any], preferences: dict[str, Any]) -> float:
        preferred_teaching_type = preferences.get("preferred_teaching_type")
        preferred_concept_id = preferences.get("preferred_concept_id")
        if preferred_concept_id:
            return 1.0 if preferred_concept_id == question["concept_id"] else 0.25
        if preferred_teaching_type and preferred_teaching_type == question["teaching_type"]:
            return 0.9
        if preferred_teaching_type:
            return 0.35
        return 0.5

    def _canonical_alignment(self, question: dict[str, Any]) -> float:
        has_curated_mapping = bool(
            question.get("assist2017_question_id")
            and question.get("assist2017_concept_id")
            and question.get("q_matrix_reference")
            and question.get("canonical_mapping_source")
        )
        return 1.0 if has_curated_mapping else 0.0

    def _content_completeness(self, question: dict[str, Any]) -> float:
        availability = question.get("content_availability") or self.content.content_availability(
            question
        )
        if availability.get("status") == "available":
            return 1.0
        missing_fields = set(availability.get("missing_fields", []))
        essential = {"stem", "standard_answer", "explanation", "concept_metadata"}
        return round(max(0.0, 1.0 - len(missing_fields & essential) / len(essential)), 4)

    def _canonical_mapping(self, question: dict[str, Any]) -> dict[str, Any]:
        return {
            "question_id": question.get("question_id"),
            "concept_id": question.get("concept_id"),
            "concept_name": question.get("concept_name"),
            "teaching_type": question.get("teaching_type"),
            "assist2017_question_id": question.get("assist2017_question_id"),
            "assist2017_concept_id": question.get("assist2017_concept_id"),
            "q_matrix_reference": question.get("q_matrix_reference"),
            "source": question.get("canonical_mapping_source", "local_sequence_fallback"),
        }

    def _context_support(self, question: dict[str, Any], preferences: dict[str, Any]) -> float:
        score = 0.0
        if preferences.get("context_included_reasons"):
            score += 0.4
        if preferences.get("knowledge_doc_types"):
            score += 0.3
        if preferences.get("preferred_concept_id") == question["concept_id"]:
            score += 0.2
        if preferences.get("preferred_teaching_type") == question["teaching_type"]:
            score += 0.1
        return round(min(score, 1.0), 4)

    def _concept_mastery(self, concept_id: str, progress: KTLearningProgress) -> float:
        for state in progress.concept_states:
            if state.concept_id == concept_id:
                return state.mastery
        return 0.45

    def _with_reason(self, item: dict[str, Any]) -> dict[str, Any]:
        factors = item["score_factors"]
        reason_parts = []
        if factors["weak_concept_match"] >= 1.0:
            reason_parts.append(f"匹配映射知识点「{item['concept_name']}」")
        if factors["forgetting_urgency"] >= 0.5:
            reason_parts.append("遗忘风险较高")
        if factors.get("prediction_risk", 0.0) >= 0.5:
            reason_parts.append("DGEKT 预测答对概率偏低")
        canonical = item.get("canonical_mapping", {})
        if canonical.get("assist2017_question_id"):
            reason_parts.append(f"对齐 ASSIST2017 question {canonical['assist2017_question_id']}")
        context_rationale = item.get("context_rationale", {})
        for reason in context_rationale.get("included_reasons", [])[:2]:
            reason_parts.append(reason)
        for reason in context_rationale.get("gap_reasons", [])[:1]:
            reason_parts.append(reason)
        availability = item.get("content_availability", {})
        if availability.get("status") == "partial":
            reason_parts.append(availability.get("fallback_message") or "教学内容不完整")
        if factors["novelty"] < 0.2:
            reason_parts.append("近期做过，因此降权")
        else:
            reason_parts.append("近期未重复练习")
        reason_parts.append("难度与当前掌握度接近")
        return item | {"reason": "；".join(reason_parts)}


recommender = RiskPrioritizedRecommender()
