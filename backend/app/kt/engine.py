from __future__ import annotations

from typing import Protocol

from app.schemas.learning import AttributionEvidence, KTDiagnosis, KTLearningProgress, LearningEvent


class KTStateEngine(Protocol):
    """Stable seam for mock, DGEKT, SAFKT, or BKT learning-state engines."""

    def update_from_event(
        self,
        progress: KTLearningProgress,
        event: LearningEvent,
    ) -> KTLearningProgress:
        """Fold one learning event into the student's knowledge-tracing state."""

    def diagnose(
        self,
        progress: KTLearningProgress,
        target_question_id: str | None = None,
    ) -> KTDiagnosis:
        """Return authoritative KT facts for planning."""

    def explain_prediction(
        self,
        progress: KTLearningProgress,
        target_question_id: str,
    ) -> AttributionEvidence:
        """Return expert-facing attribution evidence for one prediction."""
