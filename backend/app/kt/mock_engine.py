from __future__ import annotations

from .engine import KTStateEngine
from ..schemas.learning import (
    AttributionEvidence,
    ConceptState,
    KTDiagnosis,
    KTLearningProgress,
    LearningEvent,
    TeachingType,
)


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
        if event.type == "answer_submitted" and "is_correct" in event.payload:
            self._apply_answer_result(progress, event)
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

    def _apply_answer_result(
        self,
        progress: KTLearningProgress,
        event: LearningEvent,
    ) -> None:
        concept_id = event.payload.get("concept_id")
        concept_name = event.payload.get("concept_name")
        if not concept_id or not concept_name:
            return

        state = self._get_or_create_concept_state(
            progress=progress,
            concept_id=str(concept_id),
            concept_name=str(concept_name),
            teaching_type=str(event.payload.get("teaching_type", TeachingType.CONCEPT.value)),
        )
        is_correct = event.payload["is_correct"] is True
        state.evidence_count += 1
        state.recent_accuracy = self._rolling_accuracy(state.recent_accuracy, state.evidence_count, is_correct)
        if is_correct:
            state.mastery = min(1.0, state.mastery + 0.15)
            state.forgetting_risk = max(0.0, state.forgetting_risk - 0.1)
            state.status = "stable" if state.mastery >= 0.75 else "learning"
            progress.pending_question = None
        else:
            state.mastery = max(0.0, state.mastery - 0.08)
            state.forgetting_risk = min(1.0, state.forgetting_risk + 0.2)
            state.status = "weak"
            progress.error_records.append(
                {
                    "question_id": event.payload.get("question_id"),
                    "concept_id": state.concept_id,
                    "concept_name": state.concept_name,
                    "submitted_answer": event.payload.get("answer"),
                    "correct_answer": event.payload.get("correct_answer"),
                    "mistake_patterns": event.payload.get("mistake_patterns", []),
                }
            )
            progress.error_records = progress.error_records[-30:]
            progress.review_queue.append(
                {
                    "question_id": event.payload.get("question_id"),
                    "concept_id": state.concept_id,
                    "reason": "deterministic grading marked incorrect",
                }
            )
            progress.review_queue = progress.review_queue[-30:]

    def _get_or_create_concept_state(
        self,
        progress: KTLearningProgress,
        concept_id: str,
        concept_name: str,
        teaching_type: str,
    ) -> ConceptState:
        for state in progress.concept_states:
            if state.concept_id == concept_id:
                return state
        state = ConceptState(
            concept_id=concept_id,
            concept_name=concept_name,
            teaching_type=TeachingType(teaching_type),
            mastery=0.45,
            forgetting_risk=0.35,
            status="learning",
        )
        progress.concept_states.append(state)
        return state

    def _rolling_accuracy(
        self,
        previous_accuracy: float,
        evidence_count: int,
        is_correct: bool,
    ) -> float:
        previous_count = max(evidence_count - 1, 0)
        previous_correct = previous_accuracy * previous_count
        current_correct = 1.0 if is_correct else 0.0
        return round((previous_correct + current_correct) / evidence_count, 3)
