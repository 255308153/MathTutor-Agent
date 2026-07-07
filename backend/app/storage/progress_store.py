from __future__ import annotations

from copy import deepcopy

from ..schemas.learning import KTLearningProgress


class InMemoryProgressStore:
    """Small local progress store for the V1 demo loop."""

    def __init__(self) -> None:
        self._progress_by_student: dict[str, KTLearningProgress] = {}

    def get_or_create(self, student_id: str) -> KTLearningProgress:
        progress = self._progress_by_student.get(student_id)
        if progress is None:
            progress = KTLearningProgress(student_id=student_id)
            self._progress_by_student[student_id] = progress
        return deepcopy(progress)

    def save(self, progress: KTLearningProgress) -> KTLearningProgress:
        self._progress_by_student[progress.student_id] = deepcopy(progress)
        return deepcopy(progress)


progress_store = InMemoryProgressStore()
