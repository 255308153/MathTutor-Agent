from __future__ import annotations

from copy import deepcopy
from typing import Protocol

from ..core.config import get_settings
from ..schemas.learning import KTLearningProgress
from .sqlite_store import SqliteLearningStore, get_learning_store


class ProgressStore(Protocol):
    def get_or_create(self, student_id: str) -> KTLearningProgress:
        """Load or create durable learning progress for a student."""

    def save(self, progress: KTLearningProgress) -> KTLearningProgress:
        """Persist an existing progress snapshot without recomputing mastery."""


class InMemoryProgressStore:
    """Small local progress store for isolated tests and ephemeral demos."""

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


class SqliteProgressStore:
    """Default durable progress store for continuous learning recovery."""

    def __init__(self, store: SqliteLearningStore | None = None) -> None:
        self._store = store or get_learning_store()

    def get_or_create(self, student_id: str) -> KTLearningProgress:
        progress = self._store.get_progress(student_id)
        if progress is None:
            progress = KTLearningProgress(student_id=student_id)
            self._store.save_progress(progress)
        return deepcopy(progress)

    def save(self, progress: KTLearningProgress) -> KTLearningProgress:
        saved = self._store.save_progress(progress)
        return deepcopy(saved)


def create_progress_store() -> ProgressStore:
    settings = get_settings()
    if settings.persistence_backend == "memory":
        return InMemoryProgressStore()
    return SqliteProgressStore()


progress_store: ProgressStore = create_progress_store()
