from __future__ import annotations

from typing import Any

from ..schemas.learning import KTDiagnosis, KTLearningProgress
from ..storage.content_repository import DemoTeachingContentRepository, content_repository


class RiskPrioritizedRecommender:
    def __init__(self, content: DemoTeachingContentRepository | None = None) -> None:
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
            "novelty": self._novelty(question, progress),
            "preference_fit": self._preference_fit(question, preferences),
        }
        score = round(
            factors["weak_concept_match"] * 0.35
            + factors["difficulty_fit"] * 0.2
            + factors["forgetting_urgency"] * 0.2
            + factors["novelty"] * 0.15
            + factors["preference_fit"] * 0.1,
            4,
        )
        public = self.content.public_question(question)
        return public | {
            "stem_summary": str(question["stem"])[:60],
            "concept": {
                "concept_id": question["concept_id"],
                "concept_name": question["concept_name"],
                "teaching_type": question["teaching_type"],
            },
            "score": score,
            "score_factors": factors,
        }

    def _weak_concept_match(self, question: dict[str, Any], diagnosis: KTDiagnosis) -> float:
        weak_concept_ids = {item["concept_id"] for item in diagnosis.weak_concepts}
        if question["concept_id"] in weak_concept_ids:
            return 1.0
        return 0.45 if weak_concept_ids else 0.65

    def _difficulty_fit(self, question: dict[str, Any], progress: KTLearningProgress) -> float:
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
        if preferred_concept_id and preferred_concept_id == question["concept_id"]:
            return 1.0
        if preferred_teaching_type and preferred_teaching_type == question["teaching_type"]:
            return 0.9
        if preferred_concept_id or preferred_teaching_type:
            return 0.35
        return 0.5

    def _concept_mastery(self, concept_id: str, progress: KTLearningProgress) -> float:
        for state in progress.concept_states:
            if state.concept_id == concept_id:
                return state.mastery
        return 0.45

    def _with_reason(self, item: dict[str, Any]) -> dict[str, Any]:
        factors = item["score_factors"]
        reason_parts = []
        if factors["weak_concept_match"] >= 1.0:
            reason_parts.append("匹配当前薄弱知识点")
        if factors["forgetting_urgency"] >= 0.5:
            reason_parts.append("遗忘风险较高")
        if factors["novelty"] < 0.2:
            reason_parts.append("近期做过，因此降权")
        else:
            reason_parts.append("近期未重复练习")
        reason_parts.append("难度与当前掌握度接近")
        return item | {"reason": "；".join(reason_parts)}


recommender = RiskPrioritizedRecommender()
