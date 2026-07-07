from __future__ import annotations

from app.kt.engine import KTStateEngine
from app.schemas.learning import AttributionEvidence, KTDiagnosis, KTLearningProgress, LearningEvent


class MockKTStateEngine(KTStateEngine):
    """Deterministic placeholder for wiring the agent loop before DGEKT is connected."""

    def update_from_event(
        self,
        progress: KTLearningProgress,
        event: LearningEvent,
    ) -> KTLearningProgress:
        progress.current_session_id = event.session_id
        progress.recent_events.append(event)
        progress.recent_events = progress.recent_events[-30:]
        progress.version += 1
        return progress

    def diagnose(
        self,
        progress: KTLearningProgress,
        target_question_id: str | None = None,
    ) -> KTDiagnosis:
        weak = [
            {
                "concept_id": state.concept_id,
                "concept_name": state.concept_name,
                "mastery": state.mastery,
                "reason": "mock mastery below threshold",
            }
            for state in progress.concept_states
            if state.mastery < 0.6
        ]
        risks = [
            {
                "concept_id": state.concept_id,
                "concept_name": state.concept_name,
                "forgetting_risk": state.forgetting_risk,
            }
            for state in progress.concept_states
            if state.forgetting_risk >= 0.5
        ]
        return KTDiagnosis(
            weak_concepts=weak[:3],
            forgetting_risks=risks[:3],
            prediction_probability=0.58 if target_question_id else None,
            evidence=["MockKTStateEngine used for V1 loop wiring."],
        )

    def explain_prediction(
        self,
        progress: KTLearningProgress,
        target_question_id: str,
    ) -> AttributionEvidence:
        return AttributionEvidence(
            target_question_id=target_question_id,
            prediction_probability=0.58,
            top_paths=[],
            key_history=[],
            weak_concepts=progress.weak_concepts,
        )
